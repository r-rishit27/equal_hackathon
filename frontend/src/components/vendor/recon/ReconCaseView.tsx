import { Fragment, useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { Check, ChevronDown, ChevronRight, Download, LayoutDashboard, Link2, Loader2, RefreshCw, ShieldCheck, Unlink, X } from 'lucide-react'
import axios from 'axios'
import {
  acknowledgeCase, confirmCheck, correctEvidence, detachSegment, evidenceCropPath, evidenceRowId, fetchReconCase, overrideMatch,
  reconExportPath, rerunCase, reviewLine, type LineResult, type ReconCase,
} from '../../../api/recon'
import { downloadAuthed, useAuthedObjectUrl } from '../../../api/authedFiles'
import { useFocusTrap } from '../../../ui'
import { CaseVitals } from './CaseVitals'
import { FourWay } from './FourWay'
import { ReconGraph } from './ReconGraph'
import { PayVerdict } from './PayVerdict'
import { CaseStatusChip, Flags } from './ReconFolder'
import CaseDocuments from './CaseDocuments'
import { VendorLink } from '../../records/RecordLink'
import './recon.css'
import {
  KIND_LABEL, MATCH_LABEL, SEVERITY_TONE, matchBadge, STATUS_LABEL, filterLines, filterMoney, inr, primaryStatus, qty, type LineFilter,
} from './reconFormat'

/** The chip row, read left to right as a reviewer's order of business.
 *
 * Over-billed first because it is the only group that can cost the payer money,
 * and separate from under-billed because the two are opposite news — see the
 * note on LineFilter. `tone` colours that difference: the exposure is a warning,
 * the vendor's shortfall is neutral information.
 */
const FILTERS: { key: LineFilter; label: string; tone?: 'bad' | 'plain' }[] = [
  { key: 'over', label: 'Over-billed', tone: 'bad' },
  { key: 'check', label: 'To check' },
  { key: 'under', label: 'Vendor under-billed', tone: 'plain' },
  { key: 'not_in_po', label: 'Not in PO' },
  { key: 'extra', label: 'Report only' },
  { key: 'all', label: 'All lines' },
]

/** Open on the exposure if there is any, then on what needs a look, else everything. */
function openingFilter(lines: LineResult[]): LineFilter {
  if (filterLines(lines, 'over').length) return 'over'
  if (filterLines(lines, 'check').length) return 'check'
  return 'all'
}

/**
 * One invoice reconciled against its PO and the site report — the content of
 * the reconciliation card (ReconCard), laid out like the bill card: a header
 * with the case number, vendor and actions, then a scrolling body. Approver-
 * first: fixed, labelled sections — documents, totals, checks, lines,
 * approvals, sources — with nothing hidden except each line's own detail.
 */
export default function ReconCaseView({ caseId, notify, onClose }: {
  caseId: string; notify: (msg: string, type?: 'error' | 'info') => void; onClose: () => void
}) {
  const [c, setC] = useState<ReconCase | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [filter, setFilter] = useState<LineFilter | null>(null)
  const [open, setOpen] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [matching, setMatching] = useState<LineResult | null>(null)
  const [correcting, setCorrecting] = useState<LineResult | null>(null)
  const [acking, setAcking] = useState(false)
  /** Step 1 shows what was read from each document; step 2 the reconciliation built from it. */
  const [detaching, setDetaching] = useState<ReconCase['attached'][number] | null>(null)
  // The reconciliation is what somebody came for. Landing on "Documents read"
  // put a click between them and the answer, every time.
  const [step, setStep] = useState<'docs' | 'recon'>('recon')

  const load = useCallback(async () => {
    try { setC(await fetchReconCase(caseId)); setError(null) } catch (e) {
      setError(axios.isAxiosError(e) ? (e.response?.data?.detail ?? 'Could not load this case') : 'Could not load this case')
    }
  }, [caseId])
  useEffect(() => { load() }, [load])

  async function run<T>(fn: () => Promise<T>, done?: string): Promise<void> {
    setBusy(true)
    try {
      const r = await fn()
      if (r && typeof r === 'object' && 'summary' in (r as object)) setC(r as unknown as ReconCase)
      else await load()
      if (done) notify(done, 'info')
    } catch (e) {
      notify(axios.isAxiosError(e) ? (e.response?.data?.detail ?? 'That didn’t work') : 'That didn’t work', 'error')
    } finally { setBusy(false) }
  }

  // Until the reviewer picks a chip, the view opens where their attention belongs.
  const shown: LineFilter = filter ?? (c ? openingFilter(c.lines) : 'all')
  const lines = useMemo(() => (c ? filterLines(c.lines, shown) : []), [c, shown])
  const poLines = useMemo(() => (c ? c.lines.filter(l => l.kind === 'po' && l.po_key) : []), [c])

  const close = <button className="rk__close" onClick={onClose} aria-label="Close"><X size={18} /></button>
  if (error || !c) {
    return (
      <div className="rk__card rc">
        <header className="rk__hdr"><div className="vc__grow"><div className="rk__title">Reconciliation</div></div>{close}</header>
        <div className="rk__body">{error
          ? <div className="vc__err vc__err--inline">{error}</div>
          : <div className="vc__muted vc__xs rc__pad"><Loader2 size={14} className="rc__spin" /> Loading…</div>}</div>
      </div>
    )
  }

  const s = c.summary
  const openBlockers = c.lines.filter(l => !l.reviewed && (l.severity === 'BLOCKER' || (l.needs_review_cell && l.severity !== 'INFO'))).length
  const failed = c.header.filter(h => !h.passed)
  const passed = c.header.filter(h => h.passed)

  return (
    <div className="rk__card rc">
      <header className="rk__hdr">
        <div className="vc__grow vc__min0">
          <div className="rk__chips"><CaseStatusChip status={s.status} /><Flags counts={s.counts} />
            {s.acknowledged_by && <span className="vc__muted vc__xs">Acknowledged by {s.acknowledged_by}</span>}</div>
          <div className="rk__title">{s.invoice_no ? `Invoice ${s.invoice_no}` : 'Waiting for the invoice'}</div>
          <div className="rk__sub">
            {s.ref && (
              <button className="rk__id" title="Copy a link to this reconciliation"
                onClick={() => navigator.clipboard?.writeText(window.location.href).then(() => notify('Link copied', 'info'), () => {})}>
                {s.ref}<Link2 size={12} />
              </button>
            )}
            {s.supplier_id && <VendorLink supplierId={s.supplier_id} className="rk__vendor" title="Open vendor">{s.vendor_name ?? 'Vendor'}</VendorLink>}
            <span className="rk__meta">{[s.po_number ? `PO ${s.po_number}` : 'No PO yet', s.store_sn ? `Store ${s.store_sn}` : null].filter(Boolean).join(' · ')}</span>
          </div>
        </div>
        <div className="rk__acts">
          {/* A way back out. This card opens over the Recon folder, and until
              now the only exit was the close cross — so the dashboard and the
              other documents were reachable only by guessing that. */}
          <button className="vc__btn vc__btn--sm" onClick={onClose}
            title="Back to the reconciliation dashboard and every document on this vendor">
            <LayoutDashboard size={14} /><span className="rk__btn-text">Dashboard</span></button>
          <button className="vc__btn vc__btn--sm" disabled={busy}
            onClick={() => downloadAuthed(reconExportPath(caseId), `recon-${(s.ref ?? s.invoice_no ?? caseId).replace(/\//g, '-')}.xlsx`).catch(() => notify('Export failed', 'error'))}>
            <Download size={14} /><span className="rk__btn-text">Export</span></button>
          <button className="vc__btn vc__btn--sm" disabled={busy} onClick={() => run(() => rerunCase(caseId), 'Re-checked')}><RefreshCw size={14} /><span className="rk__btn-text">Re-run</span></button>
          <button className="vc__btn vc__btn--primary vc__btn--sm" disabled={busy || s.status === 'ACKNOWLEDGED'} onClick={() => setAcking(true)}
            title={openBlockers ? `${openBlockers} blocker line(s) still open` : 'Mark this reconciliation as checked'}><ShieldCheck size={14} />Acknowledge</button>
          {close}
        </div>
      </header>

      <div className="rk__body">

      <div className="vc__seg rc__steps" role="tablist" aria-label="Step">
        <button role="tab" aria-selected={step === 'docs'} className={step === 'docs' ? 'on' : undefined} onClick={() => setStep('docs')}>1 · Documents read</button>
        <button role="tab" aria-selected={step === 'recon'} className={step === 'recon' ? 'on' : undefined} onClick={() => setStep('recon')}>2 · Reconciliation</button>
      </div>

      {step === 'docs' && <CaseDocuments key={s.computed_at ?? ''} caseId={caseId} title={`${s.invoice_no ?? 'Waiting for invoice'} · ${s.po_number ?? 'no PO yet'}`} onReconcile={() => setStep('recon')} />}

      {step === 'recon' && <>
      <PayVerdict s={s} onShowFlagged={() => setFilter('over')} />

      {(s.rollup_lines?.length ?? 0) > 0 && (
        /* Said out loud, not quietly dropped. Two section headings on this
           invoice carry the subtotal of the lines beneath them; counting both
           levels bills the work twice, and on IS-HO-26-27-120 that was the
           entire ₹7,49,170.79 "exposure". */
        <p className="rc__tablenote rc__rollup">
          {s.rollup_lines!.length === 1 ? 'One line is' : `${s.rollup_lines!.length} lines are`} a
          section heading carrying the subtotal of the lines below —{' '}
          {s.rollup_lines!.map(r => `${r.description} ₹${inr(r.amount)}`).join('; ')}.
          {' '}Not billed again here; the work is charged on the detail lines.
        </p>
      )}

      <section className="rc__totals" aria-label="Totals">
        <Total label="PO value" v={s.po_total} />
        <Total label="Supported" v={s.expected_total} hint="What the PO and the site report back" />
        <Total label="Billed" v={s.billed_total} />
        <Total label="Over-billed" v={s.money_at_risk} tone={Number(s.money_at_risk) > 0 ? 'bad' : undefined} hint="Billed above what is supported — your exposure" />
        <Total label="Under-billed" v={s.under_billed} hint="Supported but not billed — the vendor's loss" />
      </section>

      {/* The four questions a reviewer actually answers — ordered, received,
          verified, paid — come first. The dense per-line table below is still
          here for anyone who needs it, but it is no longer the first thing
          anybody meets. */}
      <CaseVitals s={s} lines={c.lines} attached={c.attached} />

      <section className="rc__sec" aria-label="Four-way">
        <div className="vc__subhead">This invoice against each document</div>
        <FourWay caseId={caseId} cover={s.leg_cover} />
      </section>

      <section className="rc__sec" aria-label="Checks">
        <div className="vc__subhead">Checks</div>
        <div className="vc__box rc__checks">
          {failed.map(h => {
            // A check that asked for a judgement needs somewhere to give it.
            // `confirmable` carries exactly what the reviewer is looking at, and
            // goes back with the answer so a re-read of the document asks again
            // rather than coasting on a yes about other words.
            const asked = typeof h.evidence?.confirmable === 'string' ? h.evidence.confirmable : null
            return (
              <div key={h.code} className="rc__check">
                <span className={`vc__chip vc__chip--${SEVERITY_TONE[h.severity]} vc__chip--xs`}>{h.severity === 'BLOCKER' ? 'Blocker' : h.severity === 'REVIEW' ? 'Review' : 'Info'}</span>
                <span className="vc__strong">{h.label}</span><span className="vc__muted vc__xs">{h.detail}</span>
                {asked && (
                  <button type="button" className="vc__btn vc__btn--sm rc__check-act" disabled={busy}
                    onClick={() => run(() => confirmCheck(caseId, h.code, asked), 'Confirmed')}>
                    Yes, confirm
                  </button>
                )}
              </div>
            )
          })}
          {passed.length > 0 && (
            <div className="rc__check rc__check--ok"><Check size={13} className="vc__okc" /><span className="vc__xs">{passed.map(h => h.label).join(' · ')}</span></div>
          )}
        </div>
      </section>

      {/* Demoted, not deleted. The four cards answer the usual questions; this
          table is what you open when the answer is not enough — so it starts
          closed rather than filling the screen. */}
      {/* Open. It was demoted when the four cards were new and the table was
          the only thing on the screen; since then every request has been for
          the line-by-line view, so that judgement was wrong. */}
      <details className="rc__sec rc__linesdetail" open>
        <summary className="vc__subhead rc__linessummary">
          Every line, side by side ({c.lines.length})
        </summary>
      <section aria-label="Lines">
        <div className="rc__lineshead">
          <div className="vc__subhead vc__sr-only">Lines</div>
          <div className="rc__filters" role="tablist">
            {FILTERS.map(f => {
              const n = filterLines(c.lines, f.key).length
              // An empty group is not worth a chip; "All lines" always stays.
              if (!n && f.key !== 'all') return null
              const money = filterMoney(c.lines, f.key)
              return (
                <button key={f.key} role="tab" aria-selected={shown === f.key}
                  className={`vc__fchip${shown === f.key ? ' on' : ''}${f.tone ? ` vc__fchip--${f.tone}` : ''}`}
                  onClick={() => setFilter(f.key)}>
                  {f.label} {n}
                  {money !== null && <span className="vc__fchip-m">₹{inr(money)}</span>}
                </button>
              )
            })}
          </div>
        </div>
        <div className="rc__scroll">
          <table className="rc__table rc__table--lines rc__srctable">
            {/* One colour per source, the same as in the document viewer: PO, site audit, invoice, then the result. */}
            <thead>
              <tr className="rc__group">
                <th rowSpan={2} className="rc__sticky rc__group-item">Item (as on PO)</th>
                <th rowSpan={2} className="rc__group-item">Unit</th>
                <th colSpan={2} className="rc__src rc__src--po rc__src-start"><span className="rc__src-dot" />PO</th>
                <th colSpan={3} className="rc__src rc__src--evidence rc__src-start"><span className="rc__src-dot" />Site audit</th>
                <th colSpan={2} className="rc__src rc__src--pod rc__src-start"><span className="rc__src-dot" />Goods receipt</th>
                <th colSpan={3} className="rc__src rc__src--invoice rc__src-start"><span className="rc__src-dot" />Invoice</th>
                <th colSpan={4} className="rc__src rc__src--result rc__src-start"><span className="rc__src-dot" />Result</th>
              </tr>
              <tr>
                <th className="rc__src rc__src--po rc__src-start rc__num">Qty</th><th className="rc__src rc__src--po rc__num">Rate</th>
                <th className="rc__src rc__src--evidence rc__src-start rc__num">Verified</th>
                {/* Most of these reports price the work as well as count it, and
                    the rate was being read and thrown away. Where a report
                    prints a discounted rate that is the one shown: it is the
                    rate the parties settled on. */}
                <th className="rc__src rc__src--evidence rc__num" title="The rate on the site report, after the discount where it prints one. The PO remains what is payable.">Rate</th>
                <th className="rc__src rc__src--evidence rc__num" title="The certified quantity at the report's own rate.">Value ₹</th>
                <th className="rc__src rc__src--pod rc__src-start rc__num" title="What the goods receipt says arrived. From a Dynamics GRN this is per line; from a delivery proof only when the bill has one line, since a proof counts packages, not items.">Received</th>
                {/* The receipt leg in money, beside the quantity. A reviewer
                    reconciling against the proof is comparing values, and the
                    figure was already being used — it was simply not shown. */}
                <th className="rc__src rc__src--pod rc__num" title="What the receipt is worth. From a Dynamics GRN this is the booked value, which excludes tax; from a delivery proof it is the carrier's declared consignment value, which includes it.">Value ₹</th>
                <th className="rc__src rc__src--invoice rc__src-start rc__num">Qty</th><th className="rc__src rc__src--invoice rc__num">Rate</th>
                <th className="rc__src rc__src--invoice rc__num">Amount</th>
                <th className="rc__src rc__src--result rc__src-start rc__num">Expected ₹</th><th className="rc__src rc__src--result rc__num">Δ ₹</th>
                <th className="rc__src rc__src--result">Status</th>
                {/* Every number on a row is only as good as the pairing that put
                    the two documents side by side. A 62% match means the
                    difference beside it may be between two unrelated items —
                    computed all along, shown nowhere. */}
                <th className="rc__src rc__src--result" title="How this line was paired with its counterpart, and how sure that pairing is.">Match</th>
              </tr>
            </thead>
            <tbody>
              {lines.length === 0 && <tr><td colSpan={12} className="vc__muted vc__xs rc__pad">Nothing here.</td></tr>}
              {lines.map(l => {
                const ps = primaryStatus(l)
                const isOpen = open === l.id
                const d = Number(l.delta)
                return (
                  <Fragment key={l.id}>
                    <tr className={`rc__click${isOpen ? ' is-open' : ''}${l.reviewed ? ' is-reviewed' : ''}`} onClick={() => setOpen(isOpen ? null : l.id)}>
                      <td className="rc__sticky rc__item">{isOpen ? <ChevronDown size={13} /> : <ChevronRight size={13} />}<span>{l.description}</span></td>
                      <td>{l.unit ?? '—'}</td>
                      <td className={`rc__src rc__src--po rc__src-start rc__num${has(l, 'OVER_PO') ? ' rc__diff' : ''}`}>{qty(l.po_qty)}</td>
                      <td className={`rc__src rc__src--po rc__num${has(l, 'RATE_HIGHER', 'RATE_LOWER') ? ' rc__diff' : ''}`}>{inr(l.po_rate)}</td>
                      <td className={`rc__src rc__src--evidence rc__src-start rc__num${l.needs_review_cell ? ' rc__cell-check' : ''}${has(l, 'OVER_VERIFIED', 'NOT_DONE', 'UNDER_USED') ? ' rc__diff' : ''}`}>{qty(l.verified_qty)}</td>
                      {/* A rate against nothing verified is the report pricing a
                          line the auditor then found undone. Muted, like the
                          invoice's own rate-with-no-quantity, so it reads as
                          what it is rather than as a stray number. */}
                      <td className={`rc__src rc__src--evidence rc__num${Number(l.verified_qty) === 0 ? ' vc__muted' : ''}`}
                        title={Number(l.verified_qty) === 0 && l.verified_rate != null
                          ? 'The site report prices this line, but the auditor certified none of it, so the site supports nothing for it.'
                          : undefined}>{inr(l.verified_rate)}</td>
                      <td className="rc__src rc__src--evidence rc__num">{inr(l.verified_amt)}</td>
                      {/* A figure read from a GRN and one derived from a
                          single-line consignment are not the same evidence, so
                          the derived one is marked rather than passed off. */}
                      <td className={`rc__src rc__src--pod rc__src-start rc__num${l.receipt_basis === 'single_line_consignment' ? ' rc__derived' : ''}`}
                        title={l.received_qty == null
                          ? 'No per-line goods receipt. A delivery proof confirms the consignment and its value for the whole invoice, not quantities per item.'
                          : l.receipt_basis === 'single_line_consignment'
                            ? 'From the delivery proof. This bill has one line, so the whole consignment arrived against it — the quantity is the invoice’s, not a figure read off the proof.'
                            : undefined}>{qty(l.received_qty)}</td>
                      <td className={`rc__src rc__src--pod rc__num${l.receipt_basis === 'single_line_consignment' ? ' rc__derived' : ''}`}
                        title={l.receipt_basis === 'single_line_consignment'
                          ? 'The carrier’s declared consignment value, which includes tax.'
                          : l.received_amt != null ? 'Booked on the Dynamics GRN, excluding tax.' : undefined}>
                        {inr(l.received_amt)}
                      </td>
                      <td className={`rc__src rc__src--invoice rc__src-start rc__num${has(l, 'OVER_PO', 'OVER_VERIFIED', 'UNDER_BILLED') ? ' rc__diff' : ''}`}>{qty(l.billed_qty)}</td>
                      {/* A rate with no quantity reads as a bug and is not one:
                          the vendor listed the item, priced it and billed none
                          of it. Muted and explained, so nobody chases it. */}
                      <td className={`rc__src rc__src--invoice rc__num${has(l, 'RATE_HIGHER', 'RATE_LOWER') ? ' rc__diff' : ''}${Number(l.billed_qty) === 0 && Number(l.billed_amt) === 0 ? ' vc__muted' : ''}`}
                        title={Number(l.billed_qty) === 0 && Number(l.billed_amt) === 0
                          ? 'The invoice lists this item at this rate but bills no quantity, so nothing is charged for it.'
                          : undefined}>{inr(l.billed_rate)}</td>
                      <td className="rc__src rc__src--invoice rc__num">{inr(l.billed_amt)}</td>
                      <td className="rc__src rc__src--result rc__src-start rc__num">{inr(l.expected_amt)}</td>
                      <td className={`rc__src rc__src--result rc__num${d > 0 && l.severity !== 'INFO' && l.severity !== 'OK' ? ' vc__bad' : d < 0 ? ' vc__muted' : ''}`}>{d === 0 ? '—' : inr(l.delta)}</td>
                      <td className="rc__src rc__src--result"><span className={`vc__chip vc__chip--${SEVERITY_TONE[l.severity]} vc__chip--xs`}>{STATUS_LABEL[ps]}</span>{l.reviewed && <Check size={12} className="vc__okc" aria-label="Reviewed" />}</td>
                      <td className="rc__src rc__src--result">{(() => {
                        const m = matchBadge(l)
                        return m ? (
                          <span className={`vc__chip vc__chip--${m.tone} vc__chip--xs`}
                            title={m.pct === null ? `${m.label} match — nothing to qualify` : `${m.label} · ${m.pct}% confident`}>
                            {m.label}{m.pct !== null && <span className="rc__matchpct">{m.pct}%</span>}
                          </span>
                        ) : <span className="vc__muted vc__xs">—</span>
                      })()}</td>
                    </tr>
                    {isOpen && (
                      <tr className="rc__detail"><td colSpan={15}>
                        <LineDetail line={l} busy={busy}
                          onMatch={() => setMatching(l)} onCorrect={() => setCorrecting(l)}
                          onReview={note => run(() => reviewLine(l.id, note), 'Marked reviewed')} />
                      </td></tr>
                    )}
                  </Fragment>
                )
              })}
            </tbody>
          </table>
        </div>
        {s.docs?.pod && c.lines.some(l => l.receipt_basis === 'single_line_consignment') && (
          <p className="rc__tablenote">
            Goods receipt comes from the delivery proof: this bill has one line, so the whole
            consignment arrived against it. Load the Dynamics GRN for a receipt read line by line.
          </p>
        )}
        {s.docs?.pod && c.lines.some(l => l.received_qty == null) && (
          <p className="rc__tablenote">
            Goods receipt is blank per line because this invoice's receipt evidence is a delivery
            proof: it confirms the consignment and its value for the invoice as a whole, not
            quantities per item. Load the Dynamics GRN for line-level receipt.
          </p>
        )}
      </section>
      </details>

      {c.approvals.length > 0 && (
        <section className="rc__sec" aria-label="Approvals">
          <div className="vc__subhead">Approvals{c.approvals[0].memo_ref ? ` · ${c.approvals[0].memo_ref}` : ''}</div>
          <div className="vc__box">
            {c.approvals.map((a, i) => (
              <div key={i} className="vc__docrow">
                <span className={`vc__chip vc__chip--${a.status.toLowerCase() === 'approved' ? 'ok' : 'warn'} vc__chip--xs`}>{a.status}</span>
                <span className="vc__strong">{a.approver}</span><span className="vc__muted vc__xs">{a.date ?? ''}</span>
                {a.remark && <span className="vc__xs">“{a.remark}”</span>}
              </div>
            ))}
          </div>
        </section>
      )}

      <section className="rc__sec" aria-label="Sources">
        <div className="vc__subhead">Sources</div>
        <div className="vc__box">
          {c.attached.map(a => (
            <div key={a.id} className="vc__docrow">
              <span className="vc__chip vc__chip--plain vc__chip--xs">{KIND_LABEL[a.kind] ?? a.kind}</span>
              <div className="vc__grow vc__min0">
                <div className="vc__ellipsis">{a.file_name}</div>
                <div className="vc__muted vc__xs">{a.summary ?? ''} · page{a.pages.length > 1 ? 's' : ''} {a.pages.length > 1 ? `${a.pages[0]}–${a.pages[a.pages.length - 1]}` : a.pages[0]}{a.link_method === 'user' ? ' · linked by hand' : ''}</div>
              </div>
              <button className="vc__iconbtn vc__iconbtn--sm" aria-label="Detach from this invoice" title="Detach from this invoice" disabled={busy}
                onClick={() => setDetaching(a)}><Unlink size={14} /></button>
            </div>
          ))}
        </div>
      </section>

      {/* What used to stand here was the activity log — "recomputed · loop",
          "EDGES REBUILT · system", over and over. It said a recompute
          happened and never what the recompute concluded; nobody reviewing an
          invoice has a question it answers. The linkage does: this is how the
          documents are actually tied together, and where that is thin. */}
      <section className="rc__sec" aria-label="How these documents are linked">
        <div className="vc__subhead">How these documents are linked</div>
        <ReconGraph caseId={caseId} />
      </section>

      {c.events.length > 0 && (
        /* Kept, because "who re-ran this and when" is a real question when
           something looks wrong — just not the headline it had become. */
        <details className="rc__sec">
          <summary className="vc__subhead rc__linessummary">Activity ({c.events.length})</summary>
          <ul className="rc__events">
            {c.events.slice(0, 15).map((e, i) => <li key={i} className="vc__xs"><span className="vc__muted">{new Date(e.at).toLocaleString('en-IN')}</span> · {e.kind.replace(/_/g, ' ')}{e.actor ? ` · ${e.actor}` : ''}</li>)}
          </ul>
        </details>
      )}

      </>}

      {matching && (
        <MatchDialog line={matching} poLines={poLines} onClose={() => setMatching(null)}
          onPick={async key => {
            const other = matching.invoice_key ?? matching.evidence_key
            setMatching(null)
            if (other) await run(() => overrideMatch(caseId, other, key), key ? 'Matched. We’ll remember this for this vendor.' : 'Marked as not in this PO')
          }} />
      )}
      {correcting && (
        <CorrectDialog line={correcting} onClose={() => setCorrecting(null)}
          onSave={async patch => {
            const id = evidenceRowId(correcting.evidence_key)
            setCorrecting(null)
            if (id) await run(() => correctEvidence(id, patch), 'Reading corrected')
          }} />
      )}
      {detaching && (
        <Modal title="Detach this document?" onClose={() => setDetaching(null)}>
          <div className="vc__xs rc__pad">
            <span className="vc__strong">{KIND_LABEL[detaching.kind] ?? detaching.kind}</span> · {detaching.file_name}{detaching.summary ? ` · ${detaching.summary}` : ''}
            <p className="vc__muted">This invoice will be reconciled without it.{detaching.kind === 'PURCHASE_ORDER'
              ? ' Without the PO nothing on the invoice can be checked, so every line shows as at risk.' : ''} You can link it again from Recon → Files.</p>
          </div>
          <div className="rc__modal-f">
            <button className="vc__btn vc__btn--sm" onClick={() => setDetaching(null)}>Keep it</button>
            <button className="vc__btn vc__btn--primary vc__btn--sm" disabled={busy}
              onClick={async () => { const a = detaching; setDetaching(null); await run(() => detachSegment(caseId, a.id), 'Detached') }}>
              <Unlink size={14} />Detach</button>
          </div>
        </Modal>
      )}
      {acking && (
        <AckDialog openBlockers={openBlockers} onClose={() => setAcking(false)}
          onAck={async note => { setAcking(false); await run(() => acknowledgeCase(caseId, note, openBlockers > 0), 'Acknowledged') }} />
      )}
      </div>
    </div>
  )
}

/** Whether a line carries any of these statuses — marks the cell that differs. */
const has = (l: LineResult, ...st: LineResult['statuses']) => st.some(x => l.statuses.includes(x))

function Total({ label, v, tone, hint }: { label: string; v: string | null; tone?: 'bad'; hint?: string }) {
  return (
    <div className="rc__total" title={hint}>
      <div className="vc__muted vc__xs">{label}</div>
      <div className={`rc__total-v${tone === 'bad' ? ' vc__bad' : ''}`}>{v === null || v === undefined ? '—' : `₹${inr(v)}`}</div>
    </div>
  )
}

function LineDetail({ line: l, busy, onMatch, onCorrect, onReview }: {
  line: LineResult; busy: boolean; onMatch: () => void; onCorrect: () => void; onReview: (note: string) => void
}) {
  const [note, setNote] = useState('')
  const others = l.statuses.filter(s => s !== primaryStatus(l) && s !== 'MATCHED')
  return (
    <div className="rc__ld">
      <div className="rc__words">
        <Word label="PO" text={l.kind === 'po' ? l.description : null} />
        <Word label="Invoice" text={l.invoice_text} />
        <Word label="Site report" text={l.evidence_text} />
      </div>
      {l.conflicts.length > 0 && <div className="rc__ld-row"><span className="vc__chip vc__chip--warn vc__chip--xs">Differs</span><span className="vc__xs">{l.conflicts.join(' · ')}</span></div>}
      {l.remark && <div className="rc__ld-row"><span className="vc__muted vc__xs">Auditor:</span><span className="vc__xs">{l.remark}</span></div>}
      {l.vendor_qty !== null && l.vendor_qty !== undefined && <div className="rc__ld-row vc__xs"><span className="vc__muted">Vendor claimed on site:</span> {qty(l.vendor_qty)}</div>}
      {others.length > 0 && <div className="rc__ld-row vc__xs"><span className="vc__muted">Also:</span> {others.map(s => STATUS_LABEL[s]).join(' · ')}</div>}
      <div className="rc__ld-row vc__xs"><span className="vc__muted">Match:</span> {MATCH_LABEL[l.match_method] ?? l.match_method}{l.match_score ? ` (${Math.round(l.match_score * 100)}%)` : ''}</div>
      {l.reviewed && <div className="rc__ld-row vc__xs"><Check size={12} className="vc__okc" /> Reviewed by {l.reviewed.by}{l.reviewed.note ? `: ${l.reviewed.note}` : ''}</div>}
      {l.needs_review_cell && <EvidenceCrop line={l} />}
      <div className="rc__ld-acts">
        {(l.invoice_key || l.evidence_key) && <button className="vc__btn vc__btn--sm" disabled={busy} onClick={onMatch}>Change match</button>}
        {evidenceRowId(l.evidence_key) && <button className="vc__btn vc__btn--sm" disabled={busy} onClick={onCorrect}>Correct reading</button>}
        {!l.reviewed && (l.severity === 'BLOCKER' || l.severity === 'REVIEW') && (
          <span className="rc__review">
            <input className="vc__field" placeholder="Note (optional)" value={note} onChange={e => setNote(e.target.value)} aria-label="Review note" />
            <button className="vc__btn vc__btn--sm" disabled={busy} onClick={() => onReview(note)}><Check size={14} />Mark reviewed</button>
          </span>
        )}
      </div>
    </div>
  )
}

function Word({ label, text }: { label: string; text: string | null }) {
  return <div className="rc__word"><div className="vc__muted vc__xs">{label}</div><div className="vc__xs">{text ?? <span className="vc__muted">—</span>}</div></div>
}

function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  // The shared trap: Tab stays inside, and Escape closes this dialog only — not the card beneath it.
  const box = useRef<HTMLDivElement>(null)
  useFocusTrap(box, true, onClose)
  // Portalled to <body> so it covers the screen wherever the case is shown.
  return createPortal(
    <div className="rc__dlg" onClick={onClose}>
      <div ref={box} className="rc__modal" role="dialog" aria-modal="true" aria-label={title} onClick={e => e.stopPropagation()}>
        <div className="rc__modal-h"><div className="vc__strong">{title}</div><button className="vc__iconbtn vc__iconbtn--sm" aria-label="Close" onClick={onClose}><X size={14} /></button></div>
        {children}
      </div>
    </div>,
    document.body,
  )
}

function MatchDialog({ line, poLines, onClose, onPick }: {
  line: LineResult; poLines: LineResult[]; onClose: () => void; onPick: (poLineKey: string | null) => void
}) {
  const [q, setQ] = useState('')
  const shown = poLines.filter(p => p.description.toLowerCase().includes(q.toLowerCase())).slice(0, 60)
  return (
    <Modal title="Which PO line is this?" onClose={onClose}>
      <div className="vc__xs rc__pad">“{line.invoice_text ?? line.evidence_text}”{line.billed_rate ? ` · rate ${inr(line.billed_rate)}` : ''}</div>
      <input className="vc__field" autoFocus placeholder="Search PO lines" value={q} onChange={e => setQ(e.target.value)} aria-label="Search PO lines" />
      <div className="rc__picklist">
        {shown.map(p => (
          <button key={p.po_key} className="rc__pick" onClick={() => onPick(p.po_key)}>
            <span className="vc__grow vc__min0 vc__ellipsis">{p.description}</span>
            <span className="vc__muted vc__xs">{p.unit ?? ''} · {inr(p.po_rate)}</span>
          </button>
        ))}
      </div>
      <div className="rc__modal-f">
        <span className="vc__muted vc__xs">We’ll remember this for future invoices from this vendor.</span>
        <button className="vc__btn vc__btn--sm" onClick={() => onPick(null)}>Not in this PO</button>
      </div>
    </Modal>
  )
}

function CorrectDialog({ line, onClose, onSave }: {
  line: LineResult; onClose: () => void
  onSave: (p: Partial<{ audit_qty: string | null; verdict: string }>) => void
}) {
  const [val, setVal] = useState(line.verified_qty ?? '')
  const [verdict, setVerdict] = useState<string>('VERIFIED')
  return (
    <Modal title="Check the auditor’s number" onClose={onClose}>
      <div className="vc__xs rc__pad">{line.evidence_text ?? line.description}</div>
      <EvidenceCrop line={line} />
      <label className="rc__lbl vc__xs">What the auditor wrote
        <input className="vc__field" inputMode="decimal" value={val} onChange={e => setVal(e.target.value)} disabled={verdict !== 'VERIFIED'} />
      </label>
      <label className="rc__lbl vc__xs">Meaning
        <select className="vc__field" value={verdict} onChange={e => setVerdict(e.target.value)}>
          <option value="VERIFIED">Counted on site</option>
          <option value="NOT_DONE">Not done / not installed</option>
          <option value="NOT_COVERED">Not covered by the audit</option>
          <option value="NOT_COUNTABLE">Not countable (in scope per Bata)</option>
        </select>
      </label>
      <div className="rc__modal-f">
        <span className="vc__muted vc__xs">The machine reading is kept in the history.</span>
        <button className="vc__btn vc__btn--primary vc__btn--sm"
          onClick={() => onSave(verdict === 'VERIFIED' ? { audit_qty: val, verdict } : { verdict })}>Save</button>
      </div>
    </Modal>
  )
}

/** The page region the number was read from — via the authenticated crop endpoint, never a public link. */
function EvidenceCrop({ line }: { line: LineResult }) {
  const loc = line.evidence_crop
  const { url, loading, error } = useAuthedObjectUrl(loc ? evidenceCropPath(loc.segment_id, loc.page, loc.bbox) : null)
  if (!loc) return null
  if (loading) return <div className="rc__crop vc__muted vc__xs"><Loader2 size={14} className="rc__spin" /> Loading the page…</div>
  if (error || !url) return <div className="rc__crop vc__muted vc__xs">Couldn’t load the page image.</div>
  return <img className="rc__crop" src={url} alt="The cell on the auditor’s sheet" />
}

function AckDialog({ openBlockers, onClose, onAck }: { openBlockers: number; onClose: () => void; onAck: (note: string) => void }) {
  const [note, setNote] = useState('')
  const need = openBlockers > 0
  return (
    <Modal title="Acknowledge this reconciliation" onClose={onClose}>
      <div className="vc__xs rc__pad">{need
        ? `${openBlockers} blocker line(s) or handwritten reading(s) are still open. Only an admin or approver can acknowledge now, with a note.`
        : 'Records that you checked this invoice against its PO and the site report.'}</div>
      <textarea className="vc__field rc__note" placeholder={need ? 'Why it’s fine to proceed' : 'Note (optional)'} value={note} onChange={e => setNote(e.target.value)} aria-label="Acknowledgement note" />
      <div className="rc__modal-f">
        <span />
        <button className="vc__btn vc__btn--primary vc__btn--sm" disabled={need && !note.trim()} onClick={() => onAck(note)}><ShieldCheck size={14} />Acknowledge</button>
      </div>
    </Modal>
  )
}
