import { useCallback, useEffect, useMemo, useState, type CSSProperties, type ReactNode } from 'react'
import { useSearchParams } from 'react-router-dom'
import { AlertTriangle, ArrowRight, Check, FileSpreadsheet, LayoutList, Mail, Network, Plus } from 'lucide-react'
import {
  Badge, Button, DataTable, EmptyState, ErrorState, PageHeader, Pager, formatDate, useScrollLock, useToast, type Column,
} from '../../ui'
import { useAuth } from '../../auth/AuthContext'
import { can } from '../../auth/permissions'
import {
  FLAG_LABELS, apiError, fetchArSummary, fetchPayments, fetchRemittances, fetchReviewBoard, fetchStatements,
  type AllocationIn, type ArSummary, type BoardGroup, type PaymentRow, type PaymentStatus, type Remittance, type StatementRow,
} from '../../api/receivables'
import { RemittanceViewer, StatementViewer } from './DocumentViewers'
import { ImportStatementModal, RecordPaymentModal, RemittanceModal } from './CaptureModals'
import PaymentWorkbench from './PaymentWorkbench'
import ReviewBoard from './ReviewBoard'
import { PaymentStatusBadge } from './badges'
import { confirmSuggested, confirmableFromList } from './confirm'
import { KIND_LABELS, fromPaise, money, pct, toPaise } from './format'
import { clickOrigin } from '../../utils/clickOrigin'
import '../bills.css' // the bill card's overlay + opening (bm__overlay, bm__card, bm-zoom-open)
import './receivables.css'

type Tab = 'review' | 'unmatched' | 'exception' | 'applied' | 'set_aside' | 'all' | 'statements' | 'remittances'

type TabGroup = 'todo' | 'done' | 'docs'

/** Grouped so the work (to do) reads apart from the record (done) and the source files. */
const TABS: { key: Tab; label: string; group: TabGroup; statuses?: PaymentStatus[]; hint: string }[] = [
  { key: 'review', label: 'Ready to confirm', group: 'todo', statuses: ['needs_review'],
    hint: 'The agent has a likely match — check it and confirm' },
  { key: 'unmatched', label: 'Needs match', group: 'todo', statuses: ['unmatched'],
    hint: 'The agent could not tell what these pay — choose the customer and invoices' },
  { key: 'exception', label: 'Follow-up', group: 'todo', statuses: ['exception'],
    hint: 'On hold — disputes, duplicates, waiting on the customer' },
  { key: 'applied', label: 'Applied', group: 'done', statuses: ['applied', 'partially_applied'], hint: 'Matched to invoices' },
  { key: 'set_aside', label: 'Excluded', group: 'done', statuses: ['not_receipt', 'reversed'],
    hint: 'Not customer payments (interest, refunds, own transfers) and bounced payments' },
  { key: 'all', label: 'All', group: 'done', hint: 'Every incoming payment' },
  { key: 'statements', label: 'Statements', group: 'docs', hint: 'Bank statements you imported' },
  { key: 'remittances', label: 'Remittances', group: 'docs', hint: 'Payment advice from customers' },
]

const PAGE = 50

/**
 * Cash Application — every incoming payment, what the agent made of it, and the
 * queue of the ones that need a person (docs/receivables/03_USER_FLOWS.md F2–F4).
 */
export default function CashApplicationPage() {
  const { user } = useAuth()
  const canCapture = !!user && can(user.role, 'payables.initiate' as Parameters<typeof can>[1])
  const canPost = !!user && can(user.role, 'payables.accounting_approval' as Parameters<typeof can>[1])
  const toast = useToast()
  const [params, setParams] = useSearchParams()
  const tab = (params.get('tab') as Tab) || 'review'
  const openId = params.get('payment')
  const statementId = params.get('statement')
  const remittanceId = params.get('remittance')
  const docTab = tab === 'remittances' || tab === 'statements'
  // Ready to confirm opens as the board (by customer, payments → invoices); the plain list is one click away.
  const board = tab === 'review' && params.get('view') !== 'list'

  const [summary, setSummary] = useState<ArSummary | null>(null)
  const [rows, setRows] = useState<PaymentRow[]>([])
  const [total, setTotal] = useState(0)
  const [counts, setCounts] = useState<Partial<Record<PaymentStatus, number>>>({})
  const [remits, setRemits] = useState<Remittance[]>([])
  const [statements, setStatements] = useState<StatementRow[]>([])
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState<string | null>(null)
  const [page, setPage] = useState(1)
  const [q, setQ] = useState('')
  const [modal, setModal] = useState<'import' | 'remit' | 'record' | null>(null)
  // The list the open payment came from, so the workbench can step through it
  // (snapshotted on open: applying one drops it from the live list).
  const [queue, setQueue] = useState<string[]>([])
  // Confirming straight from the list: rows ticked for a bulk confirm, and rows in flight.
  const [picked, setPicked] = useState<Set<string>>(new Set())
  const [confirming, setConfirming] = useState<Set<string>>(new Set())
  const [groups, setGroups] = useState<BoardGroup[]>([])
  // A payment opened from a line on the board: the invoice to show, and the board's edited lines if any.
  const [fromLine, setFromLine] = useState<{ pid: string; iid: string | null; draft: AllocationIn[] | null } | null>(null)

  const statuses = TABS.find(t => t.key === tab)?.statuses

  const load = useCallback(async () => {
    setErr(null)
    try {
      const [s, list] = await Promise.all([
        fetchArSummary(30),
        tab === 'remittances'
          ? fetchRemittances().then(r => { setRemits(r.items); return null })
          : tab === 'statements'
          ? fetchStatements().then(r => { setStatements(r.items); return null })
          : fetchPayments({ status: statuses?.join(','), q: q || undefined, limit: PAGE, offset: (page - 1) * PAGE }),
        board ? fetchReviewBoard({ q: q || undefined }).then(r => setGroups(r.groups)) : null,
      ])
      setSummary(s)
      if (list) {
        setRows(list.items)
        setTotal(list.total)
        setCounts(list.counts)
      }
    } catch (e) {
      setErr(apiError(e))
    } finally {
      setLoading(false)
    }
  }, [tab, statuses, q, page, board])

  useEffect(() => { setLoading(true); const t = setTimeout(load, q ? 250 : 0); return () => clearTimeout(t) }, [load, q])
  useEffect(() => { setPage(1); setPicked(new Set()) }, [tab, q])

  // Every upload re-runs the agent server-side within seconds. Refresh quickly for
  // half a minute after one so its results appear, then slowly while anything is
  // still unmatched.
  const [burstUntil, setBurstUntil] = useState(0)
  const kick = useCallback(() => { setBurstUntil(Date.now() + 30_000); void load() }, [load])
  const waiting = (counts.unmatched ?? 0) > 0 && !docTab
  useEffect(() => {
    const fast = burstUntil > Date.now()
    if (!fast && !waiting) return
    const t = setInterval(() => {
      if (fast && Date.now() > burstUntil) setBurstUntil(0)
      void load()
    }, fast ? 3000 : 8000)
    return () => clearInterval(t)
  }, [waiting, burstUntil, load])

  const setTab = (t: Tab) => setParams(p => { p.set('tab', t); p.delete('payment'); return p })
  const setView = (v: 'board' | 'list') => setParams(p => { if (v === 'list') p.set('view', 'list'); else p.delete('view'); return p })
  // One record open at a time: opening a payment from a statement or remittance replaces it.
  const open = (key: 'payment' | 'statement' | 'remittance', id: string) => setParams(p => {
    for (const k of ['payment', 'statement', 'remittance']) p.delete(k)
    p.set(key, id)
    return p
  })
  const openPayment = (id: string, from?: string[]) => {
    setQueue(from && from.includes(id) ? from : [id])
    open('payment', id)
  }
  const close = (key: string) => () => setParams(p => { p.delete(key); return p })
  // From inside a payment, a statement or remittance opens on top of it; closing returns to the payment as it was.
  const peek = (key: 'statement' | 'remittance', id: string) => setParams(p => {
    p.delete('statement'); p.delete('remittance'); p.set(key, id)
    return p
  })
  const closePayment = () => { setFromLine(null); close('payment')() }

  const countFor = (t: (typeof TABS)[number]) =>
    t.statuses ? t.statuses.reduce((n, s) => n + (counts[s] ?? 0), 0) : undefined
  const current = TABS.find(t => t.key === tab) ?? TABS[0]

  // What needs a person right now — counts are across all payments, not this tab.
  const toReview = counts.needs_review ?? summary?.status_counts.needs_review ?? 0
  const toMatch = counts.unmatched ?? summary?.status_counts.unmatched ?? 0
  const parked = counts.exception ?? summary?.status_counts.exception ?? 0
  const todo = toReview + toMatch + parked

  /** Start at the top of the review queue (or unmatched, once review is empty). */
  const startReview = async () => {
    const first: Tab = toReview ? 'review' : toMatch ? 'unmatched' : 'exception'
    if (tab === first && rows.length) return openPayment(rows[0].id, rows.map(r => r.id))
    try {
      const st = TABS.find(t => t.key === first)!.statuses!.join(',')
      const list = await fetchPayments({ status: st, limit: PAGE })
      const ids = list.items.map(r => r.id)
      setQueue(ids)
      // One params update: two in a row would clobber each other.
      setParams(p => {
        for (const k of ['payment', 'statement', 'remittance']) p.delete(k)
        p.set('tab', first)
        if (ids.length) p.set('payment', ids[0])
        return p
      })
    } catch (e) {
      setErr(apiError(e))
    }
  }

  /** Confirm the agent's match without opening it — one row, or every ticked row in turn. */
  const confirmRows = async (ids: string[]) => {
    const ok = rows.filter(r => ids.includes(r.id) && confirmableFromList(r)).map(r => r.id)
    const skipped = ids.length - ok.length
    if (!ok.length) return toast.warn('Open these to review', 'Only sure matches with no warnings can be confirmed from the list.')
    setConfirming(new Set(ok))
    let done = 0
    const failed: string[] = []
    for (const id of ok) {
      try { await confirmSuggested(id); done++ } catch (e) { failed.push(apiError(e)) }
      setConfirming(c => { const n = new Set(c); n.delete(id); return n })
    }
    setPicked(new Set())
    if (done) toast.success(done === 1 ? 'Payment confirmed' : `${done} payments confirmed`,
      skipped || failed.length ? `${skipped + failed.length} left to review` : undefined)
    if (failed.length) toast.error(done ? 'Some were not confirmed' : 'Not confirmed', failed[0])
    kick()
  }

  const columns: Column<PaymentRow>[] = useMemo(() => [
    { key: 'received_on', header: 'Date', render: r => <span className="nowrap">{formatDate(r.received_on)}</span>, sortValue: r => r.received_on, width: 104 },
    {
      key: 'payer', header: 'Customer', pinned: true,
      render: r => (
        <div className="ar-sugg">
          {/* An excluded line isn't from a customer: say what it is, not the token the parser took as a name. */}
          <span className="ar-strong">{r.status === 'not_receipt' ? (r.note ?? 'Not a customer payment')
            : r.customer_name ?? r.payer_name ?? 'Unknown payer'}</span>
          <span className="ar-narr" title={r.narration ?? ''}>
            {r.utr ? `${r.method ?? ''} ${r.utr}`.trim() : r.narration ?? r.payer_name ?? '—'}
          </span>
        </div>
      ),
    },
    { key: 'amount', header: 'Amount', align: 'right', render: r => <span className="ar-money ar-strong">{money(r.amount)}</span>, sortValue: r => Number(r.amount) },
    {
      key: 'invoices', header: 'Invoices',
      render: r => {
        const list = (r.suggestion_invoices ?? '').split(',').map(x => x.trim()).filter(Boolean)
        if (!list.length) return <span className="ar-muted">—</span>
        return (
          <span className="ar-chips-inline" title={list.join(', ')}>
            {list.slice(0, 2).map(n => <span key={n} className="ar-inv-chip">{n}</span>)}
            {list.length > 2 && <span className="ar-inv-chip ar-inv-chip--more">+{list.length - 2}</span>}
          </span>
        )
      },
    },
    {
      key: 'match', header: 'Match', width: 220,
      render: r => r.match_confidence == null || !r.suggestion_kind ? <span className="ar-muted">—</span> : (
        <span className="ar-match">
          <span className={`ar-pct${Number(r.match_confidence) >= 0.95 ? ' is-hi' : ''}`}>{Math.round(Number(r.match_confidence) * 100)}%</span>
          <span className="ar-match__kind">{KIND_LABELS[r.suggestion_kind] ?? r.suggestion_kind}</span>
          {r.flags?.length ? (
            <span className="ar-match__warn" title={r.flags.map(f => FLAG_LABELS[f] ?? f).join('\n')}>
              <AlertTriangle size={12} aria-label={`${r.flags.length} warning${r.flags.length === 1 ? '' : 's'}`} />
            </span>
          ) : null}
        </span>
      ),
      sortValue: r => Number(r.match_confidence ?? 0),
    },
    {
      key: 'unapplied', header: 'On account', align: 'right',
      render: r => toPaise(r.unapplied) > 0 ? <span className="ar-money">{money(r.unapplied)}</span> : <span className="ar-muted">—</span>,
      sortValue: r => Number(r.unapplied),
    },
    { key: 'status', header: 'Status', render: r => <PaymentStatusBadge status={r.status} auto={r.auto_applied} />, width: 130 },
    {
      key: 'act', header: '', align: 'right', width: 96,
      render: r => canPost && confirmableFromList(r) ? (
        // eslint-disable-next-line jsx-a11y/click-events-have-key-events, jsx-a11y/no-static-element-interactions -- stops the row opening; the button is the control
        <span onClick={e => e.stopPropagation()}>
          <Button size="sm" variant="secondary" iconLeft={<Check size={13} />} loading={confirming.has(r.id)}
            onClick={() => void confirmRows([r.id])} title={`Apply to ${r.suggestion_invoices} as suggested`}>Confirm</Button>
        </span>
      ) : null,
    },
  ], [canPost, confirming, rows]) // eslint-disable-line react-hooks/exhaustive-deps -- confirmRows reads rows

  // Beside the open payment the list keeps only who, how much and where it stands.
  // Nothing is on account until a payment is applied, so to-do tabs drop that column.
  const hidden = useMemo(() => new Set([...(current.group === 'todo' ? ['unapplied'] : []), ...(tab === 'review' ? [] : ['act'])]),
    [tab, current.group])
  const bulk = canPost && tab === 'review'
  const pickedConfirmable = rows.filter(r => picked.has(r.id) && confirmableFromList(r)).length

  // Board | List — only Ready to confirm has the board.
  const viewToggle = (
    <div className="ar-view" role="group" aria-label="View">
      <button type="button" className={board ? 'is-on' : ''} aria-pressed={board} onClick={() => setView('board')} title="By customer, payments linked to invoices">
        <Network size={14} /> Board</button>
      <button type="button" className={!board ? 'is-on' : ''} aria-pressed={!board} onClick={() => setView('list')} title="One row per payment">
        <LayoutList size={14} /> List</button>
    </div>
  )
  const k = summary?.kpis
  const aging = summary?.aging
  const agingTotal = aging ? toPaise(aging.b0_30) + toPaise(aging.b31_60) + toPaise(aging.b61_plus) : 0

  return (
    <div className="ar-shell">
    <div className="ar">
      <PageHeader
        title="Cash Application"
        sub="Incoming payments, matched to your invoices."
        actions={canCapture && (
          <>
            <Button variant="secondary" iconLeft={<Mail size={14} />} onClick={() => setModal('remit')}>Add remittance</Button>
            <Button variant="secondary" iconLeft={<Plus size={14} />} onClick={() => setModal('record')}>Record payment</Button>
            <Button variant="primary" iconLeft={<FileSpreadsheet size={14} />} onClick={() => setModal('import')}>Import statement</Button>
          </>
        )}
      />

      {/* The four numbers receivables teams track for cash application, last 30 days. */}
      <div className="ar-stats" aria-label="Last 30 days">
        <Stat label="Cash collected" period="last 30 days" value={money(summary?.payments.receipts_total)}
          sub={summary && <Trend now={toPaise(summary.payments.receipts_total)} before={toPaise(summary.previous?.receipts_total)} what="vs previous 30 days" pct />}
          sub2={summary ? `${summary.payments.receipts} payment${summary.payments.receipts === 1 ? '' : 's'}` : undefined} />
        <Stat label="Auto-match rate" value={pct(k?.match_rate)}
          bar={k?.match_rate ?? undefined}
          sub2={summary ? `${summary.payments.auto_count} of ${summary.payments.receipts} payments, by the agent` : undefined} />
        <Stat label="Unapplied cash" value={aging ? money(fromPaise(agingTotal)) : '—'}
          sub={summary ? `${money(summary.unapplied_in_review)} ready to confirm` : undefined}
          sub2={aging ? (toPaise(aging.b61_plus) > 0 ? `${money(aging.b61_plus)} unapplied over 60 days` : 'Nothing unapplied over 60 days') : undefined}
          warn2={!!aging && toPaise(aging.b61_plus) > 0} />
        <Stat label="DSO" title="Days sales outstanding" value={k?.dso != null ? `${k.dso}` : '—'} unit={k?.dso != null ? 'days' : undefined}
          sub={k?.dso != null && k.dso_previous != null ? <Trend now={k.dso} before={k.dso_previous} what="vs a month ago" days invert /> : undefined}
          sub2={summary && toPaise(summary.ar.open_ar) > 0
            ? `${Math.round(toPaise(summary.ar.overdue) / toPaise(summary.ar.open_ar) * 100)}% of ${money(summary.ar.open_ar)} open is overdue` : undefined} />
      </div>

      <div className="ar-toolbar">
        <div className="ar-tabs" role="tablist" aria-label="Payments">
          {TABS.map((t, i) => {
            const n = countFor(t)
            const sep = i > 0 && TABS[i - 1].group !== t.group
            return (
              <span key={t.key} className="ar-tabs__item">
                {sep && <span className="ar-tabs__sep" aria-hidden="true" />}
                <button role="tab" aria-selected={tab === t.key} title={t.hint}
                  className={`ar-tab${tab === t.key ? ' ar-tab--on' : ''}`} onClick={() => setTab(t.key)}>
                  {t.label}{n && t.group === 'todo' ? <span className="ar-tab__n ar-tab__n--todo">{n}</span> : null}
                </button>
              </span>
            )
          })}
        </div>
        <div className="ar-toolbar__end">
          {!docTab && (
            <input className="ar-search" type="search" placeholder="Search customer, UTR, amount" value={q}
              onChange={e => setQ(e.target.value)} aria-label="Search payments" />
          )}
          {todo > 0 && (
            <Button variant="primary" iconRight={<ArrowRight size={14} />} onClick={startReview}
              title={[toReview && `${toReview} ready to confirm`, toMatch && `${toMatch} need a match`, parked && `${parked} in follow-up`].filter(Boolean).join(' · ')}>
              Review {todo}
            </Button>
          )}
        </div>
      </div>

      {err && <ErrorState message={err} onRetry={load} />}

      {!err && tab === 'remittances' && (
        <RemittanceList items={remits} loading={loading} onOpen={id => open('remittance', id)} />
      )}
      {!err && tab === 'statements' && (
        <StatementList items={statements} loading={loading} onOpen={id => open('statement', id)}
          onImport={canCapture ? () => setModal('import') : undefined} />
      )}

      {!err && board && (
        groups.length || loading ? (
          <ReviewBoard groups={groups} canPost={canPost} onChanged={kick} toolbar={viewToggle}
            onOpenEdge={(pid, iid, draft) => { setFromLine({ pid, iid, draft }); openPayment(pid, groups.flatMap(g => g.payments.map(p => p.id))) }} />
        ) : (
          <EmptyState title={q ? 'No payments match your search' : 'Nothing to confirm'} message={q ? undefined : current.hint}
            action={canCapture && !q ? <Button variant="primary" iconLeft={<FileSpreadsheet size={14} />} onClick={() => setModal('import')}>Import statement</Button> : undefined} />
        )
      )}

      {!err && !docTab && !board && (
        <>
          {tab === 'review' && <div className="ar-subbar">{viewToggle}</div>}
          {bulk && picked.size > 0 && (
            <div className="ar-bulk" role="status">
              <span><strong>{picked.size}</strong> selected{pickedConfirmable < picked.size ? ` · ${pickedConfirmable} can be confirmed here` : ''}</span>
              <Button size="sm" variant="primary" iconLeft={<Check size={13} />} disabled={!pickedConfirmable}
                loading={confirming.size > 0} onClick={() => void confirmRows([...picked])}>Confirm {pickedConfirmable}</Button>
              <button type="button" className="ar-link" onClick={() => setPicked(new Set())}>Clear</button>
            </div>
          )}
          <DataTable
            caption="Incoming payments"
            rows={rows}
            columns={columns}
            rowKey={r => r.id}
            activeId={openId}
            hiddenColumns={hidden}
            density="comfortable"
            selectedIds={bulk ? picked : undefined}
            onSelectionChange={bulk ? setPicked : undefined}
            loading={loading && rows.length === 0}
            onRowClick={r => openPayment(r.id, rows.map(x => x.id))}
            empty={
              <EmptyState
                title={q ? 'No payments match your search' : current.group === 'todo' ? 'Nothing to do here' : 'No payments here'}
                message={q ? undefined : current.hint}
                action={canCapture && tab === 'review' && !q
                  ? <Button variant="primary" iconLeft={<FileSpreadsheet size={14} />} onClick={() => setModal('import')}>Import statement</Button>
                  : undefined}
              />
            }
          />
          {total > PAGE && <Pager page={page} perPage={PAGE} total={total} onGo={setPage} onPerPage={() => {}} label="Pages of payments" />}
        </>
      )}

    </div>
      {/* The payment opens as the bill card does: same overlay, same size, grown out of the row that was clicked. */}
      {openId && (
        <PaymentCard key={fromLine?.pid === openId ? `line-${fromLine.iid}` : 'card'} onClose={closePayment}>
          <PaymentWorkbench paymentId={openId} queue={queue} onNavigate={id => open('payment', id)}
            onClose={closePayment} onChanged={kick}
            onOpenStatement={id => peek('statement', id)} onOpenRemittance={id => peek('remittance', id)}
            draft={fromLine?.pid === openId ? fromLine.draft : null} focusInvoiceId={fromLine?.pid === openId ? fromLine.iid : null} />
        </PaymentCard>
      )}
      <StatementViewer id={statementId} onClose={close('statement')} onOpenPayment={id => openPayment(id)} focusPaymentId={openId} />
      <RemittanceViewer id={remittanceId} onClose={close('remittance')} onOpenPayment={id => openPayment(id)} currentPaymentId={openId} />
      <ImportStatementModal open={modal === 'import'} onClose={() => setModal(null)} onDone={kick}
        onView={id => open('statement', id)} />
      <RemittanceModal open={modal === 'remit'} onClose={() => setModal(null)} onDone={kick} />
      <RecordPaymentModal open={modal === 'record'} onClose={() => setModal(null)}
        onDone={id => { kick(); openPayment(id) }} />
    </div>
  )
}

function Stat({ label, period, title, value, unit, bar, sub, sub2, warn2 }: {
  label: string; period?: string; title?: string; value: string; unit?: string
  /** 0–1: drawn as a thin bar under the value. */
  bar?: number
  sub?: ReactNode; sub2?: string; warn2?: boolean
}) {
  return (
    <div className="ar-stat" title={title}>
      <span className="ar-stat__k">{label}{period && <span className="ar-stat__p"> · {period}</span>}</span>
      <span className="ar-stat__v">{value}{unit && <span className="ar-stat__u"> {unit}</span>}</span>
      {bar != null && <span className="ar-stat__bar" aria-hidden="true"><span style={{ width: `${Math.round(bar * 100)}%` }} /></span>}
      {sub != null && <span className="ar-stat__sub">{sub}</span>}
      {sub2 && <span className={`ar-stat__sub${warn2 ? ' is-warn' : ''}`}>{sub2}</span>}
    </div>
  )
}

/** Change against the period before. Up is good for cash, bad for DSO (invert). */
function Trend({ now, before, what, pct: asPct, days, invert }: {
  now: number; before: number; what: string; pct?: boolean; days?: boolean; invert?: boolean
}) {
  if (!before) return <>{asPct ? `Nothing in the 30 days before` : '—'}</>
  const diff = now - before
  if (Math.abs(diff) < (days ? 0.05 : 1)) return <>Same as {what.replace(/^vs /, '')}</>
  const up = diff > 0
  const good = invert ? !up : up
  const amount = asPct ? `${Math.round(Math.abs(diff) / before * 100)}%` : `${Math.abs(diff).toFixed(1)} days`
  return <><span className={`ar-trend ${good ? 'is-good' : 'is-bad'}`}>{up ? '▲' : '▼'} {amount}</span> {what}</>
}

function StatementList({ items, loading, onOpen, onImport }: {
  items: StatementRow[]; loading: boolean; onOpen: (id: string) => void; onImport?: () => void
}) {
  const cols: Column<StatementRow>[] = [
    { key: 'created_at', header: 'Imported', render: r => formatDate(r.created_at), width: 110 },
    { key: 'file', header: 'File', render: r => <span className="ar-strong">{r.file_name}</span> },
    { key: 'account', header: 'Account', render: r => r.bank_account ?? '—' },
    { key: 'period', header: 'Period', render: r => `${formatDate(r.period_from)} – ${formatDate(r.period_to)}` },
    { key: 'credits', header: 'Credits', align: 'right', render: r => r.credits },
    { key: 'new', header: 'New payments', align: 'right', render: r => r.imported },
    { key: 'dup', header: 'Duplicates', align: 'right', render: r => r.duplicates || '—' },
    { key: 'ex', header: 'Excluded', align: 'right', render: r => r.set_aside || '—' },
    { key: 'by', header: 'By', render: r => r.uploaded_by ?? '—' },
  ]
  return (
    <DataTable caption="Bank statements" rows={items} columns={cols} rowKey={r => r.id} loading={loading && !items.length}
      onRowClick={r => onOpen(r.id)}
      empty={<EmptyState title="No statements imported yet" message="Every statement you import is kept here — open one to see each line and what it became."
        action={onImport ? <Button variant="primary" iconLeft={<FileSpreadsheet size={14} />} onClick={onImport}>Import statement</Button> : undefined} />} />
  )
}

function RemittanceList({ items, loading, onOpen }: { items: Remittance[]; loading: boolean; onOpen: (remittanceId: string) => void }) {
  const cols: Column<Remittance>[] = [
    { key: 'created_at', header: 'Received', render: r => formatDate(r.created_at), width: 110 },
    { key: 'payer', header: 'Payer', render: r => <span className="ar-strong">{r.payer_name ?? '—'}</span> },
    { key: 'ref', header: 'UTR / ref.', render: r => <span className="ar-mono">{r.payment_reference ?? '—'}</span> },
    { key: 'total', header: 'Total', align: 'right', render: r => <span className="ar-money">{money(r.total_amount)}</span> },
    {
      key: 'lines', header: 'Invoices',
      render: r => r.lines.length ? (
        <span className="ar-chips-inline" title={r.lines.map(l => l.invoice_number).join(', ')}>
          {r.lines.slice(0, 2).map((l, i) => <span key={i} className="ar-inv-chip">{l.invoice_number}</span>)}
          {r.lines.length > 2 && <span className="ar-inv-chip ar-inv-chip--more">+{r.lines.length - 2}</span>}
        </span>
      ) : <span className="ar-muted">—</span>,
    },
    { key: 'status', header: 'Payment', render: r => r.payment_id ? <Badge tone="success">Linked</Badge> : <Badge tone="warn">Waiting for payment</Badge> },
  ]
  return (
    <DataTable caption="Remittance advice" rows={items} columns={cols} rowKey={r => r.id} loading={loading && !items.length}
      onRowClick={r => onOpen(r.id)}
      empty={<EmptyState title="No remittance advice yet" message="Paste a customer's payment email or upload their advice PDF." />} />
  )
}

/**
 * The bill card's frame around the payment: its overlay, its 1400px sheet, and
 * its opening — the card grows out of the row that was clicked. The origin is
 * taken once, when the card opens; stepping to the next payment keeps the card.
 */
function PaymentCard({ onClose, children }: { onClose: () => void; children: ReactNode }) {
  const [origin] = useState(() => clickOrigin() ?? '0px 0px')
  const [dx, dy] = origin.split(' ')
  useScrollLock(true) // as the bill card: the page behind stays put while the card is up
  return (
    <div className="bm__overlay" role="presentation" onMouseDown={e => { if (e.target === e.currentTarget) onClose() }}>
      <div className="bm__card ar-card" style={{ '--bm-dx': dx, '--bm-dy': dy } as CSSProperties}>{children}</div>
    </div>
  )
}
