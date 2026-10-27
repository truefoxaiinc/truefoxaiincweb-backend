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

The backend verifies conversation capability, request schema and consent before attempting an OAuth2 Microsoft Graph sendMail request. A SQLite lead-notification ledger prevents duplicate sends for the same conversation. This is a handoff email, not a CRM workflow. The endpoint never sends raw transcripts, only the submitted, confirmed project summary.

## Microsoft 365 setup

Use Microsoft Graph **application** `Mail.Send` with admin consent. Register a dedicated app in Microsoft Entra ID, restrict its mailbox scope with Exchange Online RBAC for Applications, and use a dedicated, authorized sender mailbox (it can send to `info@truefoxaiinc.com`). The recipient is `info@truefoxaiinc.com`; sender must be an authorized mailbox.

Set the following only in production `.env`:

```dotenv
LEAD_GRAPH_TENANT_ID=<Directory tenant ID>
LEAD_GRAPH_CLIENT_ID=<Application client ID>
LEAD_GRAPH_CLIENT_SECRET=<Secret value>
LEAD_EMAIL_FROM=<approved-sender@truefoxaiinc.com>
LEAD_EMAIL_TO=info@truefoxaiinc.com
```

Do not use SMTP mailbox/app passwords. Graph responds with HTTP 202 when a message is accepted for delivery; **acceptance is not proof of inbox delivery**. Check the recipient inbox and message trace after a consented test. No credentials should be pasted into chat or committed to Git. Restrict app permission scope to only the sending mailbox.

## Deploy safely

- Review/merge the PR and run all tests before deployment.
- Use the existing, reviewed `deploy-production.sh` with the host-network Compose override, not a bare Compose command.
- Preserve SQLite backup; no reset or removal of existing documents.
- Confirm that the new container loaded SMTP environment variables without printing their values.
- Use a test conversation and explicit consent to verify recipient delivery before relying on it.
- No real message is sent by adding or merging this code; SMTP configuration and frontend integration are both required.
