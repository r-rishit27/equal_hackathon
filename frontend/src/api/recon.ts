import axios from 'axios'

/**
 * Recon: invoices matched to their PO and the on-ground (site audit) report.
 * docs/bata-recon/04_LLD_FRONTEND.md §3. Money and quantities stay strings end
 * to end — they are Decimals on the server and only formatted for display.
 */

export type ReconStatus = 'PENDING' | 'RUNNING' | 'NEEDS_LINK' | 'NEEDS_REVIEW' | 'READY' | 'FAILED'
export type SegmentKind = 'PURCHASE_ORDER' | 'TAX_INVOICE' | 'PV_SECTION' | 'POD' | 'PAYMENT_ADVICE' | 'APPROVAL_MEMO' | 'OTHER' | 'IGNORED'
export type SegmentStatus = 'PENDING' | 'EXTRACTED' | 'NEEDS_REVIEW' | 'LINKED' | 'UNLINKED' | 'WAITING' | 'FOREIGN' | 'IGNORED' | 'FAILED'
export type Severity = 'BLOCKER' | 'REVIEW' | 'INFO' | 'OK'
export type CaseStatus = 'AWAITING_INVOICE' | 'AWAITING_PO' | 'IN_PROGRESS' | 'NEEDS_REVIEW'
  | 'AWAITING_CREDIT_NOTE' | 'AWAITING_RECEIPT' | 'RECONCILED' | 'ACKNOWLEDGED'
export type LineStatus =
  | 'RATE_HIGHER' | 'RATE_LOWER' | 'OVER_PO' | 'OVER_VERIFIED' | 'UNDER_BILLED' | 'UNDER_USED' | 'OVER_EXECUTED_CAPPED'
  | 'NOT_DONE' | 'NOT_VERIFIABLE' | 'NOT_IN_PO' | 'ADDITIONAL_ON_SITE' | 'DESCRIPTION_CONFLICT' | 'UOM_CONFLICT'
  | 'DAMAGED_UNMOUNTED' | 'AUDITOR_REMARK' | 'PCT_CHARGE_MISMATCH' | 'ARITHMETIC' | 'NO_EVIDENCE' | 'UNCHECKED_READING'
  | 'REPORT_ONLY' | 'MATCHED'
export type MatchMethod = 'EXACT' | 'ALIAS' | 'SCORE' | 'LLM' | 'HUMAN' | 'NONE'

export interface LinkCandidate {
  target_type: 'case' | 'bill' | 'po'; target_id: string; label: string; score: number
  signals: Record<string, number>; case_id: string | null; bill_id: string | null; po_id: string | null
}
export interface ReconSegment {
  id: string; kind: SegmentKind; llm_label: string | null; pages: number[]; status: SegmentStatus
  section_title: string | null; vendor_name: string | null; store_sn: string | null; confidence: number | null
  case_id: string | null; candidates: LinkCandidate[]; needs_review_cells: number; warnings: string[]
  summary: string | null; role?: string; file_name?: string; doc_id?: string; link_method?: string | null
}
export interface ReconDocument {
  id: string; file_name: string; recon_status: ReconStatus; recon_stage: string | null
  progress: { page?: number; pages?: number; segment?: number; segments?: number } | null
  error: string | null; uploaded_at: string; uploaded_by: string | null; segments: ReconSegment[]
}
export interface HeaderCheck {
  code: string; label: string; severity: Severity; passed: boolean; detail: string | null
  /** What the engine recorded. `confirmable` is present when the check is one a
   *  person can answer, and holds exactly what they are being shown. */
  evidence?: Record<string, unknown> | null
}

/** Answer a check the engine could not settle. `shown` ties the answer to what
 *  was on screen, so a re-read of the document asks again. */
export async function confirmCheck(caseId: string, code: string, shown: string, note = '') {
  await axios.post(`/api/recon/cases/${caseId}/confirm`, { code, shown, note })
}
export interface LineResult {
  id: string; ord: number; kind: 'po' | 'not_in_po' | 'additional' | 'report_only'; description: string
  po_key: string | null; invoice_key: string | null; evidence_key: string | null
  invoice_text: string | null; evidence_text: string | null; unit: string | null
  /** What the site report says the work is worth: its own rate, after the
   *  discount where it prints one, and that rate times the certified quantity. */
  verified_rate?: string | null
  verified_amt?: string | null
  po_qty: string | null; verified_qty: string | null; received_qty: string | null; vendor_qty: string | null; billed_qty: string; expected_qty: string
  /** What the receipt is worth: a GRN's booked value, excluding tax, or a
   *  carrier's declared consignment value, which includes it. */
  received_amt?: string | null
  /** How the receipt figure was arrived at: read from a GRN, or derived because
   *  a single-line bill left the consignment nowhere else to be. */
  receipt_basis?: 'grn' | 'single_line_consignment' | null
  po_rate: string | null; billed_rate: string | null; expected_amt: string; billed_amt: string; delta: string
  verdict: string | null; statuses: LineStatus[]; severity: Severity; match_method: MatchMethod; match_score: number
  conflicts: string[]; remark: string | null; is_charge: boolean; needs_review_cell: boolean
  reviewed: { by: string; at: string | null; note: string | null } | null
  /** Where the verified number was read from, for the reviewer's crop. */
  evidence_crop: { segment_id: string; page: number; bbox: number[] } | null
}
export interface ReconCaseSummary {
  /** The readable case number, "RC-0012". */
  id: string; ref: string | null; supplier_id: string | null; vendor_name: string | null; bill_id: string | null; invoice_no: string | null; po_number: string | null; store_sn: string | null
  status: CaseStatus; docs: { po: boolean; invoice: boolean; evidence: number; pod: boolean; memo: boolean }
  po_total: string | null; billed_total: string | null; expected_total: string | null
  money_at_risk: string; under_billed: string; counts: Record<'BLOCKER' | 'REVIEW' | 'INFO', number>
  /** Share of the billed value resting on a pairing we are sure of, weighted
   *  by money. Null when nothing has been paired yet — no PO has arrived — which
   *  is a missing document, not an untrustworthy match. */
  confidence?: string | null
  confidence_weakest?: { description: string; amount: string; confidence: number; method: string }[]
  /** Section headings carrying the subtotal of other lines on the same invoice.
   *  Excluded from the billing — counting them bills the work twice — and shown,
   *  because a line dropped in silence is how an understated bill gets paid. */
  rollup_lines?: { sno: number | null; description: string; amount: string }[]
  /** How much of the billed value each supporting document accounts for.
   *  Null where that document has not arrived — an absent report is not a
   *  badly performing one. */
  leg_cover?: Partial<Record<'po' | 'evidence' | 'pod' | 'payment', number | null>>
  /** The bill behind this case was deleted. The reconciliation and its
   *  documents are untouched; it is simply not something to pay. */
  bill_deleted?: boolean
  computed_at: string | null; acknowledged_by: string | null; acknowledged_at: string | null
}
export interface ReconCase {
  summary: ReconCaseSummary; header: HeaderCheck[]; lines: LineResult[]; attached: ReconSegment[]
  approvals: { memo_ref: string | null; approver: string; status: string; date: string | null; remark: string | null }[]
  events: { kind: string; actor: string | null; at: string; payload: unknown }[]
  ack_note: string | null
}

export interface UploadResult { id: string | null; file_name: string; recon_status?: ReconStatus; error?: string | null; duplicate_of?: { id: string; file_name: string; uploaded_at: string } | null }

export async function uploadReconDocuments(supplierId: string, files: File[], opts: { brandId?: string | null; force?: boolean } = {}): Promise<UploadResult[]> {
  const fd = new FormData()
  files.forEach(f => fd.append('file', f))
  if (opts.force) fd.append('force', 'true')
  const { data } = await axios.post(`/api/vendors/${supplierId}/recon/documents`, fd, { params: opts.brandId ? { brand_id: opts.brandId } : {} })
  return data
}
/** The invoice against one supporting document. Four of these per case, always
 *  in the same order — a panel that cannot be filled says why rather than
 *  disappearing, because a missing screen reads as a forgotten one. */
export type CheckState = 'MATCH' | 'DIFFERS' | 'MISSING' | 'NA'
export type FourWayCheck = { field: 'qty' | 'rate' | 'amount' | 'description'; state: CheckState; invoice: string | null; other: string | null }
export type FourWayLine = {
  description: string; key: string | null; state: CheckState; checks: FourWayCheck[]
  /** How this line was paired with its counterpart; every figure beside it is
   *  only as good as the pairing. */
  match_method?: MatchMethod | null
  match_score?: number
}
export type FourWayPanel = {
  pair: 'INVOICE_VS_PO' | 'INVOICE_VS_AUDIT' | 'INVOICE_VS_GRN' | 'INVOICE_VS_PAYMENT'
  title: string; ask: string; available: boolean; absent_reason: string
  /** What this comparison does and does not prove. */
  note?: string
  /** An assumption a person has to agree with before the panel can be trusted. */
  confirm?: string
  counts: Record<CheckState, number>
  lines: FourWayLine[]
}

/** One step of the chain of documents behind a line. */
export type EvidenceHop = { node: string; path: string[]; via: string[]; hops: number }

export async function fetchEvidencePath(caseId: string, key: string): Promise<{ start: string; reachable: EvidenceHop[] }> {
  const { data } = await axios.get(`/api/recon/cases/${caseId}/path`, { params: { key } })
  return data
}

/** How a case is held together: its documents and the links between them. */
export type CaseGraph = {
  built_at: string | null
  documents: { role: string; label: string; present: boolean; detail: string | null }[]
  links: { kind: string; n: number; avg_score: number | null; min_score: number | null
           confirmed: number; certain: number }[]
  cover: Partial<Record<string, number | null>>
}

export async function fetchCaseGraph(caseId: string): Promise<CaseGraph> {
  const { data } = await axios.get(`/api/recon/cases/${caseId}/graph`)
  return data
}

export async function fetchFourWay(caseId: string): Promise<FourWayPanel[]> {
  const { data } = await axios.get(`/api/recon/cases/${caseId}/fourway`)
  return data
}

/** What one GRN extract load did. Never just a count: a half-loaded receipt
 *  understates what was received, and an understated receipt is what makes an
 *  overpayment look acceptable. */
export type GrnLoadReport = {
  file_name: string
  ok: boolean
  sheet: string
  mapping: 'declared' | 'inferred' | ''
  saved: number
  rows_read: number
  mapped_columns: Record<string, string>
  unmapped_columns: string[]
  declared_but_absent: Record<string, string>
  skipped_rows: string[]
  rejected_sheets: string[]
  error: string | null
}

export type GrnMapping = { declared: Record<string, string>; fields: Record<string, string[]>; required: string[] }

export async function uploadGrnExtract(files: File[]): Promise<GrnLoadReport[]> {
  const fd = new FormData()
  files.forEach(f => fd.append('file', f))
  const { data } = await axios.post('/api/recon/grn/upload', fd)
  return data
}

export async function fetchGrnMapping(): Promise<GrnMapping> {
  const { data } = await axios.get('/api/recon/grn/mapping')
  return data
}

export async function fetchReconDocuments(supplierId: string, brandId?: string | null): Promise<ReconDocument[]> {
  const { data } = await axios.get(`/api/vendors/${supplierId}/recon/documents`, { params: brandId ? { brand_id: brandId } : {} })
  return data
}
export async function fetchReconCases(supplierId: string): Promise<ReconCaseSummary[]> {
  const { data } = await axios.get(`/api/vendors/${supplierId}/recon/cases`)
  return data
}
export async function fetchReconCase(caseId: string): Promise<ReconCase> {
  const { data } = await axios.get(`/api/recon/cases/${caseId}`)
  return data
}
export async function setSegmentKind(segmentId: string, kind: SegmentKind): Promise<void> {
  await axios.patch(`/api/recon/segments/${segmentId}`, { kind })
}
export async function linkSegment(segmentId: string, target: { case_id?: string; bill_id?: string; po_id?: string }): Promise<{ case_id: string }> {
  const { data } = await axios.post(`/api/recon/segments/${segmentId}/link`, target)
  return data
}
export async function ignoreSegment(segmentId: string, reason: string): Promise<void> {
  await axios.post(`/api/recon/segments/${segmentId}/ignore`, { reason })
}
export async function detachSegment(caseId: string, segmentId: string): Promise<ReconCase> {
  const { data } = await axios.post(`/api/recon/cases/${caseId}/detach`, { segment_id: segmentId })
  return data
}
export async function overrideMatch(caseId: string, otherKey: string, poLineKey: string | null): Promise<ReconCase> {
  const { data } = await axios.post(`/api/recon/cases/${caseId}/lines/match`, { other_key: otherKey, po_line_key: poLineKey })
  return data
}
export async function reviewLine(resultId: string, note: string): Promise<void> {
  await axios.post(`/api/recon/lines/${resultId}/review`, { note })
}
export async function correctEvidence(rowId: string, patch: Partial<{ audit_qty: string | null; vendor_qty: string | null; verdict: string; remark: string }>): Promise<ReconCase> {
  const { data } = await axios.post(`/api/recon/evidence/${rowId}/correct`, patch)
  return data
}
export async function acknowledgeCase(caseId: string, note: string, force = false): Promise<void> {
  await axios.post(`/api/recon/cases/${caseId}/ack`, { note, force })
}
export async function rerunCase(caseId: string): Promise<ReconCase> {
  const { data } = await axios.post(`/api/recon/cases/${caseId}/rerun`)
  return data
}
export async function fetchBillRecon(billId: string): Promise<ReconCaseSummary | null> {
  const { data } = await axios.get(`/api/bills/${billId}/recon`)
  return data
}
export async function startBillRecon(billId: string): Promise<{ doc_id: string }> {
  const { data } = await axios.post(`/api/bills/${billId}/recon/start`)
  return data
}
export const reconExportPath = (caseId: string) => `/api/recon/cases/${caseId}/export`
export const evidenceCropPath = (segmentId: string, page: number, bbox: number[]) =>
  `/api/recon/segments/${segmentId}/crop?page=${page}&bbox=${bbox.map(n => n.toFixed(1)).join(',')}`

/** "ev:<uuid>" → "<uuid>" (the evidence row id the correction endpoint takes). */
export const evidenceRowId = (key: string | null) => (key && key.startsWith('ev:') ? key.slice(3) : null)

/** What was read from each document on a case, before reconciling (GET /api/recon/cases/{id}/documents). */
export type ValueFmt = 'text' | 'money' | 'qty' | 'date' | 'pct'
export interface ExtractedField { label: string; value: string | number; fmt: ValueFmt }
/** The reconciled line a row of a document took part in: what the other documents say about it. */
export interface LineCompare {
  id: string; kind: LineResult['kind']; po_qty: string | null; po_rate: string | null; billed_qty: string | null
  billed_rate: string | null; verified_qty: string | null; vendor_qty: string | null; expected_qty: string | null
  expected_amt: string | null; billed_amt: string | null; delta: string | null; statuses: LineStatus[]; severity: Severity
  verdict: string | null; conflicts: string[]; match_method: MatchMethod; match_score: number; remark: string | null; reviewed: boolean
}
/** Cell values by column key, plus `_flag` (why the row needs a look), `_alts` (disagreeing reads),
 *  `_page` (the page of the original it was read from) and `_cmp` (its comparison, when on a case). */
export type ExtractedRow = { [key: string]: unknown; _cmp?: LineCompare | null }
export interface ExtractedTable {
  title: string
  /** `code`: the column's vocabulary role (docs/RECON_VOCABULARY.md), e.g. QTY_CLAIMED for a sheet's "Vendor Qty". */
  columns: { key: string; label: string; fmt: ValueFmt; code?: string }[]
  rows: ExtractedRow[]
}
/** The invoice a document is reconciled on: which documents are there, its totals and cross-document checks. */
export interface CaseContext {
  id: string; ref: string | null; invoice_no: string | null; po_number: string | null; store_sn: string | null; status: CaseStatus
  coverage: { po: boolean; invoice: boolean; evidence: boolean; pod: boolean }; ways: number
  totals: { po_total: string | null; expected_total: string | null; billed_total: string | null; invoice_total?: string | null; money_at_risk: string | null; under_billed: string | null }
  counts: Partial<Record<Severity, number>>; checks: HeaderCheck[]
  /** Which document's comparison these checks belong to. Null on the case
   *  itself, where the whole reconciliation is the point. */
  scope?: 'po' | 'invoice' | 'evidence' | 'pod' | 'payment' | 'memo' | 'other' | null
}
export interface CaseDocument {
  id: string; role: 'po' | 'invoice' | 'evidence' | 'pod' | 'memo' | 'other'; kind: SegmentKind; title: string
  /** upload = a file in Recon; bill = the bill already in Onsumm; register = the PO register. */
  source: 'upload' | 'bill' | 'register'
  file_name: string | null; doc_id: string | null; pages: number[]; link_method: string | null
  /** Protected path to the original file (streamed after a tenant check), and what kind of file it is. */
  download: string | null; file_type: 'pdf' | 'image' | 'sheet' | 'other' | null
  warnings: string[]; fields: ExtractedField[]; tables: ExtractedTable[]
  /** The invoice this document is reconciled on, if any. */
  case?: CaseContext | null
  /** For a part of an uploaded file: where it stands. */
  status?: SegmentStatus; vendor_name?: string | null
  /** What the part is, in the recon vocabulary (docs/RECON_VOCABULARY.md). */
  vocab?: DocVocab
}
/** Vocabulary codes for a document part: its role, which leg of the match it fills, how much a receipt can
 *  prove, and — for a site audit — the report's format and the layer its audited values come from. */
export interface DocVocab {
  doc_role: string | null; recon_leg: 'COMMITMENT' | 'DISPATCH' | 'RECEIPT' | 'QUALITY' | 'BILLING' | 'PAYMENT' | null
  receipt_granularity: 'ITEM_QTY' | 'PACKAGE' | 'CONSIGNMENT' | 'VALUE' | null
  pv_format: string | null; evidence_layer: string | null
}
/** An uploaded file opened in Recon: every part of it, as read and compared. */
export interface ReconFileView {
  id: string; file_name: string; uploaded_at: string | null; uploaded_by: string | null; recon_status: ReconStatus; error: string | null
  download: string; file_type: CaseDocument['file_type']; parts: CaseDocument[]
}
export async function fetchReconFileView(docId: string): Promise<ReconFileView> {
  const { data } = await axios.get(`/api/recon/documents/${docId}/view`)
  return data
}
export async function fetchCaseDocuments(caseId: string): Promise<CaseDocument[]> {
  const { data } = await axios.get(`/api/recon/cases/${caseId}/documents`)
  return data
}
export const segmentPagePath = (segmentId: string, page: number) => `/api/recon/segments/${segmentId}/page?page=${page}`

/** Remove a file from Recon: its parts leave their invoices, which are checked again without it. */
export async function deleteReconDocument(docId: string): Promise<{ deleted: string; cases: string[] }> {
  const { data } = await axios.delete(`/api/recon/documents/${docId}`)
  return data
}
/** Read a file again from scratch (after a failure, or once the reader has improved). */
export async function rereadReconDocument(docId: string): Promise<void> {
  await axios.post(`/api/recon/documents/${docId}/reread`)
}
