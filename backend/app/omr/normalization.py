"""
From OMRChecker's output row to our own sheet model.

OMRChecker writes one wide CSV row per image:

    file_id, input_path, output_path, score, <fields...>

Only fields the template names as the roll number or as questions are
read from it. Everything else, and above all the four metadata columns
(file paths and OMRChecker's own score), is dropped here and never
reaches answer data. The score is never used: marks are calculated only
by the application's evaluation.

Answer cells:
    "A".."D"                  RECOGNIZED
    ""                        BLANK
    two or more options       MULTI_MARK  (e.g. "AB", "ABCD")
    anything else             INVALID
    field absent from the row REVIEW_REQUIRED

Nothing is guessed: MULTI_MARK is never reduced to one of its letters and
never to BLANK, and INVALID is never mapped to a "close" answer.
"""

from .models import OMRAnswer, OMRSheet, RecognitionStatus
from .template import OMRTemplate

# Columns OMRChecker adds about the file; never answer data.
METADATA_COLUMNS = frozenset({"file_id", "input_path", "output_path", "score"})


def normalize_answer(
    raw: str | None, options: tuple[str, ...]
) -> tuple[RecognitionStatus, str | None]:
    """Classify one answer cell. Returns (status, normalized answer)."""

    if raw is None:
        return RecognitionStatus.REVIEW_REQUIRED, None

    value = raw.strip().upper()

    if value == "":
        return RecognitionStatus.BLANK, None

    letters = list(value)

    if not all(letter in options for letter in letters):
        return RecognitionStatus.INVALID, None

    if len(letters) == 1:
        return RecognitionStatus.RECOGNIZED, value

    # Several options. OMRChecker writes each marked option once, so a
    # repeated letter is not something it should produce.
    if len(set(letters)) != len(letters):
        return RecognitionStatus.INVALID, None

    return RecognitionStatus.MULTI_MARK, None


def normalize_roll(raw: str | None, template: OMRTemplate) -> tuple[str | None, str | None]:
    """
    Returns (roll number, problem code). Exactly one of them is None.

    The roll must be the template's number of digits. A column with no
    mark shortens it and a column with two marks lengthens it, so both
    are caught as malformed rather than guessed at.
    """

    if raw is None or raw.strip() == "":
        return None, "roll_missing"

    value = raw.strip()

    if not (value.isascii() and value.isdigit()) or len(value) != template.roll_digits:
        return None, "roll_malformed"

    return value, None


def normalize_sheet(
    index: int,
    display_name: str,
    row: dict[str, str] | None,
    template: OMRTemplate,
    test_questions: set[int],
) -> OMRSheet:
    """
    Build the sheet model for one recognised image.

    `row` is OMRChecker's result row for the image, or None when it could
    not be read. Only the selected test's questions become answers;
    template questions outside the test are listed in `ignored_fields`.
    """

    sheet = OMRSheet(index=index, display_name=display_name)

    if row is None:
        sheet.unreadable = True
        return sheet

    # Drop the metadata columns first; from here on they do not exist.
    fields = {k: v for k, v in row.items() if k not in METADATA_COLUMNS}

    sheet.roll_raw = fields.get(template.roll_field)
    sheet.roll_number, sheet.roll_problem = normalize_roll(
        sheet.roll_raw, template
    )

    for number in sorted(test_questions):
        raw = fields.get(template.column_for(number))
        status, answer = normalize_answer(raw, template.options)
        sheet.answers.append(
            OMRAnswer(
                question_number=number,
                raw_value=raw,
                normalized_answer=answer,
                status=status,
            )
        )

    # Fields that exist on the sheet but are not part of this test: the
    # template's other questions, and any column the template does not
    # describe at all. They are reported, never imported.
    known = {template.roll_field, *template.question_columns}
    outside = [
        column
        for column, number in template.question_columns.items()
        if number not in test_questions
    ] + sorted(fields.keys() - known)

    for column in outside:
        sheet.ignored_fields.append(column)
        if (fields.get(column) or "").strip():
            sheet.ignored_marked += 1

    return sheet
