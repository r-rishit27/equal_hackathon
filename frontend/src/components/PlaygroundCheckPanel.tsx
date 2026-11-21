import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { AlertTriangle, ChevronDown, Workflow } from 'lucide-react'
import { fetchBillPlaygroundCheck, type BillPlaygroundCheck, type FlowTermNote } from '../api/vendorCard'
import { reviewPath, vendorPath } from '../routes/paths'
import { termLabel, termValue } from './playgroundTerms'

/**
 * The vendor's playground run checked against this bill — the sheet's
 * calculated invoice amount beside the bill's amount before GST, and the
 * contract terms that calculation used. Sits under the Nova panel and reads
 * the same way: a coloured header that says the answer, figures underneath.
 *
 * Renders nothing when no run has been compared with this bill, which is
 * most bills.
 */

const inr = (v: number | null | undefined) =>
  v == null ? '—' : `₹${v.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`

const TONE = {
  match: { bg: '#f0fdf4', fg: '#15803d', bd: '#bbf7d0' },
  close: { bg: '#fffbeb', fg: '#b45309', bd: '#fde68a' },
  off:   { bg: '#fef2f2', fg: '#b91c1c', bd: '#fecaca' },
} as const

export default function PlaygroundCheckPanel({ invoiceId }: { invoiceId: string }) {
  const [check, setCheck] = useState<BillPlaygroundCheck | null>(null)
  const [open, setOpen] = useState<boolean | null>(null)

  useEffect(() => {
    let live = true
    setCheck(null)
    fetchBillPlaygroundCheck(invoiceId)
      .then(c => { if (live) setCheck(c) })
      // A check that cannot load is not a finding about the bill; the panel stays away.
      .catch(() => { if (live) setCheck(null) })
    return () => { live = false }
  }, [invoiceId])

  const r = check?.recon
  if (!check || !r) return null

  const tone = TONE[r.status]
  // A mismatch or an open question opens itself; a match stays one line.
  const expanded = open ?? (r.status !== 'match' || check.pending_terms.length > 0)
  const diff = r.difference
  const headline = r.status === 'match'
    ? 'matches the bill'
    : `${inr(Math.abs(diff))} ${diff > 0 ? 'more than' : 'less than'} the bill${r.difference_pct != null ? ` (${r.difference_pct}%)` : ''}`

  const cell: React.CSSProperties = { display: 'flex', flexDirection: 'column', gap: 2, minWidth: 0 }
  const k: React.CSSProperties = { fontSize: 11, fontWeight: 600, color: '#64748b', textTransform: 'uppercase', letterSpacing: '.04em' }
  const v: React.CSSProperties = { fontSize: 15, fontWeight: 700, color: '#0f172a', fontVariantNumeric: 'tabular-nums' }

  return (
    <div className="bm__recon" data-focus-key="playground"
      style={{ margin: '14px 0 4px', border: `1px solid ${expanded ? tone.bd : '#e5e7eb'}`, borderRadius: 10, overflow: 'hidden' }}>
      <button type="button" onClick={() => setOpen(!expanded)} aria-expanded={expanded}
        style={{ display: 'flex', alignItems: 'center', gap: 8, width: '100%', padding: '10px 14px', border: 0,
          background: tone.bg, color: tone.fg, fontWeight: 700, fontSize: 13, cursor: 'pointer', textAlign: 'left',
          borderBottom: expanded ? `1px solid ${tone.bd}` : 'none' }}>
        <ChevronDown size={14} style={{ transform: expanded ? 'none' : 'rotate(-90deg)', transition: 'transform .15s', flexShrink: 0 }} />
        {r.status === 'match' ? '✓' : '✗'} Playground check — {r.report_name || 'calculated sheet'}
        <span style={{ fontWeight: 600, fontSize: 12 }}>· {headline}</span>
      </button>

      {expanded && (
        <div style={{ padding: '12px 14px', fontSize: 13, display: 'flex', flexDirection: 'column', gap: 12 }}>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 12 }}>
            <div style={cell}>
              <span style={k}>Calculated · {r.total_name}</span>
              <span style={v}>{inr(r.sheet_total)}</span>
            </div>
            <div style={cell}>
              <span style={k}>On the bill · before GST</span>
              <span style={v}>{inr(r.before_tax)}</span>
              {r.bill_total != null && <span style={{ fontSize: 11.5, color: '#64748b' }}>{inr(r.bill_total)} with GST</span>}
            </div>
            <div style={cell}>
              <span style={k}>Difference</span>
              <span style={{ ...v, color: r.status === 'match' ? '#15803d' : tone.fg }}>
                {r.status === 'match' ? 'None' : `${diff > 0 ? '+' : '−'}${inr(Math.abs(diff))}`}
              </span>
              {r.status !== 'match' && (
                <span style={{ fontSize: 11.5, color: '#64748b' }}>
                  {diff > 0 ? 'calculated is higher' : 'bill is higher'}
                </span>
              )}
            </div>
          </div>

          {r.terms.length > 0 && (
            <div>
              <div style={{ ...k, marginBottom: 6 }}>Contract terms used</div>
              <ul style={{ margin: 0, padding: 0, listStyle: 'none', display: 'flex', flexDirection: 'column', gap: 4 }}>
                {r.terms.map(t => <TermLine key={t.field} t={t} />)}
              </ul>
            </div>
          )}

          {check.pending_terms.length > 0 && (
            <div role="note" style={{ display: 'flex', gap: 8, alignItems: 'flex-start', padding: '8px 10px',
              background: '#fffbeb', border: '1px solid #fde68a', borderRadius: 8, color: '#92400e', fontSize: 12.5 }}>
              <AlertTriangle size={14} style={{ flexShrink: 0, marginTop: 2 }} aria-hidden="true" />
              <span>
                {check.pending_terms.map(p => (
                  <span key={p.field} style={{ display: 'block' }}>
                    {p.contract_file || 'The latest contract'} sets the {termLabel(p.field).toLowerCase()} at{' '}
                    <b>{termValue(p.contract_value, p.unit)}</b>; this was calculated at <b>{termValue(p.value, p.unit)}</b>.
                  </span>
                ))}
                <Link to={reviewPath()} style={{ color: '#92400e', fontWeight: 700 }}>Choose which to use in Review Hub</Link>
                {', then run the playground again.'}
              </span>
            </div>
          )}

          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'center', fontSize: 11.5, color: '#94a3b8' }}>
            <span>
              Run{check.run_by ? ` by ${check.run_by}` : ''}
              {check.run_at ? ` · ${new Date(check.run_at).toLocaleString('en-IN', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' })}` : ''}
              {r.service_month ? ` · bill for ${r.service_month}` : ''}
              {r.status === 'close' ? ` · within ${r.close_pct}%, beyond rounding` : ''}
            </span>
            <Link to={vendorPath(check.supplier_id, 'playground')}
              style={{ marginLeft: 'auto', display: 'inline-flex', alignItems: 'center', gap: 4, color: '#2563eb', fontWeight: 600 }}>
              <Workflow size={12} aria-hidden="true" /> Open the playground
            </Link>
          </div>
        </div>
      )}
    </div>
  )
}

function TermLine({ t }: { t: FlowTermNote }) {
  return (
    <li style={{ display: 'flex', flexWrap: 'wrap', gap: 6, alignItems: 'baseline' }}>
      <span style={{ fontWeight: 600, color: '#334155' }}>{termLabel(t.field)}</span>
      <span style={{ fontWeight: 700, color: '#0f172a' }}>{termValue(t.value, t.unit)}</span>
      <span style={{ color: '#64748b', fontSize: 12 }}>
        {t.status === 'held' && <>from {t.file_name || 'the contract'}</>}
        {t.status === 'kept' && <>from {t.file_name || 'an earlier decision'} · {t.contract_file || 'the contract'} says {termValue(t.contract_value ?? '', t.unit)}</>}
        {t.status === 'changed' && (
          <span style={{ color: '#b45309' }}>
            held — {t.contract_file || 'the latest contract'} says {termValue(t.contract_value ?? '', t.unit)}
          </span>
        )}
      </span>
    </li>
  )
}
