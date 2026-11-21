import type { CaseDocument, ExtractedRow, LineResult, LineStatus, SegmentKind, Severity, ValueFmt } from '../../../api/recon'

/** Indian grouping, 2 decimals: "1128945.59" → "11,28,945.59". Strings in, strings out. */
export function inr(v: string | number | null | undefined): string {
  if (v === null || v === undefined || v === '') return '—'
  const n = typeof v === 'number' ? v : Number(v)
  if (!Number.isFinite(n)) return String(v)
  return n.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

/** Quantities: up to 3 decimals, trailing zeros trimmed. */
export function qty(v: string | number | null | undefined): string {
  if (v === null || v === undefined || v === '') return '—'
  const n = Number(v)
  if (!Number.isFinite(n)) return String(v)
  return n.toLocaleString('en-IN', { maximumFractionDigits: 3 })
}

export const SEVERITY_RANK: Record<Severity, number> = { BLOCKER: 3, REVIEW: 2, INFO: 1, OK: 0 }

/** Chip tone per severity, in the vendor card's chip vocabulary. */
export const SEVERITY_TONE: Record<Severity, 'bad' | 'warn' | 'info' | 'ok'> = { BLOCKER: 'bad', REVIEW: 'warn', INFO: 'info', OK: 'ok' }

export const STATUS_LABEL: Record<LineStatus, string> = {
  RATE_HIGHER: 'Rate above PO', RATE_LOWER: 'Rate below PO', OVER_PO: 'More than PO', OVER_VERIFIED: 'More than verified',
  UNDER_BILLED: 'Under-billed', UNDER_USED: 'Less than PO', OVER_EXECUTED_CAPPED: 'Capped at PO',
  NOT_DONE: 'Not done on site', NOT_VERIFIABLE: 'Not countable on site', NOT_IN_PO: 'Not in PO',
  ADDITIONAL_ON_SITE: 'Extra on site', DESCRIPTION_CONFLICT: 'Description differs', UOM_CONFLICT: 'Unit differs',
  DAMAGED_UNMOUNTED: 'Damaged / unmounted', AUDITOR_REMARK: 'Auditor note', PCT_CHARGE_MISMATCH: 'Charge basis differs',
  ARITHMETIC: 'Arithmetic', NO_EVIDENCE: 'Not in report', UNCHECKED_READING: 'Check handwriting',
  REPORT_ONLY: 'Report only', MATCHED: 'Matches',
}

/** Which statuses a line is "about", most important first. */
const PRIMARY_ORDER: LineStatus[] = [
  'OVER_VERIFIED', 'OVER_PO', 'RATE_HIGHER', 'NOT_DONE', 'NOT_IN_PO', 'PCT_CHARGE_MISMATCH', 'UNDER_BILLED',
  'UNCHECKED_READING', 'DESCRIPTION_CONFLICT', 'UOM_CONFLICT', 'ARITHMETIC', 'DAMAGED_UNMOUNTED', 'NO_EVIDENCE',
  'ADDITIONAL_ON_SITE', 'OVER_EXECUTED_CAPPED', 'NOT_VERIFIABLE', 'UNDER_USED', 'RATE_LOWER', 'AUDITOR_REMARK',
  'REPORT_ONLY', 'MATCHED',
]
export function primaryStatus(l: Pick<LineResult, 'statuses'>): LineStatus {
  return PRIMARY_ORDER.find(s => l.statuses.includes(s)) ?? 'MATCHED'
}

export const MATCH_LABEL: Record<string, string> = {
  EXACT: 'Exact', ALIAS: 'Learned', SCORE: 'Matched', LLM: 'AI', HUMAN: 'You', NONE: '—',
}

/**
 * How a line was paired with its counterpart, and how sure that pairing is.
 *
 * This matters more than it looks. Every number on a row is only as good as
 * the pairing that put the two documents side by side — a 62% match means the
 * difference below it might be a difference between two unrelated items. It
 * was computed all along and shown nowhere.
 *
 * An exact or human match has nothing to qualify, so it shows no number: a
 * reviewer should read a percentage as "this one is a judgement", not as
 * decoration on every row.
 */
export function matchBadge(l: Pick<LineResult, 'match_method' | 'match_score'>):
    { label: string; pct: number | null; tone: 'ok' | 'warn' | 'plain' } | null {
  const method = l.match_method
  if (!method || method === 'NONE') return null
  const label = MATCH_LABEL[method] ?? method
  if (method === 'EXACT' || method === 'HUMAN') return { label, pct: null, tone: 'ok' }
  const pct = Math.round((Number(l.match_score) || 0) * 100)
  return { label, pct, tone: pct >= 85 ? 'ok' : pct >= 70 ? 'plain' : 'warn' }
}

export const KIND_LABEL: Record<SegmentKind, string> = {
  PURCHASE_ORDER: 'Purchase order', TAX_INVOICE: 'Invoice', PV_SECTION: 'Site audit', POD: 'Delivery proof',
  PAYMENT_ADVICE: 'Payment advice', APPROVAL_MEMO: 'Approval memo', OTHER: 'Other', IGNORED: 'Ignored',
}

export const STAGE_LABEL: Record<string, string> = {
  reading: 'Reading pages', classifying: 'Working out what each page is', extracting: 'Reading the details',
  linking: 'Finding the invoice it belongs to', matching: 'Matching lines', done: 'Done',
}

/** Line filters in the case view.
 *
 * The split that matters to whoever is paying: **over-billed and under-billed
 * are not the same kind of news.** Money billed above what the PO and the site
 * report support is the payer's exposure and a reason to hold. Money the vendor
 * failed to bill is the vendor's loss — worth telling them, never a reason to
 * stop the payment. A single "Flagged 26" chip hides that distinction and makes
 * a payable invoice look like a problem, which is exactly what the PayVerdict
 * banner above the table was written to undo.
 *
 * `over` and `under` are deliberately the same sets the engine totals into
 * `money_at_risk` and `under_billed` (engine.py §summary), so a chip's count can
 * never disagree with the banner's figure.
 */
export type LineFilter =
  | 'all' | 'flagged' | 'blockers'
  | 'over'            // billed above what is supported — the payer's exposure
  | 'under'           // the vendor billed less than it could — their loss
  | 'check'           // flagged, but no money either way: descriptions, units, handwriting
  | 'under_po' | 'not_in_po' | 'extra'

const FLAGGED = (l: LineResult) => l.severity === 'BLOCKER' || l.severity === 'REVIEW'
/** Billed above support, at a severity the engine counts as risk. */
const OVER = (l: LineResult) => Number(l.delta) > 0 && FLAGGED(l)
/** The vendor's own shortfall, by the engine's definition rather than any negative delta. */
const UNDER = (l: LineResult) => Number(l.delta) < 0
  && (l.statuses.includes('UNDER_BILLED') || l.statuses.includes('PCT_CHARGE_MISMATCH'))

export function filterLines(lines: LineResult[], f: LineFilter): LineResult[] {
  switch (f) {
    case 'flagged': return lines.filter(FLAGGED)
    case 'over': return lines.filter(OVER)
    case 'under': return lines.filter(UNDER)
    case 'check': return lines.filter(l => FLAGGED(l) && !OVER(l) && !UNDER(l))
    case 'blockers': return lines.filter(l => l.severity === 'BLOCKER')
    case 'under_po': return lines.filter(l => l.statuses.includes('UNDER_USED'))
    case 'not_in_po': return lines.filter(l => l.kind === 'not_in_po')
    case 'extra': return lines.filter(l => l.kind === 'additional' || l.kind === 'report_only')
    default: return lines
  }
}

/** The money a filter's lines account for, unsigned — what a chip shows beside its count. */
export function filterMoney(lines: LineResult[], f: LineFilter): number | null {
  if (f !== 'over' && f !== 'under') return null
  const total = filterLines(lines, f).reduce((a, l) => a + Math.abs(Number(l.delta) || 0), 0)
  return total > 0 ? total : null
}

// ── Opening a document: labels and formatting shared by the viewer and the case's document cards ──

export const ROLE_LABEL: Record<CaseDocument['role'], string> = {
  po: 'Purchase order', invoice: 'Invoice', evidence: 'Site audit', pod: 'Delivery proof', memo: 'Approval memo', other: 'Other',
}
export const SOURCE_LABEL: Record<CaseDocument['source'], string> = {
  upload: '', bill: 'The bill already in Onsumm', register: 'From the PO register',
}

export function fmtValue(v: unknown, fmt: ValueFmt): string {
  if (v === null || v === undefined || v === '') return '—'
  if (fmt === 'money') return `₹${inr(v as string)}`
  if (fmt === 'qty') return qty(v as string)
  if (fmt === 'pct') return `${qty(v as string)}%`
  if (fmt === 'date') {
    const d = new Date(String(v))
    return Number.isNaN(d.getTime()) ? String(v) : d.toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' })
  }
  return String(v)
}

export const pageSpan = (p: number[]) => (p.length === 0 ? '' : p.length > 1 ? `pages ${p[0]}–${p[p.length - 1]}` : `page ${p[0]}`)

/** Rows that need a look: a reading to check, or a comparison that isn't clean. */
export const needsLook = (r: ExtractedRow) => !!r._flag || (!!r._cmp && (r._cmp.severity === 'BLOCKER' || r._cmp.severity === 'REVIEW'))
export const lookCount = (d: CaseDocument) =>
  d.warnings.length + d.tables.reduce((n, t) => n + t.rows.filter(needsLook).length, 0) + (d.case?.checks.filter(c => !c.passed && c.severity !== 'INFO').length ?? 0)

/** A part's tab label: what it is, and which section for an audit report. */
export function partLabel(d: CaseDocument): string {
  const base = d.role === 'evidence' ? (d.title || ROLE_LABEL.evidence) : ROLE_LABEL[d.role]
  if (d.status === 'IGNORED') return `${base} · set aside`
  if (d.status === 'FOREIGN') return `${base} · other vendor`
  return base
}



// ── Folders inside Recon ───────────────────────────────────────────────────

/**
 * Which folder a document belongs in.
 *
 * A finance reviewer looks for "the POs" or "the audit reports", not for a
 * filename in a list of forty. The classification already exists — every
 * segment carries its kind from the moment it was read — so filing is a
 * grouping of what is there, not new work and nothing to re-read: documents
 * uploaded months ago land in their folder the first time this screen opens.
 *
 * A Bata PDF often holds several kinds at once (a PO, three audit sections, a
 * delivery proof). Filing it in every folder would make one file look like
 * four, so it goes in ONE: the folder for the most significant kind it
 * contains, in the order below, and the row still lists everything inside it.
 */
export type ReconFolderKey =
  | 'invoice' | 'po' | 'audit' | 'receipt' | 'payment' | 'approval' | 'unfiled'

export const FOLDER_ORDER: ReconFolderKey[] = [
  'invoice', 'po', 'audit', 'receipt', 'payment', 'approval', 'unfiled',
]

export const FOLDER_LABEL: Record<ReconFolderKey, string> = {
  invoice: 'Invoices', po: 'Purchase orders', audit: 'Audit reports',
  receipt: 'Goods receipt & delivery proof', payment: 'Payment receipts',
  approval: 'Approvals', unfiled: 'Not filed yet',
}

export const FOLDER_HINT: Record<ReconFolderKey, string> = {
  invoice: 'What the vendor is charging',
  po: 'What was ordered, and at what rate',
  audit: 'What the auditor certified on site',
  receipt: 'What actually arrived',
  payment: 'What has been settled',
  approval: 'Who agreed to it',
  unfiled: 'Read, but not recognised as one of the above',
}

/** Most significant first: the kind that decides which folder a mixed file goes in. */
const KIND_FOLDER: [SegmentKind, ReconFolderKey][] = [
  ['TAX_INVOICE', 'invoice'],
  ['PURCHASE_ORDER', 'po'],
  ['PV_SECTION', 'audit'],
  ['POD', 'receipt'],
  ['PAYMENT_ADVICE', 'payment'],
  ['APPROVAL_MEMO', 'approval'],
]

export function folderOf(segments: { kind: SegmentKind; status?: string }[]): ReconFolderKey {
  // Another vendor's section, or one set aside, says nothing about where the
  // file belongs — a PO with one foreign page is still a PO.
  const kinds = new Set(segments.filter(s => s.status !== 'IGNORED' && s.status !== 'FOREIGN').map(s => s.kind))
  for (const [kind, folder] of KIND_FOLDER) if (kinds.has(kind)) return folder
  return 'unfiled'
}


/** Which leg of the reconciliation a folder's documents answer, so a row can
 *  show how much of the bill its own document accounts for. */
export const FOLDER_LEG: Partial<Record<ReconFolderKey, 'po' | 'evidence' | 'pod' | 'payment'>> = {
  po: 'po', audit: 'evidence', receipt: 'pod', payment: 'payment',
}

/** A coverage figure as a chip: how much of the invoice this document accounts
 *  for, and whether that is reassuring. Null stays null — a document that has
 *  not arrived is not one performing badly, and 0% would accuse it. */
export function coverBadge(v: number | null | undefined):
    { pct: number; tone: 'ok' | 'plain' | 'warn' } | null {
  if (v === null || v === undefined) return null
  const pct = Math.round(v * 100)
  return { pct, tone: pct >= 95 ? 'ok' : pct >= 80 ? 'plain' : 'warn' }
}
