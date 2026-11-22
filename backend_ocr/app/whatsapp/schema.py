"""WhatsApp Agent schema — additive only. See docs/whatsapp-agent/03-lld.md §4.

Runs from scripts/run_api_migrations.py (MIGRATION_STEPS), after the agent
tables exist because it ALTERs agent_draft_bills. Safe to re-run.
"""
from __future__ import annotations

import traceback

from ..config import get_conn, put_conn

DDL = """
-- One Twilio account+sender bound to one tenant (brand optional = all brands).
CREATE TABLE IF NOT EXISTS whatsapp_connections (
    id                uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id         uuid        NOT NULL,
    brand_id          uuid,
    connection_key    text        NOT NULL UNIQUE,
    account_sid       text        NOT NULL,
    sender_e164       text        NOT NULL,
    secret_ref        text        NOT NULL,      -- 'env' or 'enc:<ciphertext>'
    state             text        NOT NULL DEFAULT 'AWAITING_TEST',
    inbound_enabled   boolean     NOT NULL DEFAULT true,
    outbound_enabled  boolean     NOT NULL DEFAULT true,
    signature_failures int        NOT NULL DEFAULT 0,
    last_inbound_at   timestamptz,
    last_processed_at timestamptz,
    created_by        text,
    created_at        timestamptz NOT NULL DEFAULT now(),
    updated_at        timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_wac_tenant_active ON whatsapp_connections (tenant_id)
    WHERE state <> 'DISCONNECTED';
CREATE UNIQUE INDEX IF NOT EXISTS uq_wac_binding ON whatsapp_connections (account_sid, sender_e164)
    WHERE state <> 'DISCONNECTED';

-- Per-contact WhatsApp watch, independent of the email agent_enabled flag.
CREATE TABLE IF NOT EXISTS whatsapp_contact_watches (
    id              uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       uuid        NOT NULL,
    supplier_id     uuid        NOT NULL,
    contact_id      uuid        NOT NULL,
    phone_e164      text        NOT NULL,
    watch_enabled   boolean     NOT NULL DEFAULT true,
    consent         text        NOT NULL DEFAULT 'UNKNOWN',   -- UNKNOWN | OPTED_IN | OPTED_OUT
    consent_at      timestamptz,
    last_inbound_at timestamptz,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, contact_id)
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_wcw_active_phone ON whatsapp_contact_watches (tenant_id, phone_e164)
    WHERE watch_enabled;

-- Inbound and outbound messages. Inbound dedupes on Message SID, outbound on op_key.
CREATE TABLE IF NOT EXISTS whatsapp_messages (
    id               uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id        uuid        NOT NULL,
    connection_id    uuid        NOT NULL,
    direction        text        NOT NULL,              -- inbound | outbound
    message_sid      text,
    op_key           text,
    from_e164        text,
    to_e164          text,
    watch_id         uuid,
    supplier_id      uuid,
    contact_id       uuid,
    body             text,
    num_media        int         NOT NULL DEFAULT 0,
    outcome          text        NOT NULL DEFAULT 'RECEIVED',
    outcome_reason   text,
    provider_status  text,                              -- outbound: QUEUED|SENT|DELIVERED|READ|FAILED|UNKNOWN|REJECTED
    error_code       text,
    sent_by          text,
    received_at      timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_wam_sid ON whatsapp_messages (connection_id, message_sid)
    WHERE message_sid IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_wam_op  ON whatsapp_messages (tenant_id, op_key)
    WHERE op_key IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_wam_tenant_time ON whatsapp_messages (tenant_id, received_at DESC);
CREATE INDEX IF NOT EXISTS ix_wam_supplier    ON whatsapp_messages (tenant_id, supplier_id, received_at DESC);
CREATE INDEX IF NOT EXISTS ix_wam_unknown     ON whatsapp_messages (provider_status, updated_at)
    WHERE provider_status = 'UNKNOWN';

-- One job per attachment; the queue the worker drains with leases.
CREATE TABLE IF NOT EXISTS whatsapp_media_jobs (
    id               uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id        uuid        NOT NULL,
    message_id       uuid        NOT NULL REFERENCES whatsapp_messages(id),
    media_index      int         NOT NULL,
    media_url        text        NOT NULL,
    content_type     text,
    state            text        NOT NULL DEFAULT 'PENDING', -- PENDING|HELD|CLAIMED|RETRY_WAIT|DONE|DEAD|QUARANTINED
    attempts         int         NOT NULL DEFAULT 0,
    lease_token      uuid,
    lease_expires_at timestamptz,
    next_attempt_at  timestamptz NOT NULL DEFAULT now(),
    force_bill       boolean     NOT NULL DEFAULT false,
    content_sha256   text,
    source_file      text,
    decision         text,
    failure_code     text,
    detail           text,
    draft_id         uuid,
    created_at       timestamptz NOT NULL DEFAULT now(),
    finished_at      timestamptz,
    UNIQUE (message_id, media_index)
);
CREATE INDEX IF NOT EXISTS ix_wmj_ready ON whatsapp_media_jobs (state, next_attempt_at)
    WHERE state IN ('PENDING', 'RETRY_WAIT', 'CLAIMED');
CREATE INDEX IF NOT EXISTS ix_wmj_tenant ON whatsapp_media_jobs (tenant_id, created_at DESC);

-- Outbound status history (the current projection lives on whatsapp_messages).
CREATE TABLE IF NOT EXISTS whatsapp_status_events (
    id           uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id    uuid        NOT NULL,
    message_id   uuid,
    provider_sid text        NOT NULL,
    status       text        NOT NULL,
    error_code   text,
    received_at  timestamptz NOT NULL DEFAULT now(),
    UNIQUE (provider_sid, status)
);

-- Draft provenance, channel-neutral. Legacy rows are email.
ALTER TABLE agent_draft_bills ADD COLUMN IF NOT EXISTS source_channel  text NOT NULL DEFAULT 'email';
ALTER TABLE agent_draft_bills ADD COLUMN IF NOT EXISTS source_ref      text;
ALTER TABLE agent_draft_bills ADD COLUMN IF NOT EXISTS sender_masked   text;
ALTER TABLE agent_draft_bills ADD COLUMN IF NOT EXISTS content_sha256  text;
ALTER TABLE agent_draft_bills ADD COLUMN IF NOT EXISTS idempotency_key text;
ALTER TABLE agent_draft_bills ADD COLUMN IF NOT EXISTS related_draft_id uuid;
ALTER TABLE agent_draft_bills ADD COLUMN IF NOT EXISTS diff            jsonb;
CREATE UNIQUE INDEX IF NOT EXISTS uq_adb_idem ON agent_draft_bills (tenant_id, idempotency_key)
    WHERE idempotency_key IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_adb_sha ON agent_draft_bills (tenant_id, content_sha256)
    WHERE content_sha256 IS NOT NULL;
"""


def ensure_whatsapp_tables() -> None:
    conn = None
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute(DDL)
        conn.commit()
        put_conn(conn)
        print("[startup] whatsapp agent tables ready")
    except Exception:
        if conn:
            put_conn(conn, close=True)
        print("[startup] ERROR creating whatsapp agent tables:")
        traceback.print_exc()
