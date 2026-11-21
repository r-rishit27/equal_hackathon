import { useEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import {
  AlertTriangle, ArrowRight, Check, ChevronLeft, ChevronRight, Download, FileText, Loader2, Minus, RotateCcw, X, ZoomIn, ZoomOut,
} from 'lucide-react'
import { Document, Page, pdfjs } from 'react-pdf'
import type { CaseContext, CaseDocument, ExtractedTable, LineCompare, LineStatus, ValueFmt } from '../../../api/recon'
import { downloadAuthed, useAuthedObjectUrl } from '../../../api/authedFiles'
import { PdfLoading, useFocusTrap, useScrollLock } from '../../../ui'
import { CaseStatusChip } from './ReconFolder'
import { SEVERITY_TONE, SOURCE_LABEL, STATUS_LABEL, fmtValue, inr, needsLook, pageSpan, partLabel, lookCount, primaryStatus } from './reconFormat'

// Same worker every other react-pdf screen points at; set here too since this can be the first PDF opened.
pdfjs.GlobalWorkerOptions.workerSrc = new URL('pdfjs-dist/build/pdf.worker.min.mjs', import.meta.url).toString()

const COVER: { key: keyof CaseContext['coverage']; label: string }[] = [
  { key: 'po', label: 'PO' }, { key: 'invoice', label: 'Invoice' }, { key: 'evidence', label: 'Site audit' }, { key: 'pod', label: 'Delivery proof' },
]

/**
 * A document opened in Recon — the way contracts and bills open elsewhere in
 * the app: what was read on the left, the original on the right. Next to every
 * value read, the comparison with the invoice's other documents, as many ways
 * as there are documents (PO · invoice · site audit · delivery proof), so the
 * whole check sits in one view. Several parts (a report's sections, or a
 * case's documents) are tabs; the original turns to each part's pages.
 * Styled from recon.css alone, so it looks the same opened from any page.
 */
export default function ReconDocViewer({ title, subtitle, parts, initialPart = 0, loading, error, onClose, onOpenCase, nav }: {
  title: string; subtitle?: string; parts: CaseDocument[]; initialPart?: number
  loading?: boolean; error?: string | null; onClose: () => void
  /** Opens the invoice's full reconciliation (closes the viewer). */
  onOpenCase?: (caseId: string) => void
  /** Move between the files of the list this was opened from. */
  nav?: { index: number; count: number; onMove: (i: number) => void }
}) {
  const layer = useRef<HTMLDivElement>(null)
  useFocusTrap(layer, true, onClose)
  useScrollLock(true)
  const [at, setAt] = useState(initialPart)
  const part = parts[Math.min(at, Math.max(parts.length - 1, 0))] as CaseDocument | undefined
  const [page, setPage] = useState(part?.pages[0] ?? 1)
  useEffect(() => { setAt(initialPart) }, [initialPart, parts])
  useEffect(() => { setPage(part?.pages[0] ?? 1) }, [part?.id])   // eslint-disable-line react-hooks/exhaustive-deps
  // "Reconciliation" lays this document beside the PO, invoice and site audit; "As read" shows only what was
  // read from this document. Offered when some part is on an invoice; the choice is remembered per browser.
  const comparable = parts.some(p => p.case)
  const [view, setView] = useState<'recon' | 'read'>(() => {
    try { return localStorage.getItem(VIEW_KEY) === 'read' ? 'read' : 'recon' } catch { return 'recon' }
  })
  const pickView = (v: 'recon' | 'read') => {
    setView(v)
    try { localStorage.setItem(VIEW_KEY, v) } catch { /* private window: the choice lasts this visit */ }
  }
  const asRead = comparable && view === 'read'

  // Portalled to <body>: opened inside the vendor card (whose layout makes fixed
  // children relative to it) it would otherwise be boxed in instead of full screen.
  return createPortal(
    <div className="rc__scrim" onClick={e => { if (e.target === e.currentTarget) onClose() }}>
      <div ref={layer} tabIndex={-1} role="dialog" aria-modal="true" aria-label={title} className="rc__viewer">
        <div className="rc__viewer-h">
          <FileText size={18} className="rc__viewer-icon" />
          <div className="vc__grow vc__min0">
            <div className="vc__strong vc__ellipsis">{title}</div>
            {subtitle && <div className="vc__muted vc__xs vc__ellipsis">{subtitle}</div>}
          </div>
          {comparable && !loading && !error && (
            <div className="vc__seg" role="tablist" aria-label="View">
              <button role="tab" aria-selected={!asRead} className={!asRead ? 'on' : undefined} onClick={() => pickView('recon')}>Reconciliation</button>
              <button role="tab" aria-selected={asRead} className={asRead ? 'on' : undefined} onClick={() => pickView('read')}>As read</button>
            </div>
          )}
          {nav && nav.count > 1 && (
            <div className="rc__viewer-nav">
              <button className="vc__iconbtn vc__iconbtn--sm" aria-label="Previous document" disabled={nav.index === 0} onClick={() => nav.onMove(nav.index - 1)}><ChevronLeft size={16} /></button>
              <span className="vc__muted vc__xs rc__tnum">{nav.index + 1} / {nav.count}</span>
              <button className="vc__iconbtn vc__iconbtn--sm" aria-label="Next document" disabled={nav.index === nav.count - 1} onClick={() => nav.onMove(nav.index + 1)}><ChevronRight size={16} /></button>
            </div>
          )}
          {part?.download && (
            <button className="vc__iconbtn vc__iconbtn--sm" aria-label="Download the original" title="Download the original"
              onClick={() => downloadAuthed(part.download!, part.file_name ?? 'document')}><Download size={15} /></button>
          )}
          <button className="vc__iconbtn vc__iconbtn--sm" aria-label="Close" onClick={onClose}><X size={16} /></button>
        </div>

        {error ? <div className="rc__viewer-empty vc__bad vc__xs">{error}</div>
          : loading || !part ? <div className="rc__viewer-empty vc__muted vc__xs"><Loader2 size={16} className="rc__spin" /> Opening…</div>
          : (
            <div className="rc__viewer-body">
              <div className="rc__viewer-parsed">
                {parts.length > 1 && (
                  <div className="rc__viewer-tabs" role="tablist" aria-label="Parts">
                    {parts.map((p, i) => {
                      const n = lookCount(p)
                      const off = p.status === 'IGNORED' || p.status === 'FOREIGN'
                      return (
                        <button key={p.id} role="tab" aria-selected={i === at} className={`vc__fchip${i === at ? ' on' : ''}${off ? ' rc__tab-off' : ''}`} onClick={() => setAt(i)}>
                          {partLabel(p)}{n > 0 && !off && <span className="rc__tab-n">{n}</span>}
                        </button>
                      )
                    })}
                  </div>
                )}
                <div className="rc__viewer-scroll" role="tabpanel" aria-label={partLabel(part)}>
                  <PartPanel part={part} page={page} onPage={part.file_type === 'pdf' ? setPage : undefined} onOpenCase={onOpenCase} asRead={asRead} />
                </div>
              </div>
              <div className="rc__viewer-doc">
                <Original doc={part} page={page} onPage={setPage} />
              </div>
            </div>
          )}
      </div>
    </div>,
    document.body,
  )
}

const VIEW_KEY = 'recon.viewer.view'

const NOTICE: Record<string, string> = {
  WAITING: 'Waiting for its invoice. The comparison shows here as soon as the invoice is in Recon or Bills.',
  UNLINKED: 'Not on an invoice yet. Pick its invoice under “Needs you” in Recon.',
  EXTRACTED: 'Read, not on an invoice yet.',
  NEEDS_REVIEW: 'Read, not on an invoice yet. Some numbers need a check.',
  FAILED: 'This part couldn’t be read.',
  PENDING: 'Still being read.',
}

function PartPanel({ part: d, page, onPage, onOpenCase, asRead }: {
  part: CaseDocument; page: number; onPage?: (p: number) => void; onOpenCase?: (caseId: string) => void
  /** Only what was read from this document: no case strip, no cross-document checks, no other sources' columns. */
  asRead?: boolean
}) {
  const c = asRead ? null : d.case
  const off = d.status === 'IGNORED' || d.status === 'FOREIGN'
  const failed = c?.checks.filter(h => !h.passed) ?? []
  const passed = c?.checks.filter(h => h.passed) ?? []
  return (
    <>
      {c ? <CaseStrip c={c} onOpenCase={onOpenCase} />
        : off ? <div className="rc__notice">{d.status === 'FOREIGN' ? 'Another vendor’s section' : 'Set aside'}{d.vendor_name ? ` (${d.vendor_name})` : ''}. Not used in any reconciliation.</div>
        : asRead && d.case ? null
        : d.status && NOTICE[d.status] ? <div className="rc__notice">{NOTICE[d.status]}</div> : null}

      {d.warnings.length > 0 && (
        <div className="rc__doc-warn">
          {d.warnings.map((w, i) => <div key={i} className="vc__xs"><AlertTriangle size={12} className="rc__state--warn" /> {w}</div>)}
        </div>
      )}

      {d.fields.length > 0 && (
        <section className="rc__sec" aria-label="Details">
          <div className="rc__h">Details</div>
          <dl className="rc__fields">
            {d.fields.map(f => (
              <div key={f.label} className="rc__field">
                <dt className="vc__muted vc__xs">{f.label}</dt>
                <dd className={f.fmt === 'money' || f.fmt === 'qty' ? 'rc__tnum' : undefined}>{fmtValue(f.value, f.fmt)}</dd>
              </div>
            ))}
          </dl>
        </section>
      )}

      {c && c.checks.length > 0 && (
        <section className="rc__sec" aria-label={SCOPE_HEAD[c.scope ?? 'invoice'] ?? SCOPE_HEAD.invoice}>
          {/* Say which comparison this is. "Checks across documents" promised
              the whole reconciliation on a screen that shows one leg of it. */}
          <div className="rc__h">{SCOPE_HEAD[c.scope ?? 'invoice'] ?? SCOPE_HEAD.invoice}</div>
          <div className="rc__checks rc__checks--flat">
            {failed.map(h => (
              <div key={h.code} className="rc__check">
                <span className={`vc__chip vc__chip--${SEVERITY_TONE[h.severity]} vc__chip--xs`}>{h.severity === 'BLOCKER' ? 'Blocker' : h.severity === 'REVIEW' ? 'Review' : 'Info'}</span>
                <span className="vc__strong vc__xs">{h.label}</span><span className="vc__muted vc__xs">{h.detail}</span>
              </div>
            ))}
            {passed.length > 0 && <div className="rc__check rc__check--ok"><Check size={13} className="vc__okc" /><span className="vc__xs">{passed.map(h => h.label).join(' · ')}</span></div>}
          </div>
        </section>
      )}

      {d.tables.map(t => <LinesTable key={t.title} t={t} role={d.role} c={off ? null : c ?? null} page={page} onPage={onPage} />)}
    </>
  )
}

/** The delivery proof's own reconciliation result, where the delivery proof is.
 *
 *  Its verdict was reaching the screen only as one entry in a run-on list of
 *  passed checks at the bottom of the case — so against a POD the page looked
 *  like nothing had been reconciled at all. The leg that this document answers
 *  should say how it came out, next to the document. */
function PodVerdict({ c }: { c: CaseContext }) {
  const check = c.checks?.find(h => h.code === 'pod_matches')
  const gross = c.totals.invoice_total
  if (!check) {
    // Only worth saying when the POD is the only receipt evidence. With a site
    // audit present, receipt is already covered at item level.
    return c.coverage.evidence ? null
      : <span className="rc__receipt-note">receipt confirmed at consignment level, not per item</span>
  }
  return (
    <span className={`rc__podverdict rc__podverdict--${check.passed ? 'ok' : 'bad'}`}
      title="A delivery proof is matched on the invoice total including tax — the figure a carrier declares — and on the invoice reference it carries. It confirms a consignment and its value, never item quantities.">
      {check.passed
        ? <>✓ Reconciled against the delivery proof{gross ? ` · ₹${inr(gross)} matches the waybill` : ''}
            <span className="rc__receipt-note"> · consignment level, not per item</span></>
        : <>Delivery proof does not match{check.detail ? ` — ${check.detail}` : ''}</>}
    </span>
  )
}


/** What a tick on each chip actually means. The delivery proof is the one worth
 *  spelling out: it confirms that a consignment of a stated value reached an
 *  address, never that six of a particular item arrived. Treating it as
 *  item-level receipt is the mistake this wording exists to prevent. */
const PROVES: Record<string, string> = {
  po: 'What was ordered, and at what rate',
  invoice: "The vendor's bill",
  evidence: 'Quantities verified on site by the auditor',
  pod: 'Confirms the consignment and its value — not item quantities',
}

/** Which documents this invoice is checked against — "3-way" — with its headline numbers. */
function CaseStrip({ c, onOpenCase }: { c: CaseContext; onOpenCase?: (id: string) => void }) {
  const t = c.totals
  const risk = Number(t.money_at_risk ?? 0)
  return (
    <div className="rc__strip">
      <div className="rc__strip-row">
        <span className="rc__ways">{c.ways}-way check</span>
        <span className="rc__cover">
          {COVER.map(x => (
            <span key={x.key} className={`rc__pip rc__pip--${x.key}${c.coverage[x.key] ? ' is-on' : ''}`}
              title={c.coverage[x.key] ? `${x.label} — ${PROVES[x.key] ?? 'in'}` : `No ${x.label.toLowerCase()} yet`}>
              {c.coverage[x.key] ? <Check size={10} strokeWidth={3} /> : <Minus size={10} />}{x.label}
            </span>
          ))}
        </span>
        <CaseStatusChip status={c.status} />
        {c.coverage.pod && <PodVerdict c={c} />}
        <span className="vc__grow" />
        {onOpenCase && (
          <button className="vc__lnk vc__xs" onClick={() => onOpenCase(c.id)}>Full reconciliation{c.invoice_no ? ` · ${c.invoice_no}` : ''} <ArrowRight size={12} /></button>
        )}
      </div>
      <div className="rc__strip-nums">
        <Num label="PO value" v={t.po_total} />
        <Num label="Supported" v={t.expected_total} />
        <Num label="Billed" v={t.billed_total} />
        <Num label="Over-billed" v={t.money_at_risk} tone={risk > 0 ? 'bad' : undefined} />
        <Num label="Under-billed" v={t.under_billed} />
        {/* A carrier and a bank both state the invoice INCLUDING tax, so the
            receipt and payment legs are reconciled on that figure. Reconciling
            them against the taxable sum would report a difference of exactly
            the tax on every single document. */}
        {t.invoice_total && (
          <Num label="Invoice total (incl. tax)" v={t.invoice_total}
            hint="What the delivery proof and the remittance advice are matched against" />
        )}
      </div>
    </div>
  )
}

function Num({ label, v, tone, hint }: { label: string; v: string | null | undefined; tone?: 'bad'; hint?: string }) {
  return <div className="rc__num-cell" title={hint}><div className="vc__muted vc__xs">{label}</div><div className={`rc__tnum vc__strong${tone ? ' vc__bad' : ''}`}>{v === null || v === undefined ? '—' : `₹${inr(v)}`}</div></div>
}

/**
 * Each source keeps one colour wherever it appears — the coverage pills, the
 * column groups here and on the case's Lines table: PO blue, invoice violet,
 * site audit teal, delivery proof amber, the result slate.
 */
type Src = 'po' | 'invoice' | 'evidence' | 'pod' | 'result'
/** What a document's screen is comparing, named for the document you opened. */
const SCOPE_HEAD: Record<string, string> = {
  po: 'This purchase order against the invoice',
  evidence: 'This site report against the invoice',
  pod: 'This delivery proof against the invoice',
  payment: 'This payment against the invoice',
  memo: 'This approval',
  invoice: 'This invoice against every document on it',
}

const SRC_LABEL: Record<Src, string> = { po: 'PO', invoice: 'Invoice', evidence: 'Site audit', pod: 'Delivery proof', result: 'Result' }

type Col = { key: string; label: string; fmt: ValueFmt; diff?: LineStatus[]; from: 'read' | 'cmp' }
type Group = { src: Src; own?: boolean; cols: Col[] }

/** With a comparison beside it, a document shows only the columns the comparison uses; the rest are in Details. */
const COMPACT: Partial<Record<CaseDocument['role'], string[]>> = {
  po: ['unit', 'qty', 'rate', 'amount'],
  invoice: ['unit', 'qty', 'rate', 'amount'],
  // The report's price columns stay. Dropping them beside a comparison left
  // the one screen that reads the paper unable to show what the paper says
  // the work is worth.
  evidence: ['unit', 'po_qty', 'vendor_qty', 'audit_qty', 'verdict',
             'rate', 'rate_after_discount', 'value', 'amount', 'remark'],
  other: ['unit', 'po_qty', 'audit_qty', 'rate', 'value', 'remark'],
}
const READ_LABEL: Record<string, string> = { qty: 'Qty', rate: 'Rate', amount: 'Amount', po_qty: 'PO qty', audit_qty: 'Verified', vendor_qty: 'Vendor claimed', verdict: 'Meaning', remark: 'Remark', rate_after_discount: 'Net rate', value: 'Value ₹' }
const ROLE_SRC: Partial<Record<CaseDocument['role'], Src>> = { po: 'po', invoice: 'invoice', evidence: 'evidence', other: 'evidence', pod: 'pod' }

/** The column groups for a document's lines: its own reading, each other source on the invoice, then the result. */
function groupsFor(t: ExtractedTable, role: CaseDocument['role'], c: CaseContext | null, compared: boolean): { main: Col | null; groups: Group[] } {
  const mainCol = t.columns.find(x => MAIN.has(x.key))
  const main = mainCol ? { ...mainCol, from: 'read' as const } : null
  const own = ROLE_SRC[role] ?? 'po'
  const keep = compared ? COMPACT[role] : undefined
  const readCols: Col[] = t.columns.filter(x => !MAIN.has(x.key) && (!keep || keep.includes(x.key)))
    .filter(x => !(keep && x.key === 'vendor_qty' && !t.rows.some(r => r.vendor_qty !== null && r.vendor_qty !== undefined)))
    .map(x => ({ ...x, label: compared ? (READ_LABEL[x.key] ?? x.label) : x.label, from: 'read' as const }))
  const groups: Group[] = [{ src: own, own: true, cols: readCols }]
  if (!compared || !c) return { main, groups }
  const cov = c.coverage
  const anyVendor = t.rows.some(r => r._cmp?.vendor_qty)

  // **One document, one comparison.** Opening the site report asks how the
  // site report compares with the bill — not what the PO or the payment said.
  // Three counterparts at once is the whole reconciliation, which is what the
  // dashboard is for; here it just makes the answer hard to find.
  //
  // The invoice is the exception, because it IS the spine: every other
  // document is a counterpart to it, so its own screen shows them all.
  const INVOICE = { src: 'invoice' as const, cols: [
    { key: 'billed_qty', label: 'Qty', fmt: 'qty' as const, diff: ['OVER_PO', 'OVER_VERIFIED', 'UNDER_BILLED'] as LineStatus[], from: 'cmp' as const },
    { key: 'billed_rate', label: 'Rate', fmt: 'money' as const, diff: ['RATE_HIGHER', 'RATE_LOWER'] as LineStatus[], from: 'cmp' as const },
    { key: 'billed_amt', label: 'Amount', fmt: 'money' as const, from: 'cmp' as const }] }

  if (own !== 'invoice') {
    if (cov.invoice) groups.push(INVOICE)
    groups.push({ src: 'result', cols: [{ key: '_result', label: 'Result', fmt: 'text', from: 'cmp' }] })
    return { main, groups }
  }

  if (cov.po) groups.push({ src: 'po', cols: [
    { key: 'po_qty', label: 'Qty', fmt: 'qty' as const, diff: ['OVER_PO'] as LineStatus[], from: 'cmp' as const },
    { key: 'po_rate', label: 'Rate', fmt: 'money', diff: ['RATE_HIGHER', 'RATE_LOWER'], from: 'cmp' }] })
  if (cov.evidence) groups.push({ src: 'evidence', cols: [
    ...(anyVendor ? [{ key: 'vendor_qty', label: 'Vendor claimed', fmt: 'qty' as const, from: 'cmp' as const }] : []),
    { key: 'verified_qty', label: 'Verified', fmt: 'qty', diff: ['OVER_VERIFIED', 'NOT_DONE', 'UNDER_USED'], from: 'cmp' },
    { key: 'verified_rate', label: 'Rate', fmt: 'money', from: 'cmp' },
    { key: 'verified_amt', label: 'Value ₹', fmt: 'money', from: 'cmp' }] })
  const money = cov.po || cov.evidence
  groups.push({ src: 'result', cols: [
    ...(money ? [{ key: 'expected_amt', label: 'Expected ₹', fmt: 'money' as const, from: 'cmp' as const },
                 { key: 'delta', label: 'Δ ₹', fmt: 'money' as const, from: 'cmp' as const }] : []),
    { key: '_result', label: 'Result', fmt: 'text', from: 'cmp' }] })
  return { main, groups }
}

/** The column that names the row; it stays put while the numbers scroll. */
const MAIN = new Set(['description', 'item', 'approver'])

function LinesTable({ t, role, c, page, onPage }: {
  t: ExtractedTable; role: CaseDocument['role']; c: CaseContext | null; page?: number; onPage?: (p: number) => void
}) {
  const [only, setOnly] = useState(false)
  const compared = !!c && t.rows.some(r => r._cmp)
  const { main, groups } = useMemo(() => groupsFor(t, role, c, compared), [t, role, c, compared])
  const looks = t.rows.filter(needsLook).length
  const rows = only ? t.rows.filter(needsLook) : t.rows
  const width = (main ? 1 : 0) + groups.reduce((n, g) => n + g.cols.length, 0)
  return (
    <section className="rc__sec" aria-label={t.title}>
      <div className="rc__lineshead">
        <div className="rc__h">{t.title} <span className="vc__c">{t.rows.length}</span></div>
        {looks > 0 && (
          <div className="vc__seg" role="tablist" aria-label="Show">
            <button role="tab" aria-selected={!only} className={!only ? 'on' : undefined} onClick={() => setOnly(false)}>All</button>
            <button role="tab" aria-selected={only} className={only ? 'on' : undefined} onClick={() => setOnly(true)}>To check {looks}</button>
          </div>
        )}
      </div>
      <div className="rc__scroll">
        <table className="rc__table rc__srctable">
          <thead>
            {compared && (
              <tr className="rc__group">
                {main && <th rowSpan={2} className="rc__sticky rc__group-item">{main.label}</th>}
                {groups.map(g => g.cols.length > 0 && (
                  <th key={g.src} colSpan={g.cols.length} className={`rc__src rc__src--${g.src} rc__src-start`}>
                    <span className="rc__src-dot" />{SRC_LABEL[g.src]}{g.own && <span className="rc__src-own"> · this document</span>}
                  </th>
                ))}
              </tr>
            )}
            <tr>
              {!compared && main && <th className="rc__sticky">{main.label}</th>}
              {groups.flatMap(g => g.cols.map((col, i) => (
                <th key={`${g.src}:${col.key}`} className={cls(compared && `rc__src rc__src--${g.src}`, compared && i === 0 && 'rc__src-start', col.fmt !== 'text' && 'rc__num')}>{col.label}</th>
              )))}
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 && <tr><td colSpan={width} className="vc__muted vc__xs rc__pad">{only ? 'Nothing to check here.' : 'Nothing was read.'}</td></tr>}
            {rows.map((r, ri) => {
              const p = typeof r._page === 'number' ? r._page : null
              const go = p && onPage ? () => onPage(p) : undefined
              const x = r._cmp ?? null
              return (
                <tr key={String(r._key ?? ri)} className={cls(needsLook(r) && 'rc__row-flag', go && 'rc__click', go && p === page && 'is-open')}
                  onClick={go} title={go ? `Show page ${p} of the original` : undefined}>
                  {main && (
                    <td className="rc__sticky">
                      {fmtValue(r[main.key], main.fmt)}
                      {!!r._flag && <div className="rc__state--warn vc__xs">{String(r._flag)}</div>}
                      {x && x.conflicts.length > 0 && <div className="rc__state--warn vc__xs">Differs: {x.conflicts.join(' · ')}</div>}
                    </td>
                  )}
                  {groups.flatMap(g => g.cols.map((col, i) => {
                    const key = `${g.src}:${col.key}`
                    const tone = cls(compared && `rc__src rc__src--${g.src}`, compared && i === 0 && 'rc__src-start')
                    if (col.from === 'read') {
                      const alts = col.key === 'audit_qty' && Array.isArray(r._alts) && r._alts.length ? r._alts as string[] : null
                      const raw = col.key === 'audit_qty' && r.audit_raw ? String(r.audit_raw) : null
                      return (
                        <td key={key} className={cls(tone, col.fmt !== 'text' && 'rc__num', alts && 'rc__cell-check')}>
                          {fmtValue(r[col.key], col.fmt)}
                          {raw && <div className="vc__muted vc__xs">written “{raw}”</div>}
                          {alts && <div className="vc__muted vc__xs">read as {alts.join(' / ')}</div>}
                        </td>
                      )
                    }
                    if (col.key === '_result') {
                      return (
                        <td key={key} className={tone}>
                          {x ? <span className={`vc__chip vc__chip--${SEVERITY_TONE[x.severity]} vc__chip--xs`}>{STATUS_LABEL[primaryStatus(x)]}</span>
                            : <span className="vc__muted vc__xs">Not compared</span>}
                          {x?.reviewed && <Check size={12} className="vc__okc" aria-label="Reviewed" />}
                        </td>
                      )
                    }
                    const v = x ? x[col.key as keyof LineCompare] : null
                    const hit = x && col.diff && col.diff.some(st => x.statuses.includes(st))
                    const delta = col.key === 'delta' && x ? Number(x.delta) : 0
                    return (
                      <td key={key} className={cls(tone, 'rc__num', hit && 'rc__diff', delta > 0 && x!.severity !== 'INFO' && x!.severity !== 'OK' && 'vc__bad')}>
                        {col.key === 'delta' && x && Number(x.delta) === 0 ? '—' : fmtValue(v, col.fmt)}
                      </td>
                    )
                  }))}
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </section>
  )
}

const cls = (...c: (string | false | null | undefined | 0)[]) => c.filter(Boolean).join(' ') || undefined

/** The original file: a PDF fitted to the pane's height with paging and zoom, an image, or a download. */
function Original({ doc: d, page, onPage }: { doc: CaseDocument; page: number; onPage: (p: number) => void }) {
  const isPdf = d.file_type === 'pdf'
  const file = useAuthedObjectUrl(d.download && (isPdf || d.file_type === 'image') ? `${d.download}${d.download.includes('?') ? '&' : '?'}preview=true` : null)
  const pane = useRef<HTMLDivElement>(null)
  const [paneH, setPaneH] = useState(0)
  const [natural, setNatural] = useState<{ w: number; h: number } | null>(null)
  const [zoom, setZoom] = useState(0)
  const [numPages, setNumPages] = useState(0)

  useEffect(() => {
    const el = pane.current
    if (!el) return
    const update = () => setPaneH(el.clientHeight)
    const ro = new ResizeObserver(update)
    ro.observe(el)
    update()
    return () => ro.disconnect()
  }, [isPdf, file.url])

  if (!d.download) {
    return <div className="rc__viewer-empty vc__muted vc__xs">{d.source === 'register' ? 'This PO came from the PO register; there is no file to show.' : 'No file to show.'}</div>
  }
  if (!isPdf && d.file_type !== 'image') {
    return (
      <div className="rc__viewer-empty">
        <FileText size={40} strokeWidth={1} className="vc__muted" />
        <div className="vc__xs">A spreadsheet has no page to show; every value read from it is on the left.</div>
        <button className="vc__btn vc__btn--sm" onClick={() => downloadAuthed(d.download!, d.file_name ?? 'document')}><Download size={14} />Download</button>
      </div>
    )
  }
  if (file.error) return <div className="rc__viewer-empty vc__muted vc__xs">Couldn’t load the original.</div>
  if (!file.url) return <div className="rc__viewer-empty"><PdfLoading stage="fetching" /></div>
  if (!isPdf) return <div className="rc__viewer-img"><img src={file.url} alt={`The original ${d.file_name ?? ''}`} /></div>

  const width = !paneH || !natural ? 520 : Math.max(280, (paneH / natural.h) * natural.w + zoom)
  const inSection = d.pages.includes(page)
  return (
    <>
      <div className="rc__viewer-bar">
        {d.pages.length > 0 && (
          <button className={`vc__fchip${inSection ? ' on' : ''}`} onClick={() => onPage(d.pages[0])} title="Go to the first page of this part">
            This part: {pageSpan(d.pages)}
          </button>
        )}
        <span className="vc__grow" />
        <button className="vc__iconbtn vc__iconbtn--sm" aria-label="Zoom in" onClick={() => setZoom(z => z + 60)}><ZoomIn size={15} /></button>
        <button className="vc__iconbtn vc__iconbtn--sm" aria-label="Zoom out" onClick={() => setZoom(z => z - 60)}><ZoomOut size={15} /></button>
        <button className="vc__iconbtn vc__iconbtn--sm" aria-label="Reset zoom" onClick={() => setZoom(0)}><RotateCcw size={14} /></button>
        {numPages > 1 && <>
          <button className="vc__iconbtn vc__iconbtn--sm" aria-label="Previous page" disabled={page <= 1} onClick={() => onPage(page - 1)}><ChevronLeft size={16} /></button>
          <span className="vc__xs rc__tnum">{page} / {numPages}</span>
          <button className="vc__iconbtn vc__iconbtn--sm" aria-label="Next page" disabled={page >= numPages} onClick={() => onPage(page + 1)}><ChevronRight size={16} /></button>
        </>}
      </div>
      <div ref={pane} className={`rc__viewer-page${zoom > 0 ? ' is-zoomed' : ''}`}>
        <Document file={file.url} loading={<PdfLoading stage="rendering" />}
          onLoadSuccess={({ numPages: n }) => { setNumPages(n); if (page > n) onPage(1) }}
          error={<div className="rc__viewer-empty vc__muted vc__xs">Couldn’t open this PDF.</div>}>
          <Page pageNumber={Math.min(page, numPages || page)} width={width} renderAnnotationLayer={false} renderTextLayer={false}
            onLoadSuccess={p => setNatural({ w: p.originalWidth, h: p.originalHeight })} />
        </Document>
      </div>
    </>
  )
}
