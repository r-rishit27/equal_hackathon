"""Recon DDL (03_LLD_BACKEND.md §2). Idempotent — every statement is IF NOT EXISTS.

Applied by migrations._ensure_recon_tables (run via scripts/run_api_migrations.py).
"""

DDL: tuple[str, ...] = (
    # vendor_documents gains recon columns; doc_type 'recon' marks recon uploads.
    "ALTER TABLE vendor_documents ADD COLUMN IF NOT EXISTS recon_status VARCHAR(16)",
    "ALTER TABLE vendor_documents ADD COLUMN IF NOT EXISTS recon_error TEXT",
    "ALTER TABLE vendor_documents ADD COLUMN IF NOT EXISTS recon_stage VARCHAR(24)",
    "ALTER TABLE vendor_documents ADD COLUMN IF NOT EXISTS recon_progress JSONB",
    "ALTER TABLE vendor_documents ADD COLUMN IF NOT EXISTS recon_started_at TIMESTAMPTZ",
    "ALTER TABLE vendor_documents ADD COLUMN IF NOT EXISTS content_sha256 CHAR(64)",
    "CREATE INDEX IF NOT EXISTS idx_vdoc_recon_pending ON vendor_documents (recon_status) "
    "WHERE recon_status IN ('PENDING','RUNNING')",
    "CREATE INDEX IF NOT EXISTS idx_vdoc_sha ON vendor_documents (tenant_id, supplier_id, content_sha256)",

    """CREATE TABLE IF NOT EXISTS recon_doc_pages (
        doc_id         UUID NOT NULL REFERENCES vendor_documents(id) ON DELETE CASCADE,
        page_index     INT  NOT NULL,
        tenant_id      UUID NOT NULL,
        text           TEXT,
        source         VARCHAR(8) NOT NULL,
        ocr_confidence NUMERIC(4,3),
        doc_class      VARCHAR(24),
        class_conf     NUMERIC(4,3),
        class_method   VARCHAR(8),
        llm_label      VARCHAR(80),
        hints          JSONB,
        PRIMARY KEY (doc_id, page_index)
    )""",

    """CREATE TABLE IF NOT EXISTS recon_doc_segments (
        id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        doc_id            UUID NOT NULL REFERENCES vendor_documents(id) ON DELETE CASCADE,
        tenant_id         UUID NOT NULL,
        supplier_id       UUID NOT NULL,
        kind              VARCHAR(16) NOT NULL,
        llm_label         VARCHAR(80),
        pages             INT[] NOT NULL,
        section_title     VARCHAR(160),
        vendor_name       VARCHAR(200),
        vendor_gstin      VARCHAR(15),
        store_sn          VARCHAR(16),
        confidence        NUMERIC(4,3),
        extracted_json    JSONB,
        extractor_version VARCHAR(16),
        status            VARCHAR(16) NOT NULL DEFAULT 'PENDING',
        link_candidates   JSONB,
        warnings          JSONB,
        kind_overridden_by VARCHAR(100),
        created_at        TIMESTAMPTZ DEFAULT now()
    )""",
    "CREATE INDEX IF NOT EXISTS idx_rseg_supplier ON recon_doc_segments (tenant_id, supplier_id, kind)",
    "CREATE INDEX IF NOT EXISTS idx_rseg_doc ON recon_doc_segments (doc_id)",
    "CREATE INDEX IF NOT EXISTS idx_rseg_store ON recon_doc_segments (tenant_id, store_sn)",

    """CREATE TABLE IF NOT EXISTS purchase_orders (
        id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        tenant_id        UUID NOT NULL,
        supplier_id      UUID NOT NULL,
        po_number        VARCHAR(40) NOT NULL,
        revision         INT NOT NULL DEFAULT 1,
        po_date          DATE,
        delivery_date    DATE,
        store_sn         VARCHAR(16),
        store_name       VARCHAR(200),
        buyer_gstin      VARCHAR(15),
        vendor_gstin     VARCHAR(15),
        payment_terms    VARCHAR(80),
        requisition_no   VARCHAR(40),
        requisition_name VARCHAR(200),
        subtotal         NUMERIC(14,2),
        tax              NUMERIC(14,2),
        total            NUMERIC(14,2),
        penalties        JSONB,
        segment_id       UUID REFERENCES recon_doc_segments(id) ON DELETE SET NULL,
        superseded_by    UUID REFERENCES purchase_orders(id),
        deleted_at       TIMESTAMPTZ,
        created_at       TIMESTAMPTZ DEFAULT now(),
        UNIQUE (tenant_id, po_number, revision)
    )""",
    "CREATE INDEX IF NOT EXISTS idx_po_supplier ON purchase_orders (tenant_id, supplier_id)",

    """CREATE TABLE IF NOT EXISTS purchase_order_lines (
        id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        po_id         UUID NOT NULL REFERENCES purchase_orders(id) ON DELETE CASCADE,
        tenant_id     UUID NOT NULL,
        sno           INT NOT NULL,
        description   TEXT NOT NULL,
        norm          TEXT NOT NULL,
        unit          VARCHAR(16),
        qty           NUMERIC(14,3) NOT NULL,
        unit_price    NUMERIC(14,4) NOT NULL,
        amount        NUMERIC(14,2) NOT NULL,
        delivery_date DATE,
        UNIQUE (po_id, sno)
    )""",

    """CREATE TABLE IF NOT EXISTS recon_invoice_lines (
        id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        segment_id  UUID NOT NULL REFERENCES recon_doc_segments(id) ON DELETE CASCADE,
        tenant_id   UUID NOT NULL,
        sno         INT,
        description TEXT NOT NULL,
        norm        TEXT NOT NULL,
        hsn         VARCHAR(12),
        unit        VARCHAR(16),
        qty         NUMERIC(14,3),
        rate        NUMERIC(14,4),
        amount      NUMERIC(14,2),
        tax_rate    NUMERIC(5,2),
        confidence  NUMERIC(4,3),
        page        INT,
        bbox        JSONB,
        is_charge   BOOLEAN NOT NULL DEFAULT false,
        charge_pct  NUMERIC(6,3)
    )""",
    "CREATE INDEX IF NOT EXISTS idx_rinv_seg ON recon_invoice_lines (segment_id)",

    """CREATE TABLE IF NOT EXISTS recon_evidence_rows (
        id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        segment_id          UUID NOT NULL REFERENCES recon_doc_segments(id) ON DELETE CASCADE,
        tenant_id           UUID NOT NULL,
        sno                 INT,
        asset_code          VARCHAR(80),
        item                TEXT NOT NULL,
        norm                TEXT NOT NULL,
        unit                VARCHAR(16),
        po_qty              NUMERIC(14,3),
        vendor_qty          NUMERIC(14,3),
        audit_qty           NUMERIC(14,3),
        audit_qty_raw       VARCHAR(40),
        audit_alternatives  JSONB,
        remark              TEXT,
        verdict             VARCHAR(16),
        mounted INT, unmounted INT, damaged INT,
        rate                NUMERIC(14,4),
        rate_after_discount NUMERIC(14,4),
        row_type            VARCHAR(12) NOT NULL DEFAULT 'po',
        confidence          NUMERIC(4,3),
        needs_review        BOOLEAN NOT NULL DEFAULT false,
        page                INT,
        bbox                JSONB,
        corrected_by        VARCHAR(100),
        corrected_at        TIMESTAMPTZ,
        original_json       JSONB
    )""",
    "CREATE INDEX IF NOT EXISTS idx_rev_seg ON recon_evidence_rows (segment_id)",
    # Handwritten overwrites and reviewer corrections, per row: [{field, was, now, kind, by?, at?}]
    # (vocabulary value_change_kind). The vocabulary's own tables and code columns: recon/vocab.py sync().
    "ALTER TABLE recon_evidence_rows ADD COLUMN IF NOT EXISTS value_history JSONB",
    # The row's meaning as rules.VerdictClassifier reads it (verdict holds only a reviewer's choice).
    "ALTER TABLE recon_evidence_rows ADD COLUMN IF NOT EXISTS auto_verdict VARCHAR(16)",

    """CREATE TABLE IF NOT EXISTS recon_cases (
        id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        tenant_id          UUID NOT NULL,
        supplier_id        UUID NOT NULL,
        brand_id           UUID,
        bill_id            UUID,
        invoice_segment_id UUID REFERENCES recon_doc_segments(id) ON DELETE SET NULL,
        po_id              UUID REFERENCES purchase_orders(id) ON DELETE SET NULL,
        invoice_no         VARCHAR(80),
        store_sn           VARCHAR(16),
        status             VARCHAR(20) NOT NULL,
        summary_json       JSONB,
        money_at_risk      NUMERIC(14,2) NOT NULL DEFAULT 0,
        under_billed       NUMERIC(14,2) NOT NULL DEFAULT 0,
        counts             JSONB,
        result_hash        CHAR(64),
        engine_version     VARCHAR(16),
        computed_at        TIMESTAMPTZ,
        acknowledged_by    VARCHAR(100),
        acknowledged_at    TIMESTAMPTZ,
        ack_hash           CHAR(64),
        ack_note           TEXT,
        created_at         TIMESTAMPTZ DEFAULT now()
    )""",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_rcase_bill ON recon_cases (tenant_id, bill_id) WHERE bill_id IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS idx_rcase_supplier ON recon_cases (tenant_id, supplier_id, status)",
    "CREATE INDEX IF NOT EXISTS idx_rcase_po ON recon_cases (tenant_id, po_id)",
    # A readable, per-tenant case number ("RC-0012") for the header, links and conversations.
    "ALTER TABLE recon_cases ADD COLUMN IF NOT EXISTS ref_no INT",
    """UPDATE recon_cases rc SET ref_no = n.rn
         FROM (SELECT c.id,
                      (SELECT COALESCE(MAX(m.ref_no), 0) FROM recon_cases m WHERE m.tenant_id = c.tenant_id)
                      + row_number() OVER (PARTITION BY c.tenant_id ORDER BY c.created_at, c.id) AS rn
                 FROM recon_cases c WHERE c.ref_no IS NULL) n
        WHERE rc.id = n.id""",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_rcase_ref ON recon_cases (tenant_id, ref_no) WHERE ref_no IS NOT NULL",

    """CREATE TABLE IF NOT EXISTS recon_case_segments (
        case_id     UUID NOT NULL REFERENCES recon_cases(id) ON DELETE CASCADE,
        segment_id  UUID NOT NULL REFERENCES recon_doc_segments(id) ON DELETE CASCADE,
        tenant_id   UUID NOT NULL,
        role        VARCHAR(16) NOT NULL,
        link_method VARCHAR(8) NOT NULL,
        link_score  NUMERIC(4,3),
        linked_by   VARCHAR(100),
        linked_at   TIMESTAMPTZ DEFAULT now(),
        PRIMARY KEY (case_id, segment_id)
    )""",
    "CREATE INDEX IF NOT EXISTS idx_rcs_segment ON recon_case_segments (segment_id)",

    """CREATE TABLE IF NOT EXISTS recon_line_results (
        id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        case_id          UUID NOT NULL REFERENCES recon_cases(id) ON DELETE CASCADE,
        tenant_id        UUID NOT NULL,
        ord              INT NOT NULL,
        kind             VARCHAR(12) NOT NULL,
        line_key         VARCHAR(200) NOT NULL,
        po_line_key      VARCHAR(80),
        invoice_line_key VARCHAR(80),
        evidence_row_key VARCHAR(80),
        result           JSONB NOT NULL,
        severity         VARCHAR(8) NOT NULL,
        statuses         VARCHAR(24)[] NOT NULL,
        reviewed_by      VARCHAR(100),
        reviewed_at      TIMESTAMPTZ,
        reviewed_note    TEXT
    )""",
    "CREATE INDEX IF NOT EXISTS idx_rlr_case ON recon_line_results (case_id, ord)",

    """CREATE TABLE IF NOT EXISTS recon_header_checks (
        case_id   UUID NOT NULL REFERENCES recon_cases(id) ON DELETE CASCADE,
        tenant_id UUID NOT NULL,
        code      VARCHAR(32) NOT NULL,
        label     TEXT NOT NULL,
        severity  VARCHAR(8) NOT NULL,
        passed    BOOLEAN NOT NULL,
        detail    TEXT,
        evidence  JSONB,
        PRIMARY KEY (case_id, code)
    )""",

    """CREATE TABLE IF NOT EXISTS recon_match_overrides (
        case_id    UUID NOT NULL REFERENCES recon_cases(id) ON DELETE CASCADE,
        tenant_id  UUID NOT NULL,
        po_line_key VARCHAR(80),
        other_key  VARCHAR(80) NOT NULL,
        decided_by VARCHAR(100) NOT NULL,
        decided_at TIMESTAMPTZ DEFAULT now(),
        PRIMARY KEY (case_id, other_key)
    )""",

    """CREATE TABLE IF NOT EXISTS vendor_item_aliases (
        tenant_id    UUID NOT NULL,
        supplier_id  UUID NOT NULL,
        alias_norm   TEXT NOT NULL,
        po_item_norm TEXT NOT NULL,
        confirmed_by VARCHAR(100),
        created_at   TIMESTAMPTZ DEFAULT now(),
        hits         INT NOT NULL DEFAULT 0,
        PRIMARY KEY (tenant_id, supplier_id, alias_norm)
    )""",

    """CREATE TABLE IF NOT EXISTS recon_events (
        id        BIGSERIAL PRIMARY KEY,
        tenant_id UUID NOT NULL,
        case_id   UUID,
        doc_id    UUID,
        kind      VARCHAR(32) NOT NULL,
        payload   JSONB,
        actor     VARCHAR(100),
        at        TIMESTAMPTZ DEFAULT now()
    )""",
    "CREATE INDEX IF NOT EXISTS idx_revents_case ON recon_events (tenant_id, case_id, at)",
    "CREATE INDEX IF NOT EXISTS idx_revents_doc ON recon_events (tenant_id, doc_id, at)",

    # ── Stable line identity + append-only decisions ───────────────────────────
    # docs/reconciliation/RECON_IMPLEMENTATION_PLAN.md §6. Line identity used to be the row's
    # surrogate uuid, which re-extraction destroys (repo._save_* delete and
    # re-insert), orphaning every decision keyed on it. A natural key derived
    # from what the document prints (recon/keys.py) survives re-extraction;
    # line_uid is the durable handle decisions hang on.
    """CREATE TABLE IF NOT EXISTS recon_line_identity (
        line_uid       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        tenant_id      UUID NOT NULL,
        doc_id         UUID NOT NULL REFERENCES vendor_documents(id) ON DELETE CASCADE,
        leg            VARCHAR(16) NOT NULL,
        natural_key    VARCHAR(120) NOT NULL,
        key_basis      VARCHAR(16) NOT NULL,
        key_confidence NUMERIC(4,3) NOT NULL,
        first_seen_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
        last_seen_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
        UNIQUE (tenant_id, doc_id, leg, natural_key)
    )""",
    "CREATE INDEX IF NOT EXISTS idx_rlid_doc ON recon_line_identity (tenant_id, doc_id)",

    # Append-only. A changed mind is a NEW row with `supersedes` set; current
    # state is the latest row per (line_uid, kind). No ON DELETE CASCADE
    # anywhere: `case_id` is context, not ownership, so deleting a case can
    # never delete the record of what a person decided.
    """CREATE TABLE IF NOT EXISTS recon_decisions (
        decision_id BIGSERIAL PRIMARY KEY,
        tenant_id   UUID NOT NULL,
        line_uid    UUID REFERENCES recon_line_identity(line_uid),
        case_id     UUID,
        kind        VARCHAR(24) NOT NULL,
        payload     JSONB NOT NULL,
        supersedes  BIGINT REFERENCES recon_decisions(decision_id),
        actor       VARCHAR(100) NOT NULL,
        actor_kind  VARCHAR(8) NOT NULL DEFAULT 'human',
        decided_at  TIMESTAMPTZ NOT NULL DEFAULT now()
    )""",
    "ALTER TABLE recon_decisions DROP CONSTRAINT IF EXISTS recon_decisions_actor_kind_ck",
    "ALTER TABLE recon_decisions ADD CONSTRAINT recon_decisions_actor_kind_ck "
    "CHECK (actor_kind IN ('human','rule','model'))",
    "CREATE INDEX IF NOT EXISTS idx_rdec_line ON recon_decisions (tenant_id, line_uid, decided_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_rdec_case ON recon_decisions (tenant_id, case_id, decided_at DESC)",
    # Replay reads `decided_at <= as_of`; this serves it per tenant.
    "CREATE INDEX IF NOT EXISTS idx_rdec_asof ON recon_decisions (tenant_id, decided_at)",

    # The row tables carry their natural key and the line_uid it resolved to, so
    # a reviewer's decision re-attaches after the rows are rebuilt.
    # The row total the site report PRINTS, so its own arithmetic can be checked
    # rather than silently re-derived (20 Nov 2026).
    "ALTER TABLE recon_evidence_rows ADD COLUMN IF NOT EXISTS amount NUMERIC(16,2)",
    "ALTER TABLE recon_evidence_rows ADD COLUMN IF NOT EXISTS natural_key VARCHAR(120)",
    "ALTER TABLE recon_evidence_rows ADD COLUMN IF NOT EXISTS key_basis VARCHAR(16)",
    "ALTER TABLE recon_evidence_rows ADD COLUMN IF NOT EXISTS key_confidence NUMERIC(4,3)",
    "ALTER TABLE recon_evidence_rows ADD COLUMN IF NOT EXISTS line_uid UUID",
    "CREATE INDEX IF NOT EXISTS idx_rev_uid ON recon_evidence_rows (line_uid)",

    "ALTER TABLE recon_invoice_lines ADD COLUMN IF NOT EXISTS natural_key VARCHAR(120)",
    "ALTER TABLE recon_invoice_lines ADD COLUMN IF NOT EXISTS key_basis VARCHAR(16)",
    "ALTER TABLE recon_invoice_lines ADD COLUMN IF NOT EXISTS key_confidence NUMERIC(4,3)",
    "ALTER TABLE recon_invoice_lines ADD COLUMN IF NOT EXISTS line_uid UUID",
    "CREATE INDEX IF NOT EXISTS idx_rinv_uid ON recon_invoice_lines (line_uid)",

    # ── Replay (plan §8) ──────────────────────────────────────────────────────
    # `result_hash` covers the output, so a re-run after a reviewer decision can
    # return the stale verdict. `input_fingerprint` covers the inputs *and* the
    # decision high-water mark, so a new decision forces a real recompute.
    "ALTER TABLE recon_cases ADD COLUMN IF NOT EXISTS input_fingerprint CHAR(64)",
    "ALTER TABLE recon_cases ADD COLUMN IF NOT EXISTS rule_version VARCHAR(16)",
    # A replay is a case computed as of an earlier moment: it reads
    # `recon_decisions WHERE decided_at <= as_of` and points back at the original.
    "ALTER TABLE recon_cases ADD COLUMN IF NOT EXISTS replay_of UUID REFERENCES recon_cases(id)",
    "ALTER TABLE recon_cases ADD COLUMN IF NOT EXISTS as_of TIMESTAMPTZ",
    "CREATE INDEX IF NOT EXISTS idx_rcase_fingerprint ON recon_cases (tenant_id, input_fingerprint)",

    # ── The match surface as a projection (plan §3, R-III) ────────────────────
    # Derived from recon_line_results and recon_decisions, never authored. It can
    # be wiped and rebuilt with nothing lost — which is precisely what Plan B got
    # wrong by storing reviewer confirmations in the graph itself.
    # Postgres, not a graph database: the questions the rules ask are 1–2 hops,
    # and a graph outage must not stop payments or reviews.
    """CREATE TABLE IF NOT EXISTS recon_edges (
        edge_id    BIGSERIAL PRIMARY KEY,
        tenant_id  UUID NOT NULL,
        case_id    UUID NOT NULL REFERENCES recon_cases(id) ON DELETE CASCADE,
        kind       VARCHAR(24) NOT NULL,
        src_key    VARCHAR(200) NOT NULL,
        dst_key    VARCHAR(200) NOT NULL,
        src_line_uid UUID,
        dst_line_uid UUID,
        method     VARCHAR(16),
        score      NUMERIC(4,3),
        confirmed  BOOLEAN NOT NULL DEFAULT false,
        built_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
        UNIQUE (case_id, kind, src_key, dst_key)
    )""",
    "CREATE INDEX IF NOT EXISTS idx_redge_case ON recon_edges (tenant_id, case_id, kind)",
    "CREATE INDEX IF NOT EXISTS idx_redge_src ON recon_edges (tenant_id, src_line_uid)",
    "CREATE INDEX IF NOT EXISTS idx_redge_dst ON recon_edges (tenant_id, dst_line_uid)",

    # ── GRN: the RECEIPT leg (plan §7) ────────────────────────────────────────
    # A Microsoft Dynamics extract, not a document: no OCR, no parser, no ocr_id.
    # Column names are mapped per tenant (recon/grn.py), so the client's real
    # export costs a mapping entry rather than a migration.
    """CREATE TABLE IF NOT EXISTS recon_grn_lines (
        grn_line_id  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        tenant_id    UUID NOT NULL,
        grn_number   VARCHAR(60),
        grn_date     DATE,
        po_number    VARCHAR(40) NOT NULL,
        po_line_no   VARCHAR(20),
        item_code    VARCHAR(80),
        description  TEXT,
        norm         TEXT,
        unit         VARCHAR(16),
        qty_received NUMERIC(14,3) NOT NULL,
        rate         NUMERIC(14,4),
        amount       NUMERIC(14,2),
        msd_voucher  VARCHAR(60),
        source_file  TEXT,
        line_uid     UUID,
        ingested_at  TIMESTAMPTZ NOT NULL DEFAULT now()
    )""",
    "CREATE INDEX IF NOT EXISTS idx_grn_po ON recon_grn_lines (tenant_id, po_number)",
    "CREATE INDEX IF NOT EXISTS idx_grn_number ON recon_grn_lines (tenant_id, grn_number)",
    # Re-loading the same extract must not double the received quantity.
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_grn_line ON recon_grn_lines "
    "(tenant_id, grn_number, po_number, COALESCE(po_line_no,''), COALESCE(item_code,''))",
)
