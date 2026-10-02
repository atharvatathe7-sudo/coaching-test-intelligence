import pytest


def test_compare_test_01_to_test_02(client, test_ids):
    previous_id, current_id = test_ids

    response = client.get(f"/api/tests/{previous_id}/compare/{current_id}")
    assert response.status_code == 200

    data = response.json()
    batch = data["batch_comparison"]

    assert batch["average_marks_change"] == pytest.approx(5.2, abs=0.01)
    assert batch["average_accuracy_change"] == pytest.approx(8.6, abs=0.05)

    summary = data["student_summary"]
    assert summary["improved"] == 13
    assert summary["declined"] == 6
    assert summary["unchanged"] == 1


def test_compare_unknown_test(client, test_ids):
    assert client.get(f"/api/tests/9999/compare/{test_ids[0]}").status_code == 404
