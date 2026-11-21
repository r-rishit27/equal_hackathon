import { AlertTriangle, CheckCircle2, Clock, FileClock } from 'lucide-react'
import { useMemo } from 'react'

import type { ReconCaseSummary } from '../../../api/recon'
import { inr } from './reconFormat'

/**
 * Where the whole queue stands, in four answers.
 *
 * A reviewer opening Recon is asking one thing before anything else: **is
 * there money I should not pay yet, and what is holding the rest up.** So the
 * exposure is the headline and everything else qualifies it.
 *
 * Each panel answers a different question and uses the form that question
 * deserves — a figure where a figure is the answer, a split where a split is,
 * a meter per leg where each leg has its own whole. None of them is a chart
 * for its own sake, and nothing here is a pie.
 *
 * **Everything is a filter.** A dashboard that shows a problem and leaves you
 * to find it in a list below has only told you to go looking; clicking any
 * status, any leg or any confidence band narrows what is underneath.
 */
type Props = {
  cases: ReconCaseSummary[] | null
  active: string | null
  onPick: (filter: string | null) => void
}

/** Status fills, re-stepped after validation.
 *
 *  The obvious choice — the app's danger-600 beside warn-600 — measured ΔE 9.1
 *  to NORMAL vision, below the floor of 15: adjacent in one bar, most people
 *  cannot tell them apart. These four clear every check (worst adjacent pair
 *  ΔE 29.4 normal, 21.1 under protanopia). Amber is under 3:1 on white, which
 *  is why every segment is also named and counted in the list beside it —
 *  colour is never the only thing carrying a status here.
 */
const STATUS_GROUP = [
  { key: 'ready', label: 'Ready to pay', fill: '#047857', icon: CheckCircle2,
    has: (c: ReconCaseSummary) => c.status === 'RECONCILED' },
  { key: 'review', label: 'Needs review', fill: '#b91c1c', icon: AlertTriangle,
    has: (c: ReconCaseSummary) => c.status === 'NEEDS_REVIEW' },
  { key: 'waiting', label: 'Waiting on a document', fill: '#f59e0b', icon: Clock,
    has: (c: ReconCaseSummary) => c.status.startsWith('AWAITING') },
  { key: 'done', label: 'Signed off', fill: '#2563eb', icon: FileClock,
    has: (c: ReconCaseSummary) => c.status === 'ACKNOWLEDGED' },
  { key: 'queued', label: 'In progress', fill: '#64748b', icon: Clock,
    has: (c: ReconCaseSummary) => c.status === 'IN_PROGRESS' },
] as const

/** One whole per leg, so each gets its own meter rather than a shared axis. */
const LEGS = [
  { key: 'leg:po', label: 'Purchase order', has: (c: ReconCaseSummary) => c.docs.po },
  { key: 'leg:audit', label: 'Audit report', has: (c: ReconCaseSummary) => c.docs.evidence > 0 },
  { key: 'leg:receipt', label: 'Receipt proof', has: (c: ReconCaseSummary) => c.docs.pod },
  { key: 'leg:invoice', label: 'Invoice', has: (c: ReconCaseSummary) => c.docs.invoice },
] as const

/** Ordered bands, so the scale itself carries the meaning and no band needs a
 *  colour of its own. One hue, darker as confidence rises. */
const BANDS = [
  { key: 'conf:low', label: 'Under 50%', fill: '#bfdbfe', lo: 0, hi: 0.5 },
  { key: 'conf:mid', label: '50–70%', fill: '#7faed8', lo: 0.5, hi: 0.7 },
  { key: 'conf:good', label: '70–85%', fill: '#3b82c4', lo: 0.7, hi: 0.85 },
  { key: 'conf:high', label: '85% and up', fill: '#0b56a4', lo: 0.85, hi: 1.01 },
] as const

const n = (v: string | number | null | undefined) => Number(v ?? 0)

export function ReconDashboard({ cases, active, onPick }: Props) {
  const d = useMemo(() => {
    // A deleted bill is not in the payable queue: it has no exposure, no
    // status worth grouping and nothing to chase. It stays visible in the
    // list below, where its documents can still be reached.
    const all = (cases ?? []).filter(c => !c.bill_deleted)
    const risk = all.reduce((s, c) => s + n(c.money_at_risk), 0)
    const under = all.reduce((s, c) => s + n(c.under_billed), 0)
    const groups = STATUS_GROUP.map(g => ({ ...g, n: all.filter(g.has).length }))
    const legs = LEGS.map(l => ({ ...l, n: all.filter(l.has).length }))
    // A case with no PO has nothing paired, so it has no confidence to plot —
    // it is a missing document, not an untrustworthy match.
    const scored = all.filter(c => c.confidence !== null && c.confidence !== undefined)
    const bands = BANDS.map(b => ({
      ...b, n: scored.filter(c => n(c.confidence) >= b.lo && n(c.confidence) < b.hi).length,
    }))
    return { all, risk, under, groups, legs, bands, scored: scored.length }
  }, [cases])

  if (!cases) return null
  if (d.all.length === 0) return null

  const total = d.all.length
  const pick = (k: string) => onPick(active === k ? null : k)
  const maxBand = Math.max(1, ...d.bands.map(b => b.n))

  return (
    <section className="rd" aria-label="Where the queue stands">
      {/* The exposure, as a figure — a one-bar chart of one number is not a
          chart, it is a number with decoration. */}
      <div className="rd__hero">
        <div className="rd__hero-k">
          Billed above supported value
        </div>
        <div className={`rd__hero-v${d.risk > 0 ? ' rd__hero-v--bad' : ''}`}>
          ₹{inr(d.risk)}
        </div>
        <div className="rd__hero-d">
          across {total} invoice{total === 1 ? '' : 's'}
          {d.under > 0 && <> · vendor under-billed ₹{inr(d.under)}, their loss</>}
        </div>
      </div>

      <div className="rd__grid">
        {/* Split of one whole, read beside its figures: a thin segmented bar
            with no text on it, because the list under it carries the names and
            the counts. */}
        <div className="rd__panel">
          <h4 className="rd__h">Where the invoices stand</h4>
          <div className="rd__split" role="img"
            aria-label={d.groups.map(g => `${g.label}: ${g.n}`).join(', ')}>
            {d.groups.filter(g => g.n > 0).map(g => (
              <span key={g.key} className="rd__seg" style={{ flexGrow: g.n, background: g.fill }} />
            ))}
          </div>
          <ul className="rd__legend">
            {d.groups.map(g => {
              const Icon = g.icon
              return (
                <li key={g.key}>
                  <button type="button" className={`rd__pick${active === g.key ? ' on' : ''}`}
                    disabled={g.n === 0} onClick={() => pick(g.key)}
                    aria-pressed={active === g.key}>
                    <span className="rd__dot" style={{ background: g.fill }} aria-hidden />
                    <Icon size={13} aria-hidden className="rd__ic" />
                    <span className="rd__pick-l">{g.label}</span>
                    <span className="rd__pick-n">{g.n}</span>
                  </button>
                </li>
              )
            })}
          </ul>
        </div>

        {/* Four ratios, each against its own whole — a meter per row, not four
            slices of one pie. The gap is the story: it says which document to
            chase. */}
        <div className="rd__panel">
          <h4 className="rd__h">What each invoice is checked against</h4>
          <ul className="rd__meters">
            {d.legs.map(l => {
              const pct = Math.round((l.n / total) * 100)
              return (
                <li key={l.key}>
                  <button type="button" className={`rd__meter${active === l.key ? ' on' : ''}`}
                    onClick={() => pick(l.key)} aria-pressed={active === l.key}
                    title={`${total - l.n} invoice${total - l.n === 1 ? '' : 's'} without one`}>
                    <span className="rd__meter-l">{l.label}</span>
                    <span className="rd__meter-t">
                      <span className="rd__meter-f" style={{ width: `${pct}%` }} />
                    </span>
                    <span className="rd__meter-v">{l.n}<span className="rd__of">/{total}</span></span>
                  </button>
                </li>
              )
            })}
          </ul>
        </div>

        {/* Ordered bands on one hue. Low confidence is a concern, but painting
            it red would borrow the status palette for something that is not a
            status — the order of the scale says which end is which. */}
        <div className="rd__panel">
          <h4 className="rd__h">
            How sure the matching is
            <span className="rd__sub">share of billed value on a pairing we trust</span>
          </h4>
          {d.scored === 0 ? (
            <p className="rd__none">Nothing paired yet — these invoices are still waiting for a PO.</p>
          ) : (
            <ul className="rd__bars">
              {d.bands.map(b => (
                <li key={b.key}>
                  <button type="button" className={`rd__bar${active === b.key ? ' on' : ''}`}
                    disabled={b.n === 0} onClick={() => pick(b.key)} aria-pressed={active === b.key}>
                    <span className="rd__bar-l">{b.label}</span>
                    <span className="rd__bar-t">
                      <span className="rd__bar-f"
                        style={{ width: `${Math.round((b.n / maxBand) * 100)}%`, background: b.fill }} />
                    </span>
                    <span className="rd__bar-v">{b.n}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>

      {active && (
        <button type="button" className="vc__lnk rd__clear" onClick={() => onPick(null)}>
          Showing a filtered list · clear
        </button>
      )}
    </section>
  )
}

/** Does a case pass the dashboard's current filter? Exported so the list below
 *  and the panels above can never drift apart about what a filter means. */
export function matchesFilter(c: ReconCaseSummary, filter: string | null): boolean {
  if (!filter) return true
  const g = STATUS_GROUP.find(x => x.key === filter)
  if (g) return g.has(c)
  const l = LEGS.find(x => x.key === filter)
  if (l) return l.has(c)
  const b = BANDS.find(x => x.key === filter)
  if (b) {
    if (c.confidence === null || c.confidence === undefined) return false
    const v = Number(c.confidence)
    return v >= b.lo && v < b.hi
  }
  return true
}
