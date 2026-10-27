from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api.chat import create_lead
from app.database import migrate, transaction
from app.schemas import LeadSubmissionRequest


def _lead(consent=True):
    return LeadSubmissionRequest(
        conversation_id="conversation-test",
        name="Test Customer",
        email="test@example.com",
        company="Example Restaurant",
        project_summary="We need camera-based kitchen compliance monitoring.",
        consent_to_contact=consent,
    )


@pytest.mark.asyncio
async def test_lead_rejects_missing_or_wrong_capability(monkeypatch):
    monkeypatch.setattr("app.api.chat.authorize_conversation", lambda *_: False)
    with pytest.raises(HTTPException) as error:
        await create_lead(_lead(), SimpleNamespace(headers={}), "wrong")
    assert error.value.status_code == 404


@pytest.mark.asyncio
async def test_lead_requires_explicit_consent(monkeypatch):
    monkeypatch.setattr("app.api.chat.authorize_conversation", lambda *_: True)
    with pytest.raises(HTTPException) as error:
        await create_lead(_lead(False), SimpleNamespace(headers={}), "valid")
    assert error.value.status_code == 422


@pytest.mark.asyncio
async def test_lead_does_not_claim_unconfigured_mail_was_sent(monkeypatch):
    monkeypatch.setattr("app.api.chat.authorize_conversation", lambda *_: True)
    monkeypatch.setattr("app.api.chat.submit_lead", lambda lead: _return_false())
    result = await create_lead(_lead(), SimpleNamespace(headers={}), "valid")
    assert result.status == "not_sent"


async def _return_false():
    return False


@pytest.mark.asyncio
async def test_send_is_idempotent_and_does_not_retain_pii_in_ledger(monkeypatch, tmp_path):
    from app.services import leads
    from app.config import get_settings

    old_settings = get_settings()
    test_settings = old_settings.model_copy(
        update={
            "database_path": tmp_path / "test.sqlite3",
            "lead_smtp_host": "smtp.example.com",
            "lead_smtp_username": "service",
            "lead_smtp_password": "example",
            "lead_email_from": "sender@example.com",
            "lead_email_to": "sales@example.com",
        }
    )
    monkeypatch.setattr("app.database.get_settings", lambda: test_settings)
    monkeypatch.setattr("app.services.leads.get_settings", lambda: test_settings)
    migrate()
    with transaction() as connection:
        connection.execute(
            "INSERT INTO conversations(id,created_at,updated_at) VALUES(?,?,?)",
            ("conversation-test", "2026-10-26", "2026-10-26"),
        )
    attempts = []
    monkeypatch.setattr(leads, "_send_email", lambda item: attempts.append(item.email))
    assert await leads.submit_lead(_lead()) is True
    assert await leads.submit_lead(_lead()) is True
    assert attempts == ["test@example.com"]
    with transaction() as connection:
        rows = connection.execute("SELECT * FROM lead_notifications").fetchall()
    assert len(rows) == 1
    assert rows[0]["status"] == "sent"
    assert "test@example.com" not in str(dict(rows[0]))
