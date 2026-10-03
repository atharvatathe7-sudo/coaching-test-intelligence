"""
Checks on a batch of recognised sheets, in the context of one test.

Pure functions: nothing here touches the database or the recogniser. The
caller supplies the selected test's question numbers and roster.

Errors block the whole batch (it is imported all-or-nothing, or not at
all). Answers that need a person to decide (multi-mark, invalid, review
required) are not errors, but they also never become final answers: a
batch that has any is reported as "review_required" and not imported.
"""

from collections import Counter
from dataclasses import dataclass, field

from .models import Issue, NEEDS_REVIEW, OMRSheet, RecognitionStatus
from .template import OMRTemplate

REVIEW_ITEM_LIMIT = 200

_REVIEW_CODES = {
    RecognitionStatus.MULTI_MARK: "answer_multi_mark",
    RecognitionStatus.INVALID: "answer_invalid",
    RecognitionStatus.REVIEW_REQUIRED: "answer_review_required",
}


@dataclass
class BatchValidation:
    errors: list[Issue] = field(default_factory=list)
    warnings: list[Issue] = field(default_factory=list)
    review_items: list[dict] = field(default_factory=list)
    review_items_total: int = 0
    counts: dict = field(default_factory=dict)
    # sheet index -> "accepted" | "needs_review" | "rejected"
    sheet_states: dict[int, str] = field(default_factory=dict)

    @property
    def status(self) -> str:
        if self.errors:
            return "rejected"
        if self.review_items_total:
            return "review_required"
        return "accepted"


def check_template_covers_test(
    template: OMRTemplate, test_questions: set[int]
) -> tuple[list[Issue], list[Issue]]:
    """(errors, warnings) about the template against the selected test."""

    errors, warnings = [], []
    template_questions = set(template.question_numbers)

    if not test_questions:
        errors.append(Issue("test_has_no_questions", "This test has no questions."))
        return errors, warnings

    missing = sorted(test_questions - template_questions)
    if missing:
        errors.append(
            Issue(
                "template_incompatible",
                f"This test has {len(missing)} question(s) the sheet template "
                f"does not have (first: Q{missing[0]}).",
            )
        )

    extra = sorted(template_questions - test_questions)
    if extra:
        warnings.append(
            Issue(
                "template_fields_ignored",
                f"{len(extra)} question field(s) on the sheet template are not "
                "part of this test and are ignored (not imported).",
            )
        )

    return errors, warnings


def validate_sheets(
    sheets: list[OMRSheet],
    template: OMRTemplate,
    roster_rolls: set[str],
) -> BatchValidation:
    """Validate every sheet; the roster match is exact (no fuzzy matching)."""

    result = BatchValidation()
    answers = Counter()
    first_sheet_for_roll: dict[str, OMRSheet] = {}
    counts = Counter(submitted=len(sheets))

    if not sheets:
        result.errors.append(Issue("no_files", "No OMR images were provided."))

    ignored_columns: set[str] = set()
    ignored_marked = 0

    for sheet in sheets:
        name = sheet.display_name
        problems_before = len(result.errors)

        if sheet.unreadable:
            counts["unreadable"] += 1
            result.errors.append(
                Issue("sheet_unreadable", "The sheet could not be read.", sheet=name)
            )
            result.sheet_states[sheet.index] = "rejected"
            continue

        counts["processed"] += 1

        if sheet.roll_number is None:
            code = sheet.roll_problem or "roll_missing"
            message = (
                "No roll number was read from the sheet."
                if code == "roll_missing"
                else f"The roll number read from the sheet is not a valid "
                     f"{template.roll_digits}-digit number."
            )
            result.errors.append(Issue(code, message, sheet=name))
        elif sheet.roll_number not in roster_rolls:
            counts["unknown_student"] += 1
            result.errors.append(
                Issue(
                    "roll_unknown",
                    "The roll number is not in this test's batch roster.",
                    sheet=name,
                    roll_number=sheet.roll_number,
                )
            )
        elif sheet.roll_number in first_sheet_for_roll:
            counts["duplicate"] += 1
            earlier = first_sheet_for_roll[sheet.roll_number]
            result.errors.append(
                Issue(
                    "roll_duplicate",
                    f"This roll number was already read on {earlier.display_name}. "
                    "Neither sheet is imported until this is resolved.",
                    sheet=name,
                    roll_number=sheet.roll_number,
                )
            )
            result.sheet_states[earlier.index] = "rejected"
        else:
            first_sheet_for_roll[sheet.roll_number] = sheet

        for answer in sheet.answers:
            answers[answer.status] += 1

            if answer.status in NEEDS_REVIEW:
                result.review_items_total += 1
                if len(result.review_items) < REVIEW_ITEM_LIMIT:
                    result.review_items.append(
                        {
                            "sheet": name,
                            "roll_number": sheet.roll_number,
                            "question_number": answer.question_number,
                            "status": answer.status.value,
                            "raw_value": answer.raw_value,
                            "code": _REVIEW_CODES[answer.status],
                        }
                    )

        ignored_columns.update(sheet.ignored_fields)
        ignored_marked += sheet.ignored_marked

        if len(result.errors) > problems_before:
            result.sheet_states[sheet.index] = "rejected"
        elif sheet.index not in result.sheet_states:
            result.sheet_states[sheet.index] = (
                "needs_review" if any(a.needs_review for a in sheet.answers) else "accepted"
            )

    counts["accepted"] = sum(1 for s in result.sheet_states.values() if s == "accepted")
    counts["recognized"] = answers[RecognitionStatus.RECOGNIZED]
    counts["blank"] = answers[RecognitionStatus.BLANK]
    counts["multi_mark"] = answers[RecognitionStatus.MULTI_MARK]
    counts["invalid"] = answers[RecognitionStatus.INVALID]
    counts["review_required"] = answers[RecognitionStatus.REVIEW_REQUIRED]
    result.counts = {
        key: counts[key]
        for key in (
            "submitted", "processed", "accepted", "unreadable", "duplicate",
            "unknown_student", "recognized", "blank", "multi_mark", "invalid",
            "review_required",
        )
    }

    extra_columns = sorted(
        c for c in ignored_columns if c not in template.question_columns
    )
    if extra_columns:
        result.warnings.append(
            Issue(
                "unknown_fields_ignored",
                f"{len(extra_columns)} field(s) in the recognition output are not "
                "described by the template and were ignored.",
            )
        )

    if ignored_marked:
        result.warnings.append(
            Issue(
                "ignored_fields_marked",
                f"{ignored_marked} mark(s) on fields outside this test were "
                "ignored (not imported).",
            )
        )

    return result


def find_duplicate_answers(rows) -> list[tuple[str, int]]:
    """(roll, question) pairs that appear more than once in answer rows."""
    seen = Counter((roll, question) for roll, question, _ in rows)
    return sorted(key for key, count in seen.items() if count > 1)
