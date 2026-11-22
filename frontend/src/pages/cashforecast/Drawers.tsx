/** Right-hand drawers: day detail (S-02) and exclusions (S-03). */
import { useEffect, useId, useRef, useState, type FormEvent, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { Link } from 'react-router-dom'
import { X } from 'lucide-react'
import { Badge, Button, IconButton, useFocusTrap, useScrollLock, type BadgeTone } from '../../ui'
import { api, ApiError, billIdOf } from './api'
import { day, exact, rupees, shortDay, toPaise } from './format'
import type { CashEvent, DayDetail, Exclusion, View } from './types'

export function Drawer({
  open,
  onClose,
  title,
  sub,
  wide,
  children,
}: {
  open: boolean
  onClose: () => void
  title: string
  sub?: ReactNode
  wide?: boolean
  children: ReactNode
}) {
  const ref = useRef<HTMLDivElement>(null)
  const titleId = useId()
  useFocusTrap(ref, open, onClose)
  useScrollLock(open)
  if (!open) return null
  return createPortal(
    // eslint-disable-next-line jsx-a11y/no-static-element-interactions -- pointer convenience; Escape and the close button cover keyboard
    <div className="cf-drawer__backdrop" onMouseDown={e => e.target === e.currentTarget && onClose()}>
      <div ref={ref} className={`cf-drawer${wide ? ' cf-drawer--wide' : ''}`} role="dialog" aria-modal="true" aria-labelledby={titleId}>
        <div className="cf-drawer__head">
          <div>
            <h2 id={titleId}>{title}</h2>
            {sub && <div className="cf-drawer__sub">{sub}</div>}
          </div>
          <IconButton label="Close" icon={<X size={16} />} onClick={onClose} />
        </div>
        <div className="cf-drawer__body">{children}</div>
      </div>
    </div>,
    document.body,
  )
}

const CONFIDENCE_TONE: Record<string, BadgeTone> = {
  confirmed: 'info',
  committed: 'neutral',
  pipeline: 'warn',
  expected: 'neutral',
  estimated: 'warn',
}

type Action = { kind: 'move' | 'window' | 'promise'; event: CashEvent } | null

export function DayDrawer({
  date,
  view,
  snapshotId,
  overrides,
  canEdit,
  start,
  onClose,
  onMove,
  onSaved,
}: {
  date: string | null
  view: View
  snapshotId: string
  overrides: import('./types').Override[]
  canEdit: boolean
  start: string
  onClose: () => void
  onMove: (event: CashEvent, toDate: string) => void
  onSaved: (message: string) => void
}) {
  const [detail, setDetail] = useState<DayDetail | null>(null)
  const [error, setError] = useState('')
  const [action, setAction] = useState<Action>(null)

  useEffect(() => {
    if (!date) return
    let live = true
    setDetail(null)
    setError('')
    setAction(null)
    api
      .day(snapshotId, view, date, overrides)
      .then(d => live && setDetail(d))
      .catch((e: unknown) => live && setError(e instanceof ApiError ? e.message : 'Couldn’t load this day.'))
    return () => {
      live = false
    }
  }, [date, view, snapshotId, overrides])

  const d = detail?.day
  return (
    <Drawer
      open={!!date}
      onClose={onClose}
      title={date ? `${day(date)} · ${view === 'no_collections' ? 'No new collections' : view === 'downside' ? 'Downside' : 'Expected'} view` : ''}
      sub={
        d && (
          <>
            <div className="cf-daysum">
              <span>Opening ₹{exact(d.opening_paise)}</span>
              <span className="cf-in">In +₹{exact(d.inflow_paise)}</span>
              <span>Out −₹{exact(d.outflow_paise)}</span>
            </div>
            <div className="cf-daysum">
              <strong>Closing ₹{exact(d.closing_paise)}</strong>
              {d.below_reserve && <Badge tone="danger" icon={<span>◆</span>}>Below reserve</Badge>}
            </div>
          </>
        )
      }
    >
      {error && <p role="alert">{error}</p>}
      {!detail && !error && <p role="status">Loading…</p>}
      {detail && (
        <>
          <EventGroup title="Out" total={detail.day.outflow_paise} sign="−" events={detail.outflows} canEdit={canEdit} onAction={setAction} />
          <EventGroup title="In" total={detail.day.inflow_paise} sign="+" events={detail.inflows} canEdit={canEdit} onAction={setAction} />
          {!detail.inflows.length && !detail.outflows.length && (
            <p className="cf-muted">{detail.day.banking_day ? 'Nothing is due on this day.' : 'Not a banking day; nothing is scheduled.'}</p>
          )}
          <p className="cf-muted cf-small">Daily totals. Timing within a day isn’t modelled.</p>
        </>
      )}
      {action?.kind === 'move' && (
        <MoveForm event={action.event} start={start} onCancel={() => setAction(null)} onMove={to => { onMove(action.event, to); setAction(null) }} />
      )}
      {action?.kind === 'window' && (
        <WindowForm event={action.event} onCancel={() => setAction(null)} onSaved={m => { setAction(null); onSaved(m) }} />
      )}
      {action?.kind === 'promise' && (
        <PromiseForm event={action.event} start={start} onCancel={() => setAction(null)} onSaved={m => { setAction(null); onSaved(m) }} />
      )}
    </Drawer>
  )
}

function EventGroup({
  title,
  total,
  sign,
  events,
  canEdit,
  onAction,
}: {
  title: string
  total: number
  sign: string
  events: CashEvent[]
  canEdit: boolean
  onAction: (a: Action) => void
}) {
  if (!events.length) return null
  return (
    <section className="cf-group" aria-label={`${title === 'In' ? 'Receipts' : 'Payments'} on this day`}>
      <h3>
        <span>
          {title} ({events.length})
        </span>
        <span>
          {sign}₹{exact(total)}
        </span>
      </h3>
      <ul className="cf-events">
        {events.map(e => {
          const isBill = e.direction === 'out' && (e.source_type === 'bill' || e.source_type === 'schedule')
          const isAr = e.source_type === 'ar_invoice'
          return (
            <li key={e.event_key} className="cf-event">
              <div className="cf-event__main">
                <div className="cf-event__label">
                  {e.link_path ? <Link to={e.link_path}>{e.label}</Link> : e.label}
                  {e.moved_by_scenario && <Badge tone="brand">Changed in scenario</Badge>}
                </div>
                <div className="cf-event__amount">₹{exact(e.amount_paise)}</div>
              </div>
              <div className="cf-event__meta">
                <span className="cf-cat">{e.category}</span>
                <Badge tone={e.fixed ? 'brand' : (CONFIDENCE_TONE[e.confidence] ?? 'neutral')}>{e.fixed ? 'Fixed' : e.confidence}</Badge>
                <span>{e.date_basis}</span>
                {e.tds_note && <span>{e.tds_note}</span>}
                {e.window && <Badge tone="info">Window to {shortDay(e.window.latest)}</Badge>}
              </div>
              {canEdit && (
                <div className="cf-event__actions">
                  {!e.fixed && (
                    <Button size="sm" variant="secondary" onClick={() => onAction({ kind: 'move', event: e })}>
                      Move
                    </Button>
                  )}
                  {isBill && (
                    <Button size="sm" variant="ghost" onClick={() => onAction({ kind: 'window', event: e })}>
                      Agreed later date
                    </Button>
                  )}
                  {isAr && (
                    <Button size="sm" variant="ghost" onClick={() => onAction({ kind: 'promise', event: e })}>
                      Promise to pay
                    </Button>
                  )}
                </div>
              )}
            </li>
          )
        })}
      </ul>
    </section>
  )
}

function InlineForm({ title, children, onSubmit, onCancel, busy, error, submit }: {
  title: string
  children: ReactNode
  onSubmit: (e: FormEvent<HTMLFormElement>) => void
  onCancel: () => void
  busy?: boolean
  error?: string
  submit: string
}) {
  return (
    <form className="cf-inline-form" onSubmit={onSubmit} aria-label={title}>
      <h3>{title}</h3>
      {children}
      {error && <p role="alert" className="cf-error">{error}</p>}
      <div className="cf-form-actions">
        <Button variant="ghost" type="button" onClick={onCancel}>
          Cancel
        </Button>
        <Button type="submit" loading={busy}>
          {submit}
        </Button>
      </div>
    </form>
  )
}

function MoveForm({ event, start, onMove, onCancel }: { event: CashEvent; start: string; onMove: (to: string) => void; onCancel: () => void }) {
  const [to, setTo] = useState(event.date ?? start)
  const limit = event.direction === 'out' && (event.source_type === 'bill' || event.source_type === 'schedule')
    ? event.window?.latest ?? (event.nominal_date && event.nominal_date > (event.date ?? '') ? event.nominal_date : event.date)
    : undefined
  return (
    <InlineForm
      title={`Move ${event.label}`}
      submit="Add to scenario"
      onCancel={onCancel}
      onSubmit={e => {
        e.preventDefault()
        onMove(to)
      }}
    >
      <label className="cf-field">
        New date
        <input type="date" value={to} min={start} max={limit ?? undefined} onChange={e => setTo(e.target.value)} required />
      </label>
      {limit && <p className="cf-muted cf-small">{event.window ? `Agreed window ends ${day(limit)}.` : `Due ${day(limit)}. Record the supplier's agreement to pay later.`}</p>}
      {event.direction === 'in' && <p className="cf-muted cf-small">Moving a receipt is an assumption, not a decision.</p>}
    </InlineForm>
  )
}

function WindowForm({ event, onSaved, onCancel }: { event: CashEvent; onSaved: (m: string) => void; onCancel: () => void }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  return (
    <InlineForm
      title="Supplier agreed a later date"
      submit="Save agreement"
      busy={busy}
      error={error}
      onCancel={onCancel}
      onSubmit={async e => {
        e.preventDefault()
        const f = new FormData(e.currentTarget)
        const invoice = billIdOf(event)
        if (!invoice) return setError('This payment isn’t linked to a bill.')
        setBusy(true)
        setError('')
        try {
          await api.createWindow({
            invoice_id: invoice,
            latest_date: String(f.get('latest')),
            agreed_with: String(f.get('who')),
            evidence: String(f.get('evidence')),
          })
          onSaved(`Payment window saved for ${event.counterparty ?? 'the supplier'}. Refresh the forecast to use it.`)
        } catch (err) {
          setError(err instanceof ApiError ? err.message : 'Couldn’t save the agreement.')
        } finally {
          setBusy(false)
        }
      }}
    >
      <label className="cf-field">
        Pay no later than
        <input name="latest" type="date" min={event.nominal_date ?? event.date ?? undefined} required />
      </label>
      <label className="cf-field">
        Agreed with
        <input name="who" defaultValue={event.counterparty ?? ''} required maxLength={200} />
      </label>
      <label className="cf-field">
        Evidence
        <input name="evidence" placeholder="e.g. Email from supplier accounts, 17 Nov" required maxLength={1000} />
      </label>
    </InlineForm>
  )
}

function PromiseForm({ event, start, onSaved, onCancel }: { event: CashEvent; start: string; onSaved: (m: string) => void; onCancel: () => void }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  return (
    <InlineForm
      title="Customer promised to pay"
      submit="Save promise"
      busy={busy}
      error={error}
      onCancel={onCancel}
      onSubmit={async e => {
        e.preventDefault()
        const f = new FormData(e.currentTarget)
        const amount = toPaise(String(f.get('amount')))
        if (!amount || amount <= 0) return setError('Enter the promised amount in rupees.')
        setBusy(true)
        setError('')
        try {
          await api.createPromise({
            invoice_id: event.source_id,
            promised_date: String(f.get('date')),
            promised_amount_paise: amount,
            source: String(f.get('source')),
            note: String(f.get('note') || '') || undefined,
          })
          onSaved(`Promise saved for ${event.counterparty ?? 'the customer'}. Refresh the forecast to use it.`)
        } catch (err) {
          setError(err instanceof ApiError ? err.message : 'Couldn’t save the promise.')
        } finally {
          setBusy(false)
        }
      }}
    >
      <label className="cf-field">
        Promised date
        <input name="date" type="date" min={start} required />
      </label>
      <label className="cf-field">
        Amount (₹)
        <input name="amount" inputMode="decimal" defaultValue={exact(event.amount_paise)} required />
      </label>
      <label className="cf-field">
        How
        <select name="source" defaultValue="call">
          <option value="call">Call</option>
          <option value="email">Email</option>
          <option value="meeting">Meeting</option>
          <option value="portal">Portal</option>
          <option value="other">Other</option>
        </select>
      </label>
      <label className="cf-field">
        Note
        <input name="note" maxLength={1000} />
      </label>
    </InlineForm>
  )
}

const GROUPS: { title: string; reasons: string[] }[] = [
  { title: 'Already in the bank balance', reasons: ['SETTLED_PENDING_APPLICATION', 'PAID_VIA_DISBURSEMENT'] },
  { title: 'Counted once elsewhere', reasons: ['PAYOUT_IN_FLIGHT'] },
  { title: 'Held for review', reasons: ['SUSPECTED_DUPLICATE', 'DISPUTED'] },
  { title: 'Not payable', reasons: ['REJECTED', 'VOID'] },
  { title: 'Needs information', reasons: ['UNDATED', 'NON_INR', 'TEMPLATE_WITHOUT_AMOUNT'] },
  { title: 'Downside view only', reasons: ['AGED_OVER_60_DAYS_DOWNSIDE'] },
]

const LINK_LABEL: Record<string, string> = {
  SETTLED_PENDING_APPLICATION: 'Apply receipt',
  SUSPECTED_DUPLICATE: 'Review in Review Hub',
}

export function ExclusionsDrawer({ open, snapshotId, onClose }: { open: boolean; snapshotId: string; onClose: () => void }) {
  const [rows, setRows] = useState<Exclusion[] | null>(null)
  const [error, setError] = useState('')
  useEffect(() => {
    if (!open) return
    let live = true
    api
      .exclusions(snapshotId)
      .then(r => live && setRows(r))
      .catch((e: unknown) => live && setError(e instanceof ApiError ? e.message : 'Couldn’t load exclusions.'))
    return () => {
      live = false
    }
  }, [open, snapshotId])
  return (
    <Drawer open={open} onClose={onClose} title={`Not in this forecast${rows ? ` (${rows.length})` : ''}`}
      sub="These records exist but are left out so nothing is counted twice or forecast without basis.">
      {error && <p role="alert">{error}</p>}
      {!rows && !error && <p role="status">Loading…</p>}
      {rows && !rows.length && <p className="cf-muted">Nothing is excluded.</p>}
      {rows &&
        GROUPS.map(g => {
          const items = rows.filter(r => g.reasons.includes(r.reason))
          if (!items.length) return null
          return (
            <section key={g.title} className="cf-group">
              <h3>
                <span>{g.title}</span>
              </h3>
              <ul className="cf-events">
                {items.map(x => (
                  <li key={x.source_type + x.source_id + x.reason} className="cf-event">
                    <div className="cf-event__main">
                      <div className="cf-event__label">{x.label}</div>
                      <div className="cf-event__amount">{rupees(x.amount_paise)}</div>
                    </div>
                    <div className="cf-event__meta">
                      <span>{x.detail}</span>
                      {x.link_path && (
                        <Link to={x.link_path}>{LINK_LABEL[x.reason] ?? 'Open source'} ›</Link>
                      )}
                    </div>
                  </li>
                ))}
              </ul>
            </section>
          )
        })}
    </Drawer>
  )
}
