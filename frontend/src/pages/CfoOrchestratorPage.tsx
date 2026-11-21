import { useState } from 'react'
import { Link } from 'react-router-dom'
import { ArrowUpRight, BadgeIndianRupee, Building2, Check, Eye, Flag, LoaderCircle, FileSearch, GitBranch, Play, ReceiptText, Workflow } from 'lucide-react'
import { useInvoiceChecks, type ControlState } from '../api/useInvoiceChecks'
import { useEntitlements } from '../auth/EntitlementsContext'
import { billPath, vendorPath } from '../routes/paths'
import { Button } from '../ui'
import './cfo-orchestrator.css'

const stages = [
  { id: 'kyc', name: 'Vendor identification & KYC', icon: FileSearch, description: 'Review GST registration, PAN and the beneficiary bank account.' },
  { id: 'setup', name: 'Vendor master setup', icon: Building2, description: 'Review contact details, extracted KYC evidence and the stored vendor master.' },
  { id: 'recon', name: 'Invoice reconciliation', icon: GitBranch, description: 'Inspect the reconciliation case linked to the invoice.' },
  { id: 'approval', name: 'Invoice approval', icon: ReceiptText, description: 'Review the recorded invoice approval decision.' },
  { id: 'payment', name: 'Payment readiness', icon: BadgeIndianRupee, description: 'Review upstream controls, disbursement status and invoice amount.' },
]

const outcomes = {
  ready: { label: 'Passed', Icon: Check },
  review: { label: 'Needs review', Icon: Eye },
  blocked: { label: 'Blocked', Icon: Flag },
}

function Outcome({ state }: { state: ControlState }) {
  const { label, Icon } = outcomes[state]
  return <span className="cfo-outcome" data-state={state}><Icon size={14} aria-hidden="true" />{label}</span>
}

export default function CfoOrchestratorPage({ brandId }: { brandId?: string }) {
  const { bills, bill, selectBill, checks, busy, error, run } = useInvoiceChecks(brandId, 'cfo')
  const { has } = useEntitlements()
  const [selected, setSelected] = useState(stages[0].id)
  const stage = stages.find(item => item.id === selected)!
  const supplier = bills?.find(item => item.invoice_id === bill)?.supplier_id
  const evidence = checks.find(check => check.id === selected)
  const totals = (Object.keys(outcomes) as ControlState[]).map(state => ({ state, count: checks.filter(check => check.state === state).length }))
  return <main className="cfo-workspace">
    <header className="cfo-banner">
      <Workflow size={32} aria-hidden="true" />
      <div><h1>CFO Orchestrator</h1><p>Run invoice controls and inspect the evidence before payment review.</p></div>
    </header>
    <section className="cfo-panel" aria-labelledby="cfo-run">
      <div className="cfo-heading"><GitBranch aria-hidden="true" /><h2 id="cfo-run">Invoice control pipeline</h2></div>
      <div className="cfo-controls">
        <label>Recent invoice
          <select value={bill} disabled={!bills?.length || busy} onChange={e => { selectBill(e.target.value); setSelected(stages[0].id) }}>
            <option value="">{error && !bills ? 'Invoices unavailable' : !bills ? 'Loading invoices…' : bills.length ? 'Choose an invoice' : 'No recent invoices'}</option>
            {bills?.map(row => <option key={row.invoice_id} value={row.invoice_id}>{[row.invoice_number || row.invoice_id, row.vendor_name].filter(Boolean).join(' · ')}</option>)}
          </select>
        </label>
        <Button variant="primary" disabled={!bill || busy} loading={busy} onClick={() => void run()}><Play size={15} />Run workflow</Button>
      </div>
      {error && <p role="alert">{error}</p>}
      <div className="cfo-track" aria-label="Workflow stages" aria-busy={busy}>
        {stages.map(({ id, name, icon: Icon }) => {
          const result = checks.find(check => check.id === id)
          const state = result?.state ?? (busy ? 'running' : 'pending')
          const Symbol = result ? outcomes[result.state].Icon : busy ? LoaderCircle : Icon
          return <button data-state={state} key={id} aria-pressed={id === selected} onClick={() => setSelected(id)}>
            <span className="cfo-node"><Symbol key={state} size={23} aria-hidden="true" /></span>
            <strong>{name}</strong><small>{result ? outcomes[result.state].label : busy ? 'Checking' : 'Pending'}</small>
          </button>
        })}
      </div>
    </section>
    <section className="cfo-panel" aria-labelledby="cfo-evidence">
      <div className="cfo-heading"><FileSearch aria-hidden="true" /><h2 id="cfo-evidence">Stage evidence</h2></div>
      <div data-state={evidence?.state} className="cfo-evidence" aria-live="polite"><h3>{stage.name}</h3><p>{evidence?.detail || stage.description}</p>
        {evidence?.items && <ul className="cfo-control-list">
          {evidence.items.map(item => <li key={item.label}><div><strong>{item.label}</strong><p>{item.detail}</p></div>
            <Outcome state={item.state} /></li>)}
        </ul>}
        {supplier && has('vendors') && (selected === 'kyc' || selected === 'setup') && <div className="cfo-vendor-links">
          <Link to={vendorPath(supplier, 'compliance')}>Vendor KYC <ArrowUpRight size={14} /></Link>
          {selected === 'setup' && <>
            <Link to={vendorPath(supplier, 'contacts')}>Manage contacts <ArrowUpRight size={14} /></Link>
            <Link to={vendorPath(supplier, 'documents')}>Source documents <ArrowUpRight size={14} /></Link>
          </>}
        </div>}
        {bill && has('bills') && <Link to={billPath(bill)}>Open invoice <ArrowUpRight size={14} /></Link>}
      </div>
      <div className="cfo-summary" role="status">{busy ? 'Running invoice controls?' : checks.length ? <>
          <strong>{checks.length} stages evaluated</strong>
          {totals.map(({ state, count }) => <span key={state} className="cfo-tally">{count} <Outcome state={state} /></span>)}
        </> : 'Awaiting a workflow run'}
      </div>
    </section>
  </main>
}
