import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { FileText, Upload } from 'lucide-react'
import {
  Button, DataTable, EmptyState, ErrorState, Modal, PageHeader, Pager, SkeletonRows, formatDate, formatDateTime,
  useToast, type Column,
} from '../../ui'
import { useAuth } from '../../auth/AuthContext'
import { can } from '../../auth/permissions'
import PdfFullscreen from '../../components/PdfFullscreen'
import {
  REASON_LABELS, apiError, arInvoiceDocumentUrl, fetchArInvoice, fetchArInvoices, setArInvoiceStatus,
  type ArInvoiceRow, type ReasonCode,
} from '../../api/receivables'
import { PATHS, arCustomerPath, arInvoicePath, arPaymentPath } from '../../routes/paths'
import { InvoiceStatusBadge } from './badges'
import { money } from './format'
import './receivables.css'

type Tab = 'open' | 'overdue' | 'partially_paid' | 'paid' | 'disputed' | 'all'
const TABS: { key: Tab; label: string; status?: string; overdue?: boolean }[] = [
  { key: 'open', label: 'Open', status: 'open,partially_paid' },
  { key: 'overdue', label: 'Overdue', overdue: true },
  { key: 'partially_paid', label: 'Part-paid', status: 'partially_paid' },
  { key: 'paid', label: 'Paid', status: 'paid' },
  { key: 'disputed', label: 'On hold', status: 'disputed' },
  { key: 'all', label: 'All' },
]
const PAGE = 50

/** Sales invoices — what customers owe us. Same table and states as Bills, read from the other side. */
export default function ArInvoicesPage() {
  const navigate = useNavigate()
  const { invoiceId } = useParams<{ invoiceId?: string }>()
  const { user } = useAuth()
  const canUpload = !!user && can(user.role, 'payables.initiate' as Parameters<typeof can>[1])
  const [tab, setTab] = useState<Tab>('open')
  const [q, setQ] = useState('')
  const [page, setPage] = useState(1)
  const [rows, setRows] = useState<ArInvoiceRow[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState<string | null>(null)

  const t = TABS.find(x => x.key === tab)!
  const load = useCallback(async () => {
    setErr(null)
    try {
      const r = await fetchArInvoices({ status: t.status, overdue: t.overdue || undefined, q: q || undefined, limit: PAGE, offset: (page - 1) * PAGE })
      setRows(r.items)
      setTotal(r.total)
    } catch (e) {
      setErr(apiError(e))
    } finally {
      setLoading(false)
    }
  }, [t, q, page])
  useEffect(() => { setLoading(true); const h = setTimeout(load, q ? 250 : 0); return () => clearTimeout(h) }, [load, q])
  useEffect(() => { setPage(1) }, [tab, q])

  const columns: Column<ArInvoiceRow>[] = useMemo(() => [
    { key: 'number', header: 'Invoice', pinned: true, render: r => <span className="ar-strong">{r.invoice_number}</span>, sortValue: r => r.invoice_number },
    { key: 'customer', header: 'Customer', render: r => r.customer_name, sortValue: r => r.customer_name },
    { key: 'date', header: 'Date', render: r => formatDate(r.invoice_date), sortValue: r => r.invoice_date ?? '' },
    { key: 'due', header: 'Due', render: r => formatDate(r.due_date), sortValue: r => r.due_date ?? '' },
    { key: 'po', header: 'PO', render: r => r.po_number ?? <span className="ar-muted">—</span> },
    { key: 'total', header: 'Total', align: 'right', render: r => <span className="ar-money">{money(r.total_amount)}</span>, sortValue: r => Number(r.total_amount) },
    { key: 'received', header: 'Received', align: 'right', render: r => <span className="ar-money">{Number(r.amount_received) ? money(r.amount_received) : '—'}</span> },
    { key: 'tds', header: 'TDS', align: 'right', render: r => <span className="ar-money">{Number(r.tds_amount) ? money(r.tds_amount) : '—'}</span> },
    { key: 'outstanding', header: 'Outstanding', align: 'right', render: r => <span className="ar-money ar-strong">{money(r.outstanding)}</span>, sortValue: r => Number(r.outstanding) },
    { key: 'status', header: 'Status', render: r => <InvoiceStatusBadge status={r.status} overdue={r.days_overdue} /> },
  ], [])

  return (
    <div className="ar">
      <PageHeader title="Sales Invoices" sub="What customers owe you. Payments applied by the agent or by your team settle them here."
        actions={canUpload && <Button iconLeft={<Upload size={14} />} onClick={() => navigate(PATHS['ar-upload'])}>Upload invoices</Button>} />
      <div className="ar-toolbar">
        <div className="ar-tabs" role="tablist" aria-label="Invoices">
          {TABS.map(x => (
            <button key={x.key} role="tab" aria-selected={tab === x.key} className={`ar-tab${tab === x.key ? ' ar-tab--on' : ''}`}
              onClick={() => setTab(x.key)}>{x.label}</button>
          ))}
        </div>
        <input className="ar-search" type="search" placeholder="Search invoice no. or customer" value={q}
          onChange={e => setQ(e.target.value)} aria-label="Search invoices" />
      </div>
      {err && <ErrorState message={err} onRetry={load} />}
      {!err && (
        <>
          <DataTable caption="Sales invoices" rows={rows} columns={columns} rowKey={r => r.id} loading={loading && !rows.length}
            onRowClick={r => navigate(arInvoicePath(r.id))}
            empty={<EmptyState title="No invoices here" icon={<FileText size={20} />}
              message={tab === 'open' ? 'Upload your sales invoices so incoming payments have something to match.' : undefined}
              action={canUpload && tab === 'open' ? <Button iconLeft={<Upload size={14} />} onClick={() => navigate(PATHS['ar-upload'])}>Upload invoices</Button> : undefined} />} />
          {total > PAGE && <Pager page={page} perPage={PAGE} total={total} onGo={setPage} onPerPage={() => {}} label="Pages of invoices" />}
        </>
      )}
      <InvoiceDetail id={invoiceId ?? null} onClose={() => navigate(PATHS['ar-invoices'])} onChanged={load} />
    </div>
  )
}

function InvoiceDetail({ id, onClose, onChanged }: { id: string | null; onClose: () => void; onChanged: () => void }) {
  const toast = useToast()
  const navigate = useNavigate()
  const { user } = useAuth()
  const canPost = !!user && can(user.role, 'payables.accounting_approval' as Parameters<typeof can>[1])
  const [inv, setInv] = useState<Awaited<ReturnType<typeof fetchArInvoice>> | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [pdf, setPdf] = useState(false)
  const load = useCallback(async () => {
    if (!id) return
    setErr(null)
    try { setInv(await fetchArInvoice(id)) } catch (e) { setErr(apiError(e)) }
  }, [id])
  useEffect(() => { setInv(null); void load() }, [load])

  const status = async (s: 'disputed' | 'open' | 'void') => {
    if (!inv) return
    try {
      await setArInvoiceStatus(inv.id, s)
      toast.success(s === 'disputed' ? 'Put on hold — the agent won’t apply cash to it' : s === 'void' ? 'Invoice voided' : 'Released')
      onChanged()
      await load()
    } catch (e) {
      toast.error('That didn’t work', apiError(e))
    }
  }

  return (
    <Modal open={!!id} onClose={onClose} size="lg" title={inv ? `Invoice ${inv.invoice_number}` : 'Invoice'}
      description={inv ? inv.customer_name : undefined}
      footer={inv && (
        <div className="ar-actions ar-actions--split" style={{ width: '100%' }}>
          <div className="ar-actions">
            {canPost && ['open', 'partially_paid'].includes(inv.status) && <Button variant="ghost" onClick={() => status('disputed')}>Put on hold</Button>}
            {canPost && inv.status === 'disputed' && <Button variant="ghost" onClick={() => status('open')}>Release hold</Button>}
            {canPost && ['open', 'disputed'].includes(inv.status) && !Number(inv.amount_received) && <Button variant="ghost" onClick={() => status('void')}>Void</Button>}
          </div>
          <div className="ar-actions">
            <Button variant="ghost" onClick={() => navigate(arCustomerPath(inv.customer_id))}>Customer</Button>
            {inv.has_document && <Button variant="secondary" iconLeft={<FileText size={14} />} onClick={() => setPdf(true)}>View PDF</Button>}
          </div>
        </div>
      )}>
      {err && <ErrorState message={err} onRetry={load} />}
      {!inv && !err && <SkeletonRows rows={5} cols={3} />}
      {inv && (
        <div className="ar-wb">
          <div className="ar-facts">
            <F k="Status" v={<InvoiceStatusBadge status={inv.status} overdue={inv.days_overdue} />} />
            <F k="Invoice date" v={formatDate(inv.invoice_date)} />
            <F k="Due" v={formatDate(inv.due_date)} />
            <F k="Customer PO" v={inv.po_number} />
            <F k="Customer GSTIN" v={inv.customer_gstin} />
            <F k="Terms" v={inv.payment_terms} />
          </div>
          <div className="ar-facts">
            <F k="Taxable value" v={money(inv.taxable_amount)} />
            <F k="Tax" v={money(inv.tax_amount)} />
            <F k="Total" v={money(inv.total_amount)} />
            <F k="Received" v={money(inv.amount_received)} />
            <F k="TDS deducted" v={money(inv.tds_amount)} />
            <F k="Other deductions" v={money(inv.deduction_amount)} />
            <F k="Outstanding" v={<strong>{money(inv.outstanding)}</strong>} />
          </div>
          <div className="ar-section">
            <div className="ar-section__title">Payments applied</div>
            {inv.applications.length === 0 ? <div className="ar-muted">Nothing received yet.</div> : (
              <div className="ar-alloc-wrap">
                <table className="ar-alloc">
                  <thead><tr><th>Received</th><th>Payer / UTR</th><th className="num">Applied</th><th className="num">TDS</th><th className="num">Held back</th><th>By</th></tr></thead>
                  <tbody>
                    {inv.applications.map(a => (
                      <tr key={a.id} style={{ cursor: 'pointer', ...(a.reversed_at ? { opacity: 0.5, textDecoration: 'line-through' } : {}) }}
                        onClick={() => navigate(arPaymentPath(a.payment_id))}>
                        <td>{formatDate(a.received_on)}</td>
                        <td>{a.payer_name ?? '—'} <span className="ar-muted">{a.utr ?? ''}</span></td>
                        <td className="num ar-money">{money(a.amount_applied)}</td>
                        <td className="num ar-money">{Number(a.tds_amount) ? money(a.tds_amount) : '—'}</td>
                        <td className="num ar-money">{Number(a.deduction_amount) ? `${money(a.deduction_amount)} · ${REASON_LABELS[a.reason_code as ReasonCode] ?? ''}` : '—'}</td>
                        <td className="ar-muted">{a.method === 'auto' ? 'Agent' : a.applied_by} · {formatDateTime(a.created_at)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      )}
      {pdf && inv && <PdfFullscreen url={arInvoiceDocumentUrl(inv.id)} name={`${inv.invoice_number}.pdf`} onClose={() => setPdf(false)} />}
    </Modal>
  )
}

function F({ k, v }: { k: string; v: React.ReactNode }) {
  return <div className="ar-fact"><span className="ar-fact__k">{k}</span><span className="ar-fact__v">{v || '—'}</span></div>
}
