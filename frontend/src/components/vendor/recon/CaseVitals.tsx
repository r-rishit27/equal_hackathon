import type { LineResult, ReconCaseSummary, ReconSegment } from '../../../api/recon'

/**
 * How well this reconciliation is actually standing up — three measures a
 * finance reviewer needs before trusting the verdict above them.
 *
 * The four comparison cards say *what* each document concluded. They are
 * silent on the question underneath: **how much is this conclusion worth?**
 * An invoice can show "all agree" on a leg that covers a fifth of its value,
 * or on pairings the matcher was barely sure of, and nothing on the screen
 * said so. All three numbers were computed already and reached nobody.
 *
 * Each uses the form its question deserves and no more: a meter per leg
 * because each has its own whole, a figure for the one headline number, and
 * ordered bars for a distribution. Nothing here is decoration — if a row has
 * no answer it says so with a dash rather than drawing an empty bar.
 */
type Props = {
  s: ReconCaseSummary
  lines: LineResult[]
  attached: ReconSegment[]
}

const LEGS = [
  { key: 'po', label: 'Purchase order', asks: 'ordered' },
  { key: 'evidence', label: 'Audit report', asks: 'verified' },
  { key: 'pod', label: 'Receipt', asks: 'received' },
  { key: 'payment', label: 'Payment', asks: 'settled' },
] as const

/** Ordered bands on one hue: the scale carries the meaning, so no band needs
 *  a colour of its own and none of them borrows the status palette. */
const BANDS = [
  { label: 'Exact', fill: '#0b56a4', of: (l: LineResult) => l.match_method === 'EXACT' || l.match_method === 'HUMAN' },
  { label: 'Strong', fill: '#3b82c4', of: (l: LineResult) => (l.match_score ?? 0) >= 0.85 },
  { label: 'Fair', fill: '#7faed8', of: (l: LineResult) => (l.match_score ?? 0) >= 0.72 },
  { label: 'Unpaired', fill: '#cbd5e1', of: (l: LineResult) => true },
] as const

export function CaseVitals({ s, lines, attached }: Props) {
  const billed = lines.filter(l => l.invoice_key)
  // Each line falls in the first band it qualifies for, so the bands partition
  // the lines and the counts add up to the total.
  const bands = BANDS.map(b => ({ ...b, n: 0 }))
  for (const l of billed) {
    const i = BANDS.findIndex(b => b.of(l))
    bands[i === -1 ? bands.length - 1 : i].n += 1
  }
  const worst = Math.max(1, ...bands.map(b => b.n))

  // What the readers were unsure of. A scanned sheet read twice can disagree
  // with itself; those cells are the ones a person was asked to settle.
  const flagged = attached.reduce((n, a) => n + (a.needs_review_cells ?? 0), 0)
  const conf = s.confidence === null || s.confidence === undefined ? null : Number(s.confidence)

  return (
    <section className="cv" aria-label="How well this reconciliation stands up">
      <div className="cv__panel">
        <h4 className="cv__h">What each document covers
          <span className="cv__sub">share of the billed value it accounts for</span></h4>
        <ul className="cv__meters">
          {LEGS.map(l => {
            const v = s.leg_cover?.[l.key]
            const pct = v === null || v === undefined ? null : Math.round(v * 100)
            return (
              <li key={l.key}>
                <span className="cv__meter-l">{l.label}</span>
                <span className="cv__meter-t">
                  {pct !== null && <span className="cv__meter-f" style={{ width: `${pct}%` }} />}
                </span>
                <span className="cv__meter-v">
                  {pct === null
                    // Not arrived is not nought. A dash asks for the document;
                    // a 0% accuses it of covering nothing.
                    ? <span className="vc__muted" title={`No ${l.label.toLowerCase()} on this case yet`}>—</span>
                    : `${pct}%`}
                </span>
              </li>
            )
          })}
        </ul>
      </div>

      <div className="cv__panel">
        <h4 className="cv__h">How sure the matching is
          <span className="cv__sub">weighted by money, not by line count</span></h4>
        {conf === null ? (
          <p className="cv__none">Nothing paired yet — this invoice is still waiting for its PO.</p>
        ) : (
          <>
            <div className={`cv__fig${conf < 0.7 ? ' cv__fig--warn' : ''}`}>{Math.round(conf * 100)}%</div>
            <ul className="cv__bars">
              {bands.filter(b => b.n > 0).map(b => (
                <li key={b.label}>
                  <span className="cv__bar-l">{b.label}</span>
                  <span className="cv__bar-t">
                    <span className="cv__bar-f" style={{ width: `${(b.n / worst) * 100}%`, background: b.fill }} />
                  </span>
                  <span className="cv__bar-v">{b.n}</span>
                </li>
              ))}
            </ul>
          </>
        )}
      </div>

      <div className="cv__panel">
        <h4 className="cv__h">How the documents read
          <span className="cv__sub">cells a reader could not settle alone</span></h4>
        <div className={`cv__fig${flagged > 0 ? ' cv__fig--warn' : ''}`}>{flagged}</div>
        <p className="cv__note">
          {flagged === 0
            ? `${attached.length} document${attached.length === 1 ? '' : 's'} read with nothing left in doubt.`
            : `across ${attached.length} document${attached.length === 1 ? '' : 's'}. A scanned sheet is read twice; where the two readings disagree the cell is left for a person rather than settled by a coin toss.`}
        </p>
      </div>
    </section>
  )
}
