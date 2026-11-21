"""Cash Flow Forecast DDL (docs/cashflow-forecast/04_LLD.md §6.2).

Idempotent: every statement is IF NOT EXISTS. Applied by
migrations._ensure_cash_forecast_tables. Money is BIGINT paise.
"""

DDL: tuple[str, ...] = (
    """CREATE TABLE IF NOT EXISTS cf_settings (
    tenant_id                           UUID PRIMARY KEY,
    reserve_paise                       BIGINT NOT NULL DEFAULT 0 CHECK (reserve_paise >= 0),
    horizon_days                        INT NOT NULL DEFAULT 30 CHECK (horizon_days BETWEEN 7 AND 91),
    timezone                            TEXT NOT NULL DEFAULT 'Asia/Kolkata',
    default_view                        TEXT NOT NULL DEFAULT 'expected'
                                        CHECK (default_view IN ('expected','downside','no_collections')),
    include_pending_approval_ap         BOOLEAN NOT NULL DEFAULT true,
    overdue_fallback_days               INT NOT NULL DEFAULT 5,
    downside_exclude_overdue_after_days INT NOT NULL DEFAULT 60,
    min_customer_history                INT NOT NULL DEFAULT 3,
    allow_self_approval                 BOOLEAN NOT NULL DEFAULT false,
    publish_daily                       BOOLEAN NOT NULL DEFAULT true,
    updated_at                          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_by                          TEXT
)""",
    """CREATE TABLE IF NOT EXISTS cf_holidays (
    tenant_id    UUID NOT NULL,
    holiday_date DATE NOT NULL,
    name         TEXT NOT NULL,
    PRIMARY KEY (tenant_id, holiday_date)
)""",
    """CREATE TABLE IF NOT EXISTS cf_account_settings (
    tenant_id           UUID NOT NULL,
    bank_account_id     UUID NOT NULL,
    include_in_forecast BOOLEAN NOT NULL,
    od_limit_paise      BIGINT NOT NULL DEFAULT 0 CHECK (od_limit_paise >= 0),
    PRIMARY KEY (tenant_id, bank_account_id)
)""",
    """CREATE TABLE IF NOT EXISTS cf_bank_balances (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL,
    bank_account_id UUID NOT NULL,
    balance_paise   BIGINT NOT NULL,                 -- negative allowed (OD drawn)
    as_of           TIMESTAMPTZ NOT NULL,
    source          VARCHAR(16) NOT NULL CHECK (source IN ('manual','statement','api')),
    source_ref      TEXT,
    created_by      TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
)""",
    """CREATE INDEX IF NOT EXISTS idx_cf_bank_balances_latest ON cf_bank_balances (tenant_id, bank_account_id, as_of DESC)""",
    """CREATE TABLE IF NOT EXISTS cf_recurring_items (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id         UUID NOT NULL,
    name              TEXT NOT NULL CHECK (length(name) BETWEEN 1 AND 120),
    category          VARCHAR(16) NOT NULL,
    direction         VARCHAR(3) NOT NULL CHECK (direction IN ('in','out')),
    amount_paise      BIGINT CHECK (amount_paise > 0),           -- NULL = template awaiting amount
    frequency         VARCHAR(10) NOT NULL CHECK (frequency IN ('weekly','monthly','quarterly')),
    anchor            TEXT NOT NULL,                             -- '0'..'6' | '1'..'31' | 'last_banking_day'
    quarter_months    SMALLINT[],
    business_day_rule VARCHAR(24) NOT NULL DEFAULT 'next_banking_day',
    confidence        VARCHAR(10) NOT NULL DEFAULT 'committed' CHECK (confidence IN ('committed','estimated')),
    statutory         BOOLEAN NOT NULL DEFAULT false,
    bank_account_id   UUID,
    start_date        DATE NOT NULL,
    end_date          DATE,
    active            BOOLEAN NOT NULL DEFAULT true,
    version           INT NOT NULL DEFAULT 1,
    created_by        TEXT NOT NULL,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (end_date IS NULL OR end_date >= start_date)
)""",
    """CREATE INDEX IF NOT EXISTS idx_cf_recurring_active ON cf_recurring_items (tenant_id) WHERE active""",
    """CREATE TABLE IF NOT EXISTS cf_adjustments (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id    UUID NOT NULL,
    name         TEXT NOT NULL,
    category     VARCHAR(16) NOT NULL,
    direction    VARCHAR(3) NOT NULL CHECK (direction IN ('in','out')),
    amount_paise BIGINT NOT NULL CHECK (amount_paise > 0),
    on_date      DATE NOT NULL,
    confidence   VARCHAR(10) NOT NULL CHECK (confidence IN ('committed','estimated')),
    note         TEXT,
    plan_id      UUID,                                           -- set when adopted from a plan
    active       BOOLEAN NOT NULL DEFAULT true,
    created_by   TEXT NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
)""",
    """CREATE INDEX IF NOT EXISTS idx_cf_adjustments_date ON cf_adjustments (tenant_id, on_date) WHERE active""",
    """CREATE TABLE IF NOT EXISTS cf_payment_windows (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id     UUID NOT NULL,
    invoice_id    UUID NOT NULL,                                 -- fact_invoices.invoice_id (AP)
    earliest_date DATE NOT NULL,
    latest_date   DATE NOT NULL CHECK (latest_date >= earliest_date),
    agreed_with   TEXT NOT NULL,
    evidence      TEXT NOT NULL,
    attachment_id UUID,                                          -- bill_attachments.id
    active        BOOLEAN NOT NULL DEFAULT true,
    recorded_by   TEXT NOT NULL,
    recorded_at   TIMESTAMPTZ NOT NULL DEFAULT now()
)""",
    """CREATE UNIQUE INDEX IF NOT EXISTS uq_cf_payment_windows_active ON cf_payment_windows (tenant_id, invoice_id) WHERE active""",
    """CREATE TABLE IF NOT EXISTS cf_collection_promises (
    id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id             UUID NOT NULL,
    invoice_id            UUID NOT NULL,                         -- ar_invoices.id
    promised_date         DATE NOT NULL,
    promised_amount_paise BIGINT NOT NULL CHECK (promised_amount_paise > 0),
    source                VARCHAR(12) NOT NULL CHECK (source IN ('call','email','meeting','portal','other')),
    note                  TEXT,
    active                BOOLEAN NOT NULL DEFAULT true,
    recorded_by           TEXT NOT NULL,
    recorded_at           TIMESTAMPTZ NOT NULL DEFAULT now()
)""",
    """CREATE UNIQUE INDEX IF NOT EXISTS uq_cf_promises_active ON cf_collection_promises (tenant_id, invoice_id) WHERE active""",
    """CREATE TABLE IF NOT EXISTS cf_planned_dates (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id    UUID NOT NULL,
    source_type  VARCHAR(16) NOT NULL,                           -- bill | schedule | recurring | adjustment
    source_id    TEXT NOT NULL,
    planned_date DATE NOT NULL,
    plan_id      UUID NOT NULL,
    active       BOOLEAN NOT NULL DEFAULT true,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
)""",
    """CREATE UNIQUE INDEX IF NOT EXISTS uq_cf_planned_active ON cf_planned_dates (tenant_id, source_type, source_id) WHERE active""",
    """CREATE TABLE IF NOT EXISTS cf_snapshots (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id         UUID NOT NULL,
    revision          INT NOT NULL CHECK (revision > 0),
    as_of             TIMESTAMPTZ NOT NULL,
    start_date        DATE NOT NULL,
    horizon_days      INT NOT NULL,
    reserve_paise     BIGINT NOT NULL,
    od_headroom_paise BIGINT NOT NULL DEFAULT 0,
    coverage          JSONB NOT NULL,
    content_hash      CHAR(64) NOT NULL,
    reason            VARCHAR(12) NOT NULL CHECK (reason IN ('scheduled','manual','plan','fixture')),
    built_by          TEXT NOT NULL,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, revision),
    UNIQUE (tenant_id, id)
)""",
    """CREATE INDEX IF NOT EXISTS idx_cf_snapshots_latest ON cf_snapshots (tenant_id, revision DESC)""",
    """CREATE TABLE IF NOT EXISTS cf_snapshot_balances (
    tenant_id       UUID NOT NULL,
    snapshot_id     UUID NOT NULL,
    bank_account_id UUID NOT NULL,
    account_name    TEXT NOT NULL,
    account_mask    TEXT,
    balance_paise   BIGINT NOT NULL,
    as_of           TIMESTAMPTZ NOT NULL,
    source          VARCHAR(16) NOT NULL,
    freshness       VARCHAR(8) NOT NULL,
    PRIMARY KEY (snapshot_id, bank_account_id),
    FOREIGN KEY (tenant_id, snapshot_id) REFERENCES cf_snapshots (tenant_id, id) ON DELETE CASCADE
)""",
    """CREATE TABLE IF NOT EXISTS cf_snapshot_events (
    tenant_id           UUID NOT NULL,
    snapshot_id         UUID NOT NULL,
    event_key           TEXT NOT NULL,
    source_type         VARCHAR(16) NOT NULL,
    source_id           TEXT NOT NULL,
    label               TEXT NOT NULL,
    counterparty        TEXT,
    counterparty_id     TEXT,
    document_number     TEXT,
    direction           VARCHAR(3) NOT NULL CHECK (direction IN ('in','out')),
    amount_paise        BIGINT NOT NULL CHECK (amount_paise > 0),
    category            VARCHAR(16) NOT NULL,
    confidence          VARCHAR(10) NOT NULL,
    date_expected       DATE,
    date_downside       DATE,
    date_no_collections DATE,
    date_basis          JSONB NOT NULL,
    nominal_date        DATE,
    window_earliest     DATE,
    window_latest       DATE,
    fixed               BOOLEAN NOT NULL DEFAULT false,
    link_path           TEXT,
    PRIMARY KEY (snapshot_id, event_key),
    FOREIGN KEY (tenant_id, snapshot_id) REFERENCES cf_snapshots (tenant_id, id) ON DELETE CASCADE,
    CHECK (date_expected IS NOT NULL OR date_downside IS NOT NULL OR date_no_collections IS NOT NULL)
)""",
    """CREATE INDEX IF NOT EXISTS idx_cf_events_exp ON cf_snapshot_events (snapshot_id, date_expected)""",
    """CREATE TABLE IF NOT EXISTS cf_snapshot_exclusions (
    tenant_id    UUID NOT NULL,
    snapshot_id  UUID NOT NULL,
    source_type  VARCHAR(16) NOT NULL,
    source_id    TEXT NOT NULL,
    reason       VARCHAR(32) NOT NULL,
    label        TEXT NOT NULL,
    amount_paise BIGINT NOT NULL,
    detail       TEXT,
    views        TEXT[] NOT NULL,
    link_path    TEXT,
    PRIMARY KEY (snapshot_id, source_type, source_id, reason),
    FOREIGN KEY (tenant_id, snapshot_id) REFERENCES cf_snapshots (tenant_id, id) ON DELETE CASCADE
)""",
    """CREATE TABLE IF NOT EXISTS cf_scenarios (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id   UUID NOT NULL,
    name        TEXT NOT NULL CHECK (length(name) BETWEEN 1 AND 120),
    description TEXT,
    snapshot_id UUID NOT NULL,
    revision    INT NOT NULL,
    view        VARCHAR(16) NOT NULL,
    overrides   JSONB NOT NULL DEFAULT '[]',
    status      VARCHAR(16) NOT NULL DEFAULT 'ok' CHECK (status IN ('ok','needs_review')),
    version     INT NOT NULL DEFAULT 1,
    archived    BOOLEAN NOT NULL DEFAULT false,
    created_by  TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, id),
    FOREIGN KEY (tenant_id, snapshot_id) REFERENCES cf_snapshots (tenant_id, id)
)""",
    """CREATE TABLE IF NOT EXISTS cf_plans (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id        UUID NOT NULL,
    scenario_id      UUID NOT NULL,
    version          INT NOT NULL DEFAULT 1,
    state            VARCHAR(12) NOT NULL
                     CHECK (state IN ('draft','submitted','approved','returned','withdrawn','superseded')),
    snapshot_id      UUID NOT NULL,
    revision         INT NOT NULL,
    view             VARCHAR(16) NOT NULL,
    overrides        JSONB NOT NULL,
    overrides_hash   CHAR(64) NOT NULL,
    metrics          JSONB NOT NULL,
    baseline_metrics JSONB NOT NULL,
    note             TEXT CHECK (length(note) <= 2000),
    submitted_by     TEXT,
    submitted_at     TIMESTAMPTZ,
    superseded_by    UUID,
    created_by       TEXT NOT NULL,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, id),
    FOREIGN KEY (tenant_id, scenario_id) REFERENCES cf_scenarios (tenant_id, id),
    FOREIGN KEY (tenant_id, snapshot_id) REFERENCES cf_snapshots (tenant_id, id)
)""",
    """CREATE UNIQUE INDEX IF NOT EXISTS uq_cf_plans_one_approved ON cf_plans (tenant_id) WHERE state = 'approved'""",
    """CREATE INDEX IF NOT EXISTS idx_cf_plans_state ON cf_plans (tenant_id, state, updated_at DESC)""",
    """CREATE TABLE IF NOT EXISTS cf_plan_decisions (
    id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id             UUID NOT NULL,
    plan_id               UUID NOT NULL,
    plan_version          INT NOT NULL,
    decision              VARCHAR(8) NOT NULL CHECK (decision IN ('approve','return')),
    note                  TEXT CHECK (length(note) <= 2000),
    decided_by            TEXT NOT NULL,
    idempotency_key       VARCHAR(80) NOT NULL,
    payload_hash          CHAR(64) NOT NULL,
    validated_on_revision INT NOT NULL,
    response              JSONB NOT NULL,
    decided_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, idempotency_key),
    UNIQUE (tenant_id, plan_id, plan_version),
    FOREIGN KEY (tenant_id, plan_id) REFERENCES cf_plans (tenant_id, id)
)""",
    """CREATE TABLE IF NOT EXISTS cf_alerts (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id      UUID NOT NULL,
    snapshot_id    UUID NOT NULL,
    breach_date    DATE NOT NULL,
    shortfall_paise BIGINT NOT NULL,
    dedupe_key     TEXT NOT NULL,
    channels       TEXT[] NOT NULL,
    sent_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, dedupe_key)
)""",
    """CREATE TABLE IF NOT EXISTS cf_accuracy (
    tenant_id      UUID NOT NULL,
    target_date    DATE NOT NULL,
    lead_days      INT NOT NULL CHECK (lead_days BETWEEN 1 AND 91),
    snapshot_id    UUID NOT NULL,
    forecast_paise BIGINT NOT NULL,
    actual_paise   BIGINT NOT NULL,
    computed_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, target_date, lead_days)
)""",
    """CREATE TABLE IF NOT EXISTS cf_audit_log (
    id         BIGSERIAL PRIMARY KEY,
    tenant_id  UUID NOT NULL,
    entity     VARCHAR(24) NOT NULL,
    entity_id  TEXT NOT NULL,
    action     VARCHAR(24) NOT NULL,
    actor      TEXT NOT NULL,
    before     JSONB,
    after      JSONB,
    request_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
)""",
    """CREATE INDEX IF NOT EXISTS idx_cf_audit_entity ON cf_audit_log (tenant_id, entity, entity_id, created_at DESC)""",
)

# The forecast publishes into fact_cashflow_daily (read by Copilot and Reports).
# The upsert needs this key; it is created only when no duplicates exist, so a
# tenant with legacy duplicate rows simply isn't published to.
PUBLISH_INDEX = (
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_fact_cashflow_daily_tenant_date "
    "ON fact_cashflow_daily (tenant_id, cashflow_date, currency_code)"
)
