import pytest


@pytest.fixture()
def finding(client, test_ids):
    """A real question-based finding from the action report."""
    report = client.get(f"/api/tests/{test_ids[0]}/action-report").json()
    item = next(
        p for p in report["priorities"]
        if p["evidence"].get("question_number")
    )
    evidence = item["evidence"]

    return {
        "test_id": test_ids[0],
        "question_number": evidence["question_number"],
        "chapter_id": evidence["chapter_id"],
        "topic_id": evidence["topic_id"],
        "finding_type": item["type"],
        "finding_title": item["title"],
        "finding_reason": item["reason"],
        "action_type": "review",
        "note": "Review worked examples.",
    }


def test_create_and_list_action(client, finding, test_ids):
    response = client.post("/api/actions", json=finding)
    assert response.status_code == 200

    action = response.json()
    assert action["status"] == "planned"
    assert action["action_type"] == "review"
    assert action["question_number"] == finding["question_number"]
    assert action["chapter_name"] and action["topic_name"]
    assert action["finding_title"] == finding["finding_title"]

    listed = client.get(f"/api/tests/{test_ids[0]}/actions").json()["actions"]
    assert [a["id"] for a in listed] == [action["id"]]


def test_actions_are_scoped_to_their_test(client, finding, test_ids):
    client.post("/api/actions", json=finding)

    other = client.get(f"/api/tests/{test_ids[1]}/actions").json()["actions"]
    assert other == []


def test_update_status_note_and_clear_note(client, finding):
    action_id = client.post("/api/actions", json=finding).json()["id"]

    updated = client.patch(
        f"/api/actions/{action_id}", json={"status": "completed"}
    ).json()
    assert updated["status"] == "completed"
    assert updated["note"] == "Review worked examples."

    updated = client.patch(
        f"/api/actions/{action_id}", json={"note": "New note"}
    ).json()
    assert updated["note"] == "New note"
    assert updated["status"] == "completed"

    updated = client.patch(
        f"/api/actions/{action_id}", json={"note": None}
    ).json()
    assert updated["note"] is None


def test_chapter_only_action(client, finding):
    body = {
        "test_id": finding["test_id"],
        "chapter_id": finding["chapter_id"],
        "action_type": "reteach",
    }
    response = client.post("/api/actions", json=body)

    assert response.status_code == 200
    assert response.json()["question_number"] is None


@pytest.mark.parametrize(
    "override, expected",
    [
        ({"test_id": 9999}, 404),
        ({"question_number": 999}, 404),
        ({"chapter_id": 9999}, 404),
        ({"topic_id": 9999}, 404),
        ({"action_type": "delete_everything"}, 422),
        ({"status": "done"}, 422),
    ],
)
def test_invalid_create(client, finding, override, expected):
    response = client.post("/api/actions", json={**finding, **override})
    assert response.status_code == expected


def test_topic_must_belong_to_chapter(client, finding):
    body = {
        "test_id": finding["test_id"],
        "chapter_id": finding["chapter_id"] + 1,
        "topic_id": finding["topic_id"],
        "action_type": "review",
    }
    response = client.post("/api/actions", json=body)

    assert response.status_code == 400


def test_update_unknown_action_and_invalid_values(client, finding):
    assert client.patch("/api/actions/9999", json={"status": "completed"}).status_code == 404

    action_id = client.post("/api/actions", json=finding).json()["id"]
    assert client.patch(f"/api/actions/{action_id}", json={"status": "bogus"}).status_code == 422
    assert client.patch(f"/api/actions/{action_id}", json={"action_type": "bogus"}).status_code == 422


def test_list_actions_for_unknown_test(client):
    assert client.get("/api/tests/9999/actions").status_code == 404
