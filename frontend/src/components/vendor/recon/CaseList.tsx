import { ChevronRight } from 'lucide-react'

import type { ReconCaseSummary } from '../../../api/recon'
import { CaseStatusChip } from './CaseStatusChip'
import { ReconLink } from '../../records/RecordLink'
import { inr } from './reconFormat'

/**
 * The invoices themselves, each one a way into its reconciliation.
 *
 * Until this existed a reconciliation could only be reached by finding a
 * *document* that happened to belong to it and clicking the invoice number in
 * its row — so the screen that answers "can I pay this" had no front door of
 * its own. The dashboard above counts and groups these cases; this is the
 * list those counts are made of, and clicking any row opens it.
 *
 * Every column is something a reviewer decides on: what is at stake, how much
 * of the bill is actually supported by documents, and how sure the matching
 * underneath is. A row with nothing at stake says so rather than printing a
 * zero in the same weight as a real exposure.
 */
export function CaseList({ cases, filtered }: {
  cases: ReconCaseSummary[]
  /** True when the dashboard is narrowing these, so the heading can say so. */
  filtered?: boolean
}) {
  if (cases.length === 0) {
    return (
      <section className="rc__sec" aria-label="Invoices">
        <div className="vc__subhead">Invoices</div>
        <div className="vc__empty">
          <div className="vc__empty-t">Nothing matches that</div>
          <div className="vc__muted vc__xs">Clear the filter above to see every invoice again.</div>
        </div>
      </section>
    )
  }
  return (
    <section className="rc__sec" aria-label="Invoices">
      <div className="vc__subhead">
        {filtered ? `Invoices matching · ${cases.length}` : `Invoices · ${cases.length}`}
      </div>
      <div className="rc__scroll">
        <table className="rc__table rc__files cl">
          <thead>
            <tr>
              <th>Invoice</th><th>Status</th>
              <th className="rc__num">At stake</th>
              <th className="rc__num" title="Share of the billed value its documents account for">Covered</th>
              <th className="rc__num" title="How sure the line matching is, weighted by money">Matching</th>
              <th><span className="vc__sr">Open</span></th>
            </tr>
          </thead>
          <tbody>
            {cases.map(c => {
              const risk = Number(c.money_at_risk ?? 0)
              const conf = c.confidence === null || c.confidence === undefined ? null : Number(c.confidence)
              const cover = coverOf(c)
              return (
                <tr key={c.id}>
                  <td>
                    <ReconLink caseId={c.id} className="cl__link" title="Open this reconciliation">
                      <span className="vc__strong">{c.invoice_no ?? 'Waiting for the invoice'}</span>
                      {c.ref && <span className="rc__ref">{c.ref}</span>}
                    </ReconLink>
                    <div className="vc__muted vc__xs">
                      {[c.po_number ? `PO ${c.po_number}` : 'No PO yet',
                        c.store_sn ? `Store ${c.store_sn}` : null].filter(Boolean).join(' · ')}
                    </div>
                  </td>
                  <td><CaseStatusChip status={c.status} billDeleted={c.bill_deleted} /></td>
                  <td className="rc__num">
                    {/* A withdrawn bill has no exposure: there is nothing to pay. */}
                    {c.bill_deleted ? <span className="vc__muted">—</span>
                      : risk > 0
                      ? <span className="vc__bad vc__strong">₹{inr(risk)}</span>
                      : <span className="vc__muted">—</span>}
                  </td>
                  <td className="rc__num">{cover === null
                    ? <span className="vc__muted">—</span>
                    : <Bar pct={cover} />}</td>
                  <td className="rc__num">{conf === null
                    // Nothing paired is not badly paired: this invoice is
                    // still waiting for a PO.
                    ? <span className="vc__muted" title="Nothing paired yet — no PO on this case">—</span>
                    : <Bar pct={Math.round(conf * 100)} />}</td>
                  <td className="rc__rowacts">
                    {/* Labelled, because an unexplained chevron is a thing you
                        hover to find out what it does. This is the way to the
                        line-by-line table and should say so. */}
                    <ReconLink caseId={c.id} className="vc__btn vc__btn--sm cl__open"
                      title="Open the line-by-line reconciliation">
                      Recon View<ChevronRight size={14} aria-hidden="true" />
                    </ReconLink>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </section>
  )
}

/** A figure and its bar on one line: the number is the fact, the bar is for
 *  scanning a column of them. */
function Bar({ pct }: { pct: number }) {
  return (
    <span className="cl__bar" title={`${pct}%`}>
      <span className="cl__bar-t"><span className="cl__bar-f" style={{ width: `${pct}%` }} /></span>
      <span className="cl__bar-v">{pct}%</span>
    </span>
  )
}

/** How much of the bill its documents account for: the weakest leg that has
 *  arrived, because a reconciliation is only as covered as its thinnest
 *  supporting document, and averaging would hide that. */
function coverOf(c: ReconCaseSummary): number | null {
  const vals = Object.values(c.leg_cover ?? {}).filter((v): v is number => typeof v === 'number')
  return vals.length ? Math.round(Math.min(...vals) * 100) : null
}
