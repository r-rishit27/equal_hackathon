import { AlertTriangle } from 'lucide-react'
import { useEffect, useState } from 'react'

import { matchBadge } from './reconFormat'
import { fetchEvidencePath, fetchFourWay, type CheckState, type EvidenceHop, type FourWayLine, type FourWayPanel } from '../../../api/recon'

/**
 * One invoice, four questions.
 *
 * The reviewer's job is not "read a reconciliation" — it is to answer four
 * things in order: was it ordered, was it verified, was it received, was it
 * paid. So the screen is four cards in that order, each stating its question,
 * and each showing the same invoice lines against a different document.
 *
 * Clean lines collapse. A list where every row looks equally important is a
 * list nobody reads, so by default only the lines that disagree are shown.
 */
const FIELD_LABEL: Record<string, string> = {
  qty: 'Qty', rate: 'Rate', amount: 'Amount', description: 'Item', reference: 'Invoice no.',
}

const TONE: Record<CheckState, string> = {
  MATCH: 'ok', DIFFERS: 'bad', MISSING: 'warn', NA: 'plain',
}

/** `rl:<uuid>` → "Invoice line". The key is an internal handle; a reviewer
 *  should read what kind of thing it is, not its uuid. */
const NODE_KIND: Record<string, string> = {
  rl: 'Invoice line', pol: 'PO line', ev: 'Audit row', grn: 'GRN line', pay: 'Payment',
}
const VIA_LABEL: Record<string, string> = {
  BILLS_AGAINST: 'bills against', CERTIFIES: 'certified by', RECEIVED_FOR: 'received as',
  PAID_BY: 'settled by', COVERED_BY: 'offset by',
}
const nodeLabel = (k: string) => NODE_KIND[k.split(':')[0]] ?? k

/** Which leg a panel answers, so it can show how much of the bill that
 *  document actually accounts for. */
const PAIR_LEG: Record<string, 'po' | 'evidence' | 'pod' | 'payment'> = {
  INVOICE_VS_PO: 'po', INVOICE_VS_AUDIT: 'evidence',
  INVOICE_VS_GRN: 'pod', INVOICE_VS_PAYMENT: 'payment',
}

export function FourWay({ caseId, cover }: {
  caseId: string
  /** Share of the billed value each leg accounts for, from the case summary. */
  cover?: Partial<Record<string, number | null>>
}) {
  const [panels, setPanels] = useState<FourWayPanel[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let live = true
    fetchFourWay(caseId)
      .then(p => { if (live) setPanels(p) })
      .catch(() => { if (live) setError('Could not load the comparison') })
    return () => { live = false }
  }, [caseId])

  if (error) return <p role="alert" className="vc__err vc__err--inline">{error}</p>
  if (!panels) return <p className="rk__muted">Loading…</p>

  return (
    <div className="fw">
      {panels.map(p => (
        <PanelCard key={p.pair} p={p} caseId={caseId} cover={cover?.[PAIR_LEG[p.pair]]} />
      ))}
    </div>
  )
}

function PanelCard({ p, caseId, cover }: {
  p: FourWayPanel; caseId: string; cover?: number | null
}) {
  const problems = p.lines.filter(l => l.state === 'DIFFERS' || l.state === 'MISSING')
  const clean = p.lines.length - problems.length
  // The dashboard answers "where does this invoice stand" in four numbers. The
  // lines behind a number are detail: available on request, never competing
  // with the number itself.
  const [open, setOpen] = useState(false)

  return (
    <section className="fw__card" aria-label={p.title}>
      <header className="fw__head">
        <h4 className="fw__title">{p.title}</h4>
        <p className="fw__ask">{p.ask}</p>
        {/* What the card is worth, not just what it concluded. "All agree" on
            a leg covering a fifth of the invoice is a different fact from
            "all agree" on one covering all of it, and the card looked the
            same either way. */}
        {typeof cover === 'number' && (
          <div className="fw__cover" title={`This document accounts for ${Math.round(cover * 100)}% of what the invoice bills`}>
            <span className="fw__cover-t">
              <span className="fw__cover-f" style={{ width: `${Math.round(cover * 100)}%` }} />
            </span>
            <span className="fw__cover-v">{Math.round(cover * 100)}% of the bill</span>
          </div>
        )}
      </header>

      {!p.available ? (
        <p className="fw__absent">{p.absent_reason}</p>
      ) : (
        <>
          {/* An assumption the panel leaned on, before any tally. A reviewer who
              reads "all agree" without this has been told the machine was sure
              when it was only persuaded. */}
          {p.confirm && (
            <p className="fw__confirm" role="note">
              <AlertTriangle size={14} aria-hidden /> {p.confirm}
            </p>
          )}
          <div className="fw__tally">
            {problems.length === 0
              ? <span className="vc__chip vc__chip--ok vc__chip--xs">All {p.lines.length} agree</span>
              : <>
                  {p.counts.DIFFERS > 0 &&
                    <span className="vc__chip vc__chip--bad vc__chip--xs">{p.counts.DIFFERS} differ</span>}
                  {p.counts.MISSING > 0 &&
                    <span className="vc__chip vc__chip--warn vc__chip--xs">{p.counts.MISSING} missing</span>}
                  {clean > 0 && <span className="rk__muted">{clean} agree</span>}
                </>}
          </div>

          {problems.length > 0 && (
            <button type="button" className="vc__lnk fw__more" onClick={() => setOpen(o => !o)}
              aria-expanded={open}>
              {open ? 'Hide the lines' : `Show the ${problems.length} line${problems.length > 1 ? 's' : ''}`}
            </button>
          )}

          {open && (
            <ul className="fw__lines">
              {problems.map(l => <LineRow key={l.key ?? l.description} l={l} caseId={caseId} />)}
            </ul>
          )}

          {/* What the comparison proves at all. The delivery-proof panel says
              "consignment and value, not item quantities" here — without it,
              "all agree" reads as line-level receipt, which a POD never gives. */}
          {p.note && <p className="fw__note">{p.note}</p>}
        </>
      )}
    </section>
  )
}

function LineRow({ l, caseId }: { l: FourWayLine; caseId: string }) {
  const [chain, setChain] = useState<EvidenceHop[] | null>(null)
  const [open, setOpen] = useState(false)
  const canTrace = Boolean(l.key) && l.state !== 'MATCH'
  const match = matchBadge({ match_method: l.match_method ?? 'NONE', match_score: l.match_score ?? 0 })

  async function trace() {
    setOpen(o => !o)
    if (chain || !l.key) return
    try {
      const r = await fetchEvidencePath(caseId, l.key)
      setChain(r.reachable)
    } catch {
      setChain([])
    }
  }

  return (
    <li className={`fw__line fw__line--${TONE[l.state]}`}>
      <span className="fw__desc" title={l.description}>
        {canTrace
          // A disagreement is a question — "says who?" — so the line itself is
          // the way to the documents behind it.
          ? <button type="button" className="vc__lnk fw__trace" onClick={trace}
                    aria-expanded={open}>{l.description}</button>
          : l.description}
      </span>
      {match && (
        <span className={`vc__chip vc__chip--${match.tone} vc__chip--xs fw__match`}
          title={match.pct === null ? `${match.label} match — nothing to qualify` : `Paired ${match.pct}% confident`}>
          {match.label}{match.pct !== null && <span className="rc__matchpct">{match.pct}%</span>}
        </span>
      )}
      <span className="fw__checks">
        {l.checks.filter(c => c.state !== 'NA').map(c => (
          <span key={c.field} className={`vc__chip vc__chip--${TONE[c.state]} vc__chip--xs`}
                title={c.state === 'MATCH' ? undefined
                       : `invoice ${c.invoice ?? '—'} · other ${c.other ?? '—'}`}>
            {FIELD_LABEL[c.field]}
            {c.state === 'DIFFERS' && <span className="fw__vs"> {c.invoice} ≠ {c.other}</span>}
            {c.state === 'MISSING' && <span className="fw__vs"> not there</span>}
          </span>
        ))}
      </span>
      {open && (
        <div className="fw__chain">
          {chain === null ? <span className="rk__muted">Tracing…</span>
            : chain.length === 0 ? <span className="rk__muted">Nothing else is linked to this line yet</span>
            : <ul>
                {chain.map(h => (
                  <li key={h.node}>
                    {h.via.map(v => VIA_LABEL[v] ?? v.toLowerCase()).join(' → ')}
                    {' → '}<strong>{nodeLabel(h.node)}</strong>
                    <span className="rk__muted"> ({h.hops} hop{h.hops === 1 ? '' : 's'})</span>
                  </li>
                ))}
              </ul>}
        </div>
      )}
    </li>
  )
}
