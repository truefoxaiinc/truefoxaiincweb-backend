import asyncio
import logging
from urllib.parse import quote

import httpx

from app.config import get_settings
from app.database import transaction, utcnow
from app.schemas import LeadSubmissionRequest

logger = logging.getLogger(__name__)


def _configured() -> bool:
    settings = get_settings()
    return all(
        (
            settings.lead_graph_tenant_id,
            settings.lead_graph_client_id,
            settings.lead_graph_client_secret,
            settings.lead_email_from,
            settings.lead_email_to,
        )
    )


def _send_email(lead: LeadSubmissionRequest) -> None:
    settings = get_settings()
    tenant = settings.lead_graph_tenant_id.strip()
    sender = settings.lead_email_from.strip()
    recipient = settings.lead_email_to.strip()
    if not (tenant and sender and recipient and "@" in sender and "@" in recipient):
        raise ValueError("Invalid Graph email configuration")

    with httpx.Client(timeout=15) as client:
        token_response = client.post(
            f"https://login.microsoftonline.com/{quote(tenant, safe='')}/oauth2/v2.0/token",
            data={
                "client_id": settings.lead_graph_client_id,
                "client_secret": settings.lead_graph_client_secret,
                "scope": "https://graph.microsoft.com/.default",
                "grant_type": "client_credentials",
            },
        )
        token_response.raise_for_status()
        access_token = token_response.json()["access_token"]

        body = "\n".join(
            (
                "A visitor explicitly agreed to share this project enquiry.",
                "",
                f"Name: {lead.name}",
                f"Email: {lead.email}",
                f"Phone: {lead.phone or 'Not provided'}",
                f"Company: {lead.company or 'Not provided'}",
                "",
                "Project requirements:",
                lead.project_summary,
                "",
                f"Conversation ID: {lead.conversation_id}",
            )
        )
        response = client.post(
            f"https://graph.microsoft.com/v1.0/users/{quote(sender, safe='')}/sendMail",
            headers={"Authorization": f"Bearer {access_token}"},
            json={
                "message": {
                    "subject": "New Truefox AI project enquiry",
                    "body": {"contentType": "Text", "content": body},
                    "toRecipients": [
                        {"emailAddress": {"address": recipient}}
                    ],
                },
                "saveToSentItems": True,
            },
        )
        response.raise_for_status()
        if response.status_code != 202:
            raise ValueError("Graph did not accept the email request")


async def submit_lead(lead: LeadSubmissionRequest) -> bool:
    if not lead.consent_to_contact or not _configured():
        return False
    with transaction() as connection:
        claim = connection.execute(
            "INSERT OR IGNORE INTO lead_notifications(conversation_id,status,created_at) VALUES(?,?,?)",
            (lead.conversation_id, "pending", utcnow()),
        )
        if claim.rowcount == 0:
            row = connection.execute(
                "SELECT status FROM lead_notifications WHERE conversation_id=?",
                (lead.conversation_id,),
            ).fetchone()
            return bool(row and row["status"] == "sent")
    try:
        await asyncio.to_thread(_send_email, lead)
    except (OSError, httpx.HTTPError, ValueError, KeyError):
        logger.exception("lead_email_delivery_failed conversation_id=%s", lead.conversation_id)
        with transaction() as connection:
            connection.execute(
                "DELETE FROM lead_notifications WHERE conversation_id=? AND status='pending'",
                (lead.conversation_id,),
            )
        return False
    with transaction() as connection:
        connection.execute(
            "UPDATE lead_notifications SET status='sent', sent_at=? WHERE conversation_id=?",
            (utcnow(), lead.conversation_id),
        )
    logger.info("lead_email_delivered conversation_id=%s", lead.conversation_id)
    return True
