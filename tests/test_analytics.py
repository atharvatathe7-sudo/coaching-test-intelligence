import pytest


def test_question_4_correct_percentage(client, test_ids):
    questions = client.get(
        f"/api/tests/{test_ids[0]}/analytics/questions"
    ).json()

    items = questions["questions"] if isinstance(questions, dict) else questions
    question_4 = next(q for q in items if q["question_number"] == 4)

    assert question_4["correct_percentage"] == 20.0


def test_chapter_and_topic_percentages(client, test_ids):
    data = client.get(
        f"/api/tests/{test_ids[0]}/analytics/chapters-topics"
    ).json()

    chapters = {c["chapter_name"]: c for c in data["chapters"]}
    topics = {t["topic_name"]: t for t in data["topics"]}

    assert chapters["Waves"]["correct_percentage"] == 46.25
    assert chapters["Mechanics"]["correct_percentage"] == pytest.approx(50.71)
    assert topics["Kinematics"]["correct_percentage"] == pytest.approx(63.33)
    assert topics["Kinematics"]["questions"] == 3


def test_action_report_and_investigation(client, test_ids):
    report = client.get(f"/api/tests/{test_ids[0]}/action-report").json()
    assert report["priority_count"] == len(report["priorities"]) > 0

    investigation = client.get(
        f"/api/tests/{test_ids[0]}/questions/4/investigation"
    ).json()
    assert investigation["performance"]["total_students"] == 20
    assert len(investigation["students"]) == 20
    assert investigation["performance"]["correct_percentage"] == 20.0
