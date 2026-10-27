# Consented chatbot lead notification

This feature is **opt-in**. The TFX model may propose sharing an enquiry near the end of a meaningful project discussion. It does not send emails from conversation text or automatically mail transcripts.

## Frontend integration required

1. After relevant discovery, show a short summary of the customer's project.
2. Ask for name, email and optionally phone/company; show an **unchecked** consent checkbox: "I agree to share these details and my project summary with Truefox AI so the team can contact me about my enquiry."
3. Only after an explicit Submit action, POST `/api/v1/leads` with JSON: `conversation_id`, `name`, `email`, `phone`, `company`, `project_summary`, `consent_to_contact: true`.
4. Include `X-Conversation-Capability` header from the existing chat/stream metadata. Do not expose this token to third-party analytics or place it in a URL.
5. On `sent`, show "Your enquiry was emailed to the Truefox AI team." On `not_sent`, show a delivery failure and a verified alternative contact path. Do not pretend a lead was sent based on AI text alone.
6. Do not make submission mandatory to continue the conversation. Consent must be optional.

Example request:

```json
{
  "conversation_id": "conversation-uuid",
  "name": "Example Customer",
  "email": "customer@example.com",
  "phone": "+1 ...",
  "company": "Example Restaurant",
  "project_summary": "Interested in kitchen AI monitoring across existing cameras.",
  "consent_to_contact": true
}
```

The backend verifies conversation capability, request schema and consent before attempting an authenticated TLS email. A SQLite lead-notification ledger prevents duplicate sends for the same conversation. This is a handoff email, not a CRM workflow. The endpoint never sends raw transcripts, only the submitted, confirmed project summary.

## Server configuration

Set the following **only in the production .env** (never commit secrets):

```dotenv
LEAD_SMTP_HOST=smtp.example.com
LEAD_SMTP_PORT=587
LEAD_SMTP_USERNAME=notification-account@example.com
LEAD_SMTP_PASSWORD=replace-with-app-password
LEAD_EMAIL_FROM=notification-account@example.com
LEAD_EMAIL_TO=info@truefoxaiinc.com
LEAD_SMTP_SSL=false
```

Use port 465 and `LEAD_SMTP_SSL=true` only when the provider requires implicit TLS. SMTP must support authentication and certificate verification; the 587 flow requires STARTTLS.

## Deploy safely

- Review/merge the PR and run all tests before deployment.
- Use the existing, reviewed `deploy-production.sh` with the host-network Compose override, not a bare Compose command.
- Preserve SQLite backup; no reset or removal of existing documents.
- Confirm that the new container loaded SMTP environment variables without printing their values.
- Use a test conversation and explicit consent to verify recipient delivery before relying on it.
- No real message is sent by adding or merging this code; SMTP configuration and frontend integration are both required.
