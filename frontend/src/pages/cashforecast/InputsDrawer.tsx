/** Forecast inputs (S-04): balances, recurring obligations, adjustments, windows, promises, settings. */
import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { Trash2 } from 'lucide-react'
import { Badge, Button, IconButton } from '../../ui'
import { api, ApiError } from './api'
import { Drawer } from './Drawers'
import { CATEGORY_LABELS, exact, rupees, shortDay, stamp, toPaise } from './format'
import type { Account, Adjustment, Me, PromiseRow, RecurringItem, Settings, WindowRow } from './types'

export type InputsTab = 'balances' | 'recurring' | 'adjustments' | 'windows' | 'promises' | 'settings'
const TABS: { key: InputsTab; label: string }[] = [
  { key: 'balances', label: 'Balances' },
  { key: 'recurring', label: 'Recurring' },
  { key: 'adjustments', label: 'Adjustments' },
  { key: 'windows', label: 'Payment windows' },
  { key: 'promises', label: 'Promises' },
  { key: 'settings', label: 'Settings' },
]

function useLoad<T>(fn: () => Promise<T>, deps: unknown[]) {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState('')
  const [n, setN] = useState(0)
  // eslint-disable-next-line react-hooks/exhaustive-deps -- deps are the caller's
  const load = useCallback(fn, deps)
  useEffect(() => {
    let live = true
    setError('')
    load()
      .then(d => live && setData(d))
      .catch((e: unknown) => live && setError(e instanceof ApiError ? e.message : 'Couldn’t load.'))
    return () => {
      live = false
    }
  }, [load, n])
  return { data, error, reload: () => setN(x => x + 1) }
}

export default function InputsDrawer({
  open,
  tab,
  onTab,
  me,
  onClose,
  onChanged,
}: {
  open: boolean
  tab: InputsTab
  onTab: (t: InputsTab) => void
  me: Me
  onClose: () => void
  onChanged: (message: string) => void
}) {
  const tabs = TABS.filter(t => t.key !== 'settings' || me.can.view)
  return (
    <Drawer open={open} onClose={onClose} title="Forecast inputs" wide>
      <div className="cf-tabs" role="tablist" aria-label="Input type">
        {tabs.map(t => (
          <button key={t.key} type="button" role="tab" aria-selected={tab === t.key} className="cf-tab" onClick={() => onTab(t.key)}>
            {t.label}
          </button>
        ))}
      </div>
      <div role="tabpanel">
        {tab === 'balances' && <Balances me={me} onChanged={onChanged} />}
        {tab === 'recurring' && <Recurring me={me} onChanged={onChanged} />}
        {tab === 'adjustments' && <Adjustments me={me} onChanged={onChanged} />}
        {tab === 'windows' && <Windows me={me} onChanged={onChanged} />}
        {tab === 'promises' && <Promises me={me} onChanged={onChanged} />}
        {tab === 'settings' && <SettingsTab me={me} onChanged={onChanged} />}
      </div>
    </Drawer>
  )
}

type TabProps = { me: Me; onChanged: (m: string) => void }

function Err({ text }: { text: string }) {
  return text ? (
    <p role="alert" className="cf-error">
      {text}
    </p>
  ) : null
}

function nowLocal(): string {
  const d = new Date()
  d.setMinutes(d.getMinutes() - d.getTimezoneOffset())
  return d.toISOString().slice(0, 16)
}

export function BalanceForm({ accounts, onSaved }: { accounts: Account[]; onSaved: (m: string) => void }) {
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const included = accounts.filter(a => a.include_in_forecast)
  const submit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    const f = new FormData(e.currentTarget)
    const amount = toPaise(String(f.get('amount')))
    if (amount === null) return setError('Enter the balance in rupees, e.g. 43,51,482.50.')
    const asOf = new Date(String(f.get('asof')))
    if (Number.isNaN(asOf.getTime())) return setError('Enter when the balance was read.')
    setBusy(true)
    setError('')
    try {
      await api.addBalance(String(f.get('account')), amount, asOf.toISOString())
      onSaved('Balance saved. Refresh the forecast to use it.')
      e.currentTarget?.reset?.()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Couldn’t save the balance.')
    } finally {
      setBusy(false)
    }
  }
  return (
    <form className="cf-inline-form" onSubmit={submit} aria-label="Add a bank balance">
      <h3>Add today’s balance</h3>
      <label className="cf-field">
        Account
        <select name="account" required>
          {(included.length ? included : accounts).map(a => (
            <option key={a.bank_account_id} value={a.bank_account_id}>
              {a.account_name} {a.account_mask ?? ''}
            </option>
          ))}
        </select>
      </label>
      <label className="cf-field">
        Balance (₹)
        <input name="amount" inputMode="decimal" required />
      </label>
      <label className="cf-field">
        As of
        <input name="asof" type="datetime-local" defaultValue={nowLocal()} required />
      </label>
      <Err text={error} />
      <div className="cf-form-actions">
        <Button type="submit" loading={busy}>
          Save balance
        </Button>
      </div>
    </form>
  )
}

function Balances({ me, onChanged }: TabProps) {
  const { data, error, reload } = useLoad(() => api.accounts(), [])
  const [err, setErr] = useState('')
  const toggle = async (a: Account) => {
    try {
      await api.patchAccount(a.bank_account_id, { include_in_forecast: !a.include_in_forecast })
      reload()
      onChanged('Account updated. Refresh the forecast to use it.')
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : 'Couldn’t update the account.')
    }
  }
  return (
    <>
      <Err text={error || err} />
      {data && (
        <table className="cf-table">
          <thead>
            <tr>
              <th scope="col">Account</th>
              <th scope="col" className="cf-num">Balance</th>
              <th scope="col">As of</th>
              <th scope="col">In forecast</th>
            </tr>
          </thead>
          <tbody>
            {data.map(a => (
              <tr key={a.bank_account_id}>
                <th scope="row">
                  {a.account_name} <span className="cf-muted">{a.account_mask}</span>
                  {a.account_type === 'OVERDRAFT' && a.od_limit_paise > 0 && <div className="cf-small cf-muted">Limit {rupees(a.od_limit_paise)}</div>}
                </th>
                <td className="cf-num">{a.balance_paise == null ? '—' : exact(a.balance_paise, { symbol: true })}</td>
                <td>{a.as_of ? `${stamp(a.as_of)} · ${a.source}` : 'No balance'}</td>
                <td>
                  {me.can.settings ? (
                    <input type="checkbox" checked={a.include_in_forecast} aria-label={`Include ${a.account_name} in forecast`} onChange={() => toggle(a)} />
                  ) : a.include_in_forecast ? (
                    'Yes'
                  ) : (
                    'No'
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {data && me.can.edit && <BalanceForm accounts={data} onSaved={m => { reload(); onChanged(m) }} />}
    </>
  )
}

const WEEKDAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']

function when(r: RecurringItem): string {
  const anchor =
    r.frequency === 'weekly'
      ? WEEKDAYS[Number(r.anchor)] ?? r.anchor
      : r.anchor === 'last_banking_day'
        ? 'last banking day'
        : `${r.anchor}${['th', 'st', 'nd', 'rd'][Number(r.anchor) % 10 > 3 || [11, 12, 13].includes(Number(r.anchor)) ? 0 : Number(r.anchor) % 10]}`
  const roll = r.business_day_rule === 'previous_banking_day' ? ' · prev day' : ''
  return `${r.frequency[0].toUpperCase()}${r.frequency.slice(1)} · ${anchor}${roll}`
}

function Recurring({ me, onChanged }: TabProps) {
  const { data, error, reload } = useLoad(() => api.recurring(), [])
  const [editing, setEditing] = useState<RecurringItem | 'new' | null>(null)
  const [err, setErr] = useState('')
  const act = async (fn: () => Promise<unknown>, msg: string) => {
    setErr('')
    try {
      await fn()
      reload()
      onChanged(msg)
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : 'Couldn’t save.')
    }
  }
  return (
    <>
      <div className="cf-card__head">
        <h3>Recurring obligations{data ? ` (${data.length})` : ''}</h3>
        {me.can.edit && (
          <div className="cf-form-actions">
            <Button size="sm" variant="secondary" onClick={() => act(() => api.seedTemplates(), 'Statutory templates added. Fill in their amounts.')}>
              Templates
            </Button>
            <Button size="sm" onClick={() => setEditing('new')}>
              + Add
            </Button>
          </div>
        )}
      </div>
      <Err text={error || err} />
      {data && (
        <table className="cf-table">
          <thead>
            <tr>
              <th scope="col">Name</th>
              <th scope="col" className="cf-num">Amount</th>
              <th scope="col">When</th>
              {me.can.edit && <th scope="col"><span className="cf-sr">Actions</span></th>}
            </tr>
          </thead>
          <tbody>
            {data.map(r => (
              <tr key={r.id}>
                <th scope="row">
                  {r.name} {r.confidence === 'estimated' && <Badge tone="warn">est.</Badge>}
                </th>
                <td className="cf-num">{r.amount_paise ? rupees(r.amount_paise) : <Badge tone="warn">Needs amount</Badge>}</td>
                <td>{when(r)}</td>
                {me.can.edit && (
                  <td className="cf-row-actions">
                    <Button size="sm" variant="ghost" onClick={() => setEditing(r)}>
                      Edit
                    </Button>
                    <IconButton label={`Remove ${r.name}`} icon={<Trash2 size={14} />} onClick={() => act(() => api.deleteRecurring(r.id), 'Item removed.')} />
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {editing && (
        <RecurringForm
          item={editing === 'new' ? null : editing}
          onCancel={() => setEditing(null)}
          onSave={body =>
            act(
              () => (editing === 'new' ? api.createRecurring(body) : api.updateRecurring(editing.id, { ...body, expected_version: editing.version })),
              'Saved. Refresh the forecast to use it.',
            ).then(() => setEditing(null))
          }
        />
      )}
    </>
  )
}

function RecurringForm({
  item,
  onSave,
  onCancel,
}: {
  item: RecurringItem | null
  onSave: (b: Omit<RecurringItem, 'id' | 'version'>) => void
  onCancel: () => void
}) {
  const [freq, setFreq] = useState(item?.frequency ?? 'monthly')
  const [error, setError] = useState('')
  const submit = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    const f = new FormData(e.currentTarget)
    const s = (k: string) => String(f.get(k) ?? '')
    const amountText = s('amount').trim()
    const amount = amountText ? toPaise(amountText) : null
    if (amountText && (!amount || amount <= 0)) return setError('Enter a positive amount, or leave it blank for a template.')
    onSave({
      name: s('name'),
      category: s('category'),
      direction: 'out',
      amount_paise: amount,
      frequency: freq,
      anchor: s('anchor'),
      quarter_months: freq === 'quarterly' ? s('months').split(',').map(x => Number(x.trim())).filter(Boolean) : null,
      business_day_rule: s('rule') as RecurringItem['business_day_rule'],
      confidence: s('confidence') as RecurringItem['confidence'],
      statutory: s('category') === 'statutory',
      start_date: s('start'),
      end_date: s('end') || null,
    })
  }
  return (
    <form className="cf-inline-form" onSubmit={submit} aria-label={item ? 'Edit recurring item' : 'Add recurring item'}>
      <h3>{item ? `Edit ${item.name}` : 'Add recurring item'}</h3>
      <label className="cf-field">
        Name
        <input name="name" defaultValue={item?.name} required maxLength={120} />
      </label>
      <label className="cf-field">
        Category
        <select name="category" defaultValue={item?.category ?? 'other'}>
          {Object.entries(CATEGORY_LABELS)
            .filter(([k]) => k !== 'customer' && k !== 'supplier')
            .map(([k, v]) => (
              <option key={k} value={k}>
                {v}
              </option>
            ))}
        </select>
      </label>
      <label className="cf-field">
        Amount (₹)
        <input name="amount" inputMode="decimal" defaultValue={item?.amount_paise ? exact(item.amount_paise) : ''} />
      </label>
      <label className="cf-field">
        Frequency
        <select value={freq} onChange={e => setFreq(e.target.value as RecurringItem['frequency'])}>
          <option value="weekly">Weekly</option>
          <option value="monthly">Monthly</option>
          <option value="quarterly">Quarterly</option>
        </select>
      </label>
      <label className="cf-field">
        {freq === 'weekly' ? 'Weekday' : 'Day of month'}
        {freq === 'weekly' ? (
          <select name="anchor" defaultValue={item?.anchor ?? '0'}>
            {WEEKDAYS.map((w, i) => (
              <option key={w} value={String(i)}>
                {w}
              </option>
            ))}
          </select>
        ) : (
          <select name="anchor" defaultValue={item?.anchor ?? '1'}>
            <option value="last_banking_day">Last banking day</option>
            {Array.from({ length: 31 }, (_, i) => (
              <option key={i + 1} value={String(i + 1)}>
                {i + 1}
              </option>
            ))}
          </select>
        )}
      </label>
      {freq === 'quarterly' && (
        <label className="cf-field">
          Months (comma separated)
          <input name="months" defaultValue={item?.quarter_months?.join(', ') ?? '6, 9, 12, 3'} required />
        </label>
      )}
      <label className="cf-field">
        If not a banking day
        <select name="rule" defaultValue={item?.business_day_rule ?? 'next_banking_day'}>
          <option value="previous_banking_day">Pay the previous banking day</option>
          <option value="next_banking_day">Pay the next banking day</option>
        </select>
      </label>
      <label className="cf-field">
        Confidence
        <select name="confidence" defaultValue={item?.confidence ?? 'committed'}>
          <option value="committed">Committed</option>
          <option value="estimated">Estimated</option>
        </select>
      </label>
      <label className="cf-field">
        Starts
        <input name="start" type="date" defaultValue={item?.start_date ?? new Date().toISOString().slice(0, 10)} required />
      </label>
      <label className="cf-field">
        Ends
        <input name="end" type="date" defaultValue={item?.end_date ?? ''} />
      </label>
      <Err text={error} />
      <div className="cf-form-actions">
        <Button type="button" variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
        <Button type="submit">Save</Button>
      </div>
    </form>
  )
}

function Adjustments({ me, onChanged }: TabProps) {
  const { data, error, reload } = useLoad(() => api.adjustments(), [])
  const [err, setErr] = useState('')
  const submit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    const form = e.currentTarget
    const f = new FormData(form)
    const s = (k: string) => String(f.get(k) ?? '')
    const amount = toPaise(s('amount'))
    if (!amount || amount <= 0) return setErr('Enter a positive amount in rupees.')
    setErr('')
    try {
      await api.createAdjustment({
        name: s('name'),
        category: s('category'),
        direction: s('direction') as 'in' | 'out',
        amount_paise: amount,
        on_date: s('date'),
        confidence: s('confidence') as 'committed' | 'estimated',
        note: s('note') || null,
      })
      form.reset()
      reload()
      onChanged('Adjustment saved. Refresh the forecast to use it.')
    } catch (er) {
      setErr(er instanceof ApiError ? er.message : 'Couldn’t save.')
    }
  }
  return (
    <>
      <Err text={error || err} />
      {data && (
        <table className="cf-table">
          <thead>
            <tr>
              <th scope="col">Item</th>
              <th scope="col">Date</th>
              <th scope="col" className="cf-num">Amount</th>
              {me.can.edit && <th scope="col"><span className="cf-sr">Actions</span></th>}
            </tr>
          </thead>
          <tbody>
            {data.map(a => (
              <tr key={a.id}>
                <th scope="row">
                  {a.name} {a.confidence === 'estimated' && <Badge tone="warn">est.</Badge>} {a.plan_id && <Badge tone="brand">From plan</Badge>}
                </th>
                <td>{shortDay(a.on_date)}</td>
                <td className="cf-num">{rupees(a.direction === 'in' ? a.amount_paise : -a.amount_paise, { sign: true })}</td>
                {me.can.edit && (
                  <td>
                    <IconButton label={`Remove ${a.name}`} icon={<Trash2 size={14} />} onClick={async () => {
                      await api.deleteAdjustment(a.id).catch(() => undefined)
                      reload()
                      onChanged('Adjustment removed.')
                    }} />
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {data && !data.length && <p className="cf-muted">No one-off items. Add things that aren’t in bills: insurance, capex, refunds.</p>}
      {me.can.edit && (
        <form className="cf-inline-form" onSubmit={submit} aria-label="Add adjustment">
          <h3>Add one-off item</h3>
          <label className="cf-field">
            Name
            <input name="name" required maxLength={120} />
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
            <input name="date" type="date" required />
          </label>
          <label className="cf-field">
            Confidence
            <select name="confidence" defaultValue="committed">
              <option value="committed">Committed</option>
              <option value="estimated">Estimated</option>
            </select>
          </label>
          <label className="cf-field">
            Note
            <input name="note" maxLength={1000} />
          </label>
          <div className="cf-form-actions">
            <Button type="submit">Add</Button>
          </div>
        </form>
      )}
    </>
  )
}

function Windows({ me, onChanged }: TabProps) {
  const { data, error, reload } = useLoad(() => api.windows(), [])
  return (
    <>
      <p className="cf-muted cf-small">Record a supplier’s agreement from the day view: open a bill and choose “Agreed later date”.</p>
      <Err text={error} />
      {data && !data.length && <p className="cf-muted">No agreed payment windows.</p>}
      {data && data.length > 0 && (
        <table className="cf-table">
          <thead>
            <tr>
              <th scope="col">Agreed with</th>
              <th scope="col">Window</th>
              <th scope="col">Evidence</th>
              {me.can.edit && <th scope="col"><span className="cf-sr">Actions</span></th>}
            </tr>
          </thead>
          <tbody>
            {data.map((w: WindowRow) => (
              <tr key={w.id}>
                <th scope="row">{w.agreed_with}</th>
                <td>
                  {shortDay(w.earliest_date)} – {shortDay(w.latest_date)}
                </td>
                <td>{w.evidence}</td>
                {me.can.edit && (
                  <td>
                    <IconButton label={`Remove window for ${w.agreed_with}`} icon={<Trash2 size={14} />} onClick={async () => {
                      await api.deleteWindow(w.id).catch(() => undefined)
                      reload()
                      onChanged('Window removed.')
                    }} />
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  )
}

function Promises({ me, onChanged }: TabProps) {
  const { data, error, reload } = useLoad(() => api.promises(), [])
  return (
    <>
      <p className="cf-muted cf-small">Record a promise from the day view: open a customer receipt and choose “Promise to pay”.</p>
      <Err text={error} />
      {data && !data.length && <p className="cf-muted">No promises recorded.</p>}
      {data && data.length > 0 && (
        <table className="cf-table">
          <thead>
            <tr>
              <th scope="col">Promised</th>
              <th scope="col" className="cf-num">Amount</th>
              <th scope="col">How</th>
              {me.can.edit && <th scope="col"><span className="cf-sr">Actions</span></th>}
            </tr>
          </thead>
          <tbody>
            {data.map((p: PromiseRow) => (
              <tr key={p.id}>
                <th scope="row">{shortDay(p.promised_date)}</th>
                <td className="cf-num">{rupees(p.promised_amount_paise)}</td>
                <td>
                  {p.source}
                  {p.note ? ` · ${p.note}` : ''}
                </td>
                {me.can.edit && (
                  <td>
                    <IconButton label="Remove promise" icon={<Trash2 size={14} />} onClick={async () => {
                      await api.deletePromise(p.id).catch(() => undefined)
                      reload()
                      onChanged('Promise removed.')
                    }} />
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  )
}

function SettingsTab({ me, onChanged }: TabProps) {
  const { data, error, reload } = useLoad(() => api.settings(), [])
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  if (!data) return <Err text={error} />
  const readOnly = !me.can.settings
  const submit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    const f = new FormData(e.currentTarget)
    const reserve = toPaise(String(f.get('reserve')))
    if (reserve === null || reserve < 0) return setErr('Enter the reserve in rupees.')
    setBusy(true)
    setErr('')
    try {
      await api.saveSettings({
        reserve_paise: reserve,
        horizon_days: Number(f.get('horizon')),
        include_pending_approval_ap: f.get('pending') === 'on',
        allow_self_approval: f.get('self') === 'on',
      } as Partial<Settings>)
      reload()
      onChanged('Settings saved. Refresh the forecast to use them.')
    } catch (er) {
      setErr(er instanceof ApiError ? er.message : 'Couldn’t save settings.')
    } finally {
      setBusy(false)
    }
  }
  return (
    <form className="cf-inline-form" onSubmit={submit} aria-label="Forecast settings">
      {readOnly && <p className="cf-muted cf-small">Only an owner or admin can change these.</p>}
      <fieldset disabled={readOnly} className="cf-fieldset">
        <label className="cf-field">
          Cash reserve (₹)
          <input name="reserve" inputMode="decimal" defaultValue={exact(data.reserve_paise)} />
        </label>
        <label className="cf-field">
          Horizon (days)
          <input name="horizon" type="number" min={7} max={91} defaultValue={data.horizon_days} />
        </label>
        <label className="cf-check">
          <input name="pending" type="checkbox" defaultChecked={data.include_pending_approval_ap} /> Count bills still in approval
        </label>
        <label className="cf-check">
          <input name="self" type="checkbox" defaultChecked={data.allow_self_approval} /> Let the submitter approve their own plan
        </label>
        <p className="cf-muted cf-small">
          Holidays: {data.holidays.length ? data.holidays.map(h => `${shortDay(h.date)} ${h.name}`).join(' · ') : 'none set'}
        </p>
      </fieldset>
      <Err text={err} />
      {!readOnly && (
        <div className="cf-form-actions">
          <Button type="submit" loading={busy}>
            Save settings
          </Button>
        </div>
      )}
    </form>
  )
}

export type { Adjustment }
