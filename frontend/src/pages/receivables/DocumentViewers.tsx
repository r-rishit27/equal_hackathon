import { useCallback, useEffect, useRef, useState } from 'react'
import { AlertTriangle, Check, Download, FileText } from 'lucide-react'
import { Badge, Button, ErrorState, Modal, SkeletonRows, formatDate, formatDateTime, useToast, type BadgeTone } from '../../ui'
import PdfFullscreen from '../../components/PdfFullscreen'
import { downloadAuthed } from '../../api/authedFiles'
import {
  apiError, fetchRemittance, fetchStatement, remittanceDocumentUrl, statementDocumentUrl,
  type RemittanceDetail, type StatementDetail, type StatementLineOutcome,
} from '../../api/receivables'
import { PaymentStatusBadge } from './badges'
import { money } from './format'

const OUTCOME: Record<StatementLineOutcome, [string, BadgeTone]> = {
  new: ['Receipt', 'info'],
  duplicate: ['Already imported', 'neutral'],
  set_aside: ['Not a receipt', 'neutral'],
  bounce: ['Bounce of an earlier receipt', 'danger'],
  debit: ['Debit', 'neutral'],
  ignored: ['—', 'neutral'],
}

/**
 * A bank statement as it was imported: every line, what it became, and each
 * payment's status now. The original file opens alongside (PDF) or downloads
 * (CSV / XLSX) — from the authenticated route, never a public link.
 */
export function StatementViewer({ id, onClose, onOpenPayment, focusPaymentId }: {
  id: string | null
  onClose: () => void
  onOpenPayment: (paymentId: string) => void
  /** Opened from a payment: its line is scrolled to the middle and highlighted. */
  focusPaymentId?: string | null
}) {
  const toast = useToast()
  const [s, setS] = useState<StatementDetail | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [pdf, setPdf] = useState(false)
  const load = useCallback(async () => {
    if (!id) return
    setErr(null)
    try { setS(await fetchStatement(id)) } catch (e) { setErr(apiError(e)) }
  }, [id])
  useEffect(() => { setS(null); void load() }, [load])

  // Glide to the payment's own line once the viewer has opened, then light it up when the scroll settles.
  const focusRef = useRef<HTMLTableRowElement>(null)
  const [lit, setLit] = useState(false)
  useEffect(() => {
    setLit(false)
    const row = focusRef.current
    if (!s || !focusPaymentId || !row) return
    const reduce = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
    const box = row.closest('.u-modal__body') as HTMLElement | null
    let done = false
    const light = () => { if (!done) { done = true; setLit(true) } }
    const start = window.setTimeout(() => {
      row.scrollIntoView({ block: 'center', behavior: reduce ? 'auto' : 'smooth' })
      if (reduce) return light()
      box?.addEventListener('scrollend', light, { once: true })
      window.setTimeout(light, 1000) // browsers without scrollend, or nothing to scroll
    }, 220) // after the viewer's own opening
    return () => { window.clearTimeout(start); box?.removeEventListener('scrollend', light); done = true }
  }, [s, focusPaymentId])

  const original = async () => {
    if (!s) return
    if (s.file_format === 'pdf') return setPdf(true)
    try { await downloadAuthed(statementDocumentUrl(s.id), s.file_name) } catch (e) { toast.error('Download failed', apiError(e)) }
  }

  return (
    <Modal open={!!id} onClose={onClose} size="xl" title={s?.file_name ?? 'Bank statement'}
      description={s ? `${s.bank_account ?? 'Account not stated'} · ${formatDate(s.period_from)} – ${formatDate(s.period_to)} · imported ${formatDateTime(s.created_at)}${s.uploaded_by ? ` by ${s.uploaded_by}` : ''}` : undefined}
      footer={s?.has_document && (
        <Button variant="secondary" iconLeft={s.file_format === 'pdf' ? <FileText size={14} /> : <Download size={14} />} onClick={original}>
          {s.file_format === 'pdf' ? 'View original PDF' : `Download original ${s.file_format.toUpperCase()}`}
        </Button>
      )}>
      {err && <ErrorState message={err} onRetry={load} />}
      {!s && !err && <SkeletonRows rows={8} cols={5} />}
      {s && (
        <div className="ar-wb">
          <div className="ar-result">
            <Stat k="Credits read" v={s.credits} />
            <Stat k="New receipts" v={s.imported} />
            <Stat k="Already imported" v={s.duplicates} />
            <Stat k="Not receipts" v={s.set_aside} />
            {s.bounces > 0 && <Stat k="Bounces" v={s.bounces} />}
          </div>
          <div className="ar-alloc-wrap">
            <table className="ar-alloc">
              <thead>
                <tr><th>#</th><th>Date</th><th>Narration</th><th>Ref / UTR</th><th className="num">Debit</th><th className="num">Credit</th><th>Read as</th><th>Now</th></tr>
              </thead>
              <tbody>
                {s.lines.map(l => {
                  const [label, tone] = OUTCOME[l.outcome] ?? [l.outcome, 'neutral']
                  const focus = !!focusPaymentId && l.payment_id === focusPaymentId
                  const clickable = !!l.payment_id && !focus
                  return (
                    <tr key={l.line} ref={focus ? focusRef : undefined} className={focus ? `ar-alloc__focus${lit ? ' is-lit' : ''}` : undefined}
                      aria-current={focus ? 'true' : undefined}
                      style={clickable ? { cursor: 'pointer' } : undefined}
                      onClick={clickable ? () => onOpenPayment(l.payment_id!) : undefined}>
                      <td className="ar-muted">{l.line + 1}</td>
                      <td>{formatDate(l.date)}</td>
                      <td className="ar-narr" title={l.narration ?? ''} style={{ maxWidth: 360 }}>{l.narration ?? '—'}</td>
                      <td className="ar-muted">{l.reference ?? '—'}</td>
                      <td className="num ar-money">{l.debit ? money(l.debit) : ''}</td>
                      <td className="num ar-money">{l.credit ? money(l.credit) : ''}</td>
                      <td><Badge tone={tone}>{label}</Badge></td>
                      <td>{focus && lit && <span className="ar-tag ar-tag--brand ar-alloc__this">This payment</span>}
                        {l.payment_status ? <PaymentStatusBadge status={l.payment_status} auto={l.auto_applied} /> : null}
                        {l.customer_name ? <span className="ar-muted"> {l.customer_name}</span> : null}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
      {pdf && s && <PdfFullscreen url={statementDocumentUrl(s.id)} name={s.file_name} onClose={() => setPdf(false)} />}
    </Modal>
  )
}

/** One remittance advice: what was read, the original (PDF or the pasted text), and the payment it explains. */
export function RemittanceViewer({ id, onClose, onOpenPayment, currentPaymentId }: {
  id: string | null
  onClose: () => void
  onOpenPayment: (paymentId: string) => void
  /** The payment already open underneath, if any — no "Open the payment" for the one you came from. */
  currentPaymentId?: string | null
}) {
  const [r, setR] = useState<RemittanceDetail | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [pdf, setPdf] = useState(false)
  const load = useCallback(async () => {
    if (!id) return
    setErr(null)
    try { setR(await fetchRemittance(id)) } catch (e) { setErr(apiError(e)) }
  }, [id])
  useEffect(() => { setR(null); void load() }, [load])

  const paise = (v: number | string | null | undefined) => Math.round(Number(v ?? 0) * 100)
  const linesSum = r ? r.lines.reduce((t, l) => t + paise(l.amount_paid), 0) : 0
  const totalOff = !!r && r.total_amount != null && r.lines.length > 0 && Math.abs(paise(r.total_amount) - linesSum) > 100
  const refOk = !!r?.payment_reference && !!r.payment_utr
    && r.payment_reference.replace(/[^A-Z0-9]/gi, '').toUpperCase() === r.payment_utr.replace(/[^A-Z0-9]/gi, '').toUpperCase()
  const showOpen = !!r?.payment_id && r.payment_id !== currentPaymentId

  return (
    <Modal open={!!id} onClose={onClose} size="lg" title={r ? `Remittance from ${r.payer_name ?? 'unknown payer'}` : 'Remittance advice'}
      description={r ? `${r.source === 'pdf' ? r.source_file ?? 'PDF' : 'Pasted email text'} · added ${formatDateTime(r.created_at)}${r.created_by ? ` by ${r.created_by}` : ''}` : undefined}
      footer={r && (showOpen || r.has_document) && (
        <div className="ar-actions" style={{ width: '100%', justifyContent: 'space-between' }}>
          <span>{showOpen && <Button variant="ghost" onClick={() => onOpenPayment(r.payment_id!)}>Open the payment</Button>}</span>
          {r.has_document && <Button variant="secondary" iconLeft={<FileText size={14} />} onClick={() => setPdf(true)}>View original PDF</Button>}
        </div>
      )}>
      {err && <ErrorState message={err} onRetry={load} />}
      {!r && !err && <SkeletonRows rows={5} cols={4} />}
      {r && (
        <div className="ar-wb">
          {/* The advice at a glance: its total, large; then when, which transfer, and the payment it explains. */}
          <div className="rv-head">
            <div className="rv-hero">
              <span className="ar-cell__k">Total on the advice</span>
              <span className={`rv-hero__amt${totalOff ? ' is-off' : ''}`}>{r.total_amount != null ? money(r.total_amount) : '—'}</span>
            </div>
            <div className="rv-facts">
              <div><span className="ar-cell__k">Payment date</span><span className="rv-v">{r.payment_date ? formatDate(r.payment_date) : '—'}</span></div>
              <div>
                <span className="ar-cell__k">Reference / UTR</span>
                <span className="rv-v rv-ref">
                  <span className="ar-mono">{r.payment_reference || '—'}</span>
                  {refOk && <span className="ar-tag ar-tag--ok" title="Same reference as the bank credit"><Check size={11} /> Matches bank UTR</span>}
                </span>
              </div>
              <div>
                <span className="ar-cell__k">Linked payment</span>
                <span className="rv-v">
                  {r.payment_id
                    ? <span className="rv-link">{money(r.payment_amount)} <span className="ar-muted">· {formatDate(r.payment_received_on)}</span>
                        {r.payment_status && <PaymentStatusBadge status={r.payment_status} />}</span>
                    : <span className="ar-muted">Not yet — links when the payment arrives</span>}
                </span>
              </div>
            </div>
          </div>

          {totalOff && (
            <div className="ar-callout ar-callout--warn" role="note">
              <AlertTriangle size={13} aria-hidden="true" />
              <span>The advice says <strong>{money(r.total_amount)}</strong>, but its lines add up to <strong>{money(linesSum / 100)}</strong>
                {r.payment_amount != null && Math.abs(linesSum - paise(r.payment_amount)) <= 100 ? ' — the amount received.' : '.'}</span>
            </div>
          )}

          <div className="ar-table-wrap">
            <table className="ar-grid">
              <thead><tr><th>Line</th><th className="num">Paid</th><th className="num">Deducted</th><th>Reason</th></tr></thead>
              <tbody>
                {r.lines.length === 0 && <tr><td colSpan={4} className="ar-muted">The advice names no invoices.</td></tr>}
                {r.lines.map((l, i) => {
                  // A negative line is a note the customer set off — a deduction, not a payment.
                  const note = l.amount_paid < 0
                  return (
                    <tr key={i}>
                      <td>
                        <span className="ar-strong">{l.invoice_number}</span>
                        {note && <div className="ar-sub">{/\bCN\b|CREDIT/i.test(`${l.invoice_number} ${l.deduction_reason ?? ''}`) ? 'Credit note' : 'Debit note'}</div>}
                      </td>
                      <td className="num ar-money">{note ? <span className="ar-muted">—</span> : money(l.amount_paid)}</td>
                      <td className="num ar-money">{note ? money(-l.amount_paid) : l.deduction_amount ? money(l.deduction_amount) : <span className="ar-muted">—</span>}</td>
                      <td>{l.deduction_reason ?? <span className="ar-muted">—</span>}</td>
                    </tr>
                  )
                })}
              </tbody>
              {r.lines.length > 1 && (
                <tfoot>
                  <tr>
                    <td>{r.lines.length} lines</td>
                    <td className="num ar-money">{money(r.lines.filter(l => l.amount_paid > 0).reduce((t, l) => t + l.amount_paid, 0))}</td>
                    <td className="num ar-money">{money(r.lines.reduce((t, l) => t + (l.amount_paid < 0 ? -l.amount_paid : l.deduction_amount || 0), 0))}</td>
                    <td className="ar-muted">Net {money(linesSum / 100)}</td>
                  </tr>
                </tfoot>
              )}
            </table>
          </div>
          {r.source === 'text' && r.raw_text && (
            <div className="ar-section">
              <div className="ar-section__title">As received</div>
              <pre className="ar-raw">{r.raw_text}</pre>
            </div>
          )}
        </div>
      )}
      {pdf && r && <PdfFullscreen url={remittanceDocumentUrl(r.id)} name={r.source_file ?? 'remittance.pdf'} onClose={() => setPdf(false)} />}
    </Modal>
  )
}

function Stat({ k, v }: { k: string; v: number }) {
  return <div className="ar-kpi"><span className="ar-kpi__label">{k}</span><span className="ar-kpi__value">{v}</span></div>
}
