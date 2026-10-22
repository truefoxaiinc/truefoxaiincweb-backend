import hashlib
import json
from contextlib import closing

from app.database import connect, transaction


def start_conversation(client):
    response = client.post("/api/v1/chat", json={"message": "Hello"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["conversation_id"]
    assert payload["capability_token"]
    assert response.headers["cache-control"] == "no-store"
    return payload


def test_conversation_history_requires_capability_and_returns_generic_errors(clean_database):
    payload = start_conversation(clean_database)
    path = f"/api/v1/conversations/{payload['conversation_id']}"

    missing = clean_database.get(path)
    invalid = clean_database.get(path, headers={"X-Conversation-Capability": "incorrect"})
    unknown = clean_database.get("/api/v1/conversations/not-a-real-conversation")

    assert missing.status_code == invalid.status_code == unknown.status_code == 404
    assert missing.json() == invalid.json() == unknown.json()
    authorized = clean_database.get(path, headers={"X-Conversation-Capability": payload["capability_token"]})
    assert authorized.status_code == 200
    assert [item["role"] for item in authorized.json()] == ["user", "assistant"]


def test_followup_requires_the_matching_capability(clean_database):
    payload = start_conversation(clean_database)
    other_conversation = start_conversation(clean_database)
    request_body = {"message": "Thanks", "conversation_id": payload["conversation_id"]}

    unauthorized = clean_database.post("/api/v1/chat", json=request_body)
    cross_user = clean_database.post(
        "/api/v1/chat", json=request_body,
        headers={"X-Conversation-Capability": other_conversation["capability_token"]},
    )
    assert unauthorized.status_code == cross_user.status_code == 404
    assert unauthorized.json() == cross_user.json()

    authorized = clean_database.post(
        "/api/v1/chat", json=request_body,
        headers={"X-Conversation-Capability": payload["capability_token"]},
    )
    assert authorized.status_code == 200
    assert authorized.json()["conversation_id"] == payload["conversation_id"]
    assert authorized.json()["capability_token"] is None


def test_expired_capability_is_rejected(clean_database):
    payload = start_conversation(clean_database)
    with transaction() as connection:
        connection.execute(
            "UPDATE conversations SET capability_expires_at=0 WHERE id=?", (payload["conversation_id"],)
        )
    response = clean_database.get(
        f"/api/v1/conversations/{payload['conversation_id']}",
        headers={"X-Conversation-Capability": payload["capability_token"]},
    )
    assert response.status_code == 404
    assert "expired" not in response.text.lower()
    followup = clean_database.post(
        "/api/v1/chat",
        json={"message": "Thanks", "conversation_id": payload["conversation_id"]},
        headers={"X-Conversation-Capability": payload["capability_token"]},
    )
    assert followup.status_code == 404
    followup = clean_database.post(
        "/api/v1/chat",
        json={"message": "Thanks", "conversation_id": payload["conversation_id"]},
        headers={"X-Conversation-Capability": payload["capability_token"]},
    )
    assert followup.status_code == 404


def test_only_capability_hash_is_persisted(clean_database):
    payload = start_conversation(clean_database)
    with closing(connect()) as connection:
        row = connection.execute(
            "SELECT capability_hash FROM conversations WHERE id=?", (payload["conversation_id"],)
        ).fetchone()
    assert row["capability_hash"] == hashlib.sha256(payload["capability_token"].encode()).hexdigest()
    assert row["capability_hash"] != payload["capability_token"]


def test_capability_is_not_logged_or_returned_on_authorization_error(clean_database, caplog):
    payload = start_conversation(clean_database)
    token = payload["capability_token"]
    response = clean_database.get(
        f"/api/v1/conversations/{payload['conversation_id']}",
        headers={"X-Conversation-Capability": "wrong-secret"},
    )
    assert response.status_code == 404
    assert token not in response.text
    assert token not in caplog.text


def test_streaming_returns_capability_in_meta_and_accepts_followup(clean_database):
    response = clean_database.post("/api/v1/chat/stream", json={"message": "Hello"})
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    events = [line.removeprefix("data: ") for line in response.text.splitlines() if line.startswith("data: ")]
    meta = json.loads(events[0])
    token = meta["capability_token"]
    conversation_id = meta["conversation_id"]

    followup = clean_database.post(
        "/api/v1/chat/stream",
        json={"message": "Thanks", "conversation_id": conversation_id},
        headers={"X-Conversation-Capability": token},
    )
    assert followup.status_code == 200
    assert "event: done" in followup.text


def test_streaming_rejects_invalid_capability_before_opening_stream(clean_database):
    payload = start_conversation(clean_database)
    response = clean_database.post(
        "/api/v1/chat/stream",
        json={"message": "Thanks", "conversation_id": payload["conversation_id"]},
        headers={"X-Conversation-Capability": "bad"},
    )
    assert response.status_code == 404
    assert response.json() == {"detail": "Conversation not found or unauthorized"}
