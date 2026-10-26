import asyncio
import logging
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import parseaddr

from app.config import get_settings
from app.database import transaction, utcnow
from app.schemas import LeadSubmissionRequest

logger = logging.getLogger(__name__)


def _configured() -> bool:
    settings = get_settings()
    return all(
        (
            settings.lead_smtp_host,
            settings.lead_smtp_username,
            settings.lead_smtp_password,
            settings.lead_email_from,
            settings.lead_email_to,
        )
    )


def _send_email(lead: LeadSubmissionRequest) -> None:
    settings = get_settings()
    sender = parseaddr(settings.lead_email_from)[1]
    recipient = parseaddr(settings.lead_email_to)[1]
    if not sender or not recipient or "\r" in sender or "\n" in recipient:
        raise ValueError("Invalid lead email configuration")
    message = EmailMessage()
    message["Subject"] = "New Truefox AI project enquiry"
    message["From"] = sender
    message["To"] = recipient
    message.set_content(
        "\n".join(
            [
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
            ]
        )
    )
    context = ssl.create_default_context()
    if settings.lead_smtp_ssl:
        with smtplib.SMTP_SSL(
            settings.lead_smtp_host,
            settings.lead_smtp_port,
            timeout=12,
            context=context,
        ) as server:
            server.login(settings.lead_smtp_username, settings.lead_smtp_password)
            server.send_message(message)
    else:
        with smtplib.SMTP(
            settings.lead_smtp_host,
            settings.lead_smtp_port,
            timeout=12,
        ) as server:
            server.ehlo()
            server.starttls(context=context)
            server.ehlo()
            server.login(settings.lead_smtp_username, settings.lead_smtp_password)
            server.send_message(message)


async def submit_lead(lead: LeadSubmissionRequest) -> bool:
    if not lead.consent_to_contact or not _configured():
        return False
    with transaction() as connection:
        claim = connection.execute(
            "INSERT OR IGNORE INTO lead_notifications(conversation_id,status,created_at) VALUES(?,?,?)",
            (lead.conversation_id, "pending", utcnow()),
        )
        if claim.rowcount == 0:
            return False
    try:
        await asyncio.to_thread(_send_email, lead)
    except (OSError, smtplib.SMTPException, ValueError):
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
