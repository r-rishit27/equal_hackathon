"""Receivables + cash application DDL (docs/receivables/02_LLD.md §3).

Idempotent — every statement is IF NOT EXISTS. Applied by
migrations._ensure_receivables_tables (run via scripts/run_api_migrations.py).

Receivables live in their own ar_* tables rather than as a flag on fact_invoices:
fact_invoices is read by ~170 payable queries (reports, payment hub, review hub,
TDS, exports), and every one of them would have to learn to exclude sales
invoices. What *is* shared with payables is the machinery — the OCR reader, file
storage, the UI kit, tenancy and licensing.

Money is NUMERIC(18,2). `outstanding` and `number_norm` are generated columns so
they can never drift from what they are derived from.
"""

# Optional: fuzzy payer lookup uses pg_trgm when the database allows it. Run on its
# own so a managed DB that refuses the extension doesn't block the rest.
OPTIONAL_DDL: tuple[str, ...] = (
    "CREATE EXTENSION IF NOT EXISTS pg_trgm",
    "CREATE INDEX IF NOT EXISTS idx_ar_customers_trgm ON ar_customers USING gin (name_norm gin_trgm_ops)",
    "CREATE INDEX IF NOT EXISTS idx_ar_aliases_trgm ON ar_payer_aliases USING gin (alias_norm gin_trgm_ops)",
)

DDL: tuple[str, ...] = (
    """CREATE TABLE IF NOT EXISTS ar_settings (
        tenant_id            UUID PRIMARY KEY,
        auto_apply_enabled   BOOLEAN NOT NULL DEFAULT true,
        auto_apply_threshold NUMERIC(4,3) NOT NULL DEFAULT 0.95,
        amount_tolerance     NUMERIC(10,2) NOT NULL DEFAULT 1.00,
        writeoff_tolerance   NUMERIC(10,2) NOT NULL DEFAULT 0,
        tds_rates            NUMERIC(6,3)[] NOT NULL DEFAULT '{0.1,1,2,5,10}',
        trust_learned_tds    BOOLEAN NOT NULL DEFAULT false,
        updated_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_by           TEXT
    )""",

    """CREATE TABLE IF NOT EXISTS ar_customers (
        id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        tenant_id          UUID NOT NULL,
        name               TEXT NOT NULL,
        name_norm          TEXT NOT NULL DEFAULT '',
        gstin              VARCHAR(15),
        pan                VARCHAR(10),
        email              TEXT,
        phone              TEXT,
        address            TEXT,
        payment_terms_days INT,
        -- The TDS rate (percent) this customer last deducted, confirmed by a person.
        tds_rate_hint      NUMERIC(6,3),
        created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at         TIMESTAMPTZ NOT NULL DEFAULT now()
    )""",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_ar_customers_gstin ON ar_customers (tenant_id, gstin) "
    "WHERE gstin IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS idx_ar_customers_name ON ar_customers (tenant_id, name_norm)",
    "CREATE INDEX IF NOT EXISTS idx_ar_customers_pan ON ar_customers (tenant_id, pan) WHERE pan IS NOT NULL",

    # Names a customer's money arrives under in bank narrations. One row per
    # (alias, customer): an alias mapped to two customers is the AMBIGUOUS_PAYER case.
    """CREATE TABLE IF NOT EXISTS ar_payer_aliases (
        id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        tenant_id     UUID NOT NULL,
        alias_norm    TEXT NOT NULL,
        alias_raw     TEXT,
        customer_id   UUID NOT NULL REFERENCES ar_customers(id) ON DELETE CASCADE,
        source        VARCHAR(12) NOT NULL,          -- learned | manual | invoice
        confirmations INT NOT NULL DEFAULT 1,
        last_seen_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
        UNIQUE (tenant_id, alias_norm, customer_id)
    )""",

    """CREATE TABLE IF NOT EXISTS ar_invoices (
        id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        tenant_id        UUID NOT NULL,
        customer_id      UUID NOT NULL REFERENCES ar_customers(id),
        invoice_number   TEXT NOT NULL,
        number_norm      TEXT GENERATED ALWAYS AS
                           (regexp_replace(upper(invoice_number), '[^A-Z0-9]', '', 'g')) STORED,
        invoice_date     DATE,
        due_date         DATE,
        po_number        TEXT,
        po_norm          TEXT GENERATED ALWAYS AS
                           (regexp_replace(upper(coalesce(po_number, '')), '[^A-Z0-9]', '', 'g')) STORED,
        currency         CHAR(3) NOT NULL DEFAULT 'INR',
        taxable_amount   NUMERIC(18,2),
        tax_amount       NUMERIC(18,2),
        total_amount     NUMERIC(18,2) NOT NULL CHECK (total_amount >= 0),
        amount_received  NUMERIC(18,2) NOT NULL DEFAULT 0,
        tds_amount       NUMERIC(18,2) NOT NULL DEFAULT 0,
        deduction_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
        outstanding      NUMERIC(18,2) GENERATED ALWAYS AS
                           (total_amount - amount_received - tds_amount - deduction_amount) STORED,
        -- open | partially_paid | paid | disputed | written_off | void
        status           VARCHAR(16) NOT NULL DEFAULT 'open',
        payment_terms    TEXT,
        source_file      TEXT,
        storage_ref      TEXT,
        payload          JSONB,
        created_by       TEXT,
        created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
        paid_at          TIMESTAMPTZ,
        UNIQUE (tenant_id, customer_id, invoice_number)
    )""",
    "CREATE INDEX IF NOT EXISTS idx_ar_invoices_num ON ar_invoices (tenant_id, number_norm)",
    "CREATE INDEX IF NOT EXISTS idx_ar_invoices_po ON ar_invoices (tenant_id, po_norm) WHERE po_norm <> ''",
    "CREATE INDEX IF NOT EXISTS idx_ar_invoices_open ON ar_invoices (tenant_id, customer_id, due_date) "
    "WHERE status IN ('open','partially_paid')",
    "CREATE INDEX IF NOT EXISTS idx_ar_invoices_open_amt ON ar_invoices (tenant_id, outstanding) "
    "WHERE status IN ('open','partially_paid')",

    """CREATE TABLE IF NOT EXISTS ar_payments (
        id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        tenant_id         UUID NOT NULL,
        received_on       DATE NOT NULL,
        amount            NUMERIC(18,2) NOT NULL CHECK (amount > 0),
        currency          CHAR(3) NOT NULL DEFAULT 'INR',
        method            VARCHAR(12),
        reference         TEXT,
        utr               TEXT,
        payer_name        TEXT,
        payer_account     TEXT,
        narration         TEXT,
        bank_account      TEXT,
        source            VARCHAR(16) NOT NULL,          -- statement | manual | api
        source_file       TEXT,
        customer_id       UUID REFERENCES ar_customers(id),
        -- unmatched | needs_review | partially_applied | applied | exception | not_receipt | reversed
        status            VARCHAR(20) NOT NULL DEFAULT 'unmatched',
        applied_amount    NUMERIC(18,2) NOT NULL DEFAULT 0,
        suggestion        JSONB,
        match_confidence  NUMERIC(4,3),
        flags             TEXT[] NOT NULL DEFAULT '{}',
        auto_applied      BOOLEAN NOT NULL DEFAULT false,
        reason_code       VARCHAR(24),
        note              TEXT,
        fingerprint       TEXT,
        version           INT NOT NULL DEFAULT 1,
        created_by        TEXT,
        created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
        matched_at        TIMESTAMPTZ,
        applied_at        TIMESTAMPTZ,
        applied_by        TEXT,
        posted_at         TIMESTAMPTZ
    )""",
    # Re-importing the same statement must not double-count money.
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_ar_payments_fp ON ar_payments (tenant_id, fingerprint) "
    "WHERE fingerprint IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS idx_ar_payments_status ON ar_payments (tenant_id, status, received_on DESC)",
    "CREATE INDEX IF NOT EXISTS idx_ar_payments_utr ON ar_payments (tenant_id, utr) WHERE utr IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS idx_ar_payments_customer ON ar_payments (tenant_id, customer_id)",

    # Every imported bank statement is kept: the original file (object store, never
    # public), what was read from it line by line, and what each line became.
    """CREATE TABLE IF NOT EXISTS ar_statements (
        id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        tenant_id      UUID NOT NULL,
        file_name      TEXT NOT NULL,
        file_format    VARCHAR(8) NOT NULL,              -- csv | xlsx | pdf
        content_sha256 CHAR(64),
        storage_ref    TEXT,
        bank_account   TEXT,
        period_from    DATE,
        period_to      DATE,
        credits        INT NOT NULL DEFAULT 0,
        imported       INT NOT NULL DEFAULT 0,
        duplicates     INT NOT NULL DEFAULT 0,
        set_aside      INT NOT NULL DEFAULT 0,
        bounces        INT NOT NULL DEFAULT 0,
        -- Every line as read: date, narration, reference, amount, direction, and the
        -- outcome (new | duplicate | set_aside | bounce | ignored) with its payment id.
        lines          JSONB NOT NULL DEFAULT '[]',
        uploaded_by    TEXT,
        created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
    )""",
    "CREATE INDEX IF NOT EXISTS idx_ar_statements_tenant ON ar_statements (tenant_id, created_at DESC)",
    "ALTER TABLE ar_payments ADD COLUMN IF NOT EXISTS statement_id UUID REFERENCES ar_statements(id) ON DELETE SET NULL",
    "ALTER TABLE ar_payments ADD COLUMN IF NOT EXISTS statement_line INT",
    "CREATE INDEX IF NOT EXISTS idx_ar_payments_statement ON ar_payments (tenant_id, statement_id)",

    """CREATE TABLE IF NOT EXISTS ar_remittances (
        id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        tenant_id         UUID NOT NULL,
        payment_id        UUID REFERENCES ar_payments(id) ON DELETE SET NULL,
        customer_id       UUID REFERENCES ar_customers(id),
        payer_name        TEXT,
        payment_reference TEXT,
        payment_date      DATE,
        total_amount      NUMERIC(18,2),
        lines             JSONB NOT NULL DEFAULT '[]',
        status            VARCHAR(10) NOT NULL DEFAULT 'unlinked',   -- unlinked | linked | conflict
        source            VARCHAR(8) NOT NULL,                       -- text | pdf
        source_file       TEXT,
        storage_ref       TEXT,
        raw_text          TEXT,
        created_by        TEXT,
        created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
    )""",
    "CREATE INDEX IF NOT EXISTS idx_ar_remittances_payment ON ar_remittances (tenant_id, payment_id)",
    "CREATE INDEX IF NOT EXISTS idx_ar_remittances_unlinked ON ar_remittances (tenant_id, total_amount) "
    "WHERE status = 'unlinked'",

    """CREATE TABLE IF NOT EXISTS ar_applications (
        id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        tenant_id        UUID NOT NULL,
        payment_id       UUID NOT NULL REFERENCES ar_payments(id) ON DELETE CASCADE,
        invoice_id       UUID NOT NULL REFERENCES ar_invoices(id),
        amount_applied   NUMERIC(18,2) NOT NULL CHECK (amount_applied >= 0),
        tds_amount       NUMERIC(18,2) NOT NULL DEFAULT 0 CHECK (tds_amount >= 0),
        deduction_amount NUMERIC(18,2) NOT NULL DEFAULT 0 CHECK (deduction_amount >= 0),
        -- TDS | DISCOUNT | BANK_CHARGES | ROUNDING | SHORT_SUPPLY | DAMAGE | RATE_DIFF
        -- | DEBIT_NOTE | FX | DISPUTE | OTHER
        reason_code      VARCHAR(16),
        reason_note      TEXT,
        method           VARCHAR(10) NOT NULL,          -- auto | accepted | manual
        kind             VARCHAR(32),                   -- the matcher's suggestion kind
        confidence       NUMERIC(4,3),
        applied_by       TEXT,
        created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
        reversed_at      TIMESTAMPTZ,
        reversed_by      TEXT
    )""",
    "CREATE INDEX IF NOT EXISTS idx_ar_apps_payment ON ar_applications (tenant_id, payment_id)",
    "CREATE INDEX IF NOT EXISTS idx_ar_apps_invoice ON ar_applications (tenant_id, invoice_id)",

    """CREATE TABLE IF NOT EXISTS ar_match_jobs (
        id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        tenant_id   UUID NOT NULL,
        payment_id  UUID NOT NULL REFERENCES ar_payments(id) ON DELETE CASCADE,
        reason      VARCHAR(16) NOT NULL,
        status      VARCHAR(8) NOT NULL DEFAULT 'PENDING',   -- PENDING | RUNNING | DONE | FAILED
        attempts    INT NOT NULL DEFAULT 0,
        run_after   TIMESTAMPTZ NOT NULL DEFAULT now(),
        locked_at   TIMESTAMPTZ,
        error       TEXT,
        created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
        done_at     TIMESTAMPTZ
    )""",
    # One live job per payment: enqueue coalesces.
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_ar_jobs_live ON ar_match_jobs (payment_id) "
    "WHERE status IN ('PENDING','RUNNING')",
    "CREATE INDEX IF NOT EXISTS idx_ar_jobs_claim ON ar_match_jobs (run_after) WHERE status = 'PENDING'",

    """CREATE TABLE IF NOT EXISTS ar_events (
        id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        tenant_id  UUID NOT NULL,
        entity     VARCHAR(12) NOT NULL,      -- payment | invoice | remittance | customer | settings
        entity_id  UUID,
        action     VARCHAR(32) NOT NULL,
        actor      TEXT,                      -- a username, or 'agent'
        payload    JSONB,
        at         TIMESTAMPTZ NOT NULL DEFAULT now()
    )""",
    "CREATE INDEX IF NOT EXISTS idx_ar_events_entity ON ar_events (tenant_id, entity, entity_id, at DESC)",
)
