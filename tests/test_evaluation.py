import pytest

from backend.app.database.connection import DATABASE_PATH, PROJECT_ROOT
from backend.app.database import models
from backend.app.services.evaluation import classify_answer, evaluate_test


def test_uses_temporary_database():
    assert DATABASE_PATH != PROJECT_ROOT / "data" / "coaching.db"


@pytest.mark.parametrize(
    "answer, key, expected",
    [
        (None, "A", "blank"),
        ("", "A", "blank"),
        ("   ", "A", "blank"),
        ("A", "A", "correct"),
        ("a", "A", "correct"),
        (" b ", "B", "correct"),
        ("B", "A", "wrong"),
    ],
)
def test_classify_answer(answer, key, expected):
    assert classify_answer(answer, key) == expected


def _averages(client, test_id):
    overview = client.get(
        f"/api/tests/{test_id}/analytics/batch"
    ).json()["overview"]
    return overview["average_marks"], overview["average_accuracy"]


def test_test_01_averages(client, test_ids):
    marks, accuracy = _averages(client, test_ids[0])

    assert marks == 45.8
    assert accuracy == pytest.approx(53.9, abs=0.05)


def test_test_02_averages(client, test_ids):
    marks, accuracy = _averages(client, test_ids[1])

    assert marks == 51.0
    assert accuracy == pytest.approx(62.5, abs=0.05)


def test_stored_results_match_analytics(db, client, test_ids):
    """evaluate_test and analytics must agree (shared classification)."""
    test_id = test_ids[0]

    results = evaluate_test(db, test_id)
    assert len(results) == 20

    stored_avg = sum(r.marks for r in results) / len(results)
    marks, _ = _averages(client, test_id)

    assert stored_avg == pytest.approx(marks, abs=0.01)

    for result in db.query(models.TestResult).filter_by(test_id=test_id):
        assert (
            result.correct_count + result.wrong_count + result.blank_count
            == 30
        )


def test_evaluate_endpoint(client, test_ids):
    response = client.post(f"/api/tests/{test_ids[0]}/evaluate")

    assert response.status_code == 200
    assert response.json()["students_evaluated"] == 20
