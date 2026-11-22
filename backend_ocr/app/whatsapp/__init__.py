"""WhatsApp Agent — vendor WhatsApp invoice → draft bill.

Design: docs/whatsapp-agent/ (PRD, HLD, LLD). Module map:

  schema.py   — additive DDL (run via scripts/run_api_migrations.py)
  twilio.py   — provider adapter: signature check, media fetch, send, status rank
  repo.py     — connection / watch / scope helpers shared by ingress, worker, API
  ingress.py  — signed webhook → message + media jobs in one transaction
  intake.py   — channel-neutral bill intake: classify → OCR → dedupe → draft
  worker.py   — leased job queue in Postgres, retries, outbound reconciliation
  outbox.py   — reply policy (consent, 24h window, pause) and sending
"""
