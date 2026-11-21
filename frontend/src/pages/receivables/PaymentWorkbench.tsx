import { useCallback, useEffect, useId, useMemo, useRef, useState } from 'react'
import {
  AlertTriangle, Check, ChevronDown, ChevronLeft, ChevronRight, ChevronUp, CircleSlash, ExternalLink, FileText, Landmark, Mail,
  PauseCircle, Pencil, Plus, RefreshCw, Search, Sparkles, Undo2, X,
} from 'lucide-react'
import {
  Badge, Button, ConfirmDialog, Dropdown, ErrorState, IconButton, Modal, Select, SkeletonRows, Textarea, formatDate, formatDateTime,
  useToast,
} from '../../ui'
import { useAuth } from '../../auth/AuthContext'
import { arInvoicePath } from '../../routes/paths'
import { can } from '../../auth/permissions'
import {
  EXCEPTION_LABELS, FLAG_LABELS, REASON_LABELS, apiError, applyPayment, choosePaymentCustomer, fetchCustomers,
  fetchPayment, rematchPayment, setPaymentStatus, unapplyPayment,
  type AllocationIn, type ArInvoiceRow, type CustomerRow, type ExceptionCode, type PaymentDetail, type ReasonCode,
  type Remittance, type Suggestion,
} from '../../api/receivables'
import { RemittanceModal } from './CaptureModals'
import { KIND_LABELS, fromPaise, money, tidy, toPaise } from './format'
import { PaymentStatusBadge } from './badges'

interface Row {
  on: boolean
  applied: string
  tds: string
  ded: string
  code: ReasonCode | ''
  note: string
}

const EMPTY: Row = { on: false, applied: '', tds: '', ded: '', code: '', note: '' }

function rowsFrom(s: { allocations: AllocationIn[] } | null | undefined): Record<string, Row> {
  const out: Record<string, Row> = {}
  for (const a of s?.allocations ?? []) {
    out[a.invoice_id] = {
      on: true,
      applied: a.amount_applied,
      tds: Number(a.tds_amount) ? a.tds_amount : '',
      ded: Number(a.deduction_amount) ? a.deduction_amount : '',
      code: (a.reason_code ?? '') as ReasonCode | '',
      note: a.reason_note ?? '',
    }
  }
  return out
}

const sig = (rows: Record<string, Row>) =>
  JSON.stringify(Object.entries(rows).filter(([, r]) => r.on).sort(([a], [b]) => a.localeCompare(b))
    .map(([id, r]) => [id, toPaise(r.applied), toPaise(r.tds), toPaise(r.ded), r.code]))

/** Invoice / PO numbers compared without spaces, slashes or case — "INV/24-25/0012" = "inv 24 25 0012". */
const norm = (s: string | null | undefined) => (s ?? '').toUpperCase().replace(/[^A-Z0-9]/g, '')

/** Activity entries in words, not event codes. */
const EVENT_LABELS: Record<string, string> = {
  recorded: 'recorded the payment',
  matched: 'suggested a match',
  applied: 'applied it',
  unapplied: 'unapplied it',
  customer_chosen: 'set the customer',
  exception: 'moved it to follow-up',
  resolve: 'sent it back to review',
  not_receipt: 'excluded it — not a customer payment',
  restore: 'restored it as a customer payment',
  reverse: 'marked it bounced',
  possible_bounce: 'spotted a possible bounce',
}

/** A negative remittance line is a note the customer set off, not an invoice paid. */
const noteKind = (l: { invoice_number: string; deduction_reason: string | null }) => {
  const t = `${l.invoice_number} ${l.deduction_reason ?? ''}`.toUpperCase()
  return /\bCN\b|CREDIT/.test(t) ? 'Credit note' : /\bDN\b|DEBIT|^DN/.test(t) ? 'Debit note' : 'Set-off'
}

/** Labels short enough for the one-line reason under a deduction. */
const SHORT_REASON: Partial<Record<ReasonCode, string>> = { DEBIT_NOTE: 'Debit note', RATE_DIFF: 'Rate diff', FX: 'FX diff' }
const REASON_OPTIONS: { value: ReasonCode | ''; label: string }[] = [
  { value: '', label: 'Pick a reason' },
  ...(Object.keys(REASON_LABELS) as ReasonCode[]).filter(c => c !== 'TDS').map(c => ({ value: c, label: SHORT_REASON[c] ?? REASON_LABELS[c] })),
]

const typing = (t: EventTarget | null) =>
  t instanceof HTMLElement && (t.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(t.tagName))

type Basis = 'Narration' | 'PO no.' | 'Your pick'

/**
 * One payment, docked beside the list it came from, invoice by invoice: where it came from (bank statement,
 * remittance), which invoices it pays and on what evidence, and what each
 * invoice owes afterwards. Confirm, correct, follow up later, or undo — then on
 * to the next payment in the list. Applying needs accounting-approval rights,
 * the same roles that post payables.
 */
export default function PaymentWorkbench({
  paymentId, queue = [], onNavigate, onClose, onChanged, onOpenStatement, onOpenRemittance, draft = null, focusInvoiceId = null,
}: {
  paymentId: string | null
  /** Lines changed on the review board for this payment — the card starts from them instead of the agent's match. */
  draft?: AllocationIn[] | null
  /** The invoice whose line was clicked on the board: highlighted and scrolled to. */
  focusInvoiceId?: string | null
  /** The list this payment was opened from, for previous / next. */
  queue?: string[]
  onNavigate?: (paymentId: string) => void
  onClose: () => void
  onChanged: () => void
  onOpenStatement?: (statementId: string) => void
  onOpenRemittance?: (remittanceId: string) => void
}) {
  const toast = useToast()
  const { user } = useAuth()
  const canPost = !!user && can(user.role, 'payables.accounting_approval' as Parameters<typeof can>[1])
  const canCapture = !!user && can(user.role, 'payables.initiate' as Parameters<typeof can>[1])
  const [d, setD] = useState<PaymentDetail | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [rows, setRows] = useState<Record<string, Row>>({})
  const draftRef = useRef(draft)
  draftRef.current = draft
  const [chosen, setChosen] = useState<Suggestion | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [exc, setExc] = useState<{ code: ExceptionCode | ''; note: string } | null>(null)
  const [undo, setUndo] = useState<'unapply' | 'reverse' | null>(null)
  const [undoReason, setUndoReason] = useState('')
  const [allOpen, setAllOpen] = useState(false)
  const [src, setSrc] = useState<'agent' | 'bank' | 'remit' | null>(null)
  const [pickCustomer, setPickCustomer] = useState(false)
  const [addRemit, setAddRemit] = useState(false)
  const headId = useId()
  const headRef = useRef<HTMLHeadingElement>(null)
  // Content continues under the footer: show it with a soft edge instead of letting rows vanish.
  const bodyRef = useRef<HTMLDivElement>(null)
  const [moreBelow, setMoreBelow] = useState(false)
  const edge = useCallback(() => {
    const el = bodyRef.current
    if (el) setMoreBelow(el.scrollHeight - el.scrollTop - el.clientHeight > 4)
  }, [])

  const load = useCallback(async () => {
    if (!paymentId) return
    setErr(null)
    try {
      const r = await fetchPayment(paymentId)
      setD(r)
      const best = r.payment.suggestion?.best ?? null
      setChosen(best)
      setRows(rowsFrom(draftRef.current ? { allocations: draftRef.current } : best))
    } catch (e) {
      setErr(apiError(e))
    }
  }, [paymentId])

  useEffect(() => {
    setD(null); setAllOpen(false); setPickCustomer(false); setSrc(null)
    void load()
  }, [load])

  // Previous / next through the list it was opened from.
  const idx = paymentId ? queue.indexOf(paymentId) : -1
  const prevId = idx > 0 ? queue[idx - 1] : null
  const nextId = idx >= 0 && idx < queue.length - 1 ? queue[idx + 1] : null
  const go = useCallback((id: string | null) => { if (id && onNavigate) onNavigate(id) }, [onNavigate])

  useEffect(() => {
    if (!paymentId || exc || undo || addRemit) return
    const onKey = (e: KeyboardEvent) => {
      if (typing(e.target) || e.metaKey || e.ctrlKey || e.altKey || e.defaultPrevented) return
      if (document.querySelector('[aria-modal="true"]')) return // a dialog on top owns the keys
      if (e.key === 'ArrowRight' || e.key === 'j') { e.preventDefault(); go(nextId) }
      if (e.key === 'ArrowLeft' || e.key === 'k') { e.preventDefault(); go(prevId) }
      // Esc closes an open detail first, then the card.
      if (e.key === 'Escape') { e.preventDefault(); if (src) setSrc(null); else onClose() }
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [paymentId, exc, undo, addRemit, nextId, prevId, go, onClose, src])

  // A detail floats over the page (it never pushes the invoices out of view); a click outside it closes it.
  const proofRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!src) return
    const onDown = (e: MouseEvent) => {
      const t = e.target as Node
      if (proofRef.current?.contains(t) || (t as HTMLElement).closest?.('.ar-proofs, [aria-modal="true"], .u-toasts')) return
      setSrc(null)
    }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [src])

  useEffect(() => {
    edge()
    const el = bodyRef.current
    if (!el || typeof ResizeObserver === 'undefined') return
    const ro = new ResizeObserver(edge)
    ro.observe(el)
    if (el.firstElementChild) ro.observe(el.firstElementChild)
    return () => ro.disconnect()
  }, [edge, d])

  // Opened from a line on the board: bring that invoice into view.
  useEffect(() => {
    if (!d || !focusInvoiceId) return
    const t = setTimeout(() => bodyRef.current?.querySelector(`[data-inv="${focusInvoiceId}"]`)?.scrollIntoView({ block: 'nearest' }), 80)
    return () => clearTimeout(t)
  }, [d, focusInvoiceId])

  // Each payment opened moves focus to its heading, so screen readers announce it.
  useEffect(() => { if (paymentId) headRef.current?.focus({ preventScroll: true }) }, [paymentId])

  /** After a payment leaves the list, carry on with the next one — or close at the end. */
  const advance = () => {
    if (nextId && onNavigate) onNavigate(nextId)
    else { toast.success('All done in this list'); onClose() }
  }

  const p = d?.payment
  const sug = p?.suggestion ?? null
  const remaining = p ? toPaise(p.amount) - toPaise(p.applied_amount) : 0
  const open = p && ['unmatched', 'needs_review', 'partially_applied', 'exception'].includes(p.status)
  const applying = !!p && ['unmatched', 'needs_review', 'partially_applied'].includes(p.status)
  const editable = applying && canPost
  const remits = d?.remittances ?? []
  const hasRemit = remits.length > 0
  const bankRef = norm(p?.utr) || norm(p?.reference)
  /** An advice whose stated total disagrees with its own lines: worth stopping for before confirming. */
  const remitTotalOff = (r: Remittance) => {
    const lines = r.lines.reduce((t, l) => t + Math.round(l.amount_paid * 100), 0)
    return r.total_amount != null && r.lines.length > 0 && Math.abs(toPaise(r.total_amount) - lines) > 100
  }
  const offRemits = remits.filter(remitTotalOff)
  /** Advice numbers the agent corrected ("'8069…505' read as SL8069…505", typos): quoted → resolved. */
  const readAs = useMemo(() => {
    const m = new Map<string, string>()
    const sg = d?.payment.suggestion
    for (const o of [sg?.best, ...(sg?.alternatives ?? [])]) for (const c of o?.clues ?? []) {
      const hit = /^'(.+?)' (?:read as|looks like a typo for) (\S+)$/.exec(c)
      if (hit) m.set(norm(hit[1]), hit[2])
    }
    return m
  }, [d])
  const remitLines = useMemo(() => {
    const m = new Map<string, Remittance['lines'][number]>()
    for (const r of d?.remittances ?? []) for (const l of r.lines) {
      m.set(norm(l.invoice_number), l)
      const fixed = readAs.get(norm(l.invoice_number))
      if (fixed) m.set(norm(fixed), l)
    }
    return m
  }, [d, readAs])

  // Invoices offered in the editor: the customer's open ones, plus anything the
  // suggestion names that isn't among them (another customer's, for a group payment).
  const allRows: ArInvoiceRow[] = useMemo(() => {
    const inv = d?.open_invoices ?? []
    const extra = (chosen?.allocations ?? []).filter(a => !inv.some(i => i.id === a.invoice_id))
    // Oldest due first, everywhere on this screen.
    const byAge = (a: ArInvoiceRow, b: ArInvoiceRow) =>
      (a.due_date ?? '9999').localeCompare(b.due_date ?? '9999') || a.invoice_number.localeCompare(b.invoice_number)
    return [
      ...[...inv].sort(byAge),
      ...extra.map(a => ({ id: a.invoice_id, invoice_number: a.invoice_number, outstanding: '', due_date: null, status: 'open' } as unknown as ArInvoiceRow)),
    ]
  }, [d, chosen])
  /** Which invoice a set-off note was deducted on, read from the row's note ("Set off: DN/…"). */
  const setoffOn = (ref: string) => allRows.find(i => {
    const r = rows[i.id]
    return r?.on && norm(r.note).includes(norm(ref))
  })
  // What this payment pays comes first; the rest of the customer's open invoices on request.
  const picked = allRows.filter(i => rows[i.id]?.on)
  const shown = allOpen || picked.length === 0 ? allRows : picked
  const hiddenCount = allRows.length - shown.length

  const totals = useMemo(() => {
    let applied = 0, tds = 0, ded = 0, owes = 0, remit = 0, ticked = 0, open = 0
    for (const inv of allRows) {
      const r = rows[inv.id]
      if (!r?.on) continue
      ticked++
      applied += toPaise(r.applied); tds += toPaise(r.tds); ded += toPaise(r.ded); owes += toPaise(inv.outstanding)
      const after = inv.outstanding ? toPaise(inv.outstanding) - toPaise(r.applied) - toPaise(r.tds) - toPaise(r.ded) : 0
      if (after > 100) open += after
      const l = remitLines.get(norm(inv.invoice_number))
      if (l) remit += Math.round(l.amount_paid * 100)
    }
    return { applied, tds, ded, owes, remit, ticked, open, left: remaining - applied }
  }, [rows, remaining, allRows, remitLines])

  const set = (id: string, patch: Partial<Row>) => setRows(rs => ({ ...rs, [id]: { ...(rs[id] ?? EMPTY), ...patch } }))
  const toggle = (inv: ArInvoiceRow) => {
    const cur = rows[inv.id]
    if (cur?.on) return set(inv.id, { on: false })
    // Ticking an invoice offers what is left of the payment, up to what it owes.
    const give = Math.max(0, Math.min(toPaise(inv.outstanding), totals.left))
    set(inv.id, { on: true, applied: fromPaise(give) })
  }
  const tdsRate = d?.customer?.tds_rate_hint ? Number(d.customer.tds_rate_hint) : null
  /** The customer's usual TDS on the taxable value, taken off the cash so the invoice still settles exactly. */
  const fillTds = (inv: ArInvoiceRow) => {
    if (!tdsRate || !inv.taxable_amount) return
    const r = rows[inv.id] ?? EMPTY
    const tds = Math.round(toPaise(inv.taxable_amount) * tdsRate / 100)
    const owes = toPaise(inv.outstanding)
    const cash = toPaise(r.applied)
    const fits = owes - tds - toPaise(r.ded)
    set(inv.id, { tds: fromPaise(tds), applied: fromPaise(owes && cash > fits ? Math.max(0, fits) : cash) })
  }

  /** Why each invoice is in the match — read off the evidence on screen, nothing new decided. */
  const basis = (inv: ArInvoiceRow): Basis[] => {
    const out: Basis[] = []
    const n = norm(inv.invoice_number)
    const narr = norm(p?.narration) + norm(p?.reference)
    if (n.length >= 4 && narr.includes(n)) out.push('Narration')
    if (inv.po_number && norm(inv.po_number).length >= 4 && narr.includes(norm(inv.po_number))) out.push('PO no.')
    // On the advice: the Remittance column already says so, so no tag repeats it.
    if (remitLines.has(n)) return out
    if (out.length) return out
    // The match type is on the agent icon; a row only says something the icon doesn't.
    return chosen?.allocations.some(a => a.invoice_id === inv.id) ? [] : ['Your pick']
  }

  const unchanged = chosen && sig(rows) === sig(rowsFrom(chosen))
  const missingReason = allRows.find(i => { const r = rows[i.id]; return r?.on && toPaise(r.ded) > 0 && !r.code })
  const over = totals.left < -1
  const blocker = totals.ticked === 0 ? 'Select the invoices this pays'
    : totals.applied + totals.tds + totals.ded === 0 ? 'Enter an amount'
    : over ? `${money(fromPaise(-totals.left))} more than the payment`
    : missingReason ? `Pick a reason for the deduction on ${missingReason.invoice_number}`
    : null

  const doApply = async () => {
    if (!p) return
    const allocations: AllocationIn[] = Object.entries(rows).filter(([, r]) => r.on).map(([invoice_id, r]) => ({
      invoice_id,
      amount_applied: fromPaise(toPaise(r.applied)),
      tds_amount: fromPaise(toPaise(r.tds)),
      deduction_amount: fromPaise(toPaise(r.ded)),
      reason_code: (r.code || (toPaise(r.tds) ? 'TDS' : null)) as ReasonCode | null,
      reason_note: r.note || null,
    }))
    setBusy('apply')
    try {
      const out = await applyPayment(p.id, {
        allocations, version: p.version, method: unchanged ? 'accepted' : 'manual',
        customer_id: chosen?.customer_id ?? d?.customer?.id ?? null,
        kind: unchanged ? chosen?.kind : null, confidence: unchanged ? chosen?.confidence : null,
        allow_disputed: true,
      })
      // Forgiveness for a fast queue: one click takes it back and reopens the payment.
      const pid = p.id
      toast.show({
        tone: 'success',
        title: out.status === 'applied' ? `${money(p.amount)} applied` : 'Part of the payment applied',
        message: Number(out.left_on_account) > 0 ? `${money(out.left_on_account)} kept on account` : undefined,
        action: {
          label: 'Undo',
          onClick: () => {
            unapplyPayment(pid, 'Undone right after confirming')
              .then(() => { toast.success('Undone — back in review'); onChanged(); onNavigate?.(pid) })
              .catch(e => toast.error('Couldn’t undo', apiError(e)))
          },
        },
      })
      onChanged()
      if (queue.length > 1) advance()
      else await load()
    } catch (e) {
      toast.error('Not applied', apiError(e))
      if ((e as { response?: { status?: number } }).response?.status === 409) void load()
    } finally {
      setBusy(null)
    }
  }

  // ⌘↵ / Ctrl+↵ confirms from anywhere in the card, even mid-edit — a clerk working a queue keeps their hands on the keys.
  const applyRef = useRef<() => void>(() => {})
  applyRef.current = () => { if (editable && !blocker && busy !== 'apply') void doApply() }
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Enter' || !(e.metaKey || e.ctrlKey) || e.defaultPrevented) return
      if (document.querySelector('[aria-modal="true"]')) return
      e.preventDefault()
      applyRef.current()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [])
  const mac = typeof navigator !== 'undefined' && /Mac|iP(hone|ad)/.test(navigator.platform)

  /** Run an action; `leaves` = it takes the payment out of the list, so move on. */
  const act = async (label: string, fn: () => Promise<unknown>, ok: string, leaves = false) => {
    setBusy(label)
    try {
      await fn()
      toast.success(ok)
      onChanged()
      if (leaves && queue.length > 1) advance()
      else await load()
    } catch (e) {
      toast.error('That didn’t work', apiError(e))
    } finally {
      setBusy(null)
    }
  }

  const customerEditable = editable && !!p && toPaise(p.applied_amount) === 0
  const pickCust = (id: string) => {
    if (!p) return
    setPickCustomer(false)
    void act('customer', () => choosePaymentCustomer(p.id, id), 'Customer set — re-matched')
  }
  const options = sug?.best ? [sug.best, ...(sug.alternatives ?? [])] : []
  const fromStatement = !!d?.statement

  const footer = d && p ? (
    <div className="ar-foot">
      <div className="ar-actions">
        {canPost && open && p.status !== 'exception' && (
          <Button variant="ghost" iconLeft={<PauseCircle size={14} />} onClick={() => setExc({ code: '', note: '' })}>Follow up later</Button>
        )}
        {canPost && p.status === 'exception' && (
          <Button variant="secondary" loading={busy === 'resolve'}
            onClick={() => act('resolve', () => setPaymentStatus(p.id, 'resolve'), 'Back in review', true)}>Back to review</Button>
        )}
        {canPost && ['unmatched', 'needs_review', 'exception'].includes(p.status) && (
          <Button variant="ghost" iconLeft={<CircleSlash size={14} />} loading={busy === 'nr'}
            onClick={() => act('nr', () => setPaymentStatus(p.id, 'not_receipt'), 'Excluded — not a customer payment', true)}>Not a customer payment</Button>
        )}
        {canPost && p.status === 'not_receipt' && (
          <Button variant="secondary" loading={busy === 'restore'} onClick={() => act('restore', () => setPaymentStatus(p.id, 'restore'), 'Restored')}>Restore as customer payment</Button>
        )}
        {canPost && toPaise(p.applied_amount) > 0 && p.status !== 'reversed' && (
          <Button variant="ghost" iconLeft={<Undo2 size={14} />} onClick={() => { setUndoReason(''); setUndo('unapply') }}>Unapply</Button>
        )}
        {canPost && p.flags?.includes('POSSIBLE_BOUNCE') && p.status !== 'reversed' && (
          <Button variant="danger" onClick={() => { setUndoReason('Cheque returned / transfer recalled'); setUndo('reverse') }}>Mark bounced</Button>
        )}
      </div>
      <div className="ar-actions ar-foot__main">
        {editable && (
          <>
            <Button variant="primary" onClick={doApply} loading={busy === 'apply'} disabled={!!blocker}
              iconLeft={blocker ? undefined : <Check size={14} />}
              title={blocker ? undefined : `${mac ? '⌘' : 'Ctrl'}+Enter`} aria-keyshortcuts={mac ? 'Meta+Enter' : 'Control+Enter'}>
              {blocker ?? `${unchanged ? 'Confirm' : 'Apply'}${nextId ? ' & next' : ''}`}
              {!blocker && <kbd className="ar-kbd" aria-hidden="true">{mac ? '⌘↵' : 'Ctrl ↵'}</kbd>}
            </Button>
          </>
        )}
        {!applying && nextId && (
          <Button variant="secondary" iconRight={<ChevronRight size={14} />} onClick={() => go(nextId)}>Next payment</Button>
        )}
      </div>
    </div>
  ) : undefined

  const title = d?.customer?.name || p?.payer_name || (p ? 'Unknown payer' : 'Payment')
  const best = chosen ?? null
  const surePct = best ? Math.round(Number(best.confidence) * 100) : null
  // The bar's colour says what happens next, not just the number: a match that waits for a person is never green.
  const needsPerson = sug?.decision?.action !== 'AUTO'

  // ── Bank and remittance: one icon each at the top — green when they agree with the match, amber when
  // something needs a look, red when missing. The full detail opens from the icon.
  const bankDetail = d && p ? (
                <SourceCard icon={<Landmark size={14} />} label="Bank statement" ok={fromStatement}
                    action={d.statement && (
                      <Button variant="secondary" size="sm" iconRight={<ExternalLink size={13} />} onClick={() => onOpenStatement?.(d.statement!.id)}>Open</Button>
                    )}>
                    <dl className="ar-kv">
                      <dt>UTR / ref.</dt><dd className="ar-mono">{[p.method, p.utr || p.reference].filter(Boolean).join(' · ') || '—'}</dd>
                      <dt>Narration</dt><dd className="ar-mono">{p.narration || '—'}</dd>
                      <dt>Source</dt><dd>{d.statement ? <>{d.statement.file_name} <span className="ar-muted">· line {(p.statement_line ?? 0) + 1}</span></>
                        : p.source === 'manual' ? 'Entered by hand' : p.source}</dd>
                    </dl>
                  </SourceCard>
  ) : null
  const remitDetail = d && p ? (
                <SourceCard icon={<Mail size={14} />} label={remits.length > 1 ? `Remittance ×${remits.length}` : 'Remittance'} ok={remits.length > 0}
                  action={<>
                    {remits.length === 1 && (
                      <Button variant="secondary" size="sm" iconLeft={<FileText size={13} />} onClick={() => onOpenRemittance?.(remits[0].id)}>Original</Button>
                    )}
                    {canCapture && (
                      <Button variant="secondary" size="sm" iconLeft={<Plus size={13} />} onClick={() => setAddRemit(true)}>{remits.length ? 'Add another' : 'Add'}</Button>
                    )}
                  </>}>
                  {remits.length === 0 ? (
                    <div className="ar-srccard__none">The customer hasn’t sent an advice. Adding one re-runs the match.</div>
                  ) : remits.map(r => {
                    const linesSum = r.lines.reduce((t, l) => t + Math.round(l.amount_paid * 100), 0)
                    const totalOff = remitTotalOff(r)
                    const refOk = !!bankRef && norm(r.payment_reference) === bankRef
                    // Advice lines in the same order as the invoice table; set-off notes last.
                    const pos = (l: Remittance['lines'][number]) => l.amount_paid < 0 ? 1e6
                      : (i => i < 0 ? 1e5 : i)(allRows.findIndex(x => norm(x.invoice_number) === norm(readAs.get(norm(l.invoice_number)) ?? l.invoice_number)))
                    const lines = [...r.lines].sort((x, y) => pos(x) - pos(y))
                    return (
                      <div key={r.id} className="ar-remit">
                        <dl className="ar-kv">
                          <dt>From</dt><dd>{r.payer_name || '—'}</dd>
                          <dt>Reference</dt>
                          <dd>
                            <span className="ar-mono">{r.payment_reference || '—'}</span>
                            {refOk && <span className="ar-tag ar-tag--ok ar-kv__tag" title="Same reference as the bank credit"><Check size={11} /> Matches bank UTR</span>}
                          </dd>
                          <dt>Date</dt><dd>{r.payment_date ? formatDate(r.payment_date) : '—'}</dd>
                          <dt>Total</dt>
                          <dd>
                            <span className={`ar-money ar-strong${totalOff ? ' ar-diff' : ''}`}>{money(r.total_amount)}</span>
                            {remits.length > 1 && (
                              <Button variant="ghost" size="sm" iconLeft={<FileText size={13} />} onClick={() => onOpenRemittance?.(r.id)}>Original</Button>
                            )}
                          </dd>
                        </dl>
                        {totalOff && (
                          <div className="ar-callout ar-callout--warn" role="note">
                            <AlertTriangle size={13} aria-hidden="true" />
                            <span>The advice says <strong>{money(r.total_amount)}</strong>, but its lines add up to <strong>{money(fromPaise(linesSum))}</strong>
                              {Math.abs(linesSum - toPaise(p.amount)) <= 100 ? ' — the amount received.' : '.'} Check the original before confirming.</span>
                          </div>
                        )}
                        {r.lines.length ? (
                          <table className="ar-grid ar-grid--mini">
                            <thead><tr><th>Line</th><th className="num">Paid</th><th className="num">Deducted</th><th aria-label="In this payment" /></tr></thead>
                            <tbody>
                              {lines.map((l, i) => {
                                if (l.amount_paid < 0) {
                                  const on = setoffOn(l.invoice_number)
                                  return (
                                    <tr key={i}>
                                      <td><span className="ar-strong">{l.invoice_number}</span><div className="ar-sub">{noteKind(l)}</div></td>
                                      <td className="num ar-muted">—</td>
                                      <td className="num ar-money">{money(-l.amount_paid)}</td>
                                      <td className="num">{on
                                        ? <span className="ar-tag ar-tag--ok">Deducted on {on.invoice_number}</span>
                                        : <span className="ar-tag ar-tag--warn" title="Enter it as a deduction on the invoice it reduces">Not deducted yet</span>}</td>
                                    </tr>
                                  )
                                }
                                const fixed = readAs.get(norm(l.invoice_number))
                                const n = norm(fixed ?? l.invoice_number)
                                const openInv = allRows.find(x => norm(x.invoice_number) === n)
                                const app = d.applications.find(a => norm(a.invoice_number) === n && !a.reversed_at)
                                return (
                                  <tr key={i}>
                                    <td>
                                      <span className="ar-strong">{l.invoice_number}</span>
                                      {fixed && <div className="ar-sub" title="The agent corrected this number">Read as {fixed}</div>}
                                    </td>
                                    <td className="num ar-money">{money(l.amount_paid)}</td>
                                    <td className="num ar-money" title={l.deduction_reason ?? undefined}>{l.deduction_amount ? money(l.deduction_amount) : '—'}</td>
                                    <td className="num">{app || (openInv && rows[openInv.id]?.on) ? <span className="ar-tag ar-tag--ok">Included</span>
                                      : openInv ? <span className="ar-tag">Not selected</span>
                                      : <span className="ar-tag ar-tag--bad" title="No open invoice with this number">Not found</span>}</td>
                                  </tr>
                                )
                              })}
                            </tbody>
                          </table>
                        ) : <div className="ar-srccard__none">The advice names no invoices.</div>}
                      </div>
                    )
                  })}
                </SourceCard>
  ) : null

  // The agent's reasons and other readings open from its icon, like the sources.
  const agentDetail = d && p && applying ? (
                <section className="ar-agent" aria-label="Agent’s match">
                  <header className="ar-agent__head">
                    <Sparkles size={14} aria-hidden="true" className="ar-agent__icon" />
                    <h4>{best ? (KIND_LABELS[best.kind] ?? best.kind) : 'Agent’s match'}</h4>
                    {editable && (
                      <span className="ar-agent__end">
                        <Button variant="ghost" size="sm" iconLeft={<RefreshCw size={13} />} loading={busy === 'rematch'}
                          onClick={() => act('rematch', () => rematchPayment(p.id), 'Agent re-ran')}>Re-run</Button>
                      </span>
                    )}
                  </header>
                  {best ? (
                    <>
                      {/* The verdict (confidence + kind) sits in the summary at the top; this card gives the reasons. */}
                      {(best.clues.length > 0 || sug?.decision?.reason) && (
                        <ul className="ar-agent__clues">
                          {best.clues.filter(c => !/remittance advice lists \d+ line/i.test(c)).map((c, i) => <li key={i}>{tidy(c)}</li>)}
                          {sug?.decision?.reason && <li className="is-why">{tidy(sug.decision.reason).replace(/^\d+% sure — b/, 'B')}</li>}
                        </ul>
                      )}
                    </>
                  ) : <p className="ar-agent__none">{sug?.decision?.reason ? tidy(sug.decision.reason) : 'No match found yet.'}</p>}
                  {options.length > 1 && (
                    <div className="ar-readings" role="group" aria-labelledby={`readings-${p.id}`}>
                      {/* The reading in use is the heading above; only the others are listed, to switch to. */}
                      <span id={`readings-${p.id}`} className="ar-label">Other readings</span>
                      {options.filter(s => s !== chosen).map((s, i) => {
                        const sum = s.allocations.reduce((t, x) => t + toPaise(x.amount_applied), 0)
                        return (
                          <button key={i} type="button" className="ar-reading" onClick={() => { setChosen(s); setRows(rowsFrom(s)) }}
                            aria-label={`Use this reading instead: ${KIND_LABELS[s.kind] ?? s.kind}`}>
                            <span className="ar-reading__main">
                              <span className="ar-reading__kind">{KIND_LABELS[s.kind] ?? s.kind}</span>
                              <span className="ar-reading__inv">
                                {s.allocations.length} invoice{s.allocations.length === 1 ? '' : 's'} · {s.allocations.map(x => x.invoice_number).join(', ') || '—'}
                              </span>
                            </span>
                            <span className="ar-reading__sum ar-money">{money(fromPaise(sum))}</span>
                            <span className="ar-reading__pct">{Math.round(Number(s.confidence) * 100)}%</span>
                            <span className="ar-reading__use">Use</span>
                          </button>
                        )
                      })}
                    </div>
                  )}
                </section>
  ) : null

  type Proof = { tone: 'ok' | 'warn' | 'bad'; label: string }
  // Green only when the agent would apply it on its own; amber when it waits for you; red with no match.
  const agentProof: Proof | null = !applying ? null
    : !best ? { tone: 'bad', label: 'No match yet' }
    : { tone: needsPerson ? 'warn' : 'ok', label: KIND_LABELS[best.kind] ?? best.kind }
  const bankProof: Proof | null = !p ? null
    : p.flags?.includes('POSSIBLE_BOUNCE') ? { tone: 'bad', label: 'Possible bounce' }
    : p.flags?.includes('POSSIBLE_DUPLICATE') ? { tone: 'warn', label: 'Possible repeat' }
    : fromStatement ? { tone: 'ok', label: 'On the statement' }
    : { tone: 'warn', label: p.source === 'manual' ? 'Entered by hand' : 'Not on a statement' }
  const remitProof: Proof | null = (() => {
    if (!d || !p) return null
    if (!remits.length) return { tone: 'bad', label: 'Not received' }
    if (offRemits.length) return { tone: 'warn', label: 'Total differs' }
    for (const r of remits) for (const l of r.lines) {
      if (l.amount_paid < 0) {
        if (applying && !setoffOn(l.invoice_number)) return { tone: 'warn', label: 'Note not deducted' }
        continue
      }
      const n = norm(readAs.get(norm(l.invoice_number)) ?? l.invoice_number)
      const inv = allRows.find(x => norm(x.invoice_number) === n)
      const app = d.applications.find(a => norm(a.invoice_number) === n && !a.reversed_at)
      if (!inv && !app) return { tone: 'warn', label: 'Invoice not found' }
      if (applying && inv && !app && !rows[inv.id]?.on) return { tone: 'warn', label: 'Line not selected' }
      if (applying && inv && rows[inv.id]?.on && !l.deduction_amount) {
        const r0 = rows[inv.id]
        const setoff = /^set off/i.test(r0.note) ? toPaise(r0.ded) : 0
        if (Math.round(l.amount_paid * 100) !== toPaise(r0.applied) + setoff) return { tone: 'warn', label: 'Amounts differ' }
      }
    }
    return { tone: 'ok', label: 'Matches' }
  })()

  if (!paymentId) return null

  return (
    <aside className="ar-pane" aria-labelledby={headId}>
      <header className="ar-pane__head">
        <div className="ar-pane__title">
          <span className="ar-pane__eyebrow">Payment from</span>
          <span className="ar-pane__name">
            <h2 id={headId} tabIndex={-1} ref={headRef}>{title}</h2>
            {d && applying && d.customer && !d.customer.confirmed && /resembles/.test(sug?.customer_how ?? '') && (
              <span className="ar-tag ar-tag--warn" title={`The agent’s guess — ${sug?.customer_how}. Confirming the payment confirms the customer too.`}>Likely match</span>
            )}
            {d && !d.customer && <span className="ar-tag ar-tag--warn">Customer not identified</span>}
            {d?.customer?.tds_rate_hint && (
              <span className="ar-tag" title="This customer usually deducts TDS at this rate">Usual TDS {Number(d.customer.tds_rate_hint)}%</span>
            )}
            {customerEditable && d?.customer && (
              <Button variant="secondary" size="sm" iconLeft={<Pencil size={13} />} aria-expanded={pickCustomer} onClick={() => setPickCustomer(v => !v)}>Change</Button>
            )}
          </span>
        </div>
        <span className="ar-pane__nav">
          {queue.length > 1 && (
            <>
              {idx >= 0 && <span className="ar-pane__pos">{idx + 1} of {queue.length}</span>}
              <IconButton label="Previous payment (←)" size="sm" icon={<ChevronLeft size={15} />} disabled={!prevId} onClick={() => go(prevId)} />
              <IconButton label="Next payment (→)" size="sm" icon={<ChevronRight size={15} />} disabled={!nextId} onClick={() => go(nextId)} />
            </>
          )}
          <IconButton label="Close (Esc)" size="sm" icon={<X size={15} />} onClick={onClose} />
        </span>
      </header>

      <div className="ar-pane__body" ref={bodyRef} onScroll={edge}>
        {err && <ErrorState message={err} onRetry={load} />}
        {!d && !err && <SkeletonRows rows={6} cols={4} />}
        {d && p && (
          <div className="ar-wb">
            {/* ── The payment at a glance: the amount once, large; the rest in a row ── */}
            <div className="ar-glance">
              <div className="ar-glance__hero">
                <span className="ar-cell__k">Amount</span>
                <span className="ar-glance__amt">{money(p.amount)}</span>
                {/* Where the money goes, right under the amount it splits — live as the rows change. */}
                {editable && (
                <dl className="ar-settle" aria-live="polite">
                  {toPaise(p.applied_amount) > 0 && <div><dt>Left to apply</dt><dd>{money(fromPaise(remaining))}</dd></div>}
                  <div><dt>Cash to invoices</dt><dd>{money(fromPaise(totals.applied))}</dd></div>
                  {totals.tds > 0 && <div><dt>TDS</dt><dd>{money(fromPaise(totals.tds))}</dd></div>}
                  {totals.ded > 0 && <div><dt>Deductions</dt><dd>{money(fromPaise(totals.ded))}</dd></div>}
                  <div className={over ? 'is-bad' : totals.left > 0 ? 'is-warn' : undefined}>
                    <dt>{over ? 'Over by' : 'On account'}</dt><dd>{money(fromPaise(Math.abs(totals.left)))}</dd>
                  </div>
                  {totals.open > 0 && (
                    <div className="is-warn"><dt>Stays open</dt><dd>{money(fromPaise(totals.open))}</dd></div>
                  )}
                </dl>
                )}
              </div>
              <div className="ar-glance__cells">
                <Cell k="Received">{formatDate(p.received_on)}</Cell>
                {toPaise(p.applied_amount) > 0 && <Cell k="Applied"><span className="ar-money">{money(p.applied_amount)}</span></Cell>}
                <Cell k="Status"><PaymentStatusBadge status={p.status} auto={p.auto_applied} /></Cell>
              </div>
              <div className="ar-proofs" role="group" aria-label="Sources">
                {([
                  ['agent', 'Confidence score', <Ring key="a" pct={best ? surePct ?? 0 : 0} />, agentProof],
                  ['bank', 'Bank', <Landmark key="b" size={18} />, bankProof],
                  ['remit', 'Remittance', <Mail key="r" size={18} />, remitProof],
                ] as const).map(([key, name, icon, pr]) => pr && (
                  <button key={key} type="button" className={`ar-proof ar-proof--${key}${key === 'agent' ? '' : ` is-${pr.tone}`}${src === key ? ' is-open' : ''}`}
                    aria-expanded={src === key} aria-controls={`proof-${p.id}`} onClick={() => setSrc(v => v === key ? null : key)}
                    title={`${name}: ${pr.label} — click for details`}>
                    <span className="ar-proof__icon" aria-hidden="true">
                      {icon}
                      {key !== 'agent' && <span className="ar-proof__badge">{pr.tone === 'ok' ? <Check size={10} strokeWidth={3} /> : pr.tone === 'warn' ? '!' : <X size={10} strokeWidth={3} />}</span>}
                    </span>
                    <span className="ar-proof__txt"><span className="ar-proof__k">{name}</span>{key !== 'agent' && <span className="ar-proof__v">{pr.label}</span>}</span>
                    <ChevronDown size={14} className={`ar-proof__chev${src === key ? ' ar-rot' : ''}`} aria-hidden="true" />
                  </button>
                ))}
              </div>
              {src && (
                <div id={`proof-${p.id}`} ref={proofRef} className="ar-proof__detail" role="dialog"
                  aria-label={src === 'agent' ? 'Agent’s reasons' : src === 'bank' ? 'Bank statement' : 'Remittance'}>
                  {src === 'agent' ? agentDetail : src === 'bank' ? bankDetail : remitDetail}
                </div>
              )}
            </div>

            {pickCustomer && customerEditable && (
              <CustomerSearch busy={busy === 'customer'} onPick={pickCust} onCancel={() => setPickCustomer(false)} />
            )}

            {/* Anything that should stop a confirm sits above the invoices, on screen without scrolling. */}
            {/* A remittance problem shows on its icon above (amber); flags that aren't about one source stay here. */}
            {(p.flags?.length ?? 0) > 0 && (
              <ul className="ar-warns">
                {p.flags.map(f => <li key={f}><AlertTriangle size={13} aria-hidden="true" />{FLAG_LABELS[f] ?? f}</li>)}
              </ul>
            )}

            {/* ── What you're confirming comes first, so it's on screen without scrolling; the evidence follows. ── */}
            {/* ── Already applied ── */}
            {d.applications.length > 0 && (
              <section className="ar-block">
                <header className="ar-block__head"><h3>Applied to invoices</h3></header>
                <div className="ar-table-wrap">
                  <table className="ar-grid ar-grid--inv">
                    <thead>
                      <tr>
                        <th>Invoice</th><th className="num">Remittance</th><th className="num">Cash</th>
                        <th className="num">TDS</th><th className="num">Deduction</th><th className="num">Settled</th>
                        <th>By</th>
                      </tr>
                    </thead>
                    <tbody>
                      {d.applications.map(a => {
                        const l = remitLines.get(norm(a.invoice_number))
                        const settled = toPaise(a.amount_applied) + toPaise(a.tds_amount) + toPaise(a.deduction_amount)
                        return (
                          <tr key={a.id} className={a.reversed_at ? 'is-reversed' : undefined}>
                            <td><span className="ar-strong">{a.invoice_number}</span>{a.reversed_at && <> <Badge tone="neutral">Undone</Badge></>}</td>
                            <td className="num ar-money">{l ? money(l.amount_paid) : '—'}</td>
                            <td className="num ar-money">{money(a.amount_applied)}</td>
                            <td className="num ar-money">{Number(a.tds_amount) ? money(a.tds_amount) : '—'}</td>
                            <td className="num ar-money">{Number(a.deduction_amount)
                              ? <>{money(a.deduction_amount)}<div className="ar-sub">{REASON_LABELS[a.reason_code as ReasonCode] ?? a.reason_code}</div></> : '—'}</td>
                            <td className="num ar-money ar-strong">{money(fromPaise(settled))}</td>
                            <td className="nowrap">
                              {a.method === 'auto' ? <span className="ar-tag ar-tag--brand"><Sparkles size={11} /> Agent</span> : a.applied_by || '—'}
                              <div className="ar-sub">{formatDateTime(a.created_at)}</div>
                            </td>
                          </tr>
                        )
                      })}
                    </tbody>
                  </table>
                </div>
              </section>
            )}

            {/* ── The invoices this payment pays — one row each ── */}
            {applying && (
              <section className="ar-block">
                {allRows.length === 0 ? (
                  d.customer ? (
                    <div className="ar-panel__empty">{d.customer.name} has no open invoices. Upload the invoice, or keep the payment on account.</div>
                  ) : customerEditable ? (
                    <CustomerSearch busy={busy === 'customer'} onPick={pickCust} prompt="Who paid? Choose the customer to see their open invoices." />
                  ) : <div className="ar-panel__empty">Customer not identified.</div>
                ) : (
                  /* Two cards on shared rows: left = the invoices and what they owe; right = what this payment puts against each. */
                  <div className="ar-split-wrap">
                    <table className="ar-grid ar-grid--inv ar-grid--edit ar-split">
                      {/* Both cards 48.5% wide with a 3% gap; columns split inside each card. */}
                      <colgroup>
                        <col style={{ width: '4%' }} />
                        <col style={{ width: hasRemit ? '19.5%' : '27.5%' }} />
                        <col style={{ width: hasRemit ? '12.5%' : '17%' }} />
                        {hasRemit && <col style={{ width: '12.5%' }} />}
                        <col style={{ width: '3%' }} />
                        <col style={{ width: '13.5%' }} /><col style={{ width: '11.5%' }} /><col style={{ width: '13.5%' }} /><col style={{ width: '10%' }} />
                      </colgroup>
                      <thead>
                        <tr className="ar-split__titles">
                          <th colSpan={hasRemit ? 4 : 3} className="gL s e">
                            <span className="ar-split__title">
                              <span>
                                {toPaise(p.applied_amount) > 0 ? 'Still open' : 'Invoices'}
                                <span className="ar-block__count">{picked.length} of {allRows.length} open</span>
                              </span>
                              {picked.length > 0 && allRows.length > picked.length && (
                                <Button variant="secondary" size="sm" aria-expanded={allOpen} onClick={() => setAllOpen(v => !v)}
                                  iconLeft={allOpen ? <ChevronUp size={13} /> : <ChevronDown size={13} />}>
                                  {allOpen ? 'Selected only' : `Show ${hiddenCount} more`}
                                </Button>
                              )}
                            </span>
                          </th>
                          <th className="gap" aria-hidden="true" />
                          <th colSpan={4} className="gR s e">
                            <span className="ar-split__title">
                              <span>Applying from this payment</span>
                              <span className="ar-split__sum" title="Cash from this payment; TDS and deductions are in the totals row">{money(fromPaise(totals.applied))}</span>
                            </span>
                          </th>
                        </tr>
                        <tr>
                          <th className="chk gL s" aria-label="Select" />
                          <th className="gL">Invoice</th><th className={`num gL${hasRemit ? '' : ' e'}`}>Outstanding</th>{hasRemit && <th className="num gL e">Remittance</th>}
                          <th className="gap" aria-hidden="true" />
                          <th className="num gR s">Cash</th><th className="num gR">TDS</th><th className="num gR">Deduction</th>
                          <th className="num gR e">Left to pay</th>
                        </tr>
                      </thead>
                      <tbody>
                        {shown.map(inv => {
                          const r = rows[inv.id] ?? EMPTY
                          const owes = inv.outstanding ? toPaise(inv.outstanding) : null
                          const after = owes == null ? null : owes - toPaise(r.applied) - toPaise(r.tds) - toPaise(r.ded)
                          const late = inv.due_date ? Math.floor((Date.now() - new Date(inv.due_date).getTime()) / 86_400_000) : null
                          const l = remitLines.get(norm(inv.invoice_number))
                          // Offered only when the invoice is still short and no remittance line speaks for it.
                          const tdsFill = r.on && editable && tdsRate && inv.taxable_amount && !toPaise(r.tds) && !l && after != null && after > 100
                            ? Math.round(toPaise(inv.taxable_amount) * tdsRate / 100) : 0
                          // A small gap offered as a deduction in one click; a big one is a real part-payment, left open.
                          const shortBy = r.on && editable && owes && after != null && after > 100 && after <= owes * 0.02 && !toPaise(r.ded) ? after : 0
                          // A set-off note explains its own gap (shown under Deduction); anything else is called out.
                          const setoffDed = /^set off/i.test(r.note) ? toPaise(r.ded) : 0
                          const remitDiff = !!l && r.on && Math.round(l.amount_paid * 100) !== toPaise(r.applied) + setoffDed
                          return (
                            <tr key={inv.id} className={[r.on && 'is-on', inv.id === focusInvoiceId && 'is-focus'].filter(Boolean).join(' ') || undefined}
                              data-inv={inv.id}>
                              <td className="chk gL s">
                                <input type="checkbox" checked={r.on} disabled={!editable} onChange={() => toggle(inv)} aria-label={`Select ${inv.invoice_number}`} />
                              </td>
                              <td className="gL">
                                <span className="ar-inv">
                                  {inv.customer_id
                                    ? <a className="ar-invlink" href={arInvoicePath(inv.id)} target="_blank" rel="noopener noreferrer"
                                        title="Open the invoice in a new tab">{inv.invoice_number}<ExternalLink size={11} aria-hidden="true" /></a>
                                    : <span className="ar-strong">{inv.invoice_number}</span>}
                                  {inv.status === 'disputed' && <span className="ar-tag ar-tag--bad">Disputed</span>}
                                  {inv.status === 'partially_paid' && (
                                    <span className="ar-tag" title={inv.total_amount ? `Part-paid · invoice total ${money(inv.total_amount)}` : undefined}>Part-paid</span>
                                  )}
                                </span>
                                <div className="ar-sub ar-inv-meta">
                                  {r.on && basis(inv).map(b => (
                                    <span key={b} className={`ar-tag${b === 'Your pick' ? '' : ' ar-tag--brand'}`} title="How it was matched">{b}</span>
                                  ))}
                                  {late != null && late > 0
                                    ? <span title={`Due ${formatDate(inv.due_date)}`}>{late}d past due</span>
                                    : inv.due_date ? `Due ${formatDate(inv.due_date)}` : ''}
                                </div>
                              </td>
                              <td className={`num ar-money gL${hasRemit ? '' : ' e'}`}>{inv.outstanding ? money(inv.outstanding) : '—'}</td>
                              {hasRemit && (
                                <td className={`num ar-money gL e${remitDiff ? ' ar-diff' : ''}`} title={remitDiff ? 'Differs from the cash applied' : undefined}>
                                  {l ? money(l.amount_paid) : <span className="ar-muted">—</span>}
                                  {/* The advice's deduction stays inside its cell: amount, then the reason cut short (full text on hover). */}
                                  {l?.deduction_amount ? (
                                    <div className="ar-sub ar-remit-ded" title={l.deduction_reason ? `−${money(l.deduction_amount)} · ${l.deduction_reason}` : undefined}>
                                      <span>−{money(l.deduction_amount)}</span>
                                      {l.deduction_reason && <span className="ar-remit-ded__why">{l.deduction_reason}</span>}
                                    </div>
                                  ) : null}
                                  {remitDiff && !l?.deduction_amount && <div className="ar-sub">differs from the cash</div>}
                                </td>
                              )}
                              <td className="gap" aria-hidden="true" />
                              <td className="num in gR s"><AmountIn value={r.applied} disabled={!r.on || !editable} onChange={v => set(inv.id, { applied: v })} label={`Cash on ${inv.invoice_number}`} /></td>
                              <td className="num in gR">
                                <AmountIn value={r.tds} disabled={!r.on || !editable} onChange={v => set(inv.id, { tds: v })} label={`TDS on ${inv.invoice_number}`} />
                                {tdsFill > 0 && (
                                  <button type="button" className="ar-fill" onClick={() => fillTds(inv)}
                                    title={`${tdsRate}% of taxable ${money(inv.taxable_amount)} — this customer’s usual rate`}>
                                    + {tdsRate}% · {money(fromPaise(tdsFill))}
                                  </button>
                                )}
                              </td>
                              <td className="num in gR">
                                <AmountIn value={r.ded} disabled={!r.on || !editable} onChange={v => set(inv.id, { ded: v })} label={`Deduction on ${inv.invoice_number}`} />
                                {shortBy > 0 && (
                                  <button type="button" className="ar-fill" onClick={() => set(inv.id, { ded: fromPaise(shortBy) })}
                                    title="Book what’s left as a deduction so the invoice closes — you’ll pick the reason">
                                    + {money(fromPaise(shortBy))} short
                                  </button>
                                )}
                                {/* Reason and source on one line under the amount: "Debit / credit note ⌄ · DN/SGF/118". */}
                                {r.on && toPaise(r.ded) > 0 && (
                                  <div className="ar-dedmeta">
                                    <Dropdown<ReasonCode | ''> value={r.code} disabled={!editable} onChange={v => set(inv.id, { code: v })}
                                      ariaLabel={`Reason for the deduction on ${inv.invoice_number}`} className={`ar-dd-inline${r.code ? '' : ' is-need'}`}
                                      options={REASON_OPTIONS} />
                                    {/^set off/i.test(r.note) && (
                                      <span className="ar-dedmeta__src" title="Set off on the remittance advice">· {r.note.replace(/^set off:\s*/i, '')}</span>
                                    )}
                                  </div>
                                )}
                              </td>
                              <td className="num gR e">
                                {!r.on || after == null ? <span className="ar-muted">—</span>
                                  : Math.abs(after) <= 100 ? <span className="ar-tag ar-tag--ok">Paid in full</span>
                                  : after > 0 ? <><span className="ar-money ar-open">{money(fromPaise(after))}</span><div className="ar-sub">stays open</div></>
                                  : <span className="ar-tag ar-tag--bad">{money(fromPaise(-after))} over</span>}
                              </td>
                            </tr>
                          )
                        })}
                      </tbody>
                      {totals.ticked > 0 && shown.length > 1 && (
                        <tfoot>
                          <tr>
                            <td className="gL s" />
                            <td className="gL">{totals.ticked} selected</td>
                            <td className={`num ar-money gL${hasRemit ? '' : ' e'}`}>{money(fromPaise(totals.owes))}</td>
                            {hasRemit && <td className="num ar-money gL e">{totals.remit ? money(fromPaise(totals.remit)) : '—'}</td>}
                            <td className="gap" aria-hidden="true" />
                            <td className="num ar-money gR s">{money(fromPaise(totals.applied))}</td>
                            <td className="num ar-money gR">{totals.tds ? money(fromPaise(totals.tds)) : '—'}</td>
                            <td className="num ar-money gR">{totals.ded ? money(fromPaise(totals.ded)) : '—'}</td>
                            <td className="num ar-money gR e">{money(fromPaise(Math.max(0, totals.owes - totals.applied - totals.tds - totals.ded)))}</td>
                          </tr>
                        </tfoot>
                      )}
                    </table>
                  </div>
                )}
              </section>
            )}

            {(p.status === 'exception' || p.note) && (
              <div className="ar-note">
                {p.status === 'exception' && p.reason_code && <strong>{EXCEPTION_LABELS[p.reason_code as ExceptionCode] ?? p.reason_code}</strong>}
                {p.note && <span>{p.note}</span>}
              </div>
            )}

            {d.events.length > 0 && (
              <details className="ar-activity">
                <summary>Activity · {d.events.length}</summary>
                <table className="ar-grid">
                  <tbody>
                    {d.events.map((e, i) => (
                      <tr key={i}>
                        <td className="ar-muted nowrap">{formatDateTime(e.at)}</td>
                        <td>{e.actor === 'agent' ? 'Agent' : e.actor} {EVENT_LABELS[e.action] ?? e.action.replace(/_/g, ' ')}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </details>
            )}
          </div>
        )}
      </div>

      {footer && <footer className={`ar-pane__foot${moreBelow ? ' has-more' : ''}`}>{footer}</footer>}

      <Modal open={!!exc} onClose={() => setExc(null)} title="Follow up later" size="sm"
        description="Moves it to Follow-up until someone sends it back to review."
        footer={<><Button variant="ghost" onClick={() => setExc(null)}>Cancel</Button>
          <Button variant="primary" disabled={!exc?.code} loading={busy === 'exc'} onClick={async () => {
            if (!p || !exc?.code) return
            const code = exc.code as ExceptionCode
            const note = exc.note || undefined
            setExc(null)
            await act('exc', () => setPaymentStatus(p.id, 'exception', code, note), 'Moved to follow-up', true)
          }}>Move to follow-up</Button></>}>
        <div className="ar-form ar-form--1">
          <Select label="Reason" required value={exc?.code ?? ''} placeholder="Pick a reason"
            options={(Object.keys(EXCEPTION_LABELS) as ExceptionCode[]).map(c => ({ value: c, label: EXCEPTION_LABELS[c] }))}
            onChange={e => setExc(x => x && { ...x, code: e.target.value as ExceptionCode })} />
          <Textarea label="Note" rows={3} value={exc?.note ?? ''} onChange={e => setExc(x => x && { ...x, note: e.target.value })} />
        </div>
      </Modal>

      <ConfirmDialog
        open={!!undo}
        title={undo === 'reverse' ? 'Mark this payment bounced?' : 'Unapply this payment?'}
        description={undo === 'reverse'
          ? 'Every invoice it paid reopens. Use this when the cheque bounced or the transfer was recalled.'
          : 'Every invoice it paid reopens. The agent re-checks it but won’t apply it again on its own.'}
        confirmLabel={undo === 'reverse' ? 'Mark bounced' : 'Unapply'}
        tone="danger"
        onCancel={() => setUndo(null)}
        onConfirm={async () => {
          if (!p) return
          const reason = undoReason.trim() || (undo === 'reverse' ? 'Bounced / recalled' : 'Unapplied')
          await act('undo', () => undo === 'reverse' ? setPaymentStatus(p.id, 'reverse', undefined, reason) : unapplyPayment(p.id, reason),
            undo === 'reverse' ? 'Marked bounced' : 'Payment unapplied')
          setUndo(null)
        }}
      >
        <Textarea label="Reason" rows={2} value={undoReason} onChange={e => setUndoReason(e.target.value)} />
      </ConfirmDialog>

      <RemittanceModal open={addRemit} onClose={() => setAddRemit(false)}
        onDone={() => { setAddRemit(false); onChanged(); void load() }} />
    </aside>
  )
}

function Cell({ k, children, wide }: { k: string; children: React.ReactNode; wide?: boolean }) {
  return (
    <div className={`ar-cell${wide ? ' ar-cell--wide' : ''}`}>
      <span className="ar-cell__k">{k}</span>
      <span className="ar-cell__v">{children}</span>
    </div>
  )
}

/** One source of the payment: green when we have it, red when we don't, and what it said. */
function SourceCard({ icon, label, ok, action, children }: {
  icon: React.ReactNode; label: string; ok: boolean; action?: React.ReactNode; children: React.ReactNode
}) {
  return (
    <section className={`ar-srccard ${ok ? 'ar-srccard--ok' : 'ar-srccard--miss'}`} aria-label={`${label}: ${ok ? 'received' : 'missing'}`}>
      <header className="ar-srccard__head">
        <span className="ar-srccard__dot" aria-hidden="true" />
        {icon}
        <h4>{label}</h4>
        <span className="ar-srccard__state">{ok ? 'Received' : 'Missing'}</span>
        {action && <span className="ar-srccard__action">{action}</span>}
      </header>
      {children}
    </section>
  )
}

/** The agent's confidence as a ring: one colour, the arc is the score. */
function Ring({ pct }: { pct: number }) {
  const r = 18, c = 2 * Math.PI * r
  const v = Math.max(0, Math.min(100, pct))
  return (
    <svg className="ar-ring" width="44" height="44" viewBox="0 0 44 44" role="img" aria-label={`${v}% sure`}>
      <circle cx="22" cy="22" r={r} className="ar-ring__track" />
      <circle cx="22" cy="22" r={r} className="ar-ring__arc" strokeDasharray={`${(v / 100) * c} ${c}`} transform="rotate(-90 22 22)" />
      <text x="22" y="22.5" className="ar-ring__n" textAnchor="middle" dominantBaseline="central">{v}<tspan className="ar-ring__pc">%</tspan></text>
    </svg>
  )
}

/** Amount field: shows ₹1,57,350.00 like the cells beside it; plain digits while typing. */
function AmountIn({ value, disabled, onChange, label }: { value: string; disabled: boolean; onChange: (v: string) => void; label: string }) {
  const [focus, setFocus] = useState(false)
  const n = value === '' ? null : Number(value.replace(/,/g, ''))
  const shown = focus || n == null || Number.isNaN(n) ? value
    : n.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
  return (
    <span className={`ar-amt${disabled ? ' is-off' : ''}${!focus && !n ? ' is-zero' : ''}`}>
      <span className="ar-amt__cur" aria-hidden="true">₹</span>
      <input type="text" inputMode="decimal" disabled={disabled} value={shown}
        placeholder={disabled ? '' : '0.00'} onFocus={() => setFocus(true)} onBlur={() => setFocus(false)}
        onChange={e => onChange(e.target.value.replace(/[^\d.]/g, ''))} aria-label={label} />
    </span>
  )
}

/** Search customers and pick one — a person's choice is what sticks. */
function CustomerSearch({ busy, onPick, onCancel, prompt }: {
  busy: boolean; onPick: (id: string) => void; onCancel?: () => void; prompt?: string
}) {
  const [q, setQ] = useState('')
  const [opts, setOpts] = useState<CustomerRow[] | null>(null)
  useEffect(() => {
    const t = setTimeout(() => {
      fetchCustomers({ q: q || undefined, limit: 8 }).then(r => setOpts(r.items)).catch(() => setOpts([]))
    }, 200)
    return () => clearTimeout(t)
  }, [q])
  return (
    <div className="ar-csearch">
      {prompt && <div className="ar-csearch__prompt">{prompt}</div>}
      <div className="ar-csearch__input">
        <Search size={14} aria-hidden="true" />
        {/* eslint-disable-next-line jsx-a11y/no-autofocus -- the person just asked to choose */}
        <input autoFocus={!prompt} placeholder="Customer name or GSTIN" value={q} onChange={e => setQ(e.target.value)} aria-label="Search customers" />
        {onCancel && <Button variant="ghost" size="sm" onClick={onCancel}>Cancel</Button>}
      </div>
      {opts && (
        <table className="ar-grid ar-grid--pick">
          <thead><tr><th>Customer</th><th>GSTIN</th><th className="num">Open invoices</th><th className="num">Outstanding</th><th aria-label="Choose" /></tr></thead>
          <tbody>
            {opts.length === 0 && <tr><td colSpan={5} className="ar-muted">No customer matches “{q}”.</td></tr>}
            {opts.map(c => (
              <tr key={c.id}>
                <td className="ar-strong">{c.name}</td>
                <td className="ar-mono">{c.gstin || '—'}</td>
                <td className="num">{c.open_count || '—'}</td>
                <td className="num ar-money">{Number(c.outstanding) ? money(c.outstanding) : '—'}</td>
                <td className="num"><Button size="sm" variant="secondary" disabled={busy} onClick={() => onPick(c.id)}>Choose</Button></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}
