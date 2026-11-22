# WhatsApp Agent: implementation status and deploy runbook

**Status:** Built (R1 inbound + R2 replies), not yet deployed. Provider: Twilio WhatsApp Sandbox.

## 1. What was built

| Area | Files |
|---|---|
| Schema (additive) | [whatsapp/schema.py](../../backend_ocr/app/whatsapp/schema.py), registered as `_ensure_whatsapp_tables` in [migrations.py](../../backend_ocr/app/migrations.py) |
| Twilio adapter (signature, media, send, status order) | [whatsapp/twilio.py](../../backend_ocr/app/whatsapp/twilio.py) (no Twilio SDK dependency) |
| Webhook ingress + triage | [whatsapp/ingress.py](../../backend_ocr/app/whatsapp/ingress.py), [routers/whatsapp_webhook.py](../../backend_ocr/app/routers/whatsapp_webhook.py) |
| Worker (leases, fencing, backoff, drain) | [whatsapp/worker.py](../../backend_ocr/app/whatsapp/worker.py), started in [main.py](../../backend_ocr/app/main.py) |
| Intake: classify → OCR → cross-channel dedupe → draft | [whatsapp/intake.py](../../backend_ocr/app/whatsapp/intake.py) |
| Replies: policy, idempotent send, reconcile unknown | [whatsapp/outbox.py](../../backend_ocr/app/whatsapp/outbox.py) |
| Agent Hub + conversations API | [routers/whatsapp_agent.py](../../backend_ocr/app/routers/whatsapp_agent.py) |
| Licensing | `whatsapp_agent` in [services.py](../../backend_ocr/app/security/services.py) and [licensing.py](../../backend_ocr/app/security/licensing.py); webhook prefix public in [auth.py](../../backend_ocr/app/security/auth.py) |
| Frontend | [WhatsAppAgentPanel.tsx](../../frontend/src/components/agenthub/WhatsAppAgentPanel.tsx), [api/whatsapp.ts](../../frontend/src/api/whatsapp.ts), Agent Hub fleet card, WhatsApp badge in Agent Hub and Bills → Drafts |
| Tests | [tests/test_whatsapp_agent.py](../../tests/test_whatsapp_agent.py) (48 cases, signature checked against the official Twilio SDK) |

Verified before deploy: 48 unit tests, and a 49-check simulation against a throwaway Postgres. It ran the real ingress, worker, dedupe and outbox code, with media, classifier and OCR stubbed. It covered cases A1–A6, B1, B5, C2, C3, C6, D1–D3, E1–E5, E7, E8, F1–F3, F5, H1–H6 and I-1 from [05-edge-case-simulation.md](05-edge-case-simulation.md). The webhook was also checked through the full FastAPI app: signed → 200 TwiML, bad signature → 403, tenant API without login → 401.

## 2. Differences from the design

| Design | Built | Why / follow-up |
|---|---|---|
| Extract `BillIntakeService` and move email onto it (B5/B6) | WhatsApp uses a new channel-neutral intake that **reuses** the email classifiers and OCR. The email path is unchanged | Keeps the email agent risk-free for the first deploy. **Gap:** WhatsApp checks email drafts for duplicates, but email does not yet check WhatsApp drafts. Move email onto `intake.decide_and_draft` next |
| Brand-scoped connection | One connection per tenant. Brand filter applies to activity, contacts and counts through the vendor's brand | Sandbox has one sender anyway |
| Templates outside the 24h window | Not supported. Reply is blocked with `WINDOW_CLOSED` | Needs approved templates (production, R3) |
| Idempotent submit (`submit_key`) | Not changed | Submit still uses the existing ReviewPage ingest flow |
| Image invoices | Rejected with a clear reason | v2 |

## 3. Deploy runbook

1. **Backend environment** (same place the other backend secrets live):
   ```
   TWILIO_ACCOUNT_SID=AC…
   TWILIO_AUTH_TOKEN=…
   TWILIO_WHATSAPP_FROM=+14155238886
   PUBLIC_BASE_URL=https://equal.collabup.co.in     # exact origin Twilio calls; recommended
   # optional: WA_WORKER_ENABLED=true (default), WA_WORKER_CONCURRENCY=2, WA_MEDIA_MAX_BYTES=16777216
   ```
2. **Migrate** the database the deployed API uses (the step is additive and safe to re-run):
   ```
   python3 scripts/run_api_migrations.py
   ```
   Without this, `GET /api/agent/whatsapp/status` returns 503 with this instruction.
3. **License.** If `LICENSE_ENFORCEMENT=enforce`, enable **WhatsApp Agent** for the tenant in the platform admin panel. In `log`/`off` modes nothing is needed.
4. **Deploy** backend and frontend.
5. **Connect.** As a tenant admin, open Integrations, select WhatsApp (Twilio) and choose **Connect Twilio**. The card shows two URLs.
6. **Twilio Console** → Messaging → Try it out → Send a WhatsApp message → **Sandbox settings**:
   - *When a message comes in* → the webhook URL, method **POST**
   - *Status callback URL* → the status URL, method **POST**
7. **Watch a contact.** Make sure the vendor contact has the phone number (for example `+919305654811`). Turn on its switch under **WhatsApp contacts**.
8. **Test.** From that phone (already joined to the sandbox) send `hi`. The card turns **Active**. Then send a PDF invoice. Within about a minute it appears in Activity as *Draft created* and in Bills → Drafts with a **WHATSAPP** badge.

## 4. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Card stays *Awaiting test message*, "Rejected requests" grows | URL in Twilio differs from what the server signs against, or the token was rotated | Set `PUBLIC_BASE_URL` to the exact origin and paste the URL again. After rotating the token, update `TWILIO_AUTH_TOKEN` and click Connect again |
| No activity at all | Webhook not saved in Twilio, or phone's sandbox join expired (3 days) | Re-save the URL. Re-send `join <code>` |
| *Skipped — not a watched contact* | Number on the contact doesn't match the sender | Fix the contact's phone (E.164) and turn the watch on |
| Jobs stuck *Processing…* | Worker not running on this instance | Check logs for `[whatsapp] worker started`, and `WA_WORKER_ENABLED` |
| Reply fails with Twilio error | Trial balance $0, or sandbox limits | Add trial credit. Replies only work within 24 h of the vendor's last message |

## 5. Rollback

Pause **Process incoming invoices** (messages are kept as *Held*), or **Disconnect**, or set `WA_WORKER_ENABLED=false`. All schema changes are additive. Reverting the code leaves the email agent unaffected.
