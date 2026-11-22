/** What-if changes, preview delta, save and submit as a plan (S-05, S-06). */
import { useEffect, useMemo, useState, type FormEvent } from 'react'
import { Plus, Send, Trash2 } from 'lucide-react'
import { Badge, Button, IconButton, Modal } from '../../ui'
import { api, ApiError } from './api'
import { CATEGORY_LABELS, day, exact, rupees, shortDay, toPaise } from './format'
import type { CashEvent, Override, Preview, Refusal, Scenario, SnapshotRef, View } from './types'
import { kindOf } from './copy'

type ChangeKind = 'move_payment' | 'move_receipt' | 'delay_customer' | 'collect_pct' | 'exclude_receipt' | 'add_item'
const CHANGE_LABELS: Record<ChangeKind, string> = {
  move_payment: 'Move payment',
  move_receipt: 'Move receipt',
  delay_customer: 'Delay customer',
  collect_pct: 'Collect only X%',
  exclude_receipt: 'Exclude receipt',
  add_item: 'Add item',
}

function describe(o: Override, events: Map<string, CashEvent>, customers: Map<string, string>): string {
  switch (o.op) {
    case 'shift_event': {
      const e = events.get(o.event_key)
      return `Move ${e?.label ?? o.event_key}${e ? ` ₹${exact(e.amount_paise)}` : ''} ${e?.date ? shortDay(e.date) + ' ' : ''}→ ${shortDay(o.to_date)}`
    }
    case 'exclude_event':
      return `Exclude ${events.get(o.event_key)?.label ?? o.event_key}`
    case 'delay_customer':
      return `Delay ${customers.get(o.customer_id) ?? 'customer'} by ${o.days} days`
    case 'haircut_customer':
      return `Collect only ${100 - o.percent}% from ${o.customer_id === '*' ? 'every customer' : (customers.get(o.customer_id) ?? 'customer')}`
    case 'add_item':
      return `Add ${o.direction === 'in' ? 'receipt' : 'payment'} “${o.label}” ${rupees(o.amount_paise)} on ${shortDay(o.on_date)}`
  }
}

export default function ScenarioPanel({
  snapshot,
  view,
  overrides,
  onChange,
  preview,
  previewing,
  refusals,
  canEdit,
  scenarios,
  active,
  onSaved,
  onSelect,
  onSubmitted,
}: {
  snapshot: SnapshotRef
  view: View
  overrides: Override[]
  onChange: (next: Override[]) => void
  preview: Preview | null
  previewing: boolean
  refusals: Refusal[]
  canEdit: boolean
  scenarios: Scenario[]
  active: Scenario | null
  onSaved: (s: Scenario) => void
  onSelect: (s: Scenario | null) => void
  onSubmitted: (message: string) => void
}) {
  const [events, setEvents] = useState<CashEvent[]>([])
  const [adding, setAdding] = useState<ChangeKind | null>(null)
  const [saving, setSaving] = useState<'save' | 'submit' | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    let live = true
    api.events(snapshot.snapshot_id, view).then(r => live && setEvents(r)).catch(() => undefined)
    return () => {
      live = false
    }
  }, [snapshot.snapshot_id, view])

  const byKey = useMemo(() => new Map(events.map(e => [e.event_key, e])), [events])
  const customers = useMemo(
    () => new Map(events.filter(e => e.source_type === 'ar_invoice' && e.counterparty_id).map(e => [e.counterparty_id!, e.counterparty ?? ''])),
    [events],
  )
  const dirty = !active || JSON.stringify(active.overrides) !== JSON.stringify(overrides) || active.view !== view
  const refusedAt = new Map(refusals.map(r => [r.index, r]))
  const m = preview?.scenario.metrics
  const b = preview?.baseline.metrics

  const add = (o: Override) => {
    onChange([...overrides, o])
    setAdding(null)
  }

  if (!overrides.length && !active) {
    return (
      <section className="cf-card cf-scenario" aria-labelledby="cf-scn-title">
        <div className="cf-card__head">
          <h2 id="cf-scn-title">Scenario</h2>
          {canEdit && (
            <Button size="sm" iconLeft={<Plus size={14} />} onClick={() => setAdding('move_payment')}>
              New scenario
            </Button>
          )}
        </div>
        <p className="cf-muted">
          No scenario applied. Try moving a supplier payment inside its agreed window, or test a late customer.
        </p>
        {scenarios.length > 0 && <SavedPicker scenarios={scenarios} active={active} onSelect={onSelect} />}
        {adding && canEdit && <AddChange kind={adding} setKind={setAdding} events={events} customers={customers} start={snapshot.start} end={snapshot.end} headroom={snapshot.od_headroom_paise} onAdd={add} />}
      </section>
    )
  }

  return (
    <section className="cf-card cf-scenario" aria-labelledby="cf-scn-title">
      <div className="cf-card__head">
        <h2 id="cf-scn-title">Scenario{active ? ` · ${active.name}` : ''}</h2>
        <span className="cf-muted cf-small">
          {view === 'expected' ? 'Expected' : view === 'downside' ? 'Downside' : 'No new collections'} · rev {snapshot.revision}
          {dirty && overrides.length > 0 && <> · <Badge tone="warn">Unsaved changes</Badge></>}
        </span>
      </div>
      {active?.status === 'needs_review' && (
        <p className="cf-warning" role="status">
          The forecast changed since this scenario was saved. Check the changes marked below, then save again.
        </p>
      )}
      {m && b && (
        <div className="cf-delta" aria-live="polite">
          <div>
            Lowest {rupees(b.minimum_closing_paise)} → <strong>{rupees(m.minimum_closing_paise)}</strong>{' '}
            ({rupees(m.minimum_closing_paise - b.minimum_closing_paise, { sign: true })})
          </div>
          <div>
            Breach {b.first_reserve_breach_date ? shortDay(b.first_reserve_breach_date) : 'none'} →{' '}
            {m.first_reserve_breach_date ? (
              <strong className="cf-bad">{shortDay(m.first_reserve_breach_date)}</strong>
            ) : (
              <strong className="cf-good">none ✓</strong>
            )}
          </div>
          <div>
            Closing {day(snapshot.end)} {rupees(b.closing_paise)} → {rupees(m.closing_paise)}
          </div>
        </div>
      )}
      {previewing && <p className="cf-muted cf-small" role="status">Updating preview…</p>}
      <ol className="cf-changes">
        {overrides.map((o, i) => {
          const kind = kindOf(o, byKey)
          const refused = refusedAt.get(i)
          const rebase = active?.rebase?.items.find(r => r.index === i && r.status !== 'ok')
          return (
            <li key={i} className={refused ? 'cf-change cf-change--refused' : 'cf-change'}>
              <Badge tone={kind === 'decision' ? 'brand' : 'warn'} title={kind === 'assumption' ? 'A prediction, not a decision. Not carried into future forecasts.' : undefined}>
                {kind === 'decision' ? 'DECISION' : 'ASSUMPTION'}
              </Badge>
              <span className="cf-change__text">{describe(o, byKey, customers)}</span>
              {canEdit && (
                <IconButton label="Remove change" icon={<Trash2 size={14} />} onClick={() => onChange(overrides.filter((_, j) => j !== i))} />
              )}
              {refused && <p role="alert" className="cf-error">{refused.message}</p>}
              {rebase && <p className="cf-warning">{rebase.message ?? 'Needs review'}</p>}
            </li>
          )
        })}
      </ol>
      {canEdit && (
        <div className="cf-add-row">
          <label className="cf-field cf-field--inline">
            <span className="cf-sr">Add a change</span>
            <select value="" onChange={e => setAdding(e.target.value as ChangeKind)} aria-label="Add a change">
              <option value="">+ Add change…</option>
              {(Object.keys(CHANGE_LABELS) as ChangeKind[]).map(k => (
                <option key={k} value={k}>
                  {CHANGE_LABELS[k]}
                </option>
              ))}
            </select>
          </label>
          {adding && <AddChange kind={adding} setKind={setAdding} events={events} customers={customers} start={snapshot.start} end={snapshot.end} headroom={snapshot.od_headroom_paise} onAdd={add} />}
        </div>
      )}
      {preview && view === 'expected' && overrides.length > 0 && <DownsideNote snapshot={snapshot} overrides={overrides} />}
      {scenarios.length > 0 && <SavedPicker scenarios={scenarios} active={active} onSelect={onSelect} />}
      {error && <p role="alert" className="cf-error">{error}</p>}
      {canEdit && (
        <div className="cf-form-actions">
          <Button variant="ghost" onClick={() => { onChange([]); onSelect(null) }}>
            Clear
          </Button>
          <Button variant="secondary" disabled={!overrides.length || refusals.length > 0} onClick={() => setSaving('save')}>
            Save
          </Button>
          <Button iconRight={<Send size={14} />} disabled={!overrides.length || refusals.length > 0 || previewing} onClick={() => setSaving('submit')}>
            Submit as plan
          </Button>
        </div>
      )}
      {saving && (
        <SaveDialog
          mode={saving}
          active={active}
          dirty={dirty}
          preview={preview}
          overrides={overrides}
          kinds={overrides.map(o => kindOf(o, byKey))}
          snapshot={snapshot}
          view={view}
          onClose={() => setSaving(null)}
          onSaved={s => onSaved(s)}
          onSubmitted={msg => {
            setSaving(null)
            onSubmitted(msg)
          }}
          onError={setError}
        />
      )}
    </section>
  )
}

function SavedPicker({ scenarios, active, onSelect }: { scenarios: Scenario[]; active: Scenario | null; onSelect: (s: Scenario | null) => void }) {
  return (
    <label className="cf-field cf-saved">
      Saved scenarios
      <select value={active?.id ?? ''} onChange={e => onSelect(scenarios.find(s => s.id === e.target.value) ?? null)}>
        <option value="">—</option>
        {scenarios.map(s => (
          <option key={s.id} value={s.id}>
            {s.name}
          </option>
        ))}
      </select>
    </label>
  )
}

function DownsideNote({ snapshot, overrides }: { snapshot: SnapshotRef; overrides: Override[] }) {
  const [text, setText] = useState('')
  useEffect(() => {
    let live = true
    api
      .preview(snapshot.snapshot_id, snapshot.revision, 'downside', overrides)
      .then(p => {
        if (!live) return
        const m = p.scenario.metrics
        setText(
          m.first_reserve_breach_date
            ? `Downside with this scenario: lowest ${rupees(m.minimum_closing_paise)} on ${shortDay(m.minimum_date)}; below reserve from ${shortDay(m.first_reserve_breach_date)}.`
            : `Downside with this scenario stays above reserve; lowest ${rupees(m.minimum_closing_paise)} on ${shortDay(m.minimum_date)}.`,
        )
      })
      .catch(() => live && setText(''))
    return () => {
      live = false
    }
  }, [snapshot.snapshot_id, snapshot.revision, overrides])
  return text ? <p className="cf-muted cf-small">{text}</p> : null
}

function AddChange({
  kind,
  setKind,
  events,
  customers,
  start,
  end,
  headroom,
  onAdd,
}: {
  kind: ChangeKind
  setKind: (k: ChangeKind | null) => void
  events: CashEvent[]
  customers: Map<string, string>
  start: string
  end: string
  headroom: number
  onAdd: (o: Override) => void
}) {
  const [error, setError] = useState('')
  const payments = events.filter(e => e.direction === 'out' && !e.fixed)
  const receipts = events.filter(e => e.source_type === 'ar_invoice')
  const option = (e: CashEvent) => (
    <option key={e.event_key} value={e.event_key}>
      {e.label} · ₹{exact(e.amount_paise)} · {e.date ? shortDay(e.date) : ''}
      {e.window ? ` · window to ${shortDay(e.window.latest)}` : ''}
    </option>
  )
  const submit = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    setError('')
    const f = new FormData(e.currentTarget)
    const s = (k: string) => String(f.get(k) ?? '')
    if (kind === 'move_payment' || kind === 'move_receipt') onAdd({ op: 'shift_event', event_key: s('event'), to_date: s('date') })
    else if (kind === 'exclude_receipt') onAdd({ op: 'exclude_event', event_key: s('event') })
    else if (kind === 'delay_customer') onAdd({ op: 'delay_customer', customer_id: s('customer'), days: Number(s('days')) })
    else if (kind === 'collect_pct') onAdd({ op: 'haircut_customer', customer_id: s('customer'), percent: 100 - Number(s('pct')) })
    else {
      const amount = toPaise(s('amount'))
      if (!amount || amount <= 0) return setError('Enter an amount in rupees.')
      if (s('category') === 'financing' && s('direction') === 'in' && amount > headroom)
        return setError(`That's more than the ${rupees(headroom)} available on your cash-credit line.`)
      onAdd({
        op: 'add_item',
        label: s('label'),
        direction: s('direction') as 'in' | 'out',
        amount_paise: amount,
        on_date: s('date'),
        category: s('category'),
        confidence: s('confidence') as 'committed' | 'estimated',
      })
    }
  }
  return (
    <form className="cf-inline-form" onSubmit={submit} aria-label={CHANGE_LABELS[kind]}>
      <h3>{CHANGE_LABELS[kind]}</h3>
      {(kind === 'move_payment' || kind === 'move_receipt' || kind === 'exclude_receipt') && (
        <label className="cf-field">
          {kind === 'move_payment' ? 'Payment' : 'Receipt'}
          <select name="event" required defaultValue="">
            <option value="" disabled>
              Choose…
            </option>
            {(kind === 'move_payment' ? payments : receipts).map(option)}
          </select>
        </label>
      )}
      {(kind === 'move_payment' || kind === 'move_receipt') && (
        <label className="cf-field">
          New date
          <input name="date" type="date" min={start} required />
        </label>
      )}
      {(kind === 'delay_customer' || kind === 'collect_pct') && (
        <label className="cf-field">
          Customer
          <select name="customer" required defaultValue="">
            <option value="" disabled>
              Choose…
            </option>
            {kind === 'collect_pct' && <option value="*">Every customer</option>}
            {[...customers.entries()].sort((a, b) => a[1].localeCompare(b[1])).map(([id, name]) => (
              <option key={id} value={id}>
                {name}
              </option>
            ))}
          </select>
        </label>
      )}
      {kind === 'delay_customer' && (
        <label className="cf-field">
          Days later
          <input name="days" type="number" min={1} max={90} defaultValue={10} required />
        </label>
      )}
      {kind === 'collect_pct' && (
        <label className="cf-field">
          Collect (%)
          <input name="pct" type="number" min={0} max={100} defaultValue={50} required />
        </label>
      )}
      {kind === 'add_item' && (
        <>
          <label className="cf-field">
            Label
            <input name="label" required maxLength={120} />
          </label>
          <label className="cf-field">
            Direction
            <select name="direction" defaultValue="out">
              <option value="out">Payment</option>
              <option value="in">Receipt</option>
            </select>
          </label>
          <label className="cf-field">
            Amount (₹)
            <input name="amount" inputMode="decimal" required />
          </label>
          <label className="cf-field">
            Date
            <input name="date" type="date" min={start} max={end} required />
          </label>
          <label className="cf-field">
            Category
            <select name="category" defaultValue="other">
              {Object.entries(CATEGORY_LABELS).map(([k, v]) => (
                <option key={k} value={k}>
                  {v}
                </option>
              ))}
            </select>
          </label>
          <label className="cf-field">
            Confidence
            <select name="confidence" defaultValue="estimated">
              <option value="committed">Committed (a decision)</option>
              <option value="estimated">Estimated (an assumption)</option>
            </select>
          </label>
        </>
      )}
      {error && <p role="alert" className="cf-error">{error}</p>}
      <div className="cf-form-actions">
        <Button type="button" variant="ghost" onClick={() => setKind(null)}>
          Cancel
        </Button>
        <Button type="submit">Add</Button>
      </div>
    </form>
  )
}

function SaveDialog({
  mode,
  active,
  dirty,
  preview,
  overrides,
  kinds,
  snapshot,
  view,
  onClose,
  onSaved,
  onSubmitted,
  onError,
}: {
  mode: 'save' | 'submit'
  active: Scenario | null
  dirty: boolean
  preview: Preview | null
  overrides: Override[]
  kinds: ('decision' | 'assumption')[]
  snapshot: SnapshotRef
  view: View
  onClose: () => void
  onSaved: (s: Scenario) => void
  onSubmitted: (message: string) => void
  onError: (m: string) => void
}) {
  const [name, setName] = useState(active?.name ?? '')
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const m = preview?.scenario.metrics
  const b = preview?.baseline.metrics
  const decisions = kinds.filter(k => k === 'decision').length

  const go = async (e: FormEvent) => {
    e.preventDefault()
    if (mode === 'submit' && !note.trim()) return setError('Add a note for the approver.')
    setBusy(true)
    setError('')
    try {
      let scenario = active
      if (!scenario || dirty || scenario.name !== name || scenario.revision !== snapshot.revision) {
        const body = { name: name.trim(), snapshot_id: snapshot.snapshot_id, view, overrides }
        scenario = scenario
          ? await api.updateScenario(scenario.id, { ...body, expected_version: scenario.version })
          : await api.createScenario(body)
        onSaved(scenario)
      }
      if (mode === 'submit') {
        await api.createPlan(scenario.id, note.trim())
        onSubmitted('Plan submitted for approval.')
      } else {
        onClose()
      }
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : 'Couldn’t save.'
      setError(msg)
      onError('')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal
      open
      onClose={onClose}
      title={mode === 'submit' ? 'Submit cash plan for approval' : 'Save scenario'}
      closeOnBackdrop={false}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" form="cf-save-form" loading={busy}>
            {mode === 'submit' ? 'Submit plan' : 'Save scenario'}
          </Button>
        </>
      }
    >
      <form id="cf-save-form" onSubmit={go} className="cf-dialog-form">
        <label className="cf-field">
          Scenario name
          <input value={name} onChange={e => setName(e.target.value)} required maxLength={120} />
        </label>
        {mode === 'submit' && (
          <>
            <p className="cf-muted cf-small">
              {view === 'expected' ? 'Expected' : view === 'downside' ? 'Downside' : 'No new collections'} view · revision {snapshot.revision}
            </p>
            {m && b && (
              <dl className="cf-compare">
                <div>
                  <dt>Lowest balance</dt>
                  <dd>
                    {rupees(b.minimum_closing_paise)} → {rupees(m.minimum_closing_paise)}
                  </dd>
                </div>
                <div>
                  <dt>Reserve breach</dt>
                  <dd>
                    {b.first_reserve_breach_date ? shortDay(b.first_reserve_breach_date) : 'none'} →{' '}
                    {m.first_reserve_breach_date ? shortDay(m.first_reserve_breach_date) : 'none'}
                  </dd>
                </div>
              </dl>
            )}
            <p>
              {decisions} decision{decisions === 1 ? '' : 's'} · {kinds.length - decisions} assumption
              {kinds.length - decisions === 1 ? '' : 's'}
            </p>
            <label className="cf-field">
              Note for approver (required)
              <textarea value={note} onChange={e => setNote(e.target.value)} rows={3} maxLength={2000} />
            </label>
            <p className="cf-notice">Approval records the plan. It doesn’t pay or schedule anything.</p>
          </>
        )}
        {error && <p role="alert" className="cf-error">{error}</p>}
      </form>
    </Modal>
  )
}
