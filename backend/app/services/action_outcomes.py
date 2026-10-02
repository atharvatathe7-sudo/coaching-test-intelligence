"""
Teacher action outcomes: what was observed in the next comparable test.

For each action on a source test this resolves a measurement target
(topic or chapter), finds the next comparable test, and reports the
observed change in the target's correct percentage.

This is an observation only. Nothing here claims that an action caused
the change.

Next comparable test (anchored on the source test, never on the
action's timestamp): same batch, same normalized subject, strictly later
test_date, ordered by (test_date, id). Later tests with no imported
answers, or that do not contain the target, are skipped.

Percentages come from the existing topic/chapter analytics
(correct / responses), so marking schemes do not affect them.
"""

from sqlalchemy.orm import Session

from ..database.models import (
    Batch,
    Chapter,
    Question,
    StudentAnswer,
    TeacherAction,
    Test,
    Topic,
)
from .analytics import analyze_topics_and_chapters
from .audit import last_reevaluation
from .import_csv import normalize_name

# Minimum responses for the target in BOTH tests to report a measurement.
MIN_RESPONSES = 10

NOTE = (
    "Observed change between these two tests; "
    "this does not establish that the action caused it."
)


def _test_info(test: Test) -> dict:
    return {
        "id": test.id,
        "name": test.name,
        "date": test.test_date.isoformat(),
    }


def find_later_tests(db: Session, source: Test) -> list[Test]:
    """
    Later tests in the same batch and subject, earliest first.

    Strictly later dates only: a same-date test is not "subsequent".
    """

    subject = normalize_name(source.subject)

    candidates = (
        db.query(Test)
        .filter(
            Test.batch_id == source.batch_id,
            Test.test_date > source.test_date,
        )
        .order_by(Test.test_date, Test.id)
        .all()
    )

    return [t for t in candidates if normalize_name(t.subject) == subject]


def resolve_target(
    db: Session,
    action: TeacherAction,
    institute_id: int | None = None,
) -> dict | None:
    """
    Decide what to measure for an action.

    Order: the action's topic, the question's topic, the action's
    chapter, the question's chapter. A question action is always
    measured through its topic/chapter, never as "the same question"
    in another test.

    When institute_id is given, a target owned by another institute is
    never measured (treated as no target).
    """

    question = (
        db.get(Question, action.question_id) if action.question_id else None
    )
    via = question.question_number if question else None

    if action.topic_id:
        level, target_id = "topic", action.topic_id
    elif question and question.topic_id:
        level, target_id = "topic", question.topic_id
    elif action.chapter_id:
        level, target_id = "chapter", action.chapter_id
    elif question and question.chapter_id:
        level, target_id = "chapter", question.chapter_id
    else:
        return None

    model = Topic if level == "topic" else Chapter
    row = db.get(model, target_id)

    if institute_id is not None and row is not None:
        chapter = row if level == "chapter" else db.get(Chapter, row.chapter_id)
        if chapter is None or chapter.institute_id != institute_id:
            return None

    return {
        "level": level,
        "id": target_id,
        "name": row.name if row else None,
        "via_question_number": via,
    }


class _Context:
    """Per-request lookups so each test is queried/analyzed at most once."""

    def __init__(self, db: Session) -> None:
        self.db = db
        self._later: dict[int, list[Test]] = {}
        self._analytics: dict[int, dict] = {}
        self._contents: dict[int, tuple[set, set]] = {}
        self._with_answers: set[int] = set()

    def reevaluated_at(self, test: Test):
        """Last correction that changed this test's results (cached)."""
        if not hasattr(self, "_reevaluated"):
            self._reevaluated = {}
        if test.id not in self._reevaluated:
            self._reevaluated[test.id] = last_reevaluation(self.db, test.id)
        return self._reevaluated[test.id]

    def institute_of(self, test: Test) -> int | None:
        batch = self.db.get(Batch, test.batch_id)
        return batch.institute_id if batch is not None else None

    def later_tests(self, source: Test) -> list[Test]:
        if source.id not in self._later:
            later = find_later_tests(self.db, source)
            self._later[source.id] = later
            self._load(later)

        return self._later[source.id]

    def _load(self, tests: list[Test]) -> None:
        ids = [t.id for t in tests if t.id not in self._contents]

        if not ids:
            return

        for test_id in ids:
            self._contents[test_id] = (set(), set())

        for test_id, topic_id, chapter_id in self.db.query(
            Question.test_id, Question.topic_id, Question.chapter_id
        ).filter(Question.test_id.in_(ids)):
            topics, chapters = self._contents[test_id]
            topics.add(topic_id)
            chapters.add(chapter_id)

        answered = (
            self.db.query(StudentAnswer.test_id)
            .filter(StudentAnswer.test_id.in_(ids))
            .distinct()
        )
        self._with_answers.update(row[0] for row in answered)

    def has_answers(self, test_id: int) -> bool:
        return test_id in self._with_answers

    def contains(self, test_id: int, level: str, target_id: int) -> bool:
        topics, chapters = self._contents[test_id]
        return target_id in (topics if level == "topic" else chapters)

    def analytics(self, test_id: int) -> dict:
        """Topic/chapter analytics, computed once per test."""
        if test_id not in self._analytics:
            try:
                self._analytics[test_id] = analyze_topics_and_chapters(
                    self.db, test_id
                )
            except ValueError:
                self._analytics[test_id] = {"topics": [], "chapters": []}

        return self._analytics[test_id]

    def target_stats(
        self, test_id: int, level: str, target_id: int
    ) -> tuple[float | None, int]:
        """(correct percentage or None, responses) for the target."""
        data = self.analytics(test_id)
        rows = data["topics" if level == "topic" else "chapters"]
        key = "topic_id" if level == "topic" else "chapter_id"

        for row in rows:
            if row[key] == target_id:
                responses = row["responses"]
                percentage = (
                    row["correct_percentage"] if responses > 0 else None
                )
                return percentage, responses

        return None, 0


def _outcome_for(
    ctx: _Context,
    source: Test,
    action: TeacherAction,
) -> dict:
    target = resolve_target(ctx.db, action, ctx.institute_of(source))

    outcome = {
        "action": {
            "id": action.id,
            "action_type": action.action_type,
            "status": action.status,
            "note": action.note,
            "created_at": action.created_at.isoformat(),
            "finding_type": action.finding_type,
            "finding_title": action.finding_title,
        },
        "target": target,
        "source_test": _test_info(source),
        "next_test": None,
        "previous_percentage": None,
        "next_percentage": None,
        "change_pp": None,
        "previous_responses": None,
        "next_responses": None,
        "skipped_tests": [],
        "min_responses": MIN_RESPONSES,
        "status": None,
        "caveats": [],
        "note": NOTE,
    }

    if action.status == "planned":
        outcome["caveats"].append("action_still_planned")

    # The answer key or answers were corrected after the action was
    # recorded: the finding snapshot on the action may no longer match.
    reevaluated = ctx.reevaluated_at(source)
    if reevaluated is not None and reevaluated > action.created_at:
        outcome["caveats"].append("test_reevaluated_after_action")

    if target is None:
        outcome["status"] = "no_target"
        return outcome

    level, target_id = target["level"], target["id"]

    chosen = None
    skipped = []

    for test in ctx.later_tests(source):
        if not ctx.has_answers(test.id):
            skipped.append(
                {**_test_info(test), "reason": "no_answers"}
            )
        elif not ctx.contains(test.id, level, target_id):
            skipped.append(
                {**_test_info(test), "reason": "target_absent"}
            )
        else:
            chosen = test
            break

    outcome["skipped_tests"] = skipped

    if chosen is None:
        usable = any(s["reason"] == "target_absent" for s in skipped)

        if not usable:
            outcome["status"] = "no_subsequent_test"
        else:
            outcome["status"] = f"{level}_absent"

        return outcome

    previous_pct, previous_n = ctx.target_stats(source.id, level, target_id)
    next_pct, next_n = ctx.target_stats(chosen.id, level, target_id)

    outcome["next_test"] = _test_info(chosen)
    outcome["previous_percentage"] = previous_pct
    outcome["next_percentage"] = next_pct
    outcome["previous_responses"] = previous_n
    outcome["next_responses"] = next_n

    if action.created_at.date() > chosen.test_date:
        outcome["caveats"].append("action_recorded_after_next_test")

    if (source.marks_correct, source.marks_wrong, source.marks_blank) != (
        chosen.marks_correct, chosen.marks_wrong, chosen.marks_blank,
    ):
        outcome["caveats"].append("marking_scheme_differs")

    if previous_n < MIN_RESPONSES or next_n < MIN_RESPONSES:
        outcome["status"] = "insufficient_data"
        return outcome

    outcome["status"] = "measured"
    outcome["change_pp"] = round(next_pct - previous_pct, 2)

    return outcome


def get_action_outcomes(db: Session, test_id: int) -> list[dict]:
    """One outcome entry per teacher action recorded on the test."""

    source = db.get(Test, test_id)

    if source is None:
        raise ValueError(f"Test {test_id} not found.")

    actions = (
        db.query(TeacherAction)
        .filter(TeacherAction.test_id == test_id)
        .order_by(TeacherAction.created_at, TeacherAction.id)
        .all()
    )

    ctx = _Context(db)

    return [_outcome_for(ctx, source, action) for action in actions]
