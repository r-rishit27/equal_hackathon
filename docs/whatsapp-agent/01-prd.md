# WhatsApp Agent: product requirements

**Status:** Proposed · **First release:** Internal Twilio Sandbox pilot · **Entitlement:** `whatsapp_agent` (off by default)

## 1. Problem

Many Indian MSME vendors send invoices on WhatsApp, not email. Today AP staff download those PDFs from their phones, forward or re-upload them, and type in the details. That causes:

- **Lost or late invoices:** PDFs get buried in personal chats, miss due dates, and break vendor trust.
- **Duplicates:** the same invoice arrives on WhatsApp *and* email and is entered twice.
- **No audit trail:** nobody can tell where a bill came from or who touched it.
- **Data leakage:** financial documents sit on personal phones outside company controls.

The Email Agent already fixes this for email. The WhatsApp Agent brings the same automation, audit trail and human control to WhatsApp.

## 2. Goals and non-goals

### Goals
1. A watched vendor's WhatsApp PDF becomes **exactly one** reviewable draft, with no manual re-upload.
2. Use **one** bill workflow for every channel: the same classifier, OCR, duplicate check, drafts, ReviewPage and approvals.
3. Catch duplicates and corrections **across channels** (email and WhatsApp).
4. Record a visible outcome and reason for every inbound message.
5. Keep data strictly separated by tenant and brand, enforced in the API rather than only in the UI.
6. Keep humans in control: the agent never submits, approves or pays.

### Non-goals (this release)
- Photos or scans of invoices taken on a phone (JPEG/PNG). Planned for v2.
- Group chats, importing personal WhatsApp history, bulk or marketing messages.
- Payments, bank detail changes or approvals made from chat. **Chat text never authorizes money movement.**
- Fully automatic submission.

## 3. Users and permissions

| User | Goal | Allowed actions |
|---|---|---|
| Tenant admin | Set up intake for the right workspace and keep it running | Connect/disconnect, choose the brand, pause/resume inbound and outbound, manage watches |
| AP analyst | Turn every valid invoice into an accurate bill | See scoped activity, open original PDFs, edit, discard or submit drafts, resolve corrections |
| AP approver | Approve submitted bills with confidence | Existing approval workflow, plus a view of where the bill came from |
| Vendor contact | Get paid without changing habits | Join the Sandbox (pilot), send a PDF with an optional caption, receive replies |
| Platform operator | Keep the pipeline healthy | Redacted health checks, retry and dead-letter queues, alerts |

## 4. Scope by release

| Capability | R1 Sandbox pilot | R2 Communications parity | R3 Production |
|---|---|---|---|
| Connect / test / pause / disconnect | ✅ | ✅ | ✅ registered sender |
| Watch per contact (E.164) | ✅ | ✅ | ✅ |
| PDF intake → classify → OCR → draft | ✅ | ✅ | ✅ |
| Activity feed with reasons | ✅ | ✅ | ✅ |
| Duplicate and correction check across channels | ✅ | ✅ | ✅ |
| WhatsApp badge and source details in Drafts/ReviewPage | ✅ | ✅ | ✅ |
| Vendor Conversations timeline, summary, save attachment | — | ✅ | ✅ |
| Outbound replies (consent, 24h window, templates) | — | ✅ (Sandbox limits) | ✅ |
| Image invoices, multi-page photo stitching | — | — | v2 |

## 5. Functional requirements

### 5.1 Connection
- **FR-1** An admin can create a connection in Agent Hub → WhatsApp by choosing a tenant and brand and entering the Twilio account and sender details. The secret is stored through the existing secret-management pattern and only ever shown masked.
- **FR-2** The connection card shows `Disconnected · Awaiting test · Active · Paused · Needs attention`. **Active** requires one successful test message.
- **FR-3** Inbound and outbound can be paused separately. Pausing never deletes data.
- **FR-4** A Twilio account and sender pair can be linked to at most one active connection.

### 5.2 Watching contacts
- **FR-5** On a vendor contact, a user with vendor-management permission can turn on **WhatsApp watch**. The number must be valid E.164. This switch is separate from the email `agent_enabled` flag.
- **FR-6** If the same number is actively watched for two vendors in the same brand, the conflict is shown and processing is blocked (the messages are quarantined) until a person resolves it.
- **FR-7** Messages from unwatched numbers are logged with minimal metadata. Their media is **never** downloaded.

### 5.3 Intake and processing
- **FR-8** Each PDF in a message is processed on its own (one media job per attachment).
- **FR-9** Text-only messages and unsupported files (images, docx, zip) appear in the activity feed with a reason and never produce a draft.
- **FR-10** Supported PDFs go through the shared classifier (bill / contract / other) and then shared OCR. A classifier failure never defaults to "bill". It is retried or sent to review.
- **FR-11** The same Message SID delivered again by Twilio has no further effect.
- **FR-12** An invoice that already exists (same vendor, invoice number and amount, or same file hash) as a pending draft **or** posted bill, from **any** channel, is recorded as a duplicate with a link to the existing record. No new draft is created.
- **FR-13** Same vendor and invoice number with different important fields (amount, tax, date) becomes a **correction candidate**. It shows the changed fields and the earlier record. The posted bill is never changed automatically.

### 5.4 Review and submit
- **FR-14** Bills → Drafts shows a WhatsApp badge, the vendor, the masked number (`+91 98•••••210`), received time, the original PDF and the extracted fields.
- **FR-15** Submit uses the existing ingest and approval endpoints. A draft can produce at most one bill, even with retries or two open tabs.
- **FR-16** Discard records who discarded it and the reason, and keeps the audit trail.

### 5.5 Communications (R2)
- **FR-17** Vendor Conversations shows WhatsApp threads with direction, timestamps, media and linked bills.
- **FR-18** Summaries and suggested replies are clearly labelled as suggestions.
- **FR-19** A reply is allowed only if the contact has opted in and either the 24-hour window is open or an approved template is used. Otherwise the UI explains why it can't be sent.
- **FR-20** Message status is shown as `queued · sent · delivered · read · failed · unknown`.

### 5.6 Operations
- **FR-21** Refresh shows live counts and triggers a limited drain of pending and retryable jobs in the selected scope.
- **FR-22** Operators can retry temporary failures without creating extra drafts.
- **FR-23** On resume, the admin sees how many items piled up while paused and how old the oldest is, and chooses to process or discard them.

## 6. Non-functional requirements

| Area | Requirement |
|---|---|
| Latency | Webhook acknowledged in under 2 s (P95). Accepted message to draft in under 2 min (P95) |
| Reliability | No message lost after acknowledgement. Processing is exactly-once in effect (idempotent at every step) |
| Isolation | Tenant and brand resolved only from the connection key. Every read and write is filtered on the server. Two-tenant isolation test required before exit |
| Security | Twilio signature checked on every webhook. Secrets in the secret store. Media fetched only from allowed hosts. PDFs stored privately, never at public URLs |
| Privacy | Phone numbers masked in the UI and redacted in logs. Workspace retention rules apply to messages, PDFs and backups |
| AI safety | Chat and OCR text treated as untrusted input. Model outputs follow a fixed schema and can never trigger money movement or record changes |
| Availability | If the worker is down, messages queue up and are processed after recovery. Inbound and outbound can be paused for rollback |
| Compatibility | Email Agent routes and clients keep working. Database changes are additive only |

## 7. Pilot acceptance

| # | Scenario | Pass condition |
|---|---|---|
| A1 | Watched vendor sends a valid invoice PDF | One pending draft with PDF, vendor and WhatsApp details opens in ReviewPage |
| A2 | Unknown, unwatched or ambiguous number | No draft, no match in another brand. The reason is visible to authorized users |
| A3 | Text-only message or wrong file type | Outcome shown in the activity feed. No OCR |
| A4 | Same message delivered twice, or same PDF also emailed | One draft. The duplicate is linked to it with a reason |
| A5 | Same invoice number, revised amount | Correction candidate showing the differences. Posted bill untouched |
| A6 | Worker crash during processing, or double Submit click | Converges: no extra drafts or bills |
| A7 | Tenant, brand, role or license revoked | Access to messages, PDFs, drafts and counts blocked at once by the API |
| A8 | Outbound (R2) | Allowed send records its status. Opted-out contact, expired window or trial limit is rejected with a clear reason |

## 8. Dependencies and constraints

- **Twilio trial:** 30 days, about 100 WhatsApp trial units. Sandbox sign-ups expire after 3 days. Custom outbound messages are limited. Check the remaining units in the Console before any demo.
- **Production:** needs a registered WhatsApp Business sender, opt-in and template setup, and a paid plan.
- **Internal:** shared classifier and OCR (`process_pdf_async`), `agent_draft_bills`, licensing service registry, object store.

## 9. Open questions

1. Should Sandbox and production run side by side for a while, or is the switch a hard cutover per tenant?
2. Who approves message templates: the tenant admin or the platform team?
3. Retention for vendor chat text: same as email (`poc_email_messages`) or shorter?
4. Should a correction candidate tell the original submitter automatically?
