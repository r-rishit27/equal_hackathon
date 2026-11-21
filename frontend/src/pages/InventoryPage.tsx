import { useEffect, useState, type FormEvent } from 'react'
import { useAuth } from '../auth/AuthContext'
import './inventory.css'

interface Price {
  id: string; billed_units: string | number; sku: string | null; item: string; unit: string; price: number | string
  supplier: string; bill_date: string; bill_number: string | null
}
interface Projection {
  units: number; spend_paise: number; reasons: string[]; price_basis: string
  days: { date: string; incoming: number; closing: number; unmet: number; no_order_closing: number }[]
}
interface Run { result: Projection; price: Price; start: string; budget: number }
const base = (import.meta.env.VITE_API_URL ?? '') + '/api/finance-desk/inventory'
const money = (rupees: number) => rupees.toLocaleString('en-IN', { style: 'currency', currency: 'INR' })
const today = () => new Date().toLocaleDateString('en-CA')

function Planner() {
  const [prices, setPrices] = useState<Price[]>([])
  const [loading, setLoading] = useState(true)
  const [request, setRequest] = useState(0)
  const [error, setError] = useState('')
  const [selected, setSelected] = useState('')
  const [runs, setRuns] = useState<Run[]>([])
  const [busy, setBusy] = useState(false)
  useEffect(() => {
    const controller = new AbortController()
    setLoading(true)
    setError('')
    async function load() {
      try {
        const response = await fetch(base + '/prices', { signal: controller.signal })
        if (!response.ok) throw new Error(response.status === 403 ? 'Your account does not have inventory planning access.' : 'Unable to load supplier prices.')
        const data: Price[] = await response.json()
        if (!controller.signal.aborted) { setPrices(data); setSelected(data[0]?.id ?? '') }
      } catch (e) {
        if (!controller.signal.aborted) setError(e instanceof Error ? e.message : 'Unable to load prices.')
      } finally {
        if (!controller.signal.aborted) setLoading(false)
      }
    }
    void load()
    return () => controller.abort()
  }, [request])
  const price = prices.find(p => p.id === selected)

  async function calculate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!price) return
    const fields = new FormData(event.currentTarget)
    const number = (key: string) => Number(fields.get(key))
    const start = String(fields.get('start'))
    const budget = number('budget')
    setBusy(true)
    setError('')
    try {
      const response = await fetch(base + '/compare', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          line_id: price.id, start, on_hand: number('stock'), reserved: number('reserved'),
          daily_demand: number('demand'), lead_days: number('lead'), minimum_order: number('minimum'),
          pack: number('pack'), spendable_paise: Math.round(budget * 100),
          inbound_units: number('inbound'), inbound_date: fields.get('inboundDate') || null,
          quote_expiry: fields.get('expiry') || null,
          landed_unit_paise: fields.get('quote') ? Math.round(number('quote') * 100) : null,
        }),
      })
      if (!response.ok) {
        const body = await response.json()
        throw new Error(typeof body.detail === 'string' ? body.detail : 'Check the quantities, dates, and amounts.')
      }
      const result: Projection = await response.json()
      setRuns(previous => [{ price, result, start, budget }, ...previous])
    } catch (e) { setError(e instanceof Error ? e.message : 'Unable to calculate the order.') }
    finally { setBusy(false) }
  }
  return <main className="inventory-desk">
    <header><p>Finance Desk</p><h1>Inventory optimization</h1>
      <p>Plan seven days of stock using supplier bill prices and confirmed purchasing terms.</p></header>
    {loading && <p role="status">Loading bill lines…</p>}
    {error && <p role="alert">{error} {!prices.length && <button onClick={() => setRequest(n => n + 1)}>Retry</button>}</p>}
    {!loading && !error && !prices.length && <p>No priced INR bill lines with a supplier and unit are available for this account.</p>}
    {price && <form onSubmit={calculate}>
      <label>Supplier bill line<select value={selected} onChange={e => setSelected(e.target.value)}>
        {prices.map(p => <option value={p.id} key={p.id}>{p.item} · {p.supplier} · {p.bill_date} · {money(Number(p.price))}/{p.unit}</option>)}
      </select></label>
      <p>Bill {price.bill_number || price.id} · {price.bill_date} · {price.sku || price.item}</p>
      <fieldset className="inventory-controls" key={price.id}><legend>Planning inputs · {price.unit}</legend>
        <label>Start date<input name="start" type="date" min={price.bill_date} defaultValue={today()} required /></label>
        <label>Stock on hand<input name="stock" type="number" min="0" required /></label>
        <label>Reserved stock<input name="reserved" type="number" min="0" required /></label>
        <label>Daily demand<input name="demand" type="number" min="1" required /></label>
        <label>Firm inbound units (optional)<input name="inbound" type="number" min="0" /></label>
        <label>Firm inbound date<input name="inboundDate" type="date" /></label>
        <label>Lead time (days)<input name="lead" type="number" min="0" max="365" required /></label>
        <label>Minimum order<input name="minimum" type="number" min="1" required /></label>
        <label>Units per pack<input name="pack" type="number" min="1" required /></label>
        <label>Cash after commitments and reserve (₹)<input name="budget" type="number" step=".01" min="0" required /></label>
        <label>Confirmed landed price per unit (₹, optional)<input name="quote" type="number" step=".01" min=".01" /></label>
        <label>Quote valid through<input name="expiry" type="date" /></label>
      </fieldset>
      <p>Assumes full payment at order and delivery before demand on arrival day. Enter a landed price to include freight and taxes.</p>
      <button type="submit" disabled={busy}>{busy ? 'Calculating…' : 'Compare projection'}</button>
    </form>}
    {runs.map(({ result, price: source, start, budget }, i) => <section className="inventory-run" key={runs.length - i}>
      <h2>{source.item} · {source.supplier}</h2>
      <p>{start} · Bill {source.bill_number || source.id} · {result.price_basis === 'historical' ? 'Historical price estimate' : 'Confirmed landed price'}</p>
      <h3>{result.units ? result.units + ' ' + source.unit + ' · ' + money(result.spend_paise / 100) : (result.days.some(d => d.unmet > 0) ? 'Order cannot cover the shortage in time' : 'Stock covers the horizon')}</h3>
      <p>Available purchasing cash {money(budget)}</p>
      {result.reasons.map(reason => <p className="inventory-risk" key={reason}>{reason}</p>)}
      <div className="inventory-scroll"><table><thead><tr><th>Date</th><th>Without order</th><th>Incoming</th><th>With order</th><th>Unmet demand</th></tr></thead>
        <tbody>{result.days.map(d => <tr key={d.date}><th scope="row">{d.date}</th><td>{d.no_order_closing}</td><td>{d.incoming}</td><td>{d.closing}</td><td>{d.unmet}</td></tr>)}</tbody></table></div>
    </section>)}
  </main>
}

export default function InventoryPage() {
  const { user } = useAuth()
  return <Planner key={user?.company_id} />
}
