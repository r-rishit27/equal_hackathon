import { useEffect, useRef, useState, type FormEvent } from 'react'
import { useAuth } from '../auth/AuthContext'
import { Building2, ClipboardList, Package, SlidersHorizontal, ChevronRight, TrendingUp, Activity } from 'lucide-react'
import InventoryVendorPicker from './InventoryVendorPicker'
import './inventory.css'

interface Price {
  id: string; billed_units: string | number; sku: string | null; item: string; unit: string; price: number | string
  supplier_id: string; payment_terms_days: number | null; due_date: string | null
  supplier: string; bill_date: string; bill_number: string | null
}
interface Projection {
  additional_demand_covered: number; remaining_paise: number; units: number; spend_paise: number; reasons: string[]; price_basis: string
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
  const [vendor, setVendor] = useState('')
  const [allocation, setAllocation] = useState('stock')
  const [selected, setSelected] = useState('')
  const [run, setRun] = useState<Run | null>(null)
  const revision = useRef(0)
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
        if (!controller.signal.aborted) { setPrices(data) }
      } catch (e) {
        if (!controller.signal.aborted) setError(e instanceof Error ? e.message : 'Unable to load prices.')
      } finally {
        if (!controller.signal.aborted) setLoading(false)
      }
    }
    void load()
    return () => controller.abort()
  }, [request])
  const vendors = [...new Map(prices.map(p => [p.supplier_id, p.supplier])).entries()]
    .sort((a, b) => a[1].trim().localeCompare(b[1].trim(), 'en-IN', { sensitivity: 'base', numeric: true }) || a[0].localeCompare(b[0]))
  const lines = prices.filter(p => p.supplier_id === vendor)
  const price = lines.find(p => p.id === selected)

  function selectLine(id: string) {
    revision.current++
    setSelected(id)
    setAllocation('stock')
    setRun(null)
    setError('')
    setBusy(false)
  }

  async function calculate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!price) return
    const current = ++revision.current
    setRun(null)
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
          landed_unit_paise: fields.get('quote') && number('quote') !== Number(price.price) ? Math.round(number('quote') * 100) : null,
        }),
      })
      if (!response.ok) {
        const body = await response.json()
        throw new Error(typeof body.detail === 'string' ? body.detail : 'Check the quantities, dates, and amounts.')
      }
      const result: Projection = await response.json()
      if (current === revision.current) setRun({ price, result, start, budget })
    } catch (e) { if (current === revision.current) setError(e instanceof Error ? e.message : 'Unable to calculate the order.') }
    finally { if (current === revision.current) setBusy(false) }
  }
  return <main className="inventory-desk">
    <header className="inventory-heading">
      <div><h1>Inventory planning</h1><p>Plan your next purchase against seven days of demand and available cash.</p>
      </div>
      <dl className="terminal-counts"><div><dt>Vendors</dt><dd>{loading || (!prices.length && error) ? '?' : vendors.length}</dd></div>
        <div><dt>Priced invoice lines</dt><dd>{loading || (!prices.length && error) ? '?' : prices.length.toLocaleString('en-IN')}</dd></div></dl>
    </header>
    {loading && <p role="status">Loading bill lines…</p>}
    {error && <p role="alert">{error} {!prices.length && <button onClick={() => setRequest(n => n + 1)}>Retry</button>}</p>}
    {!loading && !error && !prices.length && <p>No priced INR bill lines with a supplier and unit are available for this account.</p>}
    {prices.length > 0 && <div className="inventory-overview"><section className="inventory-card">
      <h2><Building2 size={19} /> Select a purchase</h2>
      <div className="inventory-pickers">
        <InventoryVendorPicker vendors={vendors} selected={vendor} onSelect={id => { setVendor(id); selectLine('') }} />
        <label>Invoice line item<select value={selected} disabled={!vendor} onChange={e => selectLine(e.target.value)}>
          <option value="">{vendor ? 'Choose an invoice line' : 'Select a vendor first'}</option>
          {lines.map(p => <option key={p.id} value={p.id}>{p.item} · {p.bill_number || p.bill_date} · {money(Number(p.price))}/{p.unit}</option>)}
        </select></label>
      </div>
    </section><VendorActivity prices={prices} vendor={vendor} onSelect={id => { setVendor(id); selectLine('') }} /></div>}
    {price && <form onSubmit={calculate} key={price.id} onChange={() => { revision.current++; setRun(null); setBusy(false) }}>
      <section className="inventory-card inventory-source"><h2><ClipboardList size={19} /> {price.item}</h2>
        <p>{price.supplier} · Bill {price.bill_number || price.id} · {price.bill_date}</p>
        <dl><div><dt>Invoice quantity</dt><dd>{Number(price.billed_units).toLocaleString('en-IN')} {price.unit}</dd></div>
        <div><dt>Invoice unit rate</dt><dd>{money(Number(price.price))}</dd></div>
        <div><dt>Vendor payment terms</dt><dd>{price.payment_terms_days == null ? 'Unrecorded' : price.payment_terms_days + ' days'}</dd></div>
        <div><dt>Invoice due date</dt><dd>{price.due_date ?? 'Unrecorded'}</dd></div></dl>
      </section>
      <section className="inventory-card"><h2><Package size={19} /> Stock position</h2>
        <label>Use billed quantity as<select value={allocation} onChange={e => setAllocation(e.target.value)}>
          <option value="stock">In-house stock</option><option value="inbound">Firm inbound</option><option value="manual">Enter actual counts</option>
        </select></label>
        <p>Confirm where the invoiced units are today. Adjust the counts for any other stock.</p>
        <div className="inventory-controls">
        <label>Start date<input name="start" type="date" min={price.bill_date} defaultValue={price.bill_date > today() ? price.bill_date : today()} required /></label>
        <label>Stock on hand<input key={"stock-" + allocation} defaultValue={allocation === "stock" ? Number(price.billed_units) : undefined} name="stock" step="any" type="number" min="0" required /></label>
        <label>Reserved stock<input defaultValue={0} name="reserved" step="any" type="number" min="0" required /></label>
        <label>Daily demand<input name="demand" type="number" step="any" min="0.000001" required /></label>
        <label>Firm inbound units (confirmed deliveries)<input key={"inbound-" + allocation} defaultValue={allocation === "inbound" ? Number(price.billed_units) : 0} name="inbound" step="any" type="number" min="0" /></label>
        <label>Expected delivery date<input name="inboundDate" type="date" /></label>
        </div></section>
      <section className="inventory-card"><h2><SlidersHorizontal size={19} /> Purchasing terms</h2>
        <div className="inventory-controls">
        <label>Lead time (days)<input name="lead" type="number" min="0" max="365" required /></label>
        <label>Minimum order<input defaultValue={1} name="minimum" type="number" min="1" required /></label>
        <label>Units per pack<input defaultValue={1} name="pack" type="number" min="1" required /></label>
        <label>Cash after commitments and reserve (₹)<input name="budget" type="number" step=".01" min="0" required /></label>
        <label>Unit rate (₹, invoice prefill)<input defaultValue={Number(price.price)} name="quote" type="number" step="any" min="0.000001" /></label>
        <label>Quote valid through<input name="expiry" type="date" /></label>
        </div></section>
      <p>Assumes full payment at order and delivery before demand on arrival day. Review the unit rate, order minimum and pack size before comparing.</p>
      <button type="submit" disabled={busy}>{busy ? 'Calculating…' : 'Optimize stock order'} <ChevronRight size={16} /></button>
    </form>}
    {run && <Recommendation {...run} />}
  </main>
}

function VendorActivity({ prices, vendor, onSelect }: { prices: Price[]; vendor: string; onSelect: (id: string) => void }) {
  const counts = new Map<string, { name: string; count: number }>()
  for (const row of prices) {
    const entry = counts.get(row.supplier_id) ?? { name: row.supplier, count: 0 }
    entry.count++
    counts.set(row.supplier_id, entry)
  }
  const leaders = [...counts.entries()].sort((a, b) => b[1].count - a[1].count || a[1].name.localeCompare(b[1].name)).slice(0, 5)
  return <section className="inventory-card vendor-activity">
    <h2><Activity size={19} /> Vendors by invoice lines</h2>
    <div>{leaders.map(([id, { name, count }]) => <button type="button" key={id} aria-pressed={vendor === id}
      aria-label={`Select ${name}, ${count} invoice lines`} onClick={() => onSelect(id)}>
      <span>{name}</span><strong>{count}</strong><i aria-hidden="true" style={{ width: (100 * count / leaders[0][1].count) + '%' }} />
    </button>)}</div>
  </section>
}

const shortDate = (iso: string) => new Date(iso + 'T00:00:00').toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })
const quantity = (value: number) => Number(value).toLocaleString('en-IN', { maximumFractionDigits: 8 })

function Recommendation({ result, price: source, start, budget }: Run) {
  const [index, setIndex] = useState(0)
  const day = result.days[index]
  const peak = Math.max(1, ...result.days.flatMap(d => [d.closing, d.no_order_closing]))
  const share = budget > 0 ? (result.spend_paise / (budget * 100)) * 100 : 0
  return <section className="inventory-run" aria-label="Recommended order">
    <h2><TrendingUp size={19} /> Purchase recommendation</h2>
    <h3>{result.units ? `Order ${quantity(result.units)} ${source.unit}` : (result.days.some(d => d.unmet > 0) ? 'No feasible reorder' : 'Stock covers the week')}</h3>
    <p>{source.item} · {source.supplier} · Bill {source.bill_number || source.id} · {shortDate(start)}</p>
    <div className="capital-panel"><div><span>Order cost</span><strong>{money(result.spend_paise / 100)}</strong></div>
      <div><span>Cash remaining</span><strong>{money(result.remaining_paise / 100)}</strong></div>
      <div><span>Additional demand covered</span><strong>{quantity(result.additional_demand_covered)} {source.unit}</strong></div>
    </div>
    <div className="capital-meter" aria-hidden="true"><i style={{ width: share + '%' }} /></div>
    <p>{share.toLocaleString('en-IN', { maximumFractionDigits: 1 })}% of {money(budget)} purchasing cash allocated · {result.price_basis === 'historical' ? 'Invoice price estimate' : 'Entered planning rate'}</p>
    {result.reasons.map(reason => <p className="inventory-risk" key={reason}>{reason}</p>)}
    {day && <section className="stock-outlook"><h2>Closing stock by day</h2>
      <p className="stock-legend"><i /> Without order <i /> With order · {source.unit}</p>
      <div className="stock-chart">{result.days.map((d, i) => <button type="button" key={d.date}
        aria-pressed={i === index} aria-label={`${shortDate(d.date)}, without order ${d.no_order_closing}, with order ${d.closing} ${source.unit}`}
        onClick={() => setIndex(i)}>
        <span className="stock-bars"><i style={{ height: (100 * d.no_order_closing / peak) + '%' }} /><i style={{ height: (100 * d.closing / peak) + '%' }} /></span>
        <span>{shortDate(d.date)}</span>
      </button>)}</div>
      <p aria-live="polite"><strong>{shortDate(day.date)}</strong> · {quantity(day.incoming)} arriving · {quantity(day.closing)} on hand at close · {quantity(day.unmet)} unfilled ({source.unit})</p>
    </section>}
    <details><summary>Daily stock figures</summary><div className="inventory-scroll"><table><thead><tr><th>Date</th><th>Without order</th><th>Arriving</th><th>With order</th><th>Unfilled demand</th></tr></thead>
      <tbody>{result.days.map(d => <tr key={d.date}><th scope="row">{d.date}</th><td>{d.no_order_closing}</td><td>{d.incoming}</td><td>{d.closing}</td><td>{d.unmet}</td></tr>)}</tbody></table></div></details>
  </section>
}

export default function InventoryPage() {
  const { user } = useAuth()
  return <Planner key={user?.company_id} />
}
