# 02 · Class Diagrams

All backend classes live under `backend_ocr/app/recon/` unless noted otherwise. Value types are
`@dataclass(frozen=True, slots=True)`. Money and quantities use `Decimal`, never `float`.

## 1. Enums

```mermaid
classDiagram
    class DocClass {
        <<enum>>
        PURCHASE_ORDER
        TAX_INVOICE
        INVOICE_ANNEXURE
        PV_NARRATIVE
        PV_ANNEXURE_TYPED
        PV_SHEET_SCANNED
        PV_FIELD_SHEET
        POD
        APPROVAL_MEMO
        TERMS_CONDITIONS
        DELIVERY_CHALLAN
        GRN
        MEASUREMENT_SHEET
        OTHER
    }
    class SegmentKind {
        <<enum>>
        PURCHASE_ORDER
        TAX_INVOICE
        PV_SECTION
        POD
        APPROVAL_MEMO
        OTHER
        IGNORED
    }
    class AuditVerdict {
        <<enum>>
        VERIFIED
        NOT_DONE
        NOT_COUNTABLE
        NOT_COVERED
        ADDITIONAL
        UNKNOWN
    }
    class Severity {
        <<enum>>
        BLOCKER
        REVIEW
        INFO
        OK
    }
    class LineStatus {
        <<enum>>
        RATE_HIGHER
        RATE_LOWER
        OVER_PO
        OVER_VERIFIED
        UNDER_BILLED
        UNDER_USED
        OVER_EXECUTED_CAPPED
        NOT_DONE
        NOT_VERIFIABLE
        NOT_IN_PO
        ADDITIONAL_ON_SITE
        DESCRIPTION_CONFLICT
        UOM_CONFLICT
        DAMAGED_UNMOUNTED
        AUDITOR_REMARK
        PCT_CHARGE_MISMATCH
        ARITHMETIC
        NO_EVIDENCE
        MATCHED
    }
    class MatchMethod {
        <<enum>>
        EXACT
        ALIAS
        SCORE
        LLM
        HUMAN
        NONE
    }
    class ReconStatus {
        <<enum>>
        PENDING
        RUNNING
        NEEDS_LINK
        NEEDS_REVIEW
        READY
        FAILED
        SKIPPED
    }
    class CaseStatus {
        <<enum>>
        AWAITING_INVOICE
        AWAITING_PO
        IN_PROGRESS
        NEEDS_REVIEW
        RECONCILED
        ACKNOWLEDGED
    }
    class ChargeBasis {
        <<enum>>
        FIXED
        PERCENT_OF_GOODS
    }
    class TaxRegime {
        <<enum>>
        IGST
        CGST_SGST
        NONE
    }
```

### Vocabulary codes for these enums (2026-11-16)

These enums stay the code's internal names. Their vocabulary codes (`docs/RECON_VOCABULARY.md`) come from **one** mapping in `recon/vocab.py`:

| Enum | Mapping in `recon/vocab.py` | Vocabulary kind |
|---|---|---|
| `DocClass` | `DOC_CLASS_ROLE` | `doc_role` |
| `SegmentKind` | `SEGMENT_KIND_ROLE`, `SEGMENT_KIND_LEG`, `SEGMENT_KIND_GRANULARITY` | `doc_role`, `recon_leg`, `receipt_granularity` |
| `AuditVerdict` | `VERDICT_STATUS` | `verification_status` |
| `LineStatus` | the codes themselves | `recon_line_status` |
| `Severity` | `SEVERITY_OUTCOME` | `recon_outcome` |
| `MatchMethod` | `MATCH_METHOD` | `match_method` |

`TERMS_CONDITIONS`, `OTHER` and `IGNORED` are page or part types with no document role.

## 2. Reading layer: pages, classification, segmentation

```mermaid
classDiagram
    class PageInfo {
        +int index
        +str text
        +bool has_text_layer
        +str source  "text|vision|sheet"
        +float ocr_confidence
        +bytes|None png  "lazy; not kept after use"
        +tuple[float,float] size
    }
    class PageReader {
        -int max_pages
        -int dpi
        +read(file_ref: str, mime: str) AsyncIterator~PageInfo~
        +render(file_ref, index, dpi) bytes
        +crop(file_ref, index, bbox, dpi) bytes
        -_probe_text(page) str
        -_ocr_page(png) str
    }
    class PageLabel {
        +int page_index
        +DocClass doc_class
        +float confidence
        +str|None llm_label
        +str|None vendor_hint
        +str|None section_title
        +str|None store_sn
        +str method  "rule|jev|llm"
    }
    class PageClassifier {
        +classify(pages: list~PageInfo~) list~PageLabel~
        -_rules(page) PageLabel|None
        -_jev(page) PageLabel|None
        -_llm(page) PageLabel
    }
    class Segment {
        +str id
        +SegmentKind kind
        +list~int~ pages
        +str|None vendor_name
        +str|None vendor_gstin
        +str|None section_title
        +str|None store_sn
        +float confidence
    }
    class Segmenter {
        +segment(labels: list~PageLabel~, pages) list~Segment~
        -_merge_runs(labels) list~Segment~
        -_split_pv(segment, pages) list~Segment~
        -_attach_annexure(segments) list~Segment~
    }
    class SpreadsheetMapper {
        +map(doc_id) list~Segment~
        +column_roles(columns: list~str~) dict[str,str]
    }
    PageReader --> PageInfo : yields
    PageClassifier --> PageLabel : produces
    PageClassifier ..> PageInfo
    Segmenter ..> PageLabel
    Segmenter --> Segment : produces
    SpreadsheetMapper --> Segment : produces
```

## 3. Extraction layer: typed documents

```mermaid
classDiagram
    class Sourced~T~ {
        +T value
        +float confidence
        +int|None page
        +tuple|None bbox
        +str|None raw
    }
    class ExtractedDoc {
        <<abstract>>
        +str segment_id
        +SegmentKind kind
        +str extractor_version
        +list~str~ warnings
        +to_json() dict
    }
    class ExtractedPO {
        +str po_number
        +int revision
        +date po_date
        +Party vendor
        +str buyer_gstin
        +str|None store_sn
        +str|None store_name
        +str|None payment_terms
        +str|None requisition_no
        +str|None requisition_name
        +list~POLine~ lines
        +Decimal subtotal
        +Decimal tax
        +Decimal total
        +list~PenaltyTerm~ penalties
    }
    class POLine {
        +int sno
        +str description
        +str norm
        +str unit
        +Decimal qty
        +Decimal unit_price
        +Decimal amount
        +date|None delivery_date
    }
    class ExtractedInvoice {
        +str invoice_no
        +date invoice_date
        +str|None irn
        +Party vendor
        +str buyer_gstin
        +str|None place_of_supply
        +str|None po_ref
        +list~InvoiceLine~ header_lines
        +list~InvoiceLine~ annexure_lines
        +list~Charge~ charges
        +TaxBlock tax
        +Decimal taxable
        +Decimal total
        +list~Correction~ corrections
        +str|None payment_terms
    }
    class InvoiceLine {
        +int|None sno
        +str description
        +str norm
        +str|None hsn
        +str|None unit
        +Sourced~Decimal~ qty
        +Sourced~Decimal~ rate
        +Sourced~Decimal~ amount
        +Decimal|None tax_rate
        +str|None bill_line_id
    }
    class Charge {
        +str label
        +ChargeBasis basis
        +Decimal|None pct
        +Decimal amount
    }
    class TaxBlock {
        +TaxRegime regime
        +Decimal cgst
        +Decimal sgst
        +Decimal igst
        +Decimal rate
    }
    class Correction {
        +str field
        +str printed
        +str handwritten
        +int page
    }
    class PVSection {
        +str auditor
        +str store_sn
        +date verification_date
        +Party vendor
        +str section_title
        +list~EvidenceRow~ rows
        +Signatures signatures
        +str layout  "jpc_typed|matolia_scan|generic"
    }
    class EvidenceRow {
        +int|None sno
        +str|None asset_code
        +str item
        +str norm
        +str|None unit
        +Decimal|None po_qty
        +Sourced~Decimal~|None vendor_qty
        +Sourced~Decimal~|None audit_qty
        +str|None remark
        +AuditVerdict verdict
        +int|None mounted
        +int|None unmounted
        +int|None damaged
        +Decimal|None rate
        +Decimal|None rate_after_discount
        +str row_type  "po|additional"
        +bool needs_review
    }
    class ExtractedPOD {
        +str waybill_no
        +str carrier
        +list~str~ invoice_nos
        +Decimal total_invoice_value
        +int|None packages
        +Decimal|None weight
        +date|None ship_date
        +Receipt receipt
    }
    class ExtractedMemo {
        +str memo_ref
        +str subject
        +str|None store_sn
        +str|None vendor_name
        +list~Approval~ approvals
        +str body
    }
    class ExtractedOther {
        +str llm_label
        +str summary
        +dict key_values
        +list~EvidenceRow~ rows
    }
    class Party {
        +str name
        +str|None gstin
        +str|None account
    }
    ExtractedDoc <|-- ExtractedPO
    ExtractedDoc <|-- ExtractedInvoice
    ExtractedDoc <|-- PVSection
    ExtractedDoc <|-- ExtractedPOD
    ExtractedDoc <|-- ExtractedMemo
    ExtractedDoc <|-- ExtractedOther
    ExtractedPO "1" *-- "many" POLine
    ExtractedInvoice "1" *-- "many" InvoiceLine
    ExtractedInvoice *-- Charge
    ExtractedInvoice *-- TaxBlock
    ExtractedInvoice *-- Correction
    PVSection "1" *-- "many" EvidenceRow
    ExtractedPO --> Party
    ExtractedInvoice --> Party
    PVSection --> Party
    InvoiceLine --> Sourced
    EvidenceRow --> Sourced
```

```mermaid
classDiagram
    class Extractor {
        <<abstract>>
        +SegmentKind kind
        +str version
        +extract(seg: Segment, pages: list~PageInfo~, ctx: ExtractContext) ExtractedDoc
    }
    class ExtractContext {
        +str tenant_id
        +str supplier_id
        +ExtractedPO|None po_hint
        +ReconLLM llm
        +PageReader reader
    }
    class POExtractor
    class InvoiceExtractor {
        -_header(pages) ExtractedInvoice
        -_annexure(pages) list~InvoiceLine~
        -_detect_corrections(png) list~Correction~
    }
    class JpcAnnexureExtractor {
        -_tables(page) list[list[str]]
        -_columns(header_row) dict
    }
    class ScannedSheetExtractor {
        -_printed_rows(png) list~EvidenceRow~
        -_handwritten_cells(png, rows, po_hint) list~EvidenceRow~
        -_double_read(png, rows) list~EvidenceRow~
    }
    class FieldSheetExtractor
    class PODExtractor
    class MemoExtractor
    class GenericExtractor
    class ExtractorRegistry {
        +for_segment(seg: Segment) Extractor
    }
    Extractor <|-- POExtractor
    Extractor <|-- InvoiceExtractor
    Extractor <|-- JpcAnnexureExtractor
    Extractor <|-- ScannedSheetExtractor
    Extractor <|-- FieldSheetExtractor
    Extractor <|-- PODExtractor
    Extractor <|-- MemoExtractor
    Extractor <|-- GenericExtractor
    ExtractorRegistry o-- Extractor
    Extractor ..> ExtractContext
    ExtractContext --> ReconLLM
    class ReconLLM {
        +classify_page(text, png) dict
        +extract_json(prompt, schema, text, pngs, model) dict
        +read_cells(png, rows, fields) list~dict~
        +adjudicate(line, candidates) dict
        +cost_usd float
    }
```

## 4. Normalisation, linking, matching

```mermaid
classDiagram
    class TextNormalizer {
        +norm(desc: str) str
        +tokens(desc: str) set~str~
        +variant_tokens(desc: str) set~str~
        -PREFIXES: list~str~
        -SPELLING: dict[str,str]
        -MAKE_TAIL: Pattern
    }
    class UnitCanon {
        +canon(unit: str) str
        +same(a, b) bool
        -ALIASES: dict[str,str]
    }
    class Num {
        +parse_inr(s: str) Decimal|None
        +close(a, b, abs_tol, rel_tol) bool
    }
    class LinkCandidate {
        +str target_type  "bill|po|case"
        +str target_id
        +float score
        +dict signals
    }
    class DocumentLinker {
        +AUTO_SCORE = 0.85
        +AUTO_MARGIN = 0.15
        +candidates(doc: ExtractedDoc, supplier_id) list~LinkCandidate~
        +decide(cands) LinkCandidate|None
        -_ref_signal(doc, bill) float
        -_store_signal(doc, bill) float
        -_amount_signal(doc, bill) float
        -_overlap_signal(doc, po) float
        -_date_signal(doc, bill) float
    }
    class MatchPair {
        +str po_line_id
        +str|None invoice_line_key
        +str|None evidence_row_id
        +float score
        +MatchMethod method
        +list~str~ conflicts
        +str|None reason
    }
    class PairScore {
        +float rate
        +float unit
        +float name
        +float variant
        +float position
        +float total
        +list~str~ conflicts
    }
    class LineMatcher {
        +ACCEPT = 0.72
        +LLM_FLOOR = 0.35
        +match(po_lines, other_lines, aliases) list~MatchPair~
        +score(a, b) PairScore
        -_alias_hits(...)
        -_assign(matrix) list~tuple~
        -_adjudicate(unmatched, candidates) list~MatchPair~
    }
    class Hungarian {
        +solve(cost: list[list[float]]) list[tuple[int,int]]
    }
    class AliasStore {
        +load(tenant, supplier) dict[str,str]
        +save(tenant, supplier, alias_norm, po_norm, user)
    }
    LineMatcher --> PairScore
    LineMatcher --> MatchPair
    LineMatcher --> Hungarian
    LineMatcher --> ReconLLM
    LineMatcher ..> AliasStore
    LineMatcher ..> TextNormalizer
    LineMatcher ..> UnitCanon
    DocumentLinker --> LinkCandidate
    DocumentLinker ..> Num
```

## 5. Rules and engine (pure, no I/O)

```mermaid
classDiagram
    class ReconInput {
        +ExtractedPO|None po
        +list~InvoiceLine~ invoice_lines
        +ExtractedInvoice invoice
        +list~PVSection~ evidence
        +list~ExtractedPOD~ pods
        +list~ExtractedMemo~ memos
        +list~MatchPair~ matches
        +Decimal prior_billed_on_po
        +RuleConfig config
    }
    class RuleConfig {
        +Decimal rate_abs_tol = 0.50
        +Decimal rate_rel_tol = 0.001
        +Decimal qty_tol = 0.01
        +bool cap_at_po = true
        +set~str~ non_countable_keywords
        +dict[str,ChargeBasis] charge_rules
        +bool flag_under_use = true
    }
    class VerdictClassifier {
        +classify(row: EvidenceRow) AuditVerdict
        -NOT_DONE_RX
        -NOT_COVERED_RX
        -NOT_IN_SCOPE_RX
    }
    class BillingRule {
        +expected_qty(po_qty, row: EvidenceRow|None) tuple[Decimal,AuditVerdict]
        +expected_charge(charge, goods_subtotal, po_amount) Decimal
    }
    class HeaderCheck {
        +str code
        +str label
        +Severity severity
        +bool passed
        +str detail
        +dict evidence
    }
    class HeaderChecks {
        +run(inp: ReconInput) list~HeaderCheck~
        -po_reference()
        -vendor_identity()
        -buyer_store()
        -tax_regime()
        -arithmetic()
        -header_vs_annexure()
        -over_po_value()
        -dates()
        -payment_terms()
        -pod()
        -corrections()
        -approvals()
    }
    class LineResult {
        +str|None po_line_id
        +str|None invoice_line_key
        +str|None evidence_row_id
        +str description
        +str|None unit
        +Decimal|None po_qty
        +Decimal|None verified_qty
        +AuditVerdict verdict
        +Decimal billed_qty
        +Decimal|None po_rate
        +Decimal|None billed_rate
        +Decimal expected_qty
        +Decimal expected_amt
        +Decimal billed_amt
        +Decimal delta
        +list~LineStatus~ statuses
        +Severity severity
        +str|None remark
        +MatchMethod method
        +float match_score
    }
    class LineChecks {
        +run(inp: ReconInput) list~LineResult~
        -_po_line(po_line, inv, ev) LineResult
        -_unmatched_invoice(inv) LineResult
        -_additional(ev) LineResult
        -_charges(inp) list~LineResult~
    }
    class ReconSummary {
        +Decimal po_total
        +Decimal expected_total
        +Decimal billed_total
        +Decimal money_at_risk
        +Decimal under_billed
        +dict[Severity,int] counts
        +CaseStatus status
    }
    class ReconResult {
        +list~HeaderCheck~ header
        +list~LineResult~ lines
        +ReconSummary summary
        +str engine_version
    }
    class ReconEngine {
        +run(inp: ReconInput) ReconResult
    }
    ReconEngine --> HeaderChecks
    ReconEngine --> LineChecks
    ReconEngine --> ReconResult
    LineChecks --> BillingRule
    BillingRule --> VerdictClassifier
    ReconInput --> RuleConfig
    ReconResult *-- HeaderCheck
    ReconResult *-- LineResult
    ReconResult *-- ReconSummary
```

## 6. Orchestration, persistence, API, Review Hub

```mermaid
classDiagram
    class BaseWorker {
        <<existing>>
        +name
        +notify_channel
        +process_batch() int
    }
    class ReconWorker {
        +name = "recon"
        +notify_channel = "recon_docs"
        +process_batch() int
        -_run_one(doc_row)
        -_read(doc) list~PageInfo~
        -_extract_all(segments) list~ExtractedDoc~
        -_link(docs) list~CaseAttach~
        -_recompute(case_id)
    }
    class ReconPipeline {
        +ingest(doc_id) list~str~  "segment ids"
        +recompute(case_id) ReconResult
    }
    class CaseBuilder {
        +load_input(case_id) ReconInput
        +ensure_case(tenant, supplier, bill_id, po_id) str
    }
    class ReconRepository {
        +claim_pending(limit) list~dict~
        +set_doc_status(doc_id, status, error)
        +save_segments(doc_id, segments)
        +save_extraction(segment_id, doc: ExtractedDoc)
        +upsert_po(tenant, supplier, ExtractedPO) str
        +save_evidence_rows(segment_id, rows)
        +save_invoice_lines(segment_id, lines)
        +attach(case_id, segment_id, role, by)
        +detach(case_id, segment_id, by)
        +save_result(case_id, ReconResult)
        +bill_lines(bill_id) list~InvoiceLine~
        +vendor_bills(supplier_id, since) list~dict~
        +log_event(case_id, kind, payload, by)
    }
    class ReconRouter {
        <<FastAPI routes>>
        +POST /api/vendors/:sid/recon/documents
        +GET /api/vendors/:sid/recon/documents
        +GET /api/vendors/:sid/recon/cases
        +GET /api/recon/cases/:case_id
        +POST /api/recon/cases/:case_id/attach
        +POST /api/recon/cases/:case_id/detach
        +POST /api/recon/cases/:case_id/lines/:rid/match
        +POST /api/recon/evidence/:row_id/correct
        +POST /api/recon/cases/:case_id/ack
        +POST /api/recon/cases/:case_id/rerun
        +GET /api/recon/cases/:case_id/export
        +GET /api/recon/segments/:seg_id/crop
        +GET /api/bills/:bill_id/recon
    }
    class FindingAdapter {
        <<existing>>
        +detector
        +family
        +scan(conn, tenant, limit) AsyncIterator[FindingDraft]
    }
    class ReconVarianceAdapter {
        +detector = "recon_variance"
        +family = "reconciliation"
        +source_service = "recon"
        +scan(conn, tenant, limit)
    }
    BaseWorker <|-- ReconWorker
    FindingAdapter <|-- ReconVarianceAdapter
    ReconWorker --> ReconPipeline
    ReconPipeline --> PageReader
    ReconPipeline --> PageClassifier
    ReconPipeline --> Segmenter
    ReconPipeline --> ExtractorRegistry
    ReconPipeline --> DocumentLinker
    ReconPipeline --> CaseBuilder
    ReconPipeline --> LineMatcher
    ReconPipeline --> ReconEngine
    ReconPipeline --> ReconRepository
    CaseBuilder --> ReconRepository
    ReconRouter --> ReconRepository
    ReconRouter --> ReconPipeline
    ReconVarianceAdapter ..> ReconRepository
```

## 7. Frontend types (TypeScript)

```mermaid
classDiagram
    class ReconDocument {
        +string id
        +string file_name
        +ReconStatus recon_status
        +string|null error
        +ReconSegment[] segments
        +string uploaded_at
    }
    class ReconSegment {
        +string id
        +SegmentKind kind
        +number[] pages
        +string|null section_title
        +string|null vendor_name
        +string|null store_sn
        +number confidence
        +string|null case_id
        +LinkCandidate[] candidates
    }
    class ReconCaseSummary {
        +string id
        +string|null bill_id
        +string|null invoice_no
        +string|null po_number
        +string|null store_sn
        +CaseStatus status
        +DocPresence docs
        +number money_at_risk
        +SeverityCounts counts
    }
    class ReconCase {
        +ReconCaseSummary summary
        +HeaderCheck[] header
        +LineResult[] lines
        +ReconSegment[] attached
        +Approval[] approvals
        +ReconEvent[] events
    }
    ReconDocument *-- ReconSegment
    ReconCase *-- ReconCaseSummary
    ReconCase *-- HeaderCheck
    ReconCase *-- LineResult
```

The component tree is in [04_LLD_FRONTEND.md](04_LLD_FRONTEND.md).

## 8. Sequence: one file end to end

```mermaid
sequenceDiagram
    actor U as User
    participant FE as Recon UI
    participant API as recon router
    participant DB as Postgres
    participant W as ReconWorker
    participant LLM as OpenAI/Jev
    U->>FE: drop "PV Report.pdf"
    FE->>API: POST /vendors/:sid/recon/documents (multipart)
    API->>DB: vendor_documents(doc_type='recon', recon_status=PENDING)
    API->>DB: NOTIFY recon_docs
    API-->>FE: {id, recon_status: PENDING}
    W->>DB: claim (FOR UPDATE SKIP LOCKED) → RUNNING
    loop each page
        W->>W: text layer? else render + OCR
        W->>LLM: classify page (if rules unsure)
    end
    W->>W: segment → sections per vendor/PO
    W->>DB: find PO + bills for supplier
    loop each segment
        W->>LLM: extract (PO-prompted for scanned sheets, double read)
        W->>DB: save extraction + evidence rows
        W->>W: link (score candidates)
    end
    W->>W: match lines → engine
    W->>DB: save results, recon_status READY / NEEDS_LINK / NEEDS_REVIEW
    W->>DB: NOTIFY review_adapters
    FE->>API: poll GET /vendors/:sid/recon/documents (every 3s while RUNNING)
    API-->>FE: segments + linked case
    U->>FE: open case
    FE->>API: GET /recon/cases/{id}
```
