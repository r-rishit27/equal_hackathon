import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { Plus, X } from 'lucide-react'
import {
  Badge, Button, DataTable, EmptyState, ErrorState, Input, Modal, PageHeader, Pager, SkeletonRows, formatDate,
  useToast, type Column,
} from '../../ui'
import { useAuth } from '../../auth/AuthContext'
import { can } from '../../auth/permissions'
import {
  addCustomerAlias, apiError, createCustomer, fetchCustomer, fetchCustomers, removeCustomerAlias, updateCustomer,
  type CustomerDetail, type CustomerRow,
} from '../../api/receivables'
import { PATHS, arCustomerPath, arInvoicePath, arPaymentPath } from '../../routes/paths'
import { InvoiceStatusBadge, PaymentStatusBadge } from './badges'
import { money } from './format'
import './receivables.css'

const PAGE = 50

/**
 * Customers — the receivable twin of Vendors. Created automatically from the
 * Bill-To party of each uploaded sales invoice; the payer names the agent has
 * learned (and any you add) are what let it recognise their money.
 */
export default function ArCustomersPage() {
  const navigate = useNavigate()
  const { customerId } = useParams<{ customerId?: string }>()
  const { user } = useAuth()
  const canCapture = !!user && can(user.role, 'payables.initiate' as Parameters<typeof can>[1])
  const [q, setQ] = useState('')
  const [page, setPage] = useState(1)
  const [rows, setRows] = useState<CustomerRow[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState<string | null>(null)
  const [adding, setAdding] = useState(false)

  const load = useCallback(async () => {
    setErr(null)
    try {
      const r = await fetchCustomers({ q: q || undefined, limit: PAGE, offset: (page - 1) * PAGE })
      setRows(r.items)
      setTotal(r.total)
    } catch (e) {
      setErr(apiError(e))
    } finally {
      setLoading(false)
    }
  }, [q, page])
  useEffect(() => { setLoading(true); const h = setTimeout(load, q ? 250 : 0); return () => clearTimeout(h) }, [load, q])

  const columns: Column<CustomerRow>[] = useMemo(() => [
    { key: 'name', header: 'Customer', pinned: true, render: r => <span className="ar-strong">{r.name}</span>, sortValue: r => r.name },
    { key: 'gstin', header: 'GSTIN', render: r => r.gstin ?? <span className="ar-muted">—</span> },
    { key: 'open', header: 'Open invoices', align: 'right', render: r => r.open_count || '—', sortValue: r => r.open_count },
    { key: 'outstanding', header: 'Outstanding', align: 'right', render: r => <span className="ar-money ar-strong">{money(r.outstanding)}</span>, sortValue: r => Number(r.outstanding) },
    { key: 'overdue', header: 'Overdue', align: 'right', render: r => Number(r.overdue) ? <span className="ar-money">{money(r.overdue)}</span> : <span className="ar-muted">—</span>, sortValue: r => Number(r.overdue) },
    { key: 'unapplied', header: 'On account', align: 'right', render: r => Number(r.unapplied) ? <span className="ar-money">{money(r.unapplied)}</span> : <span className="ar-muted">—</span> },
    { key: 'tds', header: 'Usual TDS', align: 'right', render: r => r.tds_rate_hint ? `${Number(r.tds_rate_hint)}%` : <span className="ar-muted">—</span> },
    { key: 'last', header: 'Last payment', render: r => formatDate(r.last_payment), sortValue: r => r.last_payment ?? '' },
  ], [])

  return (
    <div className="ar">
      <PageHeader title="Customers" sub="Who owes you, and the names their money arrives under."
        actions={canCapture && <Button variant="secondary" iconLeft={<Plus size={14} />} onClick={() => setAdding(true)}>Add customer</Button>} />
      <div className="ar-toolbar">
        <span />
        <input className="ar-search" type="search" placeholder="Search name or GSTIN" value={q}
          onChange={e => { setQ(e.target.value); setPage(1) }} aria-label="Search customers" />
      </div>
      {err && <ErrorState message={err} onRetry={load} />}
      {!err && (
        <>
          <DataTable caption="Customers" rows={rows} columns={columns} rowKey={r => r.id} loading={loading && !rows.length}
            onRowClick={r => navigate(arCustomerPath(r.id))}
            empty={<EmptyState title="No customers yet" message="They are created from the Bill-To party when you upload sales invoices." />} />
          {total > PAGE && <Pager page={page} perPage={PAGE} total={total} onGo={setPage} onPerPage={() => {}} label="Pages of customers" />}
        </>
      )}
      <CustomerDetailModal id={customerId ?? null} onClose={() => navigate(PATHS['ar-customers'])} onChanged={load} />
      <AddCustomerModal open={adding} onClose={() => setAdding(false)} onDone={id => { setAdding(false); void load(); navigate(arCustomerPath(id)) }} />
    </div>
  )
}

function CustomerDetailModal({ id, onClose, onChanged }: { id: string | null; onClose: () => void; onChanged: () => void }) {
  const toast = useToast()
  const navigate = useNavigate()
  const { user } = useAuth()
  const canPost = !!user && can(user.role, 'payables.accounting_approval' as Parameters<typeof can>[1])
  const [c, setC] = useState<CustomerDetail | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [alias, setAlias] = useState('')
  const [tds, setTds] = useState('')
  const load = useCallback(async () => {
    if (!id) return
    setErr(null)
    try {
      const r = await fetchCustomer(id)
      setC(r)
      setTds(r.tds_rate_hint ? String(Number(r.tds_rate_hint)) : '')
    } catch (e) { setErr(apiError(e)) }
  }, [id])
  useEffect(() => { setC(null); void load() }, [load])

  const run = async (fn: () => Promise<unknown>, ok: string) => {
    try { await fn(); toast.success(ok); onChanged(); await load() } catch (e) { toast.error('That didn’t work', apiError(e)) }
  }

  return (
    <Modal open={!!id} onClose={onClose} size="xl" title={c?.name ?? 'Customer'} description={c?.gstin ?? undefined}>
      {err && <ErrorState message={err} onRetry={load} />}
      {!c && !err && <SkeletonRows rows={6} cols={4} />}
      {c && (
        <div className="ar-wb">
          <div className="ar-facts">
            <F k="GSTIN" v={c.gstin} /><F k="PAN" v={c.pan} /><F k="Email" v={c.email} /><F k="Phone" v={c.phone} />
            <F k="Terms" v={c.payment_terms_days ? `${c.payment_terms_days} days` : null} />
            <F k="Address" v={c.address} wide />
          </div>

          <div className="ar-section">
            <div className="ar-section__title">Payer names</div>
            <div className="ar-muted">How this customer's money shows up in bank narrations. A payment from one of these names is recognised as theirs — the agent learns new ones each time you confirm a match.</div>
            <div className="ar-chips">
              {c.aliases.length === 0 && <span className="ar-muted">None yet.</span>}
              {c.aliases.map(a => (
                <span key={a.id} className="ar-chip" title={`${a.source} · confirmed ${a.confirmations}×`}>
                  {a.alias_raw || a.alias_norm}
                  {a.source === 'learned' && <Badge tone="brand">learned</Badge>}
                  {canPost && <button type="button" aria-label={`Remove ${a.alias_norm}`}
                    onClick={() => run(() => removeCustomerAlias(c.id, a.id), 'Payer name removed')}><X size={12} /></button>}
                </span>
              ))}
            </div>
            {canPost && (
              <div className="ar-inline">
                <Input label="Add a payer name" placeholder="e.g. ACME TRADIN" value={alias} onChange={e => setAlias(e.target.value)} />
                <Button variant="secondary" disabled={alias.trim().length < 3}
                  onClick={() => run(async () => { await addCustomerAlias(c.id, alias.trim()); setAlias('') }, 'Payer name added — waiting payments re-checked')}>Add</Button>
              </div>
            )}
          </div>

          {canPost && (
            <div className="ar-section">
              <div className="ar-section__title">Usual TDS rate</div>
              <div className="ar-inline">
                <Input label="Percent of taxable value" hint="Learned from confirmed matches; the agent tries this rate first."
                  inputMode="decimal" value={tds} onChange={e => setTds(e.target.value)} />
                <Button variant="secondary" disabled={tds === (c.tds_rate_hint ? String(Number(c.tds_rate_hint)) : '')}
                  onClick={() => run(() => updateCustomer(c.id, { tds_rate_hint: tds === '' ? null : tds }), 'TDS rate saved')}>Save</Button>
              </div>
            </div>
          )}

          <div className="ar-section">
            <div className="ar-section__title">Invoices</div>
            <div className="ar-alloc-wrap">
              <table className="ar-alloc">
                <thead><tr><th>Invoice</th><th>Date</th><th>Due</th><th className="num">Total</th><th className="num">Outstanding</th><th>Status</th></tr></thead>
                <tbody>
                  {c.invoices.length === 0 && <tr><td colSpan={6} className="ar-muted">No invoices.</td></tr>}
                  {c.invoices.map(i => (
                    <tr key={i.id} style={{ cursor: 'pointer' }} onClick={() => navigate(arInvoicePath(i.id))}>
                      <td>{i.invoice_number}</td><td>{formatDate(i.invoice_date)}</td><td>{formatDate(i.due_date)}</td>
                      <td className="num ar-money">{money(i.total_amount)}</td><td className="num ar-money">{money(i.outstanding)}</td>
                      <td><InvoiceStatusBadge status={i.status} overdue={i.days_overdue} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <div className="ar-section">
            <div className="ar-section__title">Payments</div>
            <div className="ar-alloc-wrap">
              <table className="ar-alloc">
                <thead><tr><th>Received</th><th>UTR</th><th className="num">Amount</th><th className="num">On account</th><th>Status</th></tr></thead>
                <tbody>
                  {c.payments.length === 0 && <tr><td colSpan={5} className="ar-muted">No payments recorded against this customer yet.</td></tr>}
                  {c.payments.map(p => (
                    <tr key={p.id} style={{ cursor: 'pointer' }} onClick={() => navigate(arPaymentPath(p.id))}>
                      <td>{formatDate(p.received_on)}</td><td>{p.utr ?? '—'}</td>
                      <td className="num ar-money">{money(p.amount)}</td>
                      <td className="num ar-money">{Number(p.unapplied) ? money(p.unapplied) : '—'}</td>
                      <td><PaymentStatusBadge status={p.status} auto={p.auto_applied} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}
    </Modal>
  )
}

function AddCustomerModal({ open, onClose, onDone }: { open: boolean; onClose: () => void; onDone: (id: string) => void }) {
  const toast = useToast()
  const [f, setF] = useState({ name: '', gstin: '', email: '', terms: '' })
  const [busy, setBusy] = useState(false)
  const save = async () => {
    setBusy(true)
    try {
      const r = await createCustomer({ name: f.name.trim(), gstin: f.gstin.trim() || undefined, email: f.email.trim() || undefined,
        payment_terms_days: f.terms ? Number(f.terms) : undefined })
      toast.success(r.created ? 'Customer added' : 'That customer already exists — opened it')
      setF({ name: '', gstin: '', email: '', terms: '' })
      onDone(r.customer_id)
    } catch (e) {
      toast.error('Not added', apiError(e))
    } finally {
      setBusy(false)
    }
  }
  return (
    <Modal open={open} onClose={onClose} title="Add customer" size="sm"
      footer={<><Button variant="ghost" onClick={onClose}>Cancel</Button><Button onClick={save} loading={busy} disabled={!f.name.trim()}>Add</Button></>}>
      <div className="ar-form ar-form--1">
        <Input label="Name" required value={f.name} onChange={e => setF(s => ({ ...s, name: e.target.value }))} />
        <Input label="GSTIN" value={f.gstin} onChange={e => setF(s => ({ ...s, gstin: e.target.value.toUpperCase() }))} />
        <Input label="Email" type="email" value={f.email} onChange={e => setF(s => ({ ...s, email: e.target.value }))} />
        <Input label="Payment terms (days)" inputMode="numeric" value={f.terms} onChange={e => setF(s => ({ ...s, terms: e.target.value }))} />
      </div>
    </Modal>
  )
}

function F({ k, v, wide }: { k: string; v: React.ReactNode; wide?: boolean }) {
  return <div className={`ar-fact${wide ? ' ar-fact--wide' : ''}`}><span className="ar-fact__k">{k}</span><span className="ar-fact__v">{v || '—'}</span></div>
}
