# WhatsApp Agent product requirements

**Status:** Proposed · **Product:** Onsumm Agent Hub · **First release:** Internal Twilio Sandbox pilot

## Outcome

Finance teams can turn a vendor's WhatsApp invoice into a reviewable bill through the same Agent Hub and Bills workflow they use for email. They can see which contacts are watched, what happened to each message, and why a document was drafted, skipped, or flagged as a correction. Finance retains control over bill submission and approval.

The baseline is the [Vendor Bill Agent](../../VENDOR_BILL_AGENT.md), the [Agent Hub screen](../../../frontend/src/pages/AgentHubPage.tsx), and [vendor inbox workflows](../../../backend_ocr/app/routers/email_connection.py). The [technical design](whatsapp-agent-technical-design.md) describes the proposed implementation.

## Users and permissions

| User | Needs | Permitted actions |
|---|---|---|
| Tenant administrator | Set up and monitor intake for the right workspace | Configure the integration if authorized, set its brand scope, pause/resume, manage watched contacts |
| AP analyst | See every intake outcome and prepare accurate bills | Read scoped activity, open originals, edit drafts, resolve evidence, discard or submit using existing permissions |
| AP approver | Review an invoice already submitted by AP | Use the normal approval workflow and view source provenance where permitted |
| Vendor contact | Send an invoice from a known WhatsApp number | Join the pilot Sandbox and send a PDF with optional context or corrections |
| Platform operator | Diagnose connectivity and processing failures | Inspect redacted health and retry queues through existing operational controls |

## Email parity and channel behavior

| Capability | WhatsApp requirement | Release |
|---|---|---|
| Connect and disconnect | Admin configures Twilio Sandbox connection, sees test/health state, can pause or disconnect independently of Email | Sandbox |
| Watch and unwatch vendor contacts | Store one verified WhatsApp identity per watch record. Reuse Vendor Contacts and Agent Hub entry points with independent email and WhatsApp watch flags | Sandbox |
| Refresh | Refresh live counters and run a bounded drain of received/retryable jobs. Show last inbound and last processed timestamps | Sandbox |
| Classify and extract | Watched contact + supported PDF becomes eligible for invoice classification and shared OCR. Text-only and unsupported files remain visible as activity with a clear reason | Sandbox |
| Draft review | Show WhatsApp source, vendor, masked number, original PDF, extracted fields, classification, and prior bill/draft reference. Use the existing Bills Draft tab and ReviewPage | Sandbox |
| Duplicate and correction handling | Suppress exact replays and duplicate invoices across both channels. Flag corrections for human review, preserve original evidence and link the related draft or posted invoice | Sandbox |
| Draft lifecycle | Review, edit, discard or submit to the existing approval workflow, with the same authorization as email | Sandbox |
| Vendor communications | Show scoped WhatsApp conversations, attachments, bill links, thread summary, and follow-up state in Vendor Conversations. Offer authorized save-to-vendor and manual draft creation from eligible evidence | Application parity |
| Vendor replies | Authorized humans can send or draft follow-up messages, see delivery status and failure reasons. Enforce consent, the customer service window and template rules | Application parity, with live sending subject to provider eligibility |

The pilot starts with PDFs to match automated email intake. Phone-photo capture, group-chat intake, personal WhatsApp history import, bulk outreach, and payments in chat are outside this release. Each PDF candidate is processed independently when the provider delivers more than one. Chat text may help interpret an invoice but cannot authorize a payment or change vendor bank details.

## Experience and requirements

1. **Connect.** In Agent Hub → WhatsApp, an administrator selects the authorized brand scope and follows the Sandbox setup. The card shows Disconnected, Awaiting test, Active, Paused, or Needs attention. A joined test contact sends a message to confirm routing before the pilot opens. Only internal test contacts and synthetic invoices are used in the Sandbox.
2. **Watch.** A user with vendor-management permissions selects a vendor contact and enables WhatsApp watch. The system validates the E.164 number and surfaces ambiguous ownership before processing. Existing email settings remain independent.
3. **Receive.** The activity feed shows receipt, processing and outcome. Provide filters for vendor, outcome and date. Use the selected brand consistently for cards, counts, activity, and draft links. Switching brands clears stale data from the previous view.
4. **Review.** Bills → Drafts displays a WhatsApp badge and lets AP open the original PDF with extracted fields. When the vendor sends a correction, show the changed fields and linked prior record where available. Decisions use documented reasons for unreadable PDFs, duplicates, ambiguity, and non-invoices.
5. **Submit.** Existing bill review and approval screens retain validation and permission checks. A draft creates at most one submitted bill, including when the operator retries or works from two tabs. Discard records the disposition and preserves the audit reference.
6. **Follow up.** Vendor Conversations presents channel, direction, timestamps, contact, media, and linked cases. Thread summarization and any draft reply are marked as suggestions. Show why sending is unavailable when a recipient is opted out, unenrolled, outside the allowed window, or incompatible with the current trial mode.
7. **Recover.** Operators can retry transient OCR or retrieval failures without creating another draft. Administrators can pause intake and outbound separately. On resume, operators decide whether to drain buffered documents after checking their age and scope.

## Pilot acceptance

| Scenario | Observable pass condition |
|---|---|
| Joined, watched vendor sends a supported invoice | One pending draft opens in the normal bill editor with PDF, vendor and source metadata |
| Unknown, unwatched, or ambiguous number | No draft and no cross-brand match. Authorized operator sees a scoped reason |
| Text-only message or wrong MIME type | Activity outcome is visible. No automated OCR draft |
| Same message delivered twice or same PDF arrives via email | One effective draft, duplicate evidence linked or recorded with a reason |
| Same invoice number with revised amount | Correction candidate displays prior record and differences. Posted bill remains untouched until an authorized human follows the existing workflow |
| Worker crash or duplicate Submit click | Reprocessing converges without extra drafts or bills |
| Tenant, brand, role, or license changes | Inaccessible conversations, originals, draft details and aggregate counts are blocked immediately at the API |
| Outbound parity milestone | Allowed send records status. Unsupported trial send, opted-out contact and expired window get actionable rejection |

Track received-to-draft time, actionable invoice yield, duplicate suppression, OCR failures, unmatched sender rate, median human review time, and trial usage. Pilot exit requires all acceptance cases for the enabled release, a verified two-tenant isolation test, and explicit approval before using real vendor data or registered production senders.

## Trial and production scope

Twilio documents a 30-day trial and 100 WhatsApp trial units, plus shared Sandbox sender restrictions. Participants join explicitly and Sandbox enrollment expires after three days. Free-form outbound content is subject to a 24-hour customer service window and account-specific trial limitations. Confirm remaining units and custom-send eligibility in the Console before scheduling the demo. Production requires a registered sender, applicable consent and template setup, and a paid operating plan. [Twilio trial](https://www.twilio.com/docs/usage/trials) · [WhatsApp Sandbox](https://www.twilio.com/docs/whatsapp/sandbox) · [Trial WhatsApp restrictions](https://www.twilio.com/docs/usage/trials/try-out-whatsapp)
