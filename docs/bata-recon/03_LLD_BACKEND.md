# 03 · Low-Level Design: Backend

## 1. Module layout

```
backend_ocr/app/recon/
  __init__.py
  types.py              # enums + dataclasses from 02_CLASS_DIAGRAMS §1, §3, §5
  config.py             # RuleConfig defaults, thresholds, model names, env reads
  num.py                # parse_inr, close(), money rounding (ROUND_HALF_UP, 2dp)
  normalize.py          # TextNormalizer, UnitCanon, SPELLING, PREFIXES
  pages.py              # PageReader (wraps utils/ocr_engine)
  llm.py                # ReconLLM (OpenAI + Jev), JSON-schema calls, cost accounting
  classify.py           # PageClassifier
  segment.py            # Segmenter
  extract/
    __init__.py         # ExtractorRegistry
    base.py             # Extractor ABC, ExtractContext
    po.py               # POExtractor
    invoice.py          # InvoiceExtractor (header + annexure + corrections)
    pv_jpc.py           # JpcAnnexureExtractor (typed tables)
    pv_sheet.py         # ScannedSheetExtractor (Matolia; PO-prompted, double read)
    pv_field.py         # FieldSheetExtractor (Mounted/Unmounted/Damaged)
    pod.py              # PODExtractor
    memo.py             # MemoExtractor
    generic.py          # GenericExtractor
    spreadsheet.py      # SpreadsheetMapper (reads vendor_doc_rows)
    prompts.py          # all prompt templates + JSON schemas
  link.py               # DocumentLinker
  match.py              # LineMatcher, Hungarian
  aliases.py            # AliasStore
  rules.py              # VerdictClassifier, BillingRule
  engine.py             # HeaderChecks, LineChecks, ReconEngine
  case.py               # CaseBuilder (DB → ReconInput)
  pipeline.py           # ReconPipeline (ingest, recompute)
  repo.py               # ReconRepository (asyncpg)
  worker.py             # ReconWorker(BaseWorker)
  export.py             # xlsx export
backend_ocr/app/routers/recon.py
backend_ocr/app/review/adapters/recon_variance.py
backend_ocr/app/migrations.py          # + _ensure_recon_tables()
tests/recon/...                        # see 07_TEST_PLAN.md
```

**Registration:**

- **Router:** add `recon` to `main.py`. Mount it separately with
  `app.include_router(recon.router, dependencies=[Depends(require_service("recon"))])`, the same
  way as `tds_router`.
- **Worker:** add `ReconWorker()` to the `workers` list in `review/scheduler.py:77`.
- **Adapter:** add `ReconVarianceAdapter` to `review/adapters/__init__.py`.
- **Migration:** call `_ensure_recon_tables()` from the migration runner, after
  `_ensure_vendor_doc_tables()`.

## 2. Database

All tables carry `tenant_id UUID NOT NULL`. Every read filters on it.

```sql
-- 2.1 vendor_documents: new columns (existing table)
ALTER TABLE vendor_documents ADD COLUMN IF NOT EXISTS recon_status VARCHAR(16);      -- NULL unless doc_type='recon'
ALTER TABLE vendor_documents ADD COLUMN IF NOT EXISTS recon_error  TEXT;
ALTER TABLE vendor_documents ADD COLUMN IF NOT EXISTS recon_stage  VARCHAR(24);      -- reading|classifying|extracting|linking|matching|done
ALTER TABLE vendor_documents ADD COLUMN IF NOT EXISTS recon_progress JSONB;          -- {"page":3,"pages":11}
ALTER TABLE vendor_documents ADD COLUMN IF NOT EXISTS content_sha256 CHAR(64);       -- duplicate-upload detection
CREATE INDEX IF NOT EXISTS idx_vdoc_recon_pending ON vendor_documents (recon_status) WHERE recon_status IN ('PENDING','RUNNING');
CREATE INDEX IF NOT EXISTS idx_vdoc_sha ON vendor_documents (tenant_id, supplier_id, content_sha256);
-- doc_type gains the value 'recon'; DOC_TYPES = ("contract","other","recon")

-- 2.2 pages (cache of the reading step; lets re-extraction skip OCR)
CREATE TABLE IF NOT EXISTS recon_doc_pages (
  doc_id        UUID NOT NULL REFERENCES vendor_documents(id) ON DELETE CASCADE,
  page_index    INT  NOT NULL,
  tenant_id     UUID NOT NULL,
  text          TEXT,
  source        VARCHAR(8) NOT NULL,              -- text|vision|sheet
  ocr_confidence NUMERIC(4,3),
  doc_class     VARCHAR(24),
  class_conf    NUMERIC(4,3),
  class_method  VARCHAR(8),
  llm_label     VARCHAR(80),
  hints         JSONB,                            -- vendor_hint, section_title, store_sn
  PRIMARY KEY (doc_id, page_index)
);

-- 2.3 segments = logical documents inside a file
CREATE TABLE IF NOT EXISTS recon_doc_segments (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  doc_id        UUID NOT NULL REFERENCES vendor_documents(id) ON DELETE CASCADE,
  tenant_id     UUID NOT NULL,
  supplier_id   UUID NOT NULL,
  kind          VARCHAR(16) NOT NULL,             -- SegmentKind
  pages         INT[] NOT NULL,
  section_title VARCHAR(120),
  vendor_name   VARCHAR(200),
  vendor_gstin  VARCHAR(15),
  store_sn      VARCHAR(16),
  confidence    NUMERIC(4,3),
  extracted_json JSONB,                           -- ExtractedDoc.to_json()
  extractor_version VARCHAR(16),
  status        VARCHAR(16) NOT NULL DEFAULT 'PENDING', -- PENDING|EXTRACTED|NEEDS_REVIEW|LINKED|UNLINKED|FOREIGN|IGNORED|FAILED
  link_candidates JSONB,                          -- [LinkCandidate]
  kind_overridden_by VARCHAR(100),
  created_at    TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_rseg_supplier ON recon_doc_segments (tenant_id, supplier_id, kind);
CREATE INDEX IF NOT EXISTS idx_rseg_store ON recon_doc_segments (tenant_id, store_sn);

-- 2.4 purchase orders (also proposed in docs/agents/RECON_AGENT.md §9)
CREATE TABLE IF NOT EXISTS purchase_orders (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id     UUID NOT NULL,
  supplier_id   UUID NOT NULL,
  po_number     VARCHAR(40) NOT NULL,             -- 'PPO00024378' (no revision)
  revision      INT NOT NULL DEFAULT 1,
  po_date       DATE,
  store_sn      VARCHAR(16),
  store_name    VARCHAR(200),
  buyer_gstin   VARCHAR(15),
  vendor_gstin  VARCHAR(15),
  payment_terms VARCHAR(80),
  requisition_no VARCHAR(40),
  requisition_name VARCHAR(200),
  subtotal      NUMERIC(14,2),
  tax           NUMERIC(14,2),
  total         NUMERIC(14,2),
  penalties     JSONB,
  segment_id    UUID REFERENCES recon_doc_segments(id) ON DELETE SET NULL,
  superseded_by UUID REFERENCES purchase_orders(id),
  created_at    TIMESTAMPTZ DEFAULT now(),
  UNIQUE (tenant_id, po_number, revision)
);
CREATE TABLE IF NOT EXISTS purchase_order_lines (
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
);

-- 2.5 invoice annexure lines (when the bill only has header lines)
CREATE TABLE IF NOT EXISTS recon_invoice_lines (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  segment_id    UUID NOT NULL REFERENCES recon_doc_segments(id) ON DELETE CASCADE,
  tenant_id     UUID NOT NULL,
  sno           INT,
  description   TEXT NOT NULL,
  norm          TEXT NOT NULL,
  hsn           VARCHAR(12),
  unit          VARCHAR(16),
  qty           NUMERIC(14,3),
  rate          NUMERIC(14,4),
  amount        NUMERIC(14,2),
  tax_rate      NUMERIC(5,2),
  confidence    NUMERIC(4,3),
  page          INT,
  bbox          JSONB,
  is_charge     BOOLEAN NOT NULL DEFAULT false,
  charge_pct    NUMERIC(6,3)
);

-- 2.6 evidence rows (PV sections, POD lines, generic tabular evidence)
CREATE TABLE IF NOT EXISTS recon_evidence_rows (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  segment_id    UUID NOT NULL REFERENCES recon_doc_segments(id) ON DELETE CASCADE,
  tenant_id     UUID NOT NULL,
  sno           INT,
  asset_code    VARCHAR(80),
  item          TEXT NOT NULL,
  norm          TEXT NOT NULL,
  unit          VARCHAR(16),
  po_qty        NUMERIC(14,3),
  vendor_qty    NUMERIC(14,3),
  audit_qty     NUMERIC(14,3),
  audit_qty_raw VARCHAR(40),                      -- '348+102=450', '—', ''
  remark        TEXT,
  verdict       VARCHAR(16) NOT NULL,             -- AuditVerdict
  mounted INT, unmounted INT, damaged INT,
  rate          NUMERIC(14,4),
  rate_after_discount NUMERIC(14,4),
  row_type      VARCHAR(12) NOT NULL DEFAULT 'po',-- po|additional
  confidence    NUMERIC(4,3),
  needs_review  BOOLEAN NOT NULL DEFAULT false,
  page          INT,
  bbox          JSONB,                            -- audit_qty cell bbox, for crop
  corrected_by  VARCHAR(100),
  corrected_at  TIMESTAMPTZ,
  original_json JSONB                             -- value before human correction
);

-- 2.7 cases
CREATE TABLE IF NOT EXISTS recon_cases (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id     UUID NOT NULL,
  supplier_id   UUID NOT NULL,
  brand_id      UUID,
  bill_id       UUID,                             -- stg_bills.id; NULL = AWAITING_INVOICE
  invoice_segment_id UUID REFERENCES recon_doc_segments(id) ON DELETE SET NULL,
  po_id         UUID REFERENCES purchase_orders(id) ON DELETE SET NULL,
  store_sn      VARCHAR(16),
  status        VARCHAR(20) NOT NULL,             -- CaseStatus
  summary_json  JSONB,                            -- ReconSummary
  money_at_risk NUMERIC(14,2) NOT NULL DEFAULT 0,
  counts        JSONB,                            -- {"BLOCKER":1,"REVIEW":4,"INFO":12}
  engine_version VARCHAR(16),
  computed_at   TIMESTAMPTZ,
  acknowledged_by VARCHAR(100),
  acknowledged_at TIMESTAMPTZ,
  ack_note      TEXT,
  created_at    TIMESTAMPTZ DEFAULT now(),
  UNIQUE (tenant_id, bill_id)                     -- one case per bill
);
CREATE INDEX IF NOT EXISTS idx_rcase_supplier ON recon_cases (tenant_id, supplier_id, status);

CREATE TABLE IF NOT EXISTS recon_case_segments (
  case_id       UUID NOT NULL REFERENCES recon_cases(id) ON DELETE CASCADE,
  segment_id    UUID NOT NULL REFERENCES recon_doc_segments(id) ON DELETE CASCADE,
  tenant_id     UUID NOT NULL,
  role          VARCHAR(16) NOT NULL,             -- po|invoice|evidence|pod|memo|other
  link_method   VARCHAR(8) NOT NULL,              -- auto|user
  link_score    NUMERIC(4,3),
  linked_by     VARCHAR(100),
  linked_at     TIMESTAMPTZ DEFAULT now(),
  PRIMARY KEY (case_id, segment_id)
);

-- 2.8 results (replaced wholesale on every recompute)
CREATE TABLE IF NOT EXISTS recon_line_results (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  case_id       UUID NOT NULL REFERENCES recon_cases(id) ON DELETE CASCADE,
  tenant_id     UUID NOT NULL,
  ord           INT NOT NULL,
  po_line_id    UUID,
  invoice_line_key VARCHAR(80),                   -- 'bill:<stg_line_id>' | 'rl:<recon_invoice_lines.id>'
  evidence_row_id UUID,
  description   TEXT NOT NULL,
  unit          VARCHAR(16),
  po_qty NUMERIC(14,3), verified_qty NUMERIC(14,3), billed_qty NUMERIC(14,3), expected_qty NUMERIC(14,3),
  po_rate NUMERIC(14,4), billed_rate NUMERIC(14,4),
  expected_amt NUMERIC(14,2), billed_amt NUMERIC(14,2), delta NUMERIC(14,2),
  verdict       VARCHAR(16),
  statuses      VARCHAR(24)[] NOT NULL,
  severity      VARCHAR(8) NOT NULL,
  match_method  VARCHAR(8),
  match_score   NUMERIC(4,3),
  conflicts     TEXT[],
  remark        TEXT,
  reviewed_by   VARCHAR(100),                     -- carried over across recomputes by (po_line_id, invoice_line_key)
  reviewed_note TEXT
);
CREATE TABLE IF NOT EXISTS recon_header_checks (
  case_id UUID NOT NULL REFERENCES recon_cases(id) ON DELETE CASCADE,
  tenant_id UUID NOT NULL,
  code VARCHAR(32) NOT NULL, label TEXT NOT NULL, severity VARCHAR(8) NOT NULL,
  passed BOOLEAN NOT NULL, detail TEXT, evidence JSONB,
  PRIMARY KEY (case_id, code)
);

-- 2.9 human decisions that survive recompute
CREATE TABLE IF NOT EXISTS recon_match_overrides (
  case_id UUID NOT NULL REFERENCES recon_cases(id) ON DELETE CASCADE,
  tenant_id UUID NOT NULL,
  po_line_id UUID,                                -- NULL = "this invoice/evidence line is NOT in PO"
  other_key VARCHAR(80) NOT NULL,                 -- invoice_line_key or 'ev:<row_id>'
  decided_by VARCHAR(100) NOT NULL, decided_at TIMESTAMPTZ DEFAULT now(),
  PRIMARY KEY (case_id, other_key)
);
CREATE TABLE IF NOT EXISTS vendor_item_aliases (
  tenant_id UUID NOT NULL, supplier_id UUID NOT NULL,
  alias_norm TEXT NOT NULL, po_item_norm TEXT NOT NULL,
  confirmed_by VARCHAR(100), created_at TIMESTAMPTZ DEFAULT now(),
  hits INT NOT NULL DEFAULT 0,
  PRIMARY KEY (tenant_id, supplier_id, alias_norm)
);
CREATE TABLE IF NOT EXISTS recon_events (
  id BIGSERIAL PRIMARY KEY,
  tenant_id UUID NOT NULL, case_id UUID, doc_id UUID,
  kind VARCHAR(32) NOT NULL,   -- uploaded|extracted|linked|unlinked|match_override|cell_corrected|kind_changed|acknowledged|recomputed|failed
  payload JSONB, actor VARCHAR(100), at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_revents_case ON recon_events (tenant_id, case_id, at);
```

**Notify channels:**

- `recon_docs` wakes the worker. It fires on upload, re-run and kind change.
- `review_adapters` is the existing channel. The worker fires it after `save_result`.

### 2.x Vocabulary codes (adopted 2026-11-16)

Every code Recon stores comes from `docs/RECON_VOCABULARY.md`. Its machine form is `recon/vocab.py`.
- **Tables:** `vocab.sync()`, run by `_ensure_recon_tables` after the DDL above, creates `vocab_codes`, `vocab_aliases` and `vocab_meta`.
- **Generated columns:** it adds 19 STORED generated code columns to `recon_doc_pages`, `recon_doc_segments`, `recon_evidence_rows`, `recon_invoice_lines`, `recon_line_results` and `recon_header_checks`, each with a foreign key into `vocab_codes`. The columns are `doc_role`, `recon_leg`, `receipt_granularity`, `pv_format`, `evidence_layer`, `verification_status`, `scope_exclusion_source`, `line_origin`, `uom`, `uom_family`, `charge_type`, `pricing_basis`, `outcome` and `check_code`.
- **Value history:** `recon_evidence_rows.value_history` (JSONB) keeps handwritten overwrites and reviewer corrections.

Full list and rollout: `docs/bata-recon/VOCABULARY_ADOPTION.md`; how Recon uses each code: vocabulary §21.

## 3. Configuration (`recon/config.py`)

| Key | Default | Env |
|---|---|---|
| `RECON_MAX_PAGES` | 60 | `RECON_MAX_PAGES` |
| `RECON_DPI` | 200 (crops 300) | |
| `RECON_VISION_MODEL` | `gpt-4o` | `RECON_VISION_MODEL` |
| `RECON_FAST_MODEL` | `gpt-4o-mini` | `RECON_FAST_MODEL` |
| `RECON_SECOND_READ_MODEL` | `gpt-4o` (different prompt and crop) | `RECON_SECOND_READ_MODEL` |
| `LINK_AUTO_SCORE` / `LINK_AUTO_MARGIN` | 0.85 / 0.15 | |
| `MATCH_ACCEPT` / `MATCH_LLM_FLOOR` | 0.72 / 0.35 | |
| `CELL_ACCEPT_CONF` | 0.90 | |
| `RATE_ABS_TOL` / `RATE_REL_TOL` | ₹0.50 / 0.1% | per-tenant override in `tenant_settings.recon` |
| `QTY_TOL` | 0.01 | |
| `LOOKBACK_DAYS` (candidate bills) | 365 | |
| `NON_COUNTABLE_KEYWORDS` | see §11.1 | tenant-overridable |

## 4. API

Every route uses `tenant = require_tenant()` and asserts
`supplier belongs to tenant (and brand)` through the same helper `vendor_documents.py` uses.
Errors follow the existing `HTTPException(detail=str)` convention.

| Method + path | Body / query | Response | Notes |
|---|---|---|---|
| `POST /api/vendors/{sid}/recon/documents` | multipart `file` (repeatable), `brand_id?` | `[{id, file_name, recon_status, duplicate_of?}]` | Calls `store_vendor_document(..., doc_type='recon')`, sets `recon_status='PENDING'` and `content_sha256`, NOTIFYs `recon_docs`. 413 if more than 25 MB; 422 for an unsupported type |
| `GET /api/vendors/{sid}/recon/documents` | | `[ReconDocument]` with `segments[]` and their `candidates` | Polled while any doc is PENDING or RUNNING |
| `PATCH /api/recon/segments/{seg_id}` | `{kind}` | `{queued:true}` | User corrects the type. Re-extracts this segment only |
| `POST /api/recon/segments/{seg_id}/link` | `{bill_id}` or `{case_id}` or `{po_id}` | `{case_id}` | Manual link. Creates the case if needed, then recomputes |
| `POST /api/recon/segments/{seg_id}/ignore` | `{reason}` | `{}` | Status IGNORED (not relevant, other vendor) |
| `GET /api/vendors/{sid}/recon/cases` | `status?` | `[ReconCaseSummary]` | |
| `GET /api/recon/cases/{case_id}` | | `ReconCase` | header, lines, attached segments, approvals, events |
| `POST /api/recon/cases/{case_id}/detach` | `{segment_id}` | `ReconCase` | Recomputes |
| `POST /api/recon/cases/{case_id}/lines/match` | `{other_key, po_line_id\|null}` | `ReconCase` | Writes `recon_match_overrides` and an alias, then recomputes |
| `POST /api/recon/lines/{result_id}/review` | `{note}` | `{}` | Marks a flagged line reviewed |
| `POST /api/recon/evidence/{row_id}/correct` | `{audit_qty?, vendor_qty?, verdict?, remark?}` | `ReconCase` | Keeps `original_json`, sets `needs_review=false`, then recomputes every case using it |
| `POST /api/recon/cases/{case_id}/ack` | `{note}` | `{}` | Only when there are no unreviewed 🔴 lines, or with `force:true` plus a note (role `admin`/`approver`) |
| `POST /api/recon/cases/{case_id}/rerun` | `{reextract?:bool}` | `{queued:true}` | |
| `GET /api/recon/cases/{case_id}/export` | `format=xlsx` | file | |
| `GET /api/recon/segments/{seg_id}/crop` | `page, bbox` | 302 → 5-minute signed URL of a rendered PNG crop | The crop is cached in S3 under `recon-crops/…`. Never public |
| `GET /api/bills/{bill_id}/recon` | | `ReconCaseSummary \| null` | For the bill detail and approval screens |

**Response shapes** (TypeScript equivalents are in [04_LLD_FRONTEND.md §3](04_LLD_FRONTEND.md)):

```jsonc
// LineResult
{
  "id": "…", "ord": 7,
  "description": "24 Gauge 34 inch X 12 inch GI Ducting Make Asian Jindal sail",
  "invoice_text": "Supply & Installation of 24 Guage Duct",
  "evidence_text": "24 Gauge 34 inch X 12 inch GI Ducting …",
  "unit": "SM",
  "po_qty": "70", "verified_qty": "30.8", "billed_qty": "30.8", "expected_qty": "30.8",
  "po_rate": "900", "billed_rate": "900",
  "expected_amt": "27720.00", "billed_amt": "27720.00", "delta": "0.00",
  "verdict": "VERIFIED",
  "statuses": ["UNDER_USED"], "severity": "INFO",
  "match": {"method": "SCORE", "score": 0.91, "conflicts": []},
  "remark": "Verification is done through measurement…",
  "evidence_crop": {"segment_id": "…", "page": 12, "bbox": [x0,y0,x1,y1]},
  "reviewed": null
}
```

## 5. Worker

```python
class ReconWorker(BaseWorker):
    name = "recon"
    notify_channel = "recon_docs"

    async def process_batch(self) -> int:
        rows = await repo.claim_pending(limit=2)   # small: vision-heavy
        for r in rows:
            await self._run_one(r)
        return len(rows)
```

**Claim query.** This is the same shape as `CommExtractionWorker`:

```sql
UPDATE vendor_documents SET recon_status='RUNNING', recon_stage='reading'
 WHERE id IN (SELECT id FROM vendor_documents
               WHERE recon_status='PENDING' AND deleted_at IS NULL
               ORDER BY uploaded_at LIMIT $1 FOR UPDATE SKIP LOCKED)
RETURNING id, tenant_id, supplier_id, brand_id, file_path, file_name;
```

**Stale-lock recovery.** On startup, rows with `RUNNING` older than 15 minutes go back to
`PENDING`. This handles the case where another process (local vs dev) holds the worker lock; see
the review-workers-lock incident.

**`_run_one`:**

1. Run `ReconPipeline.ingest(doc_id)` with a timeout of `max(120 s, 20 s × pages)`.
2. Set the status:
   - `READY` when every segment is linked or ignored and no row needs review;
   - `NEEDS_LINK` when a segment is unlinked;
   - `NEEDS_REVIEW` when low-confidence cells exist.
3. On an exception, set `FAILED` with `recon_error`. **Partial results are kept**: segments
   already extracted stay.
4. Emit `recon_events` (extracted / failed).

## 6. ReconPipeline

```python
async def ingest(doc_id) -> list[str]:
    doc   = await repo.get_doc(doc_id)
    if doc.is_spreadsheet:
        segments = await SpreadsheetMapper().map(doc_id)        # reuse vendor_doc_rows
        pages = []
    else:
        pages = [p async for p in PageReader().read(doc.file_path, doc.mime)]   # cached → recon_doc_pages
        labels = await PageClassifier(llm).classify(pages)
        segments = Segmenter().segment(labels, pages)
    await repo.save_segments(doc_id, segments)
    po_hints = await repo.supplier_pos(doc.supplier_id)         # for PO-prompted reads
    for seg in ordered(segments):                               # POs first, then invoices, then evidence
        ex = ExtractorRegistry.for_segment(seg)
        out = await ex.extract(seg, pages, ExtractContext(..., po_hint=best_po_hint(seg, po_hints)))
        await repo.save_extraction(seg.id, out)                 # + PO tables / invoice lines / evidence rows
        if seg.kind == PURCHASE_ORDER:
            po_hints = await repo.supplier_pos(doc.supplier_id)  # newly-read PO helps later segments
    for seg in segments:
        cands = await DocumentLinker(repo).candidates(seg, doc.supplier_id)
        pick = DocumentLinker.decide(cands)
        if pick: case_id = await CaseBuilder(repo).attach_auto(seg, pick)
        else:    await repo.mark_unlinked(seg.id, cands)
    for case_id in touched_cases: await recompute(case_id)
    return [s.id for s in segments]

async def recompute(case_id) -> ReconResult:
    inp = await CaseBuilder(repo).load_input(case_id)           # applies overrides + corrected cells
    inp = replace(inp, matches=await LineMatcher(llm).match_case(inp, aliases, overrides))
    res = ReconEngine().run(inp)
    await repo.save_result(case_id, res)                        # carries over reviewed_by
    await repo.notify("review_adapters")
    return res
```

**Ordering rule:** POs are extracted first, so that scanned report sheets and invoice annexures can
be read **with the PO as a prior**.

## 7. PageReader

- Opens the file with `pymupdf` from the object-store path (`object_store.local_path(...)`), one
  page at a time.
- `_probe_text(page)` returns `page.get_text("text", sort=True)`. A page counts as having a text
  layer when it has ≥ 80 non-space characters **and** at least one digit.
- With no text layer, render the page with `page.get_pixmap(dpi=200)` and call
  `ocr_engine._call_vision`, or a thin `transcribe_page(png)` wrapper around it. **Free the pixmap
  immediately.** Store text with `source='vision'`.
- **Images** (`png`/`jpg`/`heic`→`jpg`) are a single page. **Rotation:** if the page is rotated,
  `page.set_rotation(0)`; for images, use EXIF orientation.
- Page cap: `RECON_MAX_PAGES`. Past the cap, stop, set a warning, and keep what was read (E-IN-07).
- Results are cached in `recon_doc_pages`. Re-runs skip OCR unless `reextract=true`.

## 8. PageClassifier

Classification runs in three tiers per page. It stops at the first confident answer (≥ 0.8).

**Tier 1: rules.** Regex on the page text, case-insensitive:

| Class | Rule (any) |
|---|---|
| PURCHASE_ORDER | `\bPurchase order\b` AND `PPO\d{8}` AND `Purchase requisition` |
| TERMS_CONDITIONS | `STANDARD TERMS & CONDITIONS` or `GENERAL CONDITION OF SALE` or `IMPORTANT INSTRUCTIONS` with no `\d+\.\d{2}` amounts table |
| TAX_INVOICE | `Tax Invoice` or `e-Invoice` or `IRN` AND (`GSTIN` and `Total`) |
| INVOICE_ANNEXURE | `DETAILS OF INVOICE` or `Performa Invoice` or `Proforma` AND `PO`; or a table with `Qty`/`Rate`/`Amount` and an `INV NO` header |
| PV_NARRATIVE | `PHYSICAL VERIFICATION` or `Site Visit & Physical Verification` AND (`Scope` or `Disclaimer` or `METHODOLOGY` or `CONCLUSION`) |
| PV_ANNEXURE_TYPED | `Annexure-\d+: Reporting on physical verification` or the header `Qty as per PO (A)` |
| PV_SHEET_SCANNED | `Audit Qty` AND `Vendor Qty` |
| PV_FIELD_SHEET | `Actual Measured Qty` or (`Mounted` AND `Unmounted` AND `Damaged`) |
| POD | `Waybill` or `Consignor` AND `Consignee` or `Proof of Delivery` or `LR No` |
| APPROVAL_MEMO | `Internal Memo` or `Memo Ref` AND `Approver` |

**Tier 2: Jev.** Only for pages with a text layer. Extend `_KIND_CRITERIA` in
`vendor_doc_classify.py`, or keep a private criteria set in `recon/classify.py`.

**Tier 3: LLM.** Use `RECON_FAST_MODEL` with the page PNG at 100 dpi plus the first 1,500
characters of text. The prompt (`prompts.CLASSIFY_PAGE`) returns:

```json
{"doc_class":"PV_SHEET_SCANNED","confidence":0.93,"llm_label":null,
 "vendor_hint":"INNERSPACE","vendor_gstin":"29AKRPP8699K1ZO",
 "section_title":"FURNITURE PO","store_sn":"9621",
 "is_continuation":false}
```

When the model answers `OTHER`, it must give an `llm_label` such as "Measurement sheet" or
"Delivery challan". That label is kept and shown as the type chip.

**Hints extracted on every page** (by regex, independent of class):

- `store_sn`: `SN\s*(\d{3,5})`, `Store No.*?_(\d{3,5})`, `Shop No:-\s*(\d{3,5})`, `\((\d{4})\)`
  after a store name;
- GSTINs: `\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]`;
- PO numbers: `PPO\d{8}(-\d+)?`;
- invoice-number candidates.

## 9. Segmenter

1. **Merge runs.** Consecutive pages with the same class become one segment. A page labelled
   `is_continuation` joins the previous segment.
2. **Invoices.** `TAX_INVOICE` followed by `INVOICE_ANNEXURE` merges into one `TAX_INVOICE`
   segment with `annexure_pages`.
3. **POs.** `TERMS_CONDITIONS` pages after a PO join that PO segment, but are skipped for line
   extraction.
4. **PV reports.** `PV_NARRATIVE` pages give the report-level fields (auditor, store, date,
   personnel). They are *not* a segment of their own; they are inherited by every section.
5. **PV sections.**
   - `PV_ANNEXURE_TYPED` (JPC): one segment **per (annexure, vendor)**. One annexure can hold rows
     for one vendor; the Vendor column splits further if mixed.
   - `PV_SHEET_SCANNED` (Matolia): a new segment whenever the `section_title` or `vendor_gstin`
     changes from the previous page.
   - `PV_FIELD_SHEET`: attached as **corroboration** to the section with the same (vendor, work).
     It is not separate evidence.
6. **Ownership.** A segment's `vendor_gstin` or `vendor_name` ≠ the supplier's means status
   `FOREIGN`: kept, not linked, shown under "Other vendors in this report" (E-SG-04).
7. **Memos and PODs** are one segment per page group.

## 10. Extractors

Every extractor returns its `ExtractedDoc` **and** writes `warnings[]`. Every number it outputs
must parse with `num.parse_inr`; unparseable numbers become `None` plus a warning, and are never
`0`.

### 10.1 POExtractor (text layer; vision fallback)

- **Header** by regex over page 1: `Number\s+(PPO\d{8}-\d+)`, `Date\s+(\d{2}-\d{2}-\d{4})`,
  `Terms of payment\s+(\S+)`, `Purchase requisition\s+(PPR\d+)`, the requisition name (two lines
  after the label), `GSTIN:\s*(\w{15})`, `Vendor account:\s*(V\d+)`.
- **Lines** by `page.find_tables()`. **Fallback:** a word-coordinate parser that takes the
  description column's x-range from the header words (`Description`, `Delivery`) and collects
  wrapped description lines until the next S.No.
- **De-hyphenate wraps:**
  - join `PROGRAMMI` + `NG` when the joined token is in the dictionary or the fragment is ≤ 3
    letters;
  - `Transportatio n` → `Transportation`.
- **Totals.** Read `Sales subtotal … Total`. Check Σ line amounts = subtotal; if not, warn
  `po_footing`.
- **Store SN** comes from the requisition name: `SN\s*(\d+)`.
- **Penalties.** Parse "late delivery penalty" bullets into
  `[{days_from, days_to, pct, basis:'order_value'}]`.
- **Upsert.** `purchase_orders` on `(tenant, po_number, revision)`. A higher revision sets
  `superseded_by` on the lower one (E-PO-03).

### 10.2 InvoiceExtractor

- **Header page.** Use the text layer when present. Otherwise use a vision call with
  `prompts.INVOICE_HEADER` (schema: invoice_no, date, irn, vendor gstin, buyer gstin, place of
  supply, po_ref, header lines, taxable, cgst, sgst, igst, total, payment_terms).
- **Annexure pages.** Use `find_tables()` when there is a text layer. Otherwise use vision with
  `prompts.INVOICE_ANNEXURE`, **passing the PO lines as a prior**:

  > "This table lists items from PO PPO…; for each printed row return sno, description, qty,
  > unit, rate, amount exactly as printed; do not correct or round; return rows not in the PO
  > too."

- **Charges.** Rows matching `packing|forwarding|transport|freight|installation charges|insurance`
  are flagged `is_charge`. If the amount equals `pct × goods_subtotal` (±₹1) for pct ∈ {2, 3, 5,
  10}, set `basis=PERCENT_OF_GOODS, pct`.
- **Corrections.** A second, cheap vision pass on the header crop asks "is any printed field
  overwritten/struck by hand? return field, printed, handwritten". This is how `108→109` is
  caught.
- **Bill binding.** If the segment came from a bill's own file, or matches a bill by invoice no. +
  vendor GSTIN, set `bill_id`. If that bill's `stg_bill_line_items` are header-only (≤ 2 lines
  whose total ≈ taxable, or descriptions like `GST Local Sales`, `Supply Installation of … Work`),
  the annexure lines become the case's invoice lines (`rl:` keys).

### 10.3 JpcAnnexureExtractor (typed)

- Use `page.find_tables()` (validated on the sample: 44 AHU rows extracted cleanly).
- Map columns from the header text: `Sr. No.`, `Vendor`, `Work`, `FA Code`, `Item Name`, `Unit`,
  `Qty as per PO (A)`, `Given/ Vendor Qty (B)`, `Verified Qty (C)`, `Remarks`.
- `-` or blank → `None`. `n/a` → `None`.
- `FA Code == 'Additional work'` or `po_qty is None` → `row_type='additional'`.
- **Confidence = 1.0** (typed), so there is no review.

### 10.4 ScannedSheetExtractor (Matolia; handwritten)

1. **Printed pass** (`prompts.SHEET_PRINTED`, vision): returns the vendor block, `section_title`,
   and rows `[{sno?, asset_code, item, unit, qty(=po_qty), rate, rate_after_discount}]`, plus a
   `bbox` per row. "Not in PO / Additional" rows get `row_type='additional'`.
2. **PO alignment.** Match the printed rows to the PO lines with `LineMatcher` (printed text is
   clean). This gives `po_line_id` per row.
3. **Handwriting pass A** (`prompts.SHEET_CELLS_A`). Input: a 300 dpi crop of the table region
   plus the row list (index, item, po_qty). The model returns, per row index: `vendor_qty`,
   `audit_qty`, `audit_qty_raw`, `remark`, `cell_bbox` and `legible: bool`.
4. **Handwriting pass B** (`prompts.SHEET_CELLS_B`). It uses a different crop (each row band
   separately) and a different instruction order, and returns the same fields.
5. **Agreement.** Per cell:
   - if A = B, `confidence = 0.97`;
   - otherwise `confidence = 0.5`, `needs_review = true`, and both readings go into
     `original_json`.

   Non-numeric raw values (`348+102=450`, `~`, struck-through) are parsed when possible and
   always set `needs_review` (E-EX-06).
6. **Verdict** comes from `VerdictClassifier` (§11.1) over the remark plus the blank/zero state.
7. **Consistency check** (done later, in the engine): `invoice qty == min(po, audit)` raises the
   effective confidence to 0.99. A mismatch keeps the flag and links to the crop.

### 10.5 FieldSheetExtractor

This is the same handwriting approach with fields `mounted`, `unmounted`, `damaged`, `total`,
`note`. Results are merged into the matching typed-annexure row (same section, same sno) as
corroboration. If `total ≠ verified_qty`, add warning `field_sheet_disagrees` (E-EX-09).

### 10.6 PODExtractor

Vision `prompts.POD` returns: `waybill_no`, `carrier`, `ship_date`, `invoice_nos[]`,
`total_invoice_value`, `packages`, `weight`, `consignee`, and
`receipt{stamp_text, receiver, date, legible}`. Dates are parsed as `dd/mm/yy`, and the year is
pivoted to the PO's century.

### 10.7 MemoExtractor

Use the text layer, else `RECON_FAST_MODEL`. It returns `memo_ref`, `subject`, `store_sn` (from
the subject), `vendor_name`, `approvals[{approver, status, date, remark}]` and `body`.

### 10.8 GenericExtractor

`prompts.GENERIC` returns `llm_label`, `summary`, `key_values`, and `rows[]` if the page has a
table with an item + quantity column. Rows with quantities become evidence
(`row_type='po'`, `verdict=VERIFIED`, confidence ≤ 0.8 ⇒ `needs_review`).

### 10.9 SpreadsheetMapper

1. Read `vendor_doc_tables` / `vendor_doc_rows`, which already exist; uploading through
   `store_vendor_document` triggers `store_tables_in_background`.
2. `column_roles()` maps headers to roles by fuzzy header match:

   | Role | Header synonyms |
   |---|---|
   | item | `item\|description\|particulars\|material` |
   | unit | `unit\|uom` |
   | po_qty | `qty as per po\|po qty\|qty` |
   | vendor_qty | `vendor qty\|given` |
   | audit_qty | `audit qty\|verified` |
   | rate | `rate\|unit price` |
   | amount | `amount\|total` |
   | remark | `remark` |

3. Detect the sheet type from the roles present:
   - `audit_qty` present → PV section;
   - `po_qty` + `rate` with no audit → PO-like;
   - otherwise `OTHER`.
4. If the header mapping confidence is < 0.8, the UI asks the user to confirm the column roles
   (E-IN-05).

## 11. Rules

### 11.1 VerdictClassifier

The checks run in order, case-insensitive, against `remark` + `audit_qty_raw`:

| Verdict | Condition |
|---|---|
| `ADDITIONAL` | `row_type == 'additional'` |
| `NOT_COVERED` | `not covered in audit\|out of audit\|n/?a` (and audit qty blank) |
| `NOT_COUNTABLE` | `not in scope\|as per bata instruction\|not allowed separately\|tonnage could not be checked\|best judg(e)?ment` (and audit qty blank) |
| `NOT_DONE` | `not done\|not performed\|not installed\|not found` or `audit_qty == 0` |
| `VERIFIED` | `audit_qty` is a number > 0 |
| `UNKNOWN` | audit qty blank and no remark. The engine treats this as **no evidence** for the line |

**Special case: "Not allowed separately".** Matolia's PVC conduit remark means the item is
included in another rate and **must not be billed**. The keyword list maps this remark to
`NOT_DONE` semantics (expected 0), not to `NOT_COUNTABLE`. The tenant config
`verdict_overrides: {pattern → verdict}` handles similar auditor wording.

### 11.2 BillingRule

```python
def expected_qty(po_qty, row) -> tuple[Decimal, AuditVerdict]:
    if row is None:              return po_qty, UNKNOWN       # no evidence → can't verify; flag NO_EVIDENCE
    v = VerdictClassifier.classify(row)
    if v in (NOT_COVERED, NOT_COUNTABLE): return po_qty, v
    if v == NOT_DONE:            return Decimal(0), v
    if v == VERIFIED:            return (min(po_qty, row.audit_qty) if cfg.cap_at_po else row.audit_qty), v
    return po_qty, UNKNOWN

def expected_charge(charge, goods_subtotal_expected, po_amount) -> Decimal:
    if charge.basis == PERCENT_OF_GOODS:
        return min(round2(charge.pct/100 * goods_subtotal_expected), po_amount or INF)
    return po_amount if po_amount is not None else charge.amount
```

- For a PO without evidence (Bosch), the expected value is the PO qty. Lines are flagged
  `NO_EVIDENCE` (INFO) only when **no** evidence of any kind is attached to the case. A POD counts
  as evidence for goods. A memo saying "installed" counts as weak evidence (INFO).

### 11.3 Line checks (per PO line, with matched invoice line `i` and evidence row `e`)

```
billed_qty = i.qty or 0 ; billed_rate = i.rate ; billed_amt = i.amount (recomputed: qty×rate)
exp_qty, verdict = expected_qty(po.qty, e)
expected_amt = round2(exp_qty × po.unit_price)
delta = round2(billed_qty × billed_rate − expected_amt)
statuses:
  RATE_HIGHER     if billed_rate > po.rate + tol           → BLOCKER
  RATE_LOWER      if billed_rate < po.rate − tol           → INFO
  OVER_PO         if billed_qty > po.qty + qty_tol         → BLOCKER
  OVER_VERIFIED   if verdict==VERIFIED and billed_qty > e.audit_qty + qty_tol → BLOCKER
  NOT_DONE        if verdict==NOT_DONE  (BLOCKER if billed_qty>0 else INFO)
  UNDER_BILLED    if billed_qty < exp_qty − qty_tol        → REVIEW
  UNDER_USED      if billed_qty < po.qty − qty_tol         → INFO
  OVER_EXECUTED_CAPPED if verdict==VERIFIED and e.audit_qty > po.qty and billed_qty==po.qty → INFO
  NOT_VERIFIABLE  if verdict in (NOT_COVERED, NOT_COUNTABLE) → INFO
  NO_EVIDENCE     if e is None and case has evidence segments → REVIEW ; if case has none → INFO
  DESCRIPTION_CONFLICT if match.conflicts                  → REVIEW
  UOM_CONFLICT    if canon(po.unit)≠canon(i.unit)          → REVIEW
  DAMAGED_UNMOUNTED if e.damaged or e.unmounted            → REVIEW
  AUDITOR_REMARK  if e.remark and not boilerplate(e.remark) → INFO
  ARITHMETIC      if |i.qty×i.rate − i.amount| > 1         → REVIEW
  MATCHED         if no other status
severity = max(severity of statuses)
```

- **PO lines with no invoice line:** `billed_qty = 0`. If `exp_qty > 0`, status `UNDER_BILLED`
  (this is the Anjile MCP Hooter case).
- **Invoice lines with no PO line:** `NOT_IN_PO`, BLOCKER if qty > 0, else INFO.
- **Evidence rows with `row_type=additional`:** `ADDITIONAL_ON_SITE` (REVIEW).
- **Charges:** compared against `expected_charge`. On a mismatch beyond ₹1, status
  `PCT_CHARGE_MISMATCH` (REVIEW).
- **Boilerplate remarks are skipped:** `^-$`, `verification is done through measurement…`,
  `the work is related to …`. These still show in the row detail.

### 11.4 Header checks

| code | Pass condition | Fail severity |
|---|---|---|
| `po_reference` | normalised `invoice.po_ref` (strip `-\d+`, date suffix) == `po.po_number` | BLOCKER |
| `vendor_identity` | `vendor_gstin` equal across PO, invoice, PV sections (where present) and POD consignor | BLOCKER |
| `buyer_gstin_state` | `buyer_gstin[:2]` == state of the store (from PO delivery address PIN → state) | REVIEW |
| `store_consistency` | the store SN is the same on every document that has one | REVIEW |
| `tax_regime` | vendor state ≠ place-of-supply state ⇒ IGST only; equal ⇒ CGST = SGST; `tax ≈ taxable × rate` (±₹1) | BLOCKER |
| `invoice_arithmetic` | Σ lines = subtotal; subtotal + charges = taxable; taxable + tax (+ round-off ≤ ₹1) = total | REVIEW |
| `header_vs_annexure` | header taxable == Σ annexure (±₹1) | BLOCKER |
| `within_po_value` | taxable ≤ PO total + charges, and cumulative billed on PO (other cases with same `po_id`) + this ≤ PO total | BLOCKER |
| `date_order` | po_date ≤ evidence date ≤ invoice_date | REVIEW |
| `delivery_timeliness` | POD receipt date ≤ PO delivery date; else compute the penalty from `po.penalties` | REVIEW + money_at_risk = penalty |
| `payment_terms` | invoice terms ≈ PO terms (normalised) | REVIEW |
| `pod_matches` | POD lists invoice no.; `total_invoice_value` == invoice total (±₹1); receipt present | BLOCKER on value |
| `handwritten_corrections` | no `corrections[]` on the invoice | REVIEW |
| `duplicate_invoice` | no other bill or case for the supplier with the same invoice no., or the pre-correction no. | BLOCKER |
| `approvals` | memo attached and all approvers `Approved` | INFO |

### 11.5 Summary

```
po_total        = po.subtotal
expected_total  = Σ expected_amt (lines + charges)
billed_total    = invoice taxable
money_at_risk   = Σ max(delta, 0) over lines with severity BLOCKER/REVIEW  + penalty
under_billed    = Σ max(−delta, 0) over UNDER_BILLED lines
status          = NEEDS_REVIEW if any unreviewed BLOCKER/REVIEW or evidence needs_review
                  RECONCILED   otherwise
                  ACKNOWLEDGED once acked (until the next recompute changes the result hash)
```

## 12. Matching

### 12.1 Normalisation (`normalize.py`)

```python
PREFIXES = ["supply & installation of", "supply and installation of", "supply & installation",
            "supply installation of", "providing and fixing of", "providing and fixing and",
            "providing and fixing", "providing & fixing", "supply of", "suply and installation of",
            "installation of", "fixing of"]
MAKE_TAIL = r"\bmake\b.*$"                    # "… Make Asian Jindal sail" → dropped (kept as brand tokens)
SPELLING = {"sienems":"siemens","stainner":"strainer","interartion":"integration","progamming":"programming",
            "acousting":"acoustic","accousting":"acoustic","scafolding":"scaffolding","dismenlitng":"dismantling",
            "dismentling":"dismantling","isolater":"isolator","thermostate":"thermostat","panal":"panel",
            "guage":"gauge","addresabl":"addressable","nitrial":"nitrile","nitril":"nitrile","presure":"pressure",
            "flaxible":"flexible","impuls":"impulse","promot":"promo","puch":"punch","tempreture":"temperature"}
NUMWORDS = [(r"(\d+)\s*point\s*(\d+)", r"\1.\2"), (r"(\d+)point(\d+)", r"\1.\2")]
```

- `norm()` lowercases, then:
  - de-hyphenates wraps;
  - strips prefixes;
  - removes the make tail (its brand tokens go into `brands`);
  - applies spelling and number words;
  - turns punctuation into spaces and collapses whitespace.
- `variant_tokens()` extracts:
  - sizes `\d+(\.\d+)?\s*(mm|inch|ft|fit|feet|tr|sqmm|a|w|gauge|g)\b`;
  - dimension strings `\d+x\d+(x\d+)?`;
  - `type\s+[a-z]`;
  - `\b(spn|tpn|dp|sp)\b`;
  - gauge numbers.

  It returns them canonicalised: `8 ft` = `8 fit`, `10 feet` = `10 ft`, `4.0tr` = `4 tr`.
- `UnitCanon`:

  | Canonical | Aliases |
  |---|---|
  | `nos` | no, nos, no., each, ea, pcs, set |
  | `sqm` | sm, sqm, sqmt, sq mtrs, sq m |
  | `sqft` | sf, sft, sqft |
  | `rft` | rft, running ft |
  | `m` | m, rmt, mtr, meter, metre |
  | `ls` | ls, lot, job, na |

  `RMT` vs `m`: both are **metres** (running metres), so they are the same.

### 12.2 Pair score

For a PO line `p` and a candidate `c` (an invoice line or an evidence row):

```
rate    = 1.0  if close(p.rate, c.rate | c.rate_after_discount)            (abs 0.5 / rel 0.1%)
          0.6  if close within 5% (discount/rounding)
          0.0  if c has rate and differs >5%   ; 0.5 if c has no rate
unit    = 1.0 same canon ; 0.5 unknown ; 0.0 different
name    = rapidfuzz.token_set_ratio(norm(p), norm(c)) / 100
variant = 1.0 all shared variant tokens agree ; 0.7 one side lacks tokens ; 0.2 conflict (records conflict)
position= 1.0 if |rank(p) − rank(c)| ≤ 1 in their own (sorted) orders else 0.5
total   = 0.40·rate + 0.30·name + 0.15·variant + 0.10·unit + 0.05·position
alias hit (vendor_item_aliases: norm(c) → norm(p)) ⇒ total = max(total, 0.95), method ALIAS
exact norm equality ⇒ total = 1.0, method EXACT
```

### 12.3 Assignment

1. Build the cost matrix `1 − total`, padded square with dummy rows/columns at cost `1 − LLM_FLOOR`.
2. Run `Hungarian.solve` (pure Python, O(n³), n ≤ ~80, < 50 ms).
3. Pairs with `total ≥ MATCH_ACCEPT` are accepted (`method SCORE` / `EXACT` / `ALIAS`).
4. Pairs with `LLM_FLOOR ≤ total < ACCEPT`, and every unassigned line, go to adjudication.
5. **Overrides** from `recon_match_overrides` are applied **before** scoring. Those rows and
   columns are removed from the matrix.

### 12.4 LLM adjudication (`prompts.ADJUDICATE`, `RECON_FAST_MODEL`, temperature 0)

For each line that needs adjudication, send:

- the line: description, unit, qty, rate;
- up to 5 candidate PO lines by score: id, description, unit, qty, rate, still available or not;
- the vendor name and work type.

The model returns `{"po_line_id": "…" | null, "confidence": 0-1, "reason": "…"}`.

**Guardrail.** The match is accepted only if all of these hold:

- the candidate is still unassigned;
- the rate is within 5% **or** the unit matches;
- no variant **conflict** on a size token, unless the model explicitly mentions the conflict.

When accepted, `method=LLM`. The line is still shown with the "AI" badge and `DESCRIPTION_CONFLICT`
if there are conflicts. If the guardrail rejects it, the line stays unmatched as `NOT_IN_PO` /
`NO_EVIDENCE`.

### 12.5 Three-way assembly

1. Match PO ↔ invoice lines.
2. Separately, match PO ↔ evidence rows. For JPC/Matolia sections, `po_qty` and `rate` are
   present, which makes these matches strong.
3. Join on the PO line. Rows that matched nothing on either side keep their own result rows.

## 13. Linking (`link.py`)

Candidates are the supplier's bills from the last `LOOKBACK_DAYS`, plus their cases and the
supplier's POs.

| Signal | Value | Weight |
|---|---|---|
| `ref` | doc mentions the bill's invoice no. (normalised) or the case's PO no. → 1.0 | 0.45 |
| `store` | same store SN → 1.0; same city/site name fuzzy ≥ 0.85 → 0.6 | 0.15 |
| `amount` | POD total == bill total, or annexure total == bill taxable (±₹1) → 1.0; within 2% → 0.5 | 0.15 |
| `overlap` | share of the doc's lines that match the case PO's lines with score ≥ 0.72 | 0.20 |
| `date` | po_date ≤ doc date ≤ bill date + 120 d → 1.0, else 0.3 | 0.05 |

```
score = Σ weight·signal ; ref == 1.0 ⇒ score = max(score, 0.95)
decide: top.score ≥ 0.85 and (top − second) ≥ 0.15  → auto-link
        else → NEEDS_LINK with top-3 candidates
```

**Per kind:**

| Kind | Linking rule |
|---|---|
| PURCHASE_ORDER | Links to the case(s) of bills whose `po_ref` matches. If there is no bill yet, the PO is stored and waits; a case is created when the bill arrives (`AWAITING_INVOICE`) |
| TAX_INVOICE | Binds to the bill by invoice no. + GSTIN. If there is no bill: a case with `invoice_segment_id` (orphan) |
| PV_SECTION | Uses the overlap + store signals, since it has no reference numbers |
| APPROVAL_MEMO | Linked by store SN + vendor name + date window. Memo-only links that are ambiguous are attached to **all** candidate cases for the same store and vendor; memos are informational |

## 14. Review Hub adapter (`review/adapters/recon_variance.py`)

```python
class ReconVarianceAdapter(FindingAdapter):
    detector = "recon_variance"; family = "reconciliation"; source_service = "recon"
    async def scan(self, conn, tenant_id, limit):
        # one finding per case with BLOCKER/REVIEW lines not yet reviewed
        for case in await conn.fetch(SQL_CASES_WITH_OPEN_FLAGS, tenant_id, limit):
            yield FindingDraft(
              tenant_id=tenant_id, finding_type="recon_variance", family=self.family,
              subject_type="bill", subject_id=case["bill_id"],
              severity="high" if case["blockers"] else "medium",
              title=f"{case['invoice_no']}: {case['blockers']} blocker(s), ₹{case['money_at_risk']} at risk vs PO {case['po_number']}",
              deep_link=links.vendor_recon_case(case["supplier_id"], case["id"]),
              condition_hash=condition_hash(case["id"], case["result_hash"]),
              detector=self.detector, money_at_risk=case["money_at_risk"],
              evidence=table_evidence(top_lines(case)), source_service="recon",
              key_qualifier=str(case["id"]))
```

When the case is acknowledged, or has no open flags, the condition is no longer yielded and the
existing AUTO_RESOLVE sweep closes the finding.

## 15. Export (`export.py`)

`openpyxl` writes a workbook:

- **Summary**: header checks plus totals;
- **Lines**: every `LineResult` column, with the invoice/evidence wording, statuses and the
  remark;
- **Additional items**;
- **Sources**: file names, pages.

No images are included.

## 16. Security

- Every route: `require_tenant()`, plus a supplier ownership check, plus a brand check (as in
  `vendor_documents`).
- The crop endpoint renders on the server and stores the result under
  `object_store.key("recon-crops", tenant, seg_id, f"{page}-{hash(bbox)}.png")`. It returns a
  **5-minute signed URL**. It never accepts arbitrary paths, and the bbox is clamped to the page.
- LLM calls send only page images and text. No credentials, no other tenants' data.
- `recon_events` records the actor for every human action.
- File types allowed: `pdf, png, jpg, jpeg, heic, webp, tif, tiff, xlsx, xlsm, csv`. Maximum
  25 MB. The page limit is enforced before rendering.

## 17. Observability and cost

- Log line per stage: `[recon] doc=… stage=extract seg=… kind=PV_SECTION pages=3 ms=… model=… usd=…`.
- `recon_progress` JSON drives the UI's progress bar.
- `ReconLLM.cost_usd` is accumulated per doc and stored in `recon_events(kind='extracted').payload`.
- Expected cost:
  - text-layer PO + invoice: ≈ $0;
  - a 10-page scanned Matolia report: ≈ 10 × (classify mini + printed 4o + 2 × cells 4o) ≈ $0.30–0.60.
