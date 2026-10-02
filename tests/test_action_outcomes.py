import itertools
import json
from datetime import date, datetime

import pytest

from backend.app.database import models
from backend.app.services import action_outcomes

_counter = itertools.count(1)

# Aliased so pytest does not try to collect the model classes as tests.
DbTest = models.Test
DbAction = models.TeacherAction

NOTE = (
    "Observed change between these two tests; "
    "this does not establish that the action caused it."
)


# ------------------------------------------------------------------
# Builders (direct database inserts so dates/counts are controlled)
# ------------------------------------------------------------------

class World:
    """A batch with 12 students and two chapters/topics to test with."""

    def __init__(self, db, client):
        n = next(_counter)
        self.db = db
        self.client = client
        self.batch = models.Batch(institute_id=1, name=f"Outcome Batch {n}")
        db.add(self.batch)
        db.flush()

        self.mech = models.Chapter(
            institute_id=1, subject="Physics", name=f"Mech {n}"
        )
        self.optics = models.Chapter(
            institute_id=1, subject="Physics", name=f"Optics {n}"
        )
        db.add_all([self.mech, self.optics])
        db.flush()

        self.kin = models.Topic(chapter_id=self.mech.id, name=f"Kin {n}")
        self.force = models.Topic(chapter_id=self.mech.id, name=f"Force {n}")
        self.lens = models.Topic(chapter_id=self.optics.id, name=f"Lens {n}")
        db.add_all([self.kin, self.force, self.lens])
        db.commit()

        self.students = self.add_students(self.batch)

    def add_students(self, batch):
        """12 students in the given batch (answers must stay in-batch)."""
        for i in range(12):
            self.db.add(
                models.Student(
                    batch_id=batch.id,
                    roll_number=f"S{i:02d}",
                    name=f"Student {i}",
                )
            )
        self.db.commit()
        return (
            self.db.query(models.Student).filter_by(batch_id=batch.id).all()
        )

    def test(
        self,
        name,
        test_date,
        questions,
        *,
        batch=None,
        subject="Physics",
        marks=(4.0, -1.0, 0.0),
        answered_questions=None,
        with_answers=True,
    ):
        """
        questions: {question_number: (topic, correct_students)}.
        Student i answers question q correctly when i < correct_students,
        otherwise wrongly. answered_questions limits which questions get
        answers (default all); with_answers=False imports no answers.
        """
        db = self.db
        students = (
            self.students
            if batch is None
            else db.query(models.Student).filter_by(batch_id=batch.id).all()
        )
        test = DbTest(
            batch_id=(batch or self.batch).id,
            name=name,
            subject=subject,
            test_date=test_date,
            marks_correct=marks[0],
            marks_wrong=marks[1],
            marks_blank=marks[2],
        )
        db.add(test)
        db.flush()

        for number, (topic, correct) in questions.items():
            question = models.Question(
                test_id=test.id,
                question_number=number,
                subject=subject,
                chapter_id=topic.chapter_id,
                topic_id=topic.id,
                correct_answer="A",
                difficulty="medium",
            )
            db.add(question)
            db.flush()

            if not with_answers:
                continue
            if answered_questions is not None and number not in answered_questions:
                continue

            for i, student in enumerate(students):
                db.add(
                    models.StudentAnswer(
                        test_id=test.id,
                        batch_id=test.batch_id,
                        student_id=student.id,
                        question_id=question.id,
                        answer="A" if i < correct else "B",
                    )
                )

        db.commit()
        return test

    def action(self, test, **fields):
        body = {"test_id": test.id, "action_type": "reteach"}
        body.update(fields)
        response = self.client.post("/api/actions", json=body)
        assert response.status_code == 200, response.text
        return response.json()["id"]

    def outcomes(self, test):
        response = self.client.get(f"/api/tests/{test.id}/actions/outcomes")
        assert response.status_code == 200
        return response.json()["outcomes"]

    def outcome(self, test, action_id=None):
        items = self.outcomes(test)
        if action_id is None:
            assert len(items) == 1
            return items[0]
        return next(o for o in items if o["action"]["id"] == action_id)


@pytest.fixture()
def world(db, client):
    return World(db, client)


def topic_action(world, source, topic, **extra):
    return world.action(
        source,
        topic_id=topic.id,
        chapter_id=topic.chapter_id,
        **extra,
    )


D1, D2, D3, D4 = (date(2026, 1, d) for d in (1, 8, 15, 22))


# ------------------------------------------------------------------
# Measured outcomes
# ------------------------------------------------------------------

def test_topic_action_with_valid_next_test(world):
    # Kinematics: 2 questions x 12 students; 5+5 correct -> 10/24.
    t1 = world.test("T1", D1, {1: (world.kin, 5), 2: (world.kin, 5)})
    # Next test: 3 questions; 9+9+6 correct of 36 -> 24/36.
    t2 = world.test(
        "T2", D2,
        {1: (world.kin, 9), 2: (world.kin, 9), 3: (world.kin, 6)},
    )
    topic_action(world, t1, world.kin, note="Reteach friction")

    out = world.outcome(t1)

    assert out["status"] == "measured"
    assert out["target"] == {
        "level": "topic",
        "id": world.kin.id,
        "name": world.kin.name,
        "via_question_number": None,
    }
    assert out["source_test"]["id"] == t1.id
    assert out["next_test"]["id"] == t2.id
    assert out["next_test"]["date"] == "2026-01-08"
    assert out["previous_percentage"] == 41.67
    assert out["next_percentage"] == 66.67
    assert out["previous_responses"] == 24
    assert out["next_responses"] == 36
    assert out["note"] == NOTE
    assert out["action"]["note"] == "Reteach friction"


def test_change_pp_arithmetic(world):
    t1 = world.test("T1", D1, {1: (world.kin, 7)})        # 58.33
    world.test("T2", D2, {1: (world.kin, 12)})             # 100.0
    topic_action(world, t1, world.kin)

    out = world.outcome(t1)

    assert out["previous_percentage"] == 58.33
    assert out["next_percentage"] == 100.0
    assert out["change_pp"] == pytest.approx(41.67, abs=0.01)

    # A decline is reported as a negative observed change.
    t3 = world.test("T3", D3, {1: (world.force, 12)})
    world.test("T4", D4, {1: (world.force, 3)})
    topic_action(world, t3, world.force)
    assert world.outcome(t3)["change_pp"] == -75.0


def test_chapter_action_with_valid_next_test(world):
    t1 = world.test("T1", D1, {1: (world.kin, 6), 2: (world.force, 6)})
    t2 = world.test("T2", D2, {1: (world.kin, 9), 2: (world.force, 12)})
    world.action(t1, chapter_id=world.mech.id)

    out = world.outcome(t1)

    assert out["status"] == "measured"
    assert out["target"]["level"] == "chapter"
    assert out["target"]["name"] == world.mech.name
    assert out["next_test"]["id"] == t2.id
    assert out["previous_percentage"] == 50.0
    assert out["next_percentage"] == 87.5
    assert out["previous_responses"] == 24


def test_question_action_resolves_to_its_topic(world):
    t1 = world.test(
        "T1", D1,
        {1: (world.kin, 3), 2: (world.kin, 9), 3: (world.lens, 12)},
    )
    # Question 1 only (no topic/chapter ids sent): resolved via the question.
    world.action(t1, question_number=1)
    # In T2 the same number is a different topic; Q1 must NOT be compared.
    t2 = world.test(
        "T2", D2,
        {1: (world.lens, 12), 2: (world.kin, 6), 3: (world.kin, 6)},
    )

    out = world.outcome(t1)

    assert out["target"]["level"] == "topic"
    assert out["target"]["name"] == world.kin.name
    assert out["target"]["via_question_number"] == 1
    assert out["next_test"]["id"] == t2.id
    # Topic percentages (Kinematics), not question 1's own result.
    assert out["previous_percentage"] == 50.0      # (3+9)/24
    assert out["previous_responses"] == 24
    assert out["next_percentage"] == 50.0          # (6+6)/24
    assert out["next_responses"] == 24


# ------------------------------------------------------------------
# Next-test rule
# ------------------------------------------------------------------

def test_no_subsequent_test(world):
    t1 = world.test("T1", D1, {1: (world.kin, 6)})
    topic_action(world, t1, world.kin)

    out = world.outcome(t1)

    assert out["status"] == "no_subsequent_test"
    assert out["next_test"] is None
    assert out["next_percentage"] is None
    assert out["change_pp"] is None


def test_other_batch_and_other_subject_are_ignored(world, db):
    t1 = world.test("T1", D1, {1: (world.kin, 6)})
    other_batch = models.Batch(institute_id=1, name="Another Batch X")
    db.add(other_batch)
    db.commit()
    world.add_students(other_batch)
    world.test("Other batch", D2, {1: (world.kin, 12)}, batch=other_batch)
    world.test("Chem", D2, {1: (world.kin, 12)}, subject="Chemistry")
    topic_action(world, t1, world.kin)

    assert world.outcome(t1)["status"] == "no_subsequent_test"


def test_subject_match_is_normalized(world):
    t1 = world.test("T1", D1, {1: (world.kin, 6)})
    t2 = world.test("T2", D2, {1: (world.kin, 9)}, subject="  physics ")
    topic_action(world, t1, world.kin)

    out = world.outcome(t1)

    assert out["status"] == "measured"
    assert out["next_test"]["id"] == t2.id


def test_earliest_applicable_test_wins(world):
    t1 = world.test("T1", D1, {1: (world.kin, 6)})
    t2 = world.test("T2", D2, {1: (world.kin, 9)})
    world.test("T3", D3, {1: (world.kin, 12)})
    topic_action(world, t1, world.kin)

    assert world.outcome(t1)["next_test"]["id"] == t2.id


def test_intermediate_test_without_target_is_skipped(world):
    t1 = world.test("T1", D1, {1: (world.kin, 6)})
    t2 = world.test("T2", D2, {1: (world.lens, 12)})   # no Kinematics
    t3 = world.test("T3", D3, {1: (world.kin, 9)})
    topic_action(world, t1, world.kin)

    out = world.outcome(t1)

    assert out["status"] == "measured"
    assert out["next_test"]["id"] == t3.id
    assert out["skipped_tests"] == [
        {
            "id": t2.id, "name": "T2", "date": "2026-01-08",
            "reason": "target_absent",
        }
    ]


def test_topic_and_chapter_absent_are_not_zero_percent(world):
    t1 = world.test("T1", D1, {1: (world.kin, 6)})
    world.test("T2", D2, {1: (world.lens, 12)})
    topic_id = topic_action(world, t1, world.kin)
    chapter_id = world.action(t1, chapter_id=world.mech.id)

    topic_out = world.outcome(t1, topic_id)
    chapter_out = world.outcome(t1, chapter_id)

    assert topic_out["status"] == "topic_absent"
    assert chapter_out["status"] == "chapter_absent"
    for out in (topic_out, chapter_out):
        assert out["next_test"] is None
        assert out["next_percentage"] is None
        assert out["change_pp"] is None


def test_later_test_without_answers_is_skipped(world):
    t1 = world.test("T1", D1, {1: (world.kin, 6)})
    t2 = world.test("T2", D2, {1: (world.kin, 12)}, with_answers=False)
    t3 = world.test("T3", D3, {1: (world.kin, 9)})
    topic_action(world, t1, world.kin)

    out = world.outcome(t1)

    assert out["next_test"]["id"] == t3.id
    assert out["skipped_tests"][0]["id"] == t2.id
    assert out["skipped_tests"][0]["reason"] == "no_answers"


def test_only_unanswered_later_test_means_no_subsequent_test(world):
    t1 = world.test("T1", D1, {1: (world.kin, 6)})
    world.test("T2", D2, {1: (world.kin, 12)}, with_answers=False)
    topic_action(world, t1, world.kin)

    assert world.outcome(t1)["status"] == "no_subsequent_test"


def test_same_date_test_is_not_subsequent(world):
    t1 = world.test("T1", D1, {1: (world.kin, 6)})
    world.test("Same day", D1, {1: (world.kin, 12)})
    topic_action(world, t1, world.kin)

    assert world.outcome(t1)["status"] == "no_subsequent_test"


def test_out_of_order_import_still_uses_dates(world):
    t1 = world.test("T1", D1, {1: (world.kin, 6)})
    # Imported first (lower id) but dated later.
    world.test("Late", D3, {1: (world.kin, 12)})
    early = world.test("Early", D2, {1: (world.kin, 9)})
    topic_action(world, t1, world.kin)

    out = world.outcome(t1)

    assert out["next_test"]["id"] == early.id
    assert out["next_test"]["name"] == "Early"


def test_earlier_tests_are_never_the_next_test(world):
    world.test("Before", D1, {1: (world.kin, 12)})
    t2 = world.test("T2", D2, {1: (world.kin, 6)})
    topic_action(world, t2, world.kin)

    assert world.outcome(t2)["status"] == "no_subsequent_test"


# ------------------------------------------------------------------
# Marking scheme, sample size, targets
# ------------------------------------------------------------------

def test_changed_marking_scheme_does_not_change_percentages(world):
    t1 = world.test("T1", D1, {1: (world.kin, 6)})
    world.test("T2", D2, {1: (world.kin, 9)}, marks=(2.0, -0.5, 0.0))
    topic_action(world, t1, world.kin)

    out = world.outcome(t1)

    assert out["status"] == "measured"
    assert out["previous_percentage"] == 50.0
    assert out["next_percentage"] == 75.0
    assert out["change_pp"] == 25.0
    assert "marking_scheme_differs" in out["caveats"]


def test_insufficient_responses(world):
    t1 = world.test("T1", D1, {1: (world.kin, 6)})
    t2 = world.test("T2", D2, {1: (world.kin, 9)})
    topic_action(world, t1, world.kin)

    # Drop T2's answers below the threshold of 10 responses.
    answers = (
        world.db.query(models.StudentAnswer)
        .filter_by(test_id=t2.id)
        .order_by(models.StudentAnswer.id)
        .all()
    )
    for answer in answers[: len(answers) - 9]:
        world.db.delete(answer)
    world.db.commit()

    out = world.outcome(t1)

    assert out["status"] == "insufficient_data"
    assert out["next_responses"] == 9
    assert out["previous_responses"] == 12
    assert out["next_percentage"] is not None      # still shown
    assert out["change_pp"] is None                # but not a measured change
    assert out["next_test"]["id"] == t2.id


def test_zero_responses_never_become_zero_percent(world):
    t1 = world.test("T1", D1, {1: (world.kin, 6)})
    # T2 has the topic's question but answers exist only for another one.
    world.test(
        "T2", D2,
        {1: (world.lens, 12), 2: (world.kin, 12)},
        answered_questions={1},
    )
    topic_action(world, t1, world.kin)

    out = world.outcome(t1)

    assert out["status"] == "insufficient_data"
    assert out["next_responses"] == 0
    assert out["next_percentage"] is None
    assert out["change_pp"] is None


def test_no_target(world):
    t1 = world.test("T1", D1, {1: (world.kin, 6)})
    world.test("T2", D2, {1: (world.kin, 9)})
    world.action(t1, action_type="monitor")

    out = world.outcome(t1)

    assert out["status"] == "no_target"
    assert out["target"] is None
    assert out["next_test"] is None
    assert out["note"] == NOTE


# ------------------------------------------------------------------
# Caveats
# ------------------------------------------------------------------

def test_planned_action_caveat(world):
    t1 = world.test("T1", D1, {1: (world.kin, 6)})
    world.test("T2", D2, {1: (world.kin, 9)})
    planned = topic_action(world, t1, world.kin)
    done = topic_action(world, t1, world.kin, status="completed")

    assert "action_still_planned" in world.outcome(t1, planned)["caveats"]
    assert "action_still_planned" not in world.outcome(t1, done)["caveats"]


def test_action_recorded_after_next_test(world, db):
    t1 = world.test("T1", D1, {1: (world.kin, 6)})
    t2 = world.test("T2", D2, {1: (world.kin, 9)})
    late = topic_action(world, t1, world.kin)       # created "today" (2026+)
    early = topic_action(world, t1, world.kin)

    row = db.get(DbAction, early)
    row.created_at = datetime(2026, 1, 5)           # before T2's date
    db.commit()

    late_out = world.outcome(t1, late)
    early_out = world.outcome(t1, early)

    # Source test is the anchor, so both resolve to T2 and are measured.
    assert late_out["status"] == early_out["status"] == "measured"
    assert late_out["next_test"]["id"] == early_out["next_test"]["id"] == t2.id
    assert "action_recorded_after_next_test" in late_out["caveats"]
    assert "action_recorded_after_next_test" not in early_out["caveats"]


# ------------------------------------------------------------------
# Endpoint behaviour
# ------------------------------------------------------------------

def test_outcomes_for_unknown_test(client):
    assert client.get("/api/tests/99999/actions/outcomes").status_code == 404


def test_no_actions_gives_empty_list(world):
    t1 = world.test("T1", D1, {1: (world.kin, 6)})
    assert world.outcomes(t1) == []


def test_one_entry_per_action_and_actions_stay_intact(world, client):
    t1 = world.test("T1", D1, {1: (world.kin, 6)})
    world.test("T2", D2, {1: (world.kin, 9)})
    a1 = topic_action(world, t1, world.kin, note="first")
    a2 = topic_action(world, t1, world.kin, note="second")

    assert [o["action"]["id"] for o in world.outcomes(t1)] == [a1, a2]

    # The existing action endpoints are unaffected by outcomes.
    listed = client.get(f"/api/tests/{t1.id}/actions").json()["actions"]
    assert [a["id"] for a in listed] == [a1, a2]
    updated = client.patch(f"/api/actions/{a1}", json={"status": "completed"})
    assert updated.status_code == 200
    assert "action_still_planned" not in world.outcome(t1, a1)["caveats"]


def test_analytics_computed_once_per_test(world, monkeypatch):
    t1 = world.test("T1", D1, {1: (world.kin, 6), 2: (world.lens, 6)})
    world.test("T2", D2, {1: (world.kin, 9), 2: (world.lens, 9)})
    for _ in range(3):
        topic_action(world, t1, world.kin)
    world.action(t1, chapter_id=world.mech.id)

    calls = []
    original = action_outcomes.analyze_topics_and_chapters

    def counting(db, test_id):
        calls.append(test_id)
        return original(db, test_id)

    monkeypatch.setattr(action_outcomes, "analyze_topics_and_chapters", counting)

    assert len(world.outcomes(t1)) == 4
    assert sorted(calls) == sorted(set(calls))     # no repeats
    assert len(calls) == 2                         # source + next only


def test_no_causal_wording(world):
    t1 = world.test("T1", D1, {1: (world.kin, 6)})
    world.test("T2", D2, {1: (world.lens, 9)})
    world.test("T3", D3, {1: (world.kin, 9)})
    topic_action(world, t1, world.kin)
    world.action(t1, action_type="monitor")

    text = json.dumps(world.outcomes(t1)).lower()
    # The fixed note is the one place the word appears, in a negation.
    text = text.replace(NOTE.lower(), "")

    for phrase in ("caused", "due to", "because of", "result of", "led to"):
        assert phrase not in text


# ------------------------------------------------------------------
# Demo data
# ------------------------------------------------------------------

def test_demo_test_02_is_dated_after_test_01(db, test_ids):
    first = db.get(DbTest, test_ids[0])
    second = db.get(DbTest, test_ids[1])

    assert second.test_date > first.test_date


def test_demo_topic_action_measures_test_02(client, test_ids):
    source_id, next_id = test_ids
    topics = client.get(
        f"/api/tests/{source_id}/analytics/chapters-topics"
    ).json()["topics"]
    kinematics = next(t for t in topics if t["topic_name"] == "Kinematics")

    client.post(
        "/api/actions",
        json={
            "test_id": source_id,
            "topic_id": kinematics["topic_id"],
            "chapter_id": kinematics["chapter_id"],
            "action_type": "reteach",
        },
    )

    out = client.get(
        f"/api/tests/{source_id}/actions/outcomes"
    ).json()["outcomes"][0]

    assert out["status"] == "measured"
    assert out["next_test"]["id"] == next_id
    assert out["previous_percentage"] == 63.33
    assert out["previous_responses"] == 60
    assert out["change_pp"] == pytest.approx(
        out["next_percentage"] - 63.33, abs=0.01
    )
