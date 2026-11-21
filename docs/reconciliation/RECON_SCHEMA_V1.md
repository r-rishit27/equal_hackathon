# Reckon.ai Recon Schema v1 — what to build now

**Status:** Proposed for build · 2026-11-14 (rev 2: one extraction table) · **rev 2.1, 2026-11-18: business rules confirmed by Bata — see §11**
**Pairs with:** `docs/reconciliation/design/RECON_VOCABULARY.md` (what every code means) and the CAPEX four-way architecture (where each component runs).

> ### Basic principle: the vocabulary is the dictionary; the schema is derived from it
> - **Vocabulary = dictionary** (`docs/reconciliation/design/RECON_VOCABULARY.md`): defines every code, its meaning, its aliases and its ambiguity rules. It holds no data.
> - **Schema = storage derived from the dictionary** (this file): generic code columns and JSON fields whose allowed values and keys come from the vocabulary. `vocab_codes` and `vocab_aliases` are loaded from it, and every code — in a column or inside JSON — is checked against `vocab_codes`.
> - **Vocabulary first, schema second.** Add the word to the vocabulary; only promote it to a column here when the linker or the graph loader must find a document by it.
> - **Nothing in this schema without a vocabulary entry.**

**Scope of v1:** one template, `CAPEX_FITOUT_PO_PV_INVOICE` (Bata 8255 and 9621), with POD accepted as receipt evidence for goods POs. Everything else stays in the vocabulary until a rule needs it.

> ⚠⚠ **Sections 0–6 are superseded, as of 18 November 2026.** The single-JSONB-row
> `recon_extractions` design below was tested as **Plan B in the architecture bake-off and
> lost** (48.4 vs 89.2). The build follows **`docs/reconciliation/RECON_IMPLEMENTATION_PLAN.md`** — the hybrid,
> on the relational tables that actually shipped in `backend_ocr/app/recon/`. What remains
> current here: **§11** (the Bata business rules), the leg model, `receipt_granularity`, and
> keeping two evidence layers apart.

> ⚠ **Superseded in part by §11.** The Bata call of 16 November 2026 established that the
> compared legs are **GRN ↔ invoice ↔ audit report**, with the PO as a cap and the GRN read
> from Microsoft Dynamics — not the PO-vs-PV-vs-invoice template named above. §11 states the
> confirmed rules and lists every change they force. Read §11 before building from §3–§6.

---

## 0. What changed in rev 2, and why

Rev 1 stored an extraction across three tables: `recon_documents` → `recon_lines` → `recon_line_quantities`. Those three are now **one table, `recon_extractions`**, holding one row per parsed document with its lines and their quantities as JSONB.

The reason is the architecture, not tidiness. In the four-way design the **graph is the match surface**: line alignment (`BILLS_AGAINST`), the cumulative position on a PO line, and the evidence path are all graph traversals. Nothing in reconciliation joins `recon_lines` to `recon_lines` in SQL, and nothing filters on `rate` or `item_key` in Postgres — so the indexes that justified a relational line table have no reader.

What the relational layer *is* for, in that architecture, is one thing: **the durable, replayable record of what the parsers extracted**, kept separate from the graph so a parser fix can be re-run without touching reconciliation. The natural grain for that is one parser output = one document = one row.

| | Rev 1 | Rev 2 |
|---|---|---|
| Extraction tables | 3 | **1** |
| Total new tables | 9 | **7** |
| A document's extraction is | 1 + n + m rows across 3 tables | 1 row |
| Re-extracting a document | delete-cascade, re-insert n+m rows | supersede 1 row, insert 1 row |
| Line alignment lives in | `recon_line_matches` | graph edges, recorded in `recon_results` |
| Line-level codes enforced by | FK | trigger against `vocab_codes` (§3.3) |

**What this costs, stated plainly.** Line-level codes move out of foreign keys and into a validation trigger, and ad-hoc SQL over lines becomes `jsonb_array_elements` instead of a plain `SELECT`. The trigger closes the first gap (§3.3); the second is accepted, because the readers that would have wanted plain SQL are in the graph.

---

## 1. Principles applied

1. **One extraction, one row.** A parsed document is a single row. Its lines, their quantities and their measurement workings are JSONB inside that row, because they are read as a whole document and written as a whole document.
2. **A column only when something finds the document by it.** `doc_number`, `po_number_ref`, `site_code`, `invoice_refs` and the money totals are columns because the linker and the header checks use them. Everything else is JSON.
3. **Codes are checked against the vocabulary in the database.** Document-level codes by foreign key; line- and quantity-level codes by a trigger that validates every code in the JSON against `vocab_codes`. A typo cannot be stored either way.
4. **Raw is never lost.** `raw_ocr_results` keeps the full model output, and `recon_extractions.raw_payload` keeps the extractor's own output verbatim alongside the normalised values. Every normalised value keeps its `*_raw` sibling.
5. **Existing tables are untouched.** The bill path (`raw_invoice_uploads → stg_bills → fact_bills / fact_invoices`) keeps working. Recon reads it via `upload_id` and writes back only `verification_flag` + `verification_detail`, exactly as Nova recon does.
6. **Tenant-scoped everything.** Every table has `tenant_id`; every query goes through the `require_tenant` dependency plus `AND tenant_id = caller`.
7. **New tables only.** Names are prefixed `recon_` / `vocab_` so they never collide with Nova's `billing_reconciliation_*`.
8. **The graph is derived, never the source.** `recon_extractions` can rebuild the whole graph. The graph can never rebuild `recon_extractions`.

---

## 2. Tables at a glance (7 new)

| # | Table | Purpose | Grows by |
|---|---|---|---|
| 1 | `vocab_codes` | Every allowed code, by kind | Vocab release |
| 2 | `vocab_aliases` | Raw label → code (seed + learned, tenant/vendor scoped) | Every human correction |
| 3 | **`recon_extractions`** | **One row per parsed document — every `doc_role`, its header, its lines and their quantities** | Per upload |
| 4 | `recon_runs` | One reconciliation execution (template + vocab + rule version) | Per recon |
| 5 | `recon_run_documents` | Which extraction fills which **leg** in a run | Per run |
| 6 | `recon_results` | Line and header outcomes + rupee impact + the match it rests on + resolution | Per run |
| 7 | `recon_graph_sync` | What has been projected into the graph, and at which extraction version | Per load |

```
raw_invoice_uploads ─┬─ raw_ocr_results                          (existing, unchanged)
                     ├─ stg_bills → fact_bills / fact_invoices   (existing bill path)
                     └─ recon_extractions          ONE ROW PER DOCUMENT
                              │                    header + lines[] + lines[].quantities[]
                              │
                              ├─ recon_graph_sync ──► TigerGraph  (vertices + edges; derived)
                              │                            │
recon_runs ── recon_run_documents (leg) ───────────────── traversal
     └─ recon_results ──► fact_invoices.verification_flag / verification_detail   (write-back)

vocab_codes ◄── FK on document codes, trigger on line/quantity codes
vocab_aliases ◄── normaliser
```

> **Why 7 and not 5:** the two vocab tables enforce codes and capture learning. `recon_runs` and `recon_run_documents` exist because with POD and multiple receipt documents a run must record *which document filled which leg* and *which vocab and rule version it used*, so a verdict stays replayable. `recon_graph_sync` exists because the graph is derived: without it, nothing knows whether the graph is behind the extractions.

---

## 3. DDL

### 3.1 Vocabulary

```sql
CREATE TABLE vocab_codes (
    kind            text        NOT NULL,          -- e.g. 'doc_role', 'qty_role' (list in §6)
    code            text        NOT NULL,          -- e.g. 'PROOF_OF_DELIVERY'
    label           text        NOT NULL,
    description     text,
    parent_code     text,                          -- hierarchy (work_package: HVAC_LOW_SIDE → HVAC)
    tier            char(1)     NOT NULL DEFAULT 'L' CHECK (tier IN ('N','X','L')),
    version_added   text        NOT NULL,          -- 'v1'
    deprecated      boolean     NOT NULL DEFAULT false,
    replaced_by     text,                          -- code in same kind
    PRIMARY KEY (kind, code)
);

CREATE TABLE vocab_aliases (
    alias_id          uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    kind              text        NOT NULL,
    code              text        NOT NULL,
    alias_text        text        NOT NULL,        -- as seen: 'Given/ Vendor Qty (B)'
    alias_norm        text        NOT NULL,        -- lower, collapsed spaces/punct
    scope_tenant_id   uuid        REFERENCES dim_tenants(tenant_id),     -- NULL = global
    scope_supplier_id uuid        REFERENCES dim_suppliers(supplier_id), -- NULL = all vendors
    context_doc_role  text,                        -- resolves ambiguous labels (bare 'QTY'), V§18
    source            text        NOT NULL DEFAULT 'SEED'
                       CHECK (source IN ('SEED','HUMAN','LEARNED')),
    confirmed_by      uuid        REFERENCES org_users(user_id),
    created_at        timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (kind, code) REFERENCES vocab_codes(kind, code)
);
CREATE UNIQUE INDEX vocab_aliases_uniq ON vocab_aliases
  (kind, alias_norm, COALESCE(context_doc_role,''),
   COALESCE(scope_tenant_id,'00000000-0000-0000-0000-000000000000'),
   COALESCE(scope_supplier_id,'00000000-0000-0000-0000-000000000000'));
```

**How a document-level code column is enforced:** a **generated constant "kind" column** plus a composite FK. That gives real referential integrity without Postgres `ENUM`s, which are painful to extend (`ALTER TYPE … ADD VALUE` cannot run inside a transaction).

```sql
-- pattern, used below
doc_role       text NOT NULL,
doc_role_kind  text GENERATED ALWAYS AS ('doc_role') STORED,
FOREIGN KEY (doc_role_kind, doc_role) REFERENCES vocab_codes(kind, code)
```

### 3.2 `recon_extractions` — the one table

One row per parsed document, whatever the document is. A PO, a PV report, a tax invoice and a POD are the same row shape with different `doc_role`, different `header` keys and different `qty_role`s inside `lines`.

```sql
CREATE TABLE recon_extractions (
    extraction_id        uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id            uuid        NOT NULL REFERENCES dim_tenants(tenant_id),

    -- ── provenance: where this document came from ──────────────────────────
    upload_id            uuid        REFERENCES raw_invoice_uploads(upload_id),
    ocr_id               uuid        REFERENCES raw_ocr_results(ocr_id),
    channel              text        NOT NULL,     -- vocab 'channel': UPLOAD, EMAIL_ATTACHMENT, SFTP, PORTAL, ERP_EXPORT
    email_thread_id      text,                     -- poc_email_messages.thread_id when from email
    content_sha256       text        NOT NULL,     -- dedup of identical files
    page_range           int4range,                -- when one PDF holds several documents
    parent_extraction_id uuid        REFERENCES recon_extractions(extraction_id), -- proforma inside an invoice PDF

    -- ── classification (V§2) ──────────────────────────────────────────────
    doc_role             text        NOT NULL,
    doc_subrole          text,                     -- MAIN_BILL, RA_BILL, ADVANCE_INVOICE, FINAL_BILL …
    copy_type            text,                     -- ACCOUNTING_COPY, ORIGINAL_FOR_RECIPIENT …
    role_confidence      numeric(4,3),
    role_alias_raw       text,                     -- the tenant's own word, e.g. "GRN" for a signed POD (V§18)

    -- ── link keys: columns because the linker joins on them ───────────────
    doc_number           text,                     -- PO no / invoice no / waybill no / report ref
    doc_date             date,                     -- role-qualified meaning: see header.date_role (V§18)
    supplier_id          uuid        REFERENCES dim_suppliers(supplier_id),
    supplier_gstin       text,
    buyer_gstin          text,                     -- today dropped by ingest; kept here
    site_code            text,                     -- 8255, 9621
    po_number_ref        text,                     -- on invoices / PV sections / POD-less docs
    invoice_refs         text[]      NOT NULL DEFAULT '{}',  -- POD 'Invoice List', e-way → invoice

    -- ── money: columns because header arithmetic checks run on them ───────
    currency_code        char(3)     NOT NULL DEFAULT 'INR',
    taxable_amount       numeric(18,2),
    tax_amount           numeric(18,2),
    total_amount         numeric(18,2),

    -- ── the extraction itself (keys and codes from the vocabulary) ────────
    header               jsonb       NOT NULL DEFAULT '{}',   -- per doc_role, §5.2
    lines                jsonb       NOT NULL DEFAULT '[]',   -- [{line_seq, …, quantities:[…]}], §5.3
    assurance_exclusions text[]      NOT NULL DEFAULT '{}',   -- PV disclaimers, V§10
    flags                text[]      NOT NULL DEFAULT '{}',   -- extraction_artifact codes, V§16
    raw_payload          jsonb,                               -- the extractor's own output, verbatim

    -- ── derived counters, kept for cheap sanity checks ────────────────────
    line_count           int         GENERATED ALWAYS AS (jsonb_array_length(lines)) STORED,

    -- ── bridge to the existing bill path (TAX_INVOICE only) ───────────────
    stg_bill_id          uuid        REFERENCES stg_bills(stg_bill_id),
    invoice_id           uuid        REFERENCES fact_invoices(invoice_id),

    -- ── bookkeeping ───────────────────────────────────────────────────────
    vocab_version        text        NOT NULL,
    extractor            text        NOT NULL,     -- 'po_v1','pv_jpc_v1','pv_witnessed_v1','pod_v1','invoice_v2'
    extractor_version    text        NOT NULL,
    status               text        NOT NULL DEFAULT 'EXTRACTED'
                          CHECK (status IN ('EXTRACTED','REVIEWED','SUPERSEDED','REJECTED')),
    superseded_by        uuid        REFERENCES recon_extractions(extraction_id),
    reviewed_by          uuid        REFERENCES org_users(user_id),
    created_at           timestamptz NOT NULL DEFAULT now(),
    updated_at           timestamptz NOT NULL DEFAULT now(),

    doc_role_kind        text GENERATED ALWAYS AS ('doc_role') STORED,
    FOREIGN KEY (doc_role_kind, doc_role) REFERENCES vocab_codes(kind, code),
    CONSTRAINT lines_is_array CHECK (jsonb_typeof(lines) = 'array'),
    CONSTRAINT header_is_object CHECK (jsonb_typeof(header) = 'object')
);

-- one live extraction per file per tenant; a re-extraction supersedes rather than replaces
CREATE UNIQUE INDEX recon_extractions_sha  ON recon_extractions (tenant_id, content_sha256)
  WHERE status <> 'SUPERSEDED';
CREATE INDEX recon_extractions_keys ON recon_extractions (tenant_id, doc_role, doc_number);
CREATE INDEX recon_extractions_po   ON recon_extractions (tenant_id, po_number_ref);
CREATE INDEX recon_extractions_site ON recon_extractions (tenant_id, site_code);
CREATE INDEX recon_extractions_inv  ON recon_extractions USING gin (invoice_refs);
CREATE INDEX recon_extractions_flag ON recon_extractions USING gin (flags);
-- jsonb_path_ops: smaller and faster than the default for the @? / @@ queries the loader runs
CREATE INDEX recon_extractions_lines ON recon_extractions USING gin (lines jsonb_path_ops);
```

**Addressing a line.** A line has no row of its own, so its identity is `(extraction_id, line_seq)`. That pair is the graph vertex key and the `evidence_refs` anchor in `recon_results`. `line_seq` is assigned by the extractor, is stable for the life of the row, and is never renumbered — a re-extraction creates a new `extraction_id`.

### 3.3 Enforcing line-level codes without a foreign key

Principle 3 said a typo cannot be stored. Inside JSONB a foreign key cannot do that, so a trigger does. It validates every code in `lines` against `vocab_codes` and names the offenders.

```sql
CREATE OR REPLACE FUNCTION recon_validate_line_codes() RETURNS trigger AS $$
DECLARE
    bad text;
BEGIN
    WITH l AS (
        SELECT elem FROM jsonb_array_elements(COALESCE(NEW.lines, '[]'::jsonb)) AS t(elem)
    ),
    q AS (
        SELECT qelem FROM l,
             jsonb_array_elements(COALESCE(l.elem -> 'quantities', '[]'::jsonb)) AS t(qelem)
    ),
    used AS (
        SELECT 'line_origin'    AS kind, elem  ->> 'line_origin'    AS code FROM l
        UNION ALL SELECT 'charge_type',       elem  ->> 'charge_type'       FROM l
        UNION ALL SELECT 'work_package',      elem  ->> 'work_package'      FROM l
        UNION ALL SELECT 'uom',               elem  ->> 'uom'               FROM l
        UNION ALL SELECT 'uom_family',        elem  ->> 'uom_family'        FROM l
        UNION ALL SELECT 'rate_role',         elem  ->> 'rate_role'         FROM l
        UNION ALL SELECT 'pricing_basis',     elem  ->> 'pricing_basis'     FROM l
        UNION ALL SELECT 'line_nature',       elem  ->> 'line_nature'       FROM l
        UNION ALL SELECT 'qty_role',          qelem ->> 'qty_role'          FROM q
        UNION ALL SELECT 'measure_basis',     qelem ->> 'measure_basis'     FROM q
        UNION ALL SELECT 'evidence_layer',    qelem ->> 'evidence_layer'    FROM q
    )
    SELECT string_agg(DISTINCT used.kind || '=' || used.code, ', ' ORDER BY used.kind || '=' || used.code)
      INTO bad
      FROM used
     WHERE used.code IS NOT NULL
       AND NOT EXISTS (
             SELECT 1 FROM vocab_codes v
              WHERE v.kind = used.kind AND v.code = used.code AND NOT v.deprecated
           );

    IF bad IS NOT NULL THEN
        RAISE EXCEPTION 'recon_extractions: unknown or deprecated vocabulary code(s): %', bad
          USING HINT = 'add the code to docs/reconciliation/design/RECON_VOCABULARY.md and reseed vocab_codes, or map the raw label in vocab_aliases';
    END IF;
    RETURN NEW;
END $$ LANGUAGE plpgsql;

CREATE TRIGGER recon_extractions_validate_codes
    BEFORE INSERT OR UPDATE OF lines ON recon_extractions
    FOR EACH ROW EXECUTE FUNCTION recon_validate_line_codes();
```

Two notes on this trigger. It fires `BEFORE UPDATE OF lines`, so touching `status` or `reviewed_by` on a reviewed row costs nothing. And it rejects **deprecated** codes as well as unknown ones, which a foreign key would have accepted — so this is slightly stricter than rev 1, not weaker.

`item_spec`, `verification`, `conditions` and `header` keys are validated in the app by Pydantic models generated from the vocabulary (§6), because they are key sets rather than code values.

### 3.4 Runs, legs, results, graph sync

```sql
CREATE TABLE recon_runs (
    run_id             uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id          uuid        NOT NULL REFERENCES dim_tenants(tenant_id),
    template_code      text        NOT NULL,     -- 'CAPEX_FITOUT_PO_PV_INVOICE'
    template_version   text        NOT NULL,
    vocab_version      text        NOT NULL,
    rule_version       text        NOT NULL,     -- the compiled rule set in force (replayability)
    match_type         text        NOT NULL,     -- TWO_WAY / THREE_WAY / FOUR_WAY / ERS
    invoice_id         uuid        REFERENCES fact_invoices(invoice_id),   -- the bill being judged
    status             text        NOT NULL DEFAULT 'PENDING'
                        CHECK (status IN ('PENDING','RUNNING','COMPLETED','NEEDS_INPUT','FAILED','SUPERSEDED')),
    verification_flag  bill_verification_flag,   -- roll-up written back to fact_invoices/fact_bills
    summary            jsonb       NOT NULL DEFAULT '{}',   -- payable waterfall (§5.6)
    input_fingerprint  text        NOT NULL,     -- hash(extraction ids + versions + rule_version) → idempotency
    source             text        NOT NULL DEFAULT 'graph' CHECK (source IN ('graph','mirror')),
    started_at         timestamptz NOT NULL DEFAULT now(),
    completed_at       timestamptz,
    UNIQUE (tenant_id, input_fingerprint)
);

CREATE TABLE recon_run_documents (
    run_id              uuid       NOT NULL REFERENCES recon_runs(run_id) ON DELETE CASCADE,
    extraction_id       uuid       NOT NULL REFERENCES recon_extractions(extraction_id),
    leg                 text       NOT NULL,     -- COMMITMENT / DISPATCH / RECEIPT / QUALITY / BILLING / PAYMENT
    receipt_granularity text,                    -- ITEM_QTY / PACKAGE / CONSIGNMENT / VALUE (receipt leg, V§1)
    link_method         text       NOT NULL,     -- PO_NUMBER / INVOICE_REF / SITE+GSTIN / HUMAN
    link_confidence     numeric(4,3),
    leg_kind            text GENERATED ALWAYS AS ('recon_leg') STORED,
    FOREIGN KEY (leg_kind, leg) REFERENCES vocab_codes(kind, code),
    PRIMARY KEY (run_id, extraction_id)
);

CREATE TABLE recon_results (
    result_id          uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id             uuid        NOT NULL REFERENCES recon_runs(run_id) ON DELETE CASCADE,
    tenant_id          uuid        NOT NULL,
    scope              text        NOT NULL CHECK (scope IN ('LINE','HEADER')),
    code               text        NOT NULL,     -- recon_line_status (LINE) or recon_check_code (HEADER)
    outcome            text        NOT NULL CHECK (outcome IN ('PASS','WARN','FAIL','HOLD','NA')),
    reason_codes       text[]      NOT NULL DEFAULT '{}',
    decided_by         text        NOT NULL,     -- 'rule_R2_rate_variance' | 'decision_api' | 'human'
    abstained_rules    text[]      NOT NULL DEFAULT '{}',   -- rules that could not evaluate (V§0.3)

    -- the match this result rests on; the alignment itself lives in the graph (§4)
    match              jsonb,                    -- {commitment:{extraction_id,line_seq}, receipt:{…},
                                                 --  receipt_alt:{…}, billing:{…}, method, score, confirmed_by}

    -- numbers (LINE scope)
    qty_ordered        numeric(18,4),
    qty_verified       numeric(18,4),
    qty_invoiced       numeric(18,4),
    qty_payable        numeric(18,4),             -- computed here; never stored on an extraction
    rate_applied       numeric(18,4),
    amount_expected    numeric(18,2),
    amount_invoiced    numeric(18,2),
    variance_amount    numeric(18,2),             -- invoiced − expected (rupee impact)
    expected_value     jsonb,                     -- HEADER scope: what we expected
    found_value        jsonb,                     -- HEADER scope: what we found
    evidence_refs      jsonb       NOT NULL DEFAULT '[]',   -- graph path + (extraction_id, line_seq) anchors
    assurance_level    text,                      -- derived HIGH/MEDIUM/LOW (V§9)
    severity           severity_level NOT NULL DEFAULT 'LOW',   -- existing enum

    -- lifecycle (reuse existing enum; Review Hub work_items later)
    status             billing_discrepancy_status NOT NULL DEFAULT 'OPEN',
    resolution_note    text,
    resolved_by        uuid        REFERENCES org_users(user_id),
    resolved_at        timestamptz,
    created_at         timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX recon_results_run   ON recon_results (run_id, outcome);
CREATE INDEX recon_results_open  ON recon_results (tenant_id, status) WHERE status = 'OPEN';
CREATE INDEX recon_results_match ON recon_results USING gin (match jsonb_path_ops);

CREATE TABLE recon_graph_sync (
    extraction_id      uuid        PRIMARY KEY REFERENCES recon_extractions(extraction_id) ON DELETE CASCADE,
    tenant_id          uuid        NOT NULL,
    graph_name         text        NOT NULL,
    vertices_written   int         NOT NULL DEFAULT 0,
    edges_written      int         NOT NULL DEFAULT 0,
    unresolved_refs    jsonb       NOT NULL DEFAULT '[]',   -- a missing edge is a finding, not a retry
    loaded_at          timestamptz NOT NULL DEFAULT now(),
    extractor_version  text        NOT NULL,                -- stale if it differs from the extraction's
    pruned_at          timestamptz                          -- set when the settled cluster is pruned
);
```

`recon_results.code` is validated in the app against vocab kinds `recon_line_status` / `recon_check_code`. It is not a DB foreign key, because one column holds two kinds depending on `scope`.

### 3.5 Write-back (no schema change)

```sql
UPDATE fact_invoices SET verification_flag = :flag, verification_detail = :one_line, verified_at = now()
 WHERE invoice_id = :invoice_id AND tenant_id = :tenant;
-- same for fact_bills via stg_bill_id
```

Roll-up: **RED** = any FAIL (over-billed, spec deviation, buyer GSTIN mismatch); **YELLOW** = any HOLD or unconfirmed match; **GREEN** = all PASS/NA.

---

## 4. Where line alignment went

Rev 1 had `recon_line_matches`, a table of proposed and confirmed PO ↔ receipt ↔ invoice alignments. In the architecture that alignment **is** the graph:

| Rev 1 row | Rev 2 |
|---|---|
| `commitment_line_id → billing_line_id` | `BILLS_AGAINST` edge between the two line vertices |
| `receipt_line_id` | `RECEIVED_FOR` / `CERTIFIES` edge |
| `receipt_alt_line_id` (signed site sheet) | a second `CERTIFIES` edge carrying `evidence_layer` |
| `method`, `score` | edge attributes written by the loader |
| `status = PROPOSED / CONFIRMED` | edge attribute, flipped by the Review Hub action |
| the alignment a verdict used | `recon_results.match` + `evidence_refs` |

Why that is the right place: a match is a relationship, and the questions asked of it — what else bills against this PO line, what has been billed to date, which invoices hang off this audit report — are traversals. Keeping a second copy in Postgres would mean two sources of truth for the same edge.

What Postgres still keeps is the **decision**: `recon_results.match` records the alignment each verdict rested on, as a frozen snapshot, so a replay a year later does not depend on the graph still holding that edge.

---

## 5. JSONB shapes (keys = vocabulary; validated by Pydantic models generated from the vocab)

### 5.1 `source_ref` (every line, every quantity)

```json
{ "page": 13, "table": "annex4_p2", "row": 27, "col": "verified_qty",
  "bbox": [x0,y0,x1,y1], "evidence_layer": "TYPED_ANNEXURE", "snippet": "1.00" }
```

### 5.2 `header`, per `doc_role` (v1 keys only)

| doc_role | Keys |
|---|---|
| `PURCHASE_ORDER` | `pr_number`, `pr_name`, `vendor_code`, `po_revision`, `payment_terms_raw`, `payment_milestones[]`, `delivery_date`, `price_basis`, `ld_penalty[]`, `billing_address`, `delivery_address`, `po_tax_treatment`, `inspection_window_days`, `partial_delivery_policy` |
| `PHYSICAL_VERIFICATION_REPORT` | `pv_format`, `auditor_name`, `auditor_frn`, `audit_date`, `quantity_legend{A,B,C → qty_role}`, `assurance_level_stated`, `personnel_present[]`, `po_sections[]{title_raw, work_package, vendor_gstin, section_total}`, `site{concept, core_selling_area_sqft, distance_km, project_manager}` |
| `SITE_VERIFICATION_SHEET` | `audit_date`, `signoff[]{name, person_role, signoff_capacity, signature_present, seal_present}`, `parent_report_ref` |
| `MEASUREMENT_SHEET` | `submitted_by`, `submission_date`, `parent_report_ref` |
| `TAX_INVOICE` | `is_e_invoice`, `irn`, `ack_no`, `ack_date`, `place_of_supply`, `supply_type`, `bill_to{}`, `ship_to{}`, `tax_components[]{component, rate, amount}`, `round_off`, `amount_in_words`, `billing_basis`, `remarks`, `bank{}`, `category_subtotals[]`, `reverse_charge` |
| `PROFORMA_INVOICE` | `billing_basis`, `remarks`, `parent_invoice_ref` |
| `PROOF_OF_DELIVERY` / `LORRY_RECEIPT` | `carrier`, `booking_branch`, `destination_branch`, `pickup_datetime`, `ship_date`, `consignor{}`, `consignee{}`, `declared_invoice_value`, `invoice_count`, `eway_bill_no`, `package_count`, `actual_weight_kg`, `charged_weight_kg`, `package_dimensions[]`, `freight_payment_mode`, `delivery_mode`, `receiver_name`, `received_date`, `receiver_stamp_text` |
| `APPROVAL_COMMUNICATION` | `communication_intent`, `approver_name`, `person_role`, `sent_at`, `subject`, `quoted_text` |
| any other `doc_role` | `date_role` plus whatever that role's vocabulary entry defines; an unset key is absent, never `null` |

### 5.3 `lines[]` — the line and its quantities in one object

```json
{
  "line_seq": 27,
  "line_no_raw": "58 Add.",
  "section_raw": "AC LS PO",
  "vendor_gstin": "29AABCB1043Q1ZJ",

  "line_origin": "ADDITIONAL_WORK",
  "charge_type": null,
  "work_package": "HVAC_LOW_SIDE",
  "line_nature": "INSTALL_ONLY",

  "description_raw": "Core cutting for refrigerant piping, 4 in dia",
  "description_norm": "core cutting refrigerant piping 4 in dia",
  "item_key": null,
  "hsn_sac": "9954",
  "fa_codes": [],

  "uom_raw": "Nos", "uom": "EA", "uom_family": "COUNT",
  "rate": 850.0, "rate_role": "RATE_NET", "discount_pct": 5.0,
  "pricing_basis": "UNIT_RATE", "amount": 3400.0, "tax_rate_pct": 18.0,

  "item_spec":     { "diameter": {"value": 4, "unit": "in"}, "spec_fingerprint": "…" },
  "verification":  { "status": "VERIFIED", "measurement_technique": "COUNT",
                     "visibility": "VISIBLE", "basis_source": "VENDOR_DIRECTED",
                     "remark_raw": "Counted on the directions of vendor." },
  "conditions":    [ {"code": "PHOTO_REQUIRED", "text_raw": "Photos to be shared with Audit Team",
                      "satisfied": false, "evidence_extraction_id": null} ],

  "quantities": [
    { "qty_role": "QTY_ORDERED",  "evidence_layer": "TYPED_ANNEXURE",
      "value": 4, "uom": "EA", "measure_basis": "ITEM", "value_raw": "4",
      "value_history": [], "measurement_working": null, "source_ref": { "…": "…" } },
    { "qty_role": "QTY_CLAIMED",  "evidence_layer": "TYPED_ANNEXURE",
      "value": 4, "uom": "EA", "measure_basis": "ITEM", "value_raw": "4",
      "value_history": [], "measurement_working": null, "source_ref": { "…": "…" } },
    { "qty_role": "QTY_VERIFIED", "evidence_layer": "SIGNED_SITE_SHEET",
      "value": 4, "uom": "EA", "measure_basis": "ITEM", "value_raw": "~~3~~ 4",
      "value_history": [{"was": 3, "now": 4, "kind": "HANDWRITTEN_CORRECTION"}],
      "measurement_working": null, "source_ref": { "…": "…" } }
  ],

  "source_ref": { "page": 13, "table": "annex4_p2", "row": 27, "evidence_layer": "TYPED_ANNEXURE" },
  "flags": [], "confidence": 0.94
}
```

Three rules this shape carries over from rev 1, unchanged:

- **`value: null` means stated but illegible**, and is different from the key being absent, which means not given.
- **Two evidence layers stay apart.** The typed annexure and the signed site sheet are separate entries in `quantities`, keyed by `evidence_layer`, never merged. Rev 1 enforced that with a primary key; here the Pydantic model rejects a duplicate `(qty_role, evidence_layer)` pair.
- **`QTY_PAYABLE` is never stored on an extraction.** It is computed into `recon_results.qty_payable`.

### 5.4 Keys promoted out of JSON — the rule

A key moves from `lines[]` to its own column only when **the linker or a header check** needs it, which in practice means the key appears on the document, not on the line. If a *rule* needs it, it belongs in the graph, loaded from JSON. There is no third case, so there is nothing in v1 to promote.

### 5.5 `assurance_exclusions` and inheritance

Extracted once per PV report and stored on the row. Line-level inheritance is applied by the graph loader, which writes the exclusion onto each affected line vertex in the matching `work_package` (V§10). The extraction keeps the report-level fact; the graph keeps the per-line consequence.

### 5.6 `recon_runs.summary` (payable waterfall)

```json
{ "eligible_taxable": 606740.50, "held_taxable": 30000.00, "unbilled_verified": 1850.00,
  "invoiced_taxable": 634890.50, "tax": 114280.29,
  "advance_adjustment": null, "tds": null, "retention": null, "ld_penalty": null,
  "net_payable_now": null, "pending_inputs": ["advance_ledger", "completion_date"] }
```

---

## 6. For each document listed: how it lands in the one table

Every `doc_role` in the vocabulary uses `recon_extractions`. What differs is which `header` keys are set, which `qty_role`s appear in `lines[].quantities`, and whether the document has lines at all.

| `doc_role` (V§2) | Leg | Lines? | `qty_role`s seen in `lines[]` | Header keys | Extractor | Tier |
|---|---|---|---|---|---|---|
| `PURCHASE_ORDER` | COMMITMENT | yes | `QTY_ORDERED` | §5.2 PO block | `po_v1` | **N** |
| `PO_AMENDMENT` | COMMITMENT | yes | `QTY_ORDERED` | PO block + `po_revision` | `po_v1` | X |
| `PURCHASE_REQUISITION` | COMMITMENT | yes | `QTY_ORDERED` | `pr_number`, `pr_name` | `po_v1` | X |
| `RATE_CONTRACT` | COMMITMENT | yes | — (rates only) | `price_basis`, validity | `po_v1` | X |
| `BOQ` | COMMITMENT | yes | `QTY_ORDERED` | PO block | `po_v1` | X |
| `WORK_ORDER` | COMMITMENT | yes | `QTY_ORDERED` | PO block | `po_v1` | X |
| `PHYSICAL_VERIFICATION_REPORT` | RECEIPT | yes | `QTY_ORDERED`, `QTY_CLAIMED`, `QTY_VERIFIED`, `QTY_MOUNTED`, `QTY_UNMOUNTED`, `QTY_DAMAGED` | §5.2 PV block | `pv_jpc_v1` (AUDITOR_ANNEXURE), `pv_witnessed_v1` (WITNESSED_VENDOR_SHEET) | **N** |
| `SITE_VERIFICATION_SHEET` | RECEIPT | yes | `QTY_VERIFIED` (`evidence_layer=SIGNED_SITE_SHEET`) | signoff block | same PV extractor, child row | **N** |
| `MEASUREMENT_SHEET` | RECEIPT | yes | `QTY_CLAIMED` | `submitted_by` | same PV extractor, child row | **N** |
| `PROOF_OF_DELIVERY` | RECEIPT | **no** | `QTY_DELIVERED` on a single synthetic line, `measure_basis=PACKAGE` | §5.2 POD block | `pod_v1` | **N** |
| `LORRY_RECEIPT` | DISPATCH | no | `QTY_DISPATCHED`, `measure_basis=PACKAGE` | POD block | `pod_v1` | X |
| `EWAY_BILL` | DISPATCH | no | — (`VALUE` basis only) | `eway_bill_no`, `eway_valid_upto`, `vehicle_no` | `pod_v1` | X |
| `DELIVERY_CHALLAN` | DISPATCH | yes | `QTY_DISPATCHED` | consignor/consignee | `pod_v1` | X |
| `GOODS_RECEIPT_NOTE` | RECEIPT | yes | `QTY_RECEIVED`, `QTY_ACCEPTED`, `QTY_REJECTED` | receiver, receipt date | not in v1 | X |
| `COMPLETION_CERTIFICATE` | RECEIPT | no | — | completion date, signoff | not in v1 | X |
| `COMMISSIONING_CERTIFICATE` | QUALITY | no | — | signoff, scope | not in v1 | X |
| `TAX_INVOICE` | BILLING | yes | `QTY_INVOICED` | §5.2 invoice block | `invoice_v2` | **N** |
| `PROFORMA_INVOICE` | BILLING | yes | `QTY_INVOICED` (`billing_basis=AUDIT_QTY`) | `billing_basis`, `parent_invoice_ref` | `invoice_v2`, child row | **N** |
| `CREDIT_NOTE` / `DEBIT_NOTE` | BILLING | yes | `QTY_INVOICED` (signed) | invoice block + `original_invoice_ref` | `invoice_v2` | X |
| `APPROVAL_COMMUNICATION` | — | no | — | §5.2 approval block | `email_v1` | **N** |
| `PAYMENT_ADVICE` / `BANK_STATEMENT` | PAYMENT | yes | — (amounts only) | UTR, value date | not in v1 | X |
| every tier-**L** role | per V§1 | per role | per role | `date_role` only | none yet | L |

Three things this table settles:

**A POD has no item lines, and must not be made to look as if it does.** `pod_v1` writes one synthetic line carrying `QTY_DELIVERED` with `measure_basis = PACKAGE`, and `recon_run_documents.receipt_granularity = PACKAGE`. The rule layer reads that granularity and will not use a POD as item-level receipt evidence, nor fail an invoice because the POD has no line items (V§1).

**A PV report's signed field sheets are child rows, not a second format.** `parent_extraction_id` points at the report, and the sheet's quantities carry `evidence_layer = SIGNED_SITE_SHEET`. Both layers are then available to the same rule without either overwriting the other.

**The tenant's own word for a document is kept, and does not decide the role.** `role_alias_raw` stores "GRN" when the client calls a signed POD that; `doc_role` is still `PROOF_OF_DELIVERY`, decided by evidence present (V§0.5, V§18).

---

## 7. Which vocabulary kinds are enforced where

| Vocab kind (`docs/reconciliation/design/RECON_VOCABULARY.md`) | Enforced by |
|---|---|
| `doc_role`, `recon_leg` | **DB foreign key** (generated-kind pattern, §3.1) |
| `line_origin`, `charge_type`, `work_package`, `line_nature`, `uom`, `uom_family`, `rate_role`, `pricing_basis`, `qty_role`, `measure_basis`, `evidence_layer` | **DB trigger** against `vocab_codes`, including the deprecated check (§3.3) |
| `doc_subrole`, `copy_type`, `channel`, `recon_line_status`, `recon_check_code`, `extraction_artifact`, `assurance_exclusion`, `link_method` | App validation against `vocab_codes` (promote into the trigger if a bad value ever slips through) |
| JSON key sets: `item_spec`, `verification`, `conditions`, `header` | Pydantic models generated from the vocab registry |
| Everything else in the vocabulary (tier L) | Seeded in `vocab_codes` so it is ready, but no extractor asks for it yet |

**Seeding:** a script parses `docs/reconciliation/design/RECON_VOCABULARY.md` (or a `vocab/v1.yaml` exported from it) and upserts `vocab_codes` + `vocab_aliases (source='SEED')`. Rows are never deleted; only `deprecated = true` is set. Because the trigger rejects deprecated codes, deprecating one is a breaking change for extractors and must ship with the extractor that stops emitting it.

---

## 8. Changes to existing code

| Where | Change |
|---|---|
| `utils/ocr_engine.py` invoice schema | Add `po_number_ref`, `irn`, `ack_no`, `ack_date`, `place_of_supply`, `ship_to{}`, `round_off`, `line_items[].line_no_raw`; `document_type` emits V§2 roles |
| New extractors | `po_v1`, `pv_jpc_v1` (auditor-annexure), `pv_witnessed_v1` (Matolia-style vendor sheet), `pod_v1`, `email_v1`. Each writes **one `recon_extractions` row** per document and nothing else |
| `ingest_invoice()` | After the existing insert, also write the invoice as a `recon_extractions` row (`stg_bill_id`, `invoice_id` set) so recon sees it. **No change** to `stg_bills` columns |
| New loader | `GraphLoader`: reads `recon_extractions`, writes vertices and edges, records `recon_graph_sync`, leaves an unresolved reference as a missing edge rather than retrying |
| New worker | `ReconWorker`: link → traverse → compute → write `recon_results`, roll up `verification_flag` |
| Exceptions | Until Review Hub ships: an OPEN FAIL/HOLD result creates a `wf_tasks` REVIEW (add `RECON_EXCEPTION` to `wf_entity_type`) |
| Review Hub adapter | `capex_match` adapter's `scan()` reads `recon_results` where `status = 'OPEN'`, bounded by `LINE_LIMIT`, and yields complete current truth so a resolved finding clears itself |

---

## 9. What is deliberately NOT in v1

Separate PO-terms tables, RA-bill cumulative tracking in Postgres (the cumulative position is a graph traversal), retention/DLP, GRN/SES/MB extractors, the QUALITY leg, LD computation (flag only), tolerance configuration UI, the workflow-builder UI, `work_package` hierarchy rules, handwriting history beyond `value_history`, and a site master table (`site_code` + `header.site{}` suffice until a second rule needs site attributes across documents).

**Promotion triggers:**

- `site_code` gets its own `recon_sites` table when SLAB / DISTANCE_TIER checks go live.
- `header.irn` becomes a column when an IRN-validation API check lands.
- `po_sections` becomes a table when one PV report must be split across more than three vendors routinely.
- `lines` goes back to being a table **only if** a reader appears that must filter or join on a line attribute in SQL rather than in the graph. None exists today; if one does, that is the signal, and §5.4 is the test.

---

## 10. Open items (need client or tenant confirmation)

Carried from the vocabulary, unchanged: **PPS sheet** expansion, **SIS** team/process name, **FSC** store-format code, **GTY**/**SCH** carrier codes, **TBB**, **DACC** expansion.

~~and whether Bata's "GRN" always means a signed POD or sometimes a store-level inward entry~~ — **resolved 16 Nov 2026 (§11, R8):** the GRN is an entry inside Microsoft Dynamics, never issued as a document; the vendor's delivery paper is a POD and a separate thing entirely.

New with rev 2:

- **Does Microsoft Dynamics expose an idempotency key on voucher creation?** The posting adapter is keyed on the invoice so a retry cannot double-post; that depends on the ERP honouring it.
- **One graph per tenant, or one graph with a tenant attribute?** `recon_graph_sync.graph_name` assumes per-tenant. Confirm before the loader is written, because it decides how isolation is enforced.

---

## 11. Confirmed business rules (Bata call, 16 November 2026) — and what changes in v1

Source: call "Bata X Reckon.ai: Data Clarification", 16 Nov 2026, Harminder Singh (Bata).
Full question-and-answer record in `docs/reconciliation/QUESTIONS_FOR_BATA.md`.

### 11.1 The rules, as stated

| # | Rule | Consequence for the engine |
|---|---|---|
| R1 | The match is **GRN ↔ invoice ↔ audit report**. The PO is a **cap**, not a compared leg | The template changes shape — see §11.2 |
| R2 | The **PO sets the maximum quantity and the fixed rate**. A GRN may be lower, never higher | Cap check against the PO; rate equality, not rate tolerance |
| R3 | The **auditor's certified quantity is final**, and the GRN is created from it | Payable qty = audit-certified qty, capped at PO qty. **No override facility needed** |
| R4 | **A PO is never amended once approved** | `PO_AMENDMENT` is dead for this tenant; an amendment arrives as a new PO |
| R5 | Out-of-PO lines: book the invoice in full, book a **credit note** for the excess, raise a **new PO** + new invoice for the balance | `CREDIT_NOTE` enters v1; the exception's prescribed action is "obtain credit note" |
| R6 | **One PO → many invoices. One invoice → never two POs** (prohibited) | A hard validation check, and linking is many-to-one |
| R7 | Variance threshold: invoice over GRN by **≤ ₹100 is booked**; above ₹100 goes to the **costing team** | One absolute rupee threshold. No percentage band |
| R8 | The **GRN exists only inside MSD**; no copy is issued. The vendor's delivery paper is a **POD, a separate document** | GRN ingests as a structured extract, not OCR |
| R9 | 60% advance against the PO, parked in the vendor ledger, settled at invoice booking — **not required for matching** | Advance, retention and LD leave v1 scope |
| R10 | An invoice is usually raised after the audit report, **but sometimes before**, and is corrected later by credit note | A billing document may arrive with no receipt leg yet; park, do not fail |

### 11.2 Scope of v1, restated

The v1 template is no longer `CAPEX_FITOUT_PO_PV_INVOICE` as written in the header of this
document. It is:

```
COMMITMENT   PURCHASE_ORDER                  — cap only: max quantity, fixed rate
RECEIPT      GOODS_RECEIPT_NOTE (MSD extract) — the compared receipt leg
CERTIFYING   PHYSICAL_VERIFICATION_REPORT     — the authority the GRN quantity comes from
BILLING      TAX_INVOICE  (+ CREDIT_NOTE)     — the claim, and its correction
```

`match_type` stays `THREE_WAY` on the compared legs, with the PO as a cap and the audit
report as the certifying source — which is what makes it a four-document process.

### 11.3 Changes this forces on the schema and the vocabulary

| Where | Change | Status |
|---|---|---|
| §6 table | `GOODS_RECEIPT_NOTE` moves from "not in v1" to **core v1**, extractor `grn_msd_v1` | **to do** |
| §6 table | `CREDIT_NOTE` moves from tier X to **v1**, extractor `invoice_v2` | **to do** |
| `recon_extractions.channel` | GRN rows use `ERP_EXPORT`; there is no OCR step and no `ocr_id` | no DDL change |
| §5.2 `header` | New `GOODS_RECEIPT_NOTE` block: `grn_number`, `posting_date`, `po_ref`, `received_by`, `msd_voucher` | **to do** |
| §5.2 `header` | `CREDIT_NOTE` block: `original_invoice_ref`, `reason`, `excess_line_refs[]` | **to do** |
| §5.6 `summary` | Drop `advance_adjustment`, `retention`, `ld_penalty` and both `pending_inputs` — out of scope per R9 | **to do** |
| Rules | `R_VARIANCE`: `invoice_total − grn_total > 100` → exception to the costing team | **to do** |
| Rules | `R_PO_CAP`: GRN qty ≤ PO qty, cumulative invoiced qty ≤ PO qty (R6 means cumulative matters) | **to do** |
| Rules | `R_RATE`: invoice rate **must equal** the PO rate. Not a tolerance — a rate change requires a new PO | **to do** |
| Rules | `R_SINGLE_PO`: an invoice referencing two PO numbers fails validation outright | **to do** |
| Vocabulary §2 | Annotate `PO_AMENDMENT` as **not used by Bata** (R4), and the GRN/POD ambiguity as **resolved** (R8) | **to do** |
| Vocabulary §11 | `EMAIL_APPROVAL_REQUIRED` no longer clears an out-of-PO line; it is evidence on the exception, not a gate | **to do** |

### 11.4 The ₹100 threshold, precisely

```
exception  ⟺  (invoice_total − grn_total) > 100.00 INR
```

Three things worth stating because they are easy to get wrong:

1. **It is absolute, not a percentage.** Asked directly about a percentage band, Bata's
   answer was "₹100, whichever is lower". On a ₹7.5 lakh invoice this is roughly 0.013%, so
   it is far tighter than any percentage rule we would have proposed.
2. **It compares the invoice to the GRN**, not to the PO and not line by line.
3. **The additional-line-items case breaches it by design.** The invoice is booked at full
   value against a lower GRN, so the breach is expected, and it clears when the credit note
   is produced. That exception is therefore *routine*, not an error — it must not be
   presented as a failure, or the costing team will see a red queue every day.

### 11.5 What this closes, and what is still open

**Closed by the call:** the variance threshold, the out-of-PO process, the authority of the
audit quantity, the advance question, and the meaning of "GRN" — which had been an open item
in both this document and `docs/reconciliation/design/RECON_VOCABULARY.md` §20 since the first draft.

**Still open:**

- **Dynamics posting.** Who posts the voucher, whether we need write access, and whether
  Dynamics rejects a duplicate submission. Not covered on the call.
- **The document mailbox** and typical senders.
- **Is the ₹100 per invoice or per line?** The call implies per invoice; worth one line of
  written confirmation before it is coded.
- **An invoice *below* the GRN value** — booked, or also an exception? Not asked.
- **One graph per tenant, or one graph with a tenant attribute?** Unchanged from rev 2.

**Awaited from Bata:** Excel extracts of GRN line items (2–3 samples), and one sample credit
note linked to its invoice. The GRN extract is on the critical path — until it arrives, the
receipt leg has no real input and §11.3's `grn_msd_v1` cannot be written against anything
but a guess at the column set.
