# WhatsApp Agent

**Status:** Built, awaiting deploy · **Owner:** Agent Hub · **Stage:** 01 · Ingestion & capture

The WhatsApp Agent turns a vendor's WhatsApp invoice into a draft bill. It uses the same Agent Hub → Bills → approval workflow as the [Email Agent](../agents/COMMUNICATION_AGENT.md). Finance staff still review, submit and approve every bill. The agent only prepares drafts.

## Documents

| # | Document | Read it for |
|---|---|---|
| 01 | [Product requirements (PRD)](01-prd.md) | Problem, users, scope, functional and non-functional requirements, release slices |
| 02 | [High-level design (HLD)](02-hld.md) | System context, components, deployment, data flow, trust boundaries |
| 03 | [Low-level design (LLD)](03-lld.md) | Class diagrams, schema (ERD), state machines, sequences, API contracts |
| 04 | [User flows](04-user-flows.md) | Step-by-step flow diagrams for each user |
| 05 | [Edge-case simulation](05-edge-case-simulation.md) | Failure and abuse scenarios, simulated step by step, with expected outcomes |
| 06 | [Success metrics](06-success-metrics.md) | KPIs, guardrails, formulas, targets and dashboards |
| 07 | [End-to-end plan](07-e2e-plan.md) | Phases, work breakdown, timeline, test plan, rollout and rollback |
| 08 | [Implementation and runbook](08-implementation-and-runbook.md) | What was built, differences from the design, deploy steps, troubleshooting |

## One-paragraph summary

A vendor sends a PDF invoice to the tenant's WhatsApp number (the Twilio Sandbox for the pilot). Twilio calls our signed webhook. We save the message and a job in PostgreSQL, then reply to Twilio. A worker that only sees one tenant and brand claims the job. It downloads the PDF into private storage and runs the **same** classification, OCR and duplicate/correction logic as the Email Agent. The result is a pending draft in Bills → Drafts with a WhatsApp badge. Every decision is recorded in the Agent Hub activity feed. Replies to vendors go out through a queue that checks consent and WhatsApp's 24-hour window.

## Related material

- The earlier proposals (`whatsapp-agent-prd.md`, `whatsapp-agent-technical-design.md` under `docs/agent-hub/01-ingestion/`) were removed in the docs reorganisation. This folder replaces them.
- [Vendor Bill Agent](../vendors/VENDOR_BILL_AGENT.md), [Agent Hub PRD](../agent-hub/PRD_AGENT_HUB.md), [Licensing and admin](../administration/LICENSING_AND_ADMIN.md)
- Code baseline: [agent.py](../../backend_ocr/app/routers/agent.py), [email_connection.py](../../backend_ocr/app/routers/email_connection.py), [licensing.py](../../backend_ocr/app/security/licensing.py), [services.py](../../backend_ocr/app/security/services.py)

## Terms

| Term | Meaning |
|---|---|
| Connection | One Twilio account and WhatsApp sender, linked to exactly one tenant and brand |
| Watch | A vendor contact's verified WhatsApp number that is enabled for intake |
| Inbound event | One Twilio webhook delivery, identified by its Message SID |
| Media job | One attachment from one inbound message, processed on its own |
| Draft | A row in `agent_draft_bills` with `status='pending'`, shown in Bills → Drafts |
| Customer service window | The 24 hours after the vendor's latest message, when free-form replies are allowed |
