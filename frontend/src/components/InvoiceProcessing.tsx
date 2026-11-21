import { useInvoiceChecks } from '../api/useInvoiceChecks'
import { CheckCircle2, CircleAlert, Workflow } from 'lucide-react'
import { Button } from '../ui'

export default function InvoiceProcessing({ brandId }: { brandId?: string }) {
  const { bills, bill, selectBill, checks, busy, error, run } = useInvoiceChecks(brandId)
  return (
    <section className="ah-processing" aria-labelledby="ah-processing-title">
      <div className="ah-processing__head">
        <span className="ah-agent__icon"><Workflow size={20} aria-hidden="true" /></span>
        <div>
          <h2 id="ah-processing-title">Invoice processing</h2>
          <p>Check vendor details, tax identifiers, amount and approval status.</p>
        </div>
      </div>
      <div className="ah-processing__controls">
        <label htmlFor="ah-processing-bill">Recent invoice</label>
        <select id="ah-processing-bill" value={bill} disabled={busy || !bills?.length}
          onChange={event => selectBill(event.target.value)}>
          <option value="">{bills ? bills.length ? 'Select an invoice' : 'No recent invoices' : error ? 'Invoices unavailable' : 'Loading invoices…'}</option>
          {bills?.map(row => <option key={row.invoice_id} value={row.invoice_id}>
            {[row.invoice_number || row.invoice_id, row.vendor_name].filter(Boolean).join(' · ')}
          </option>)}
        </select>
        <Button variant="primary" onClick={() => void run()} disabled={!bill || busy} loading={busy}>Run checks</Button>
      </div>
      {error && <p role="alert">{error}</p>}
      <div aria-live="polite">
        {checks.length > 0 && <ol className="ah-processing__results">
          {checks.map(check => {
            const Icon = check.state === 'ready' ? CheckCircle2 : CircleAlert
            return <li key={check.id}>
              <Icon size={18} aria-hidden="true" />
              <strong>{check.label}</strong>
              <span>{check.detail}</span>
              <small>{check.state === 'ready' ? 'Recorded' : 'Review'}</small>
            </li>
          })}
        </ol>}
      </div>
    </section>
  )
}
