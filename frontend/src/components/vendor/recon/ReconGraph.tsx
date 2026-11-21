import { useEffect, useState } from 'react'

import { fetchCaseGraph, type CaseGraph } from '../../../api/recon'

/**
 * How this reconciliation is held together.
 *
 * What stood here was an activity log — *recomputed · loop*, *EDGES REBUILT ·
 * system*, over and over. It said a recompute happened; it never said what the
 * recompute concluded. Nobody reviewing an invoice has a question that log
 * answers.
 *
 * This draws the thing itself: the documents on the case and the links the
 * matcher found between them. The invoice is the centre because every
 * comparison runs through it — the PO says what was ordered, the audit report
 * certifies the PO's lines, the delivery proof and the payment answer the
 * other two ends.
 *
 * **It is the shape, not every edge.** Thirty-eight invoice lines drawn
 * against thirty-eight PO lines is a hairball, and a reviewer cannot read one.
 * Each connection carries how many lines it holds and how strong the weakest
 * of them is, which is the question worth asking of a graph: not "is it
 * connected" but "where is it thin".
 */
const NODES = [
  { role: 'po', x: 90, y: 40, label: 'Purchase order', kind: 'BILLS_AGAINST' },
  { role: 'evidence', x: 90, y: 150, label: 'Audit report', kind: 'CERTIFIES' },
  { role: 'pod', x: 440, y: 40, label: 'Delivery proof', kind: 'RECEIVED_FOR' },
  { role: 'payment', x: 440, y: 150, label: 'Payment', kind: 'PAID_BY' },
] as const

const INVOICE = { x: 265, y: 95 }
const W = 112
const H = 40

export function ReconGraph({ caseId }: { caseId: string }) {
  const [g, setG] = useState<CaseGraph | null>(null)
  const [error, setError] = useState(false)

  useEffect(() => {
    let live = true
    fetchCaseGraph(caseId)
      .then(d => { if (live) setG(d) })
      .catch(() => { if (live) setError(true) })
    return () => { live = false }
  }, [caseId])

  if (error) return <p className="rk__muted">Could not draw the linkage.</p>
  if (!g) return <p className="rk__muted">Loading…</p>

  const present = new Map(g.documents.map(d => [d.role, d]))
  const byKind = new Map(g.links.map(l => [l.kind, l]))
  const invoice = present.get('invoice')

  return (
    <div className="rg">
      <svg viewBox="0 0 560 210" className="rg__svg" role="img"
        aria-label={describe(g)}>
        {NODES.map(n => {
          const doc = present.get(n.role)
          const link = byKind.get(n.kind)
          const on = !!doc?.present
          // Thickness carries how many lines the link holds; a document with
          // no lines linked yet still gets a hairline, so "present but not
          // matched" is visibly different from "not here at all".
          const w = link ? Math.min(7, 1.5 + Math.log2(link.n + 1)) : 1.5
          const left = n.x < INVOICE.x
          const x1 = left ? n.x + W : n.x
          const x2 = left ? INVOICE.x : INVOICE.x + W
          return (
            <g key={n.role}>
              <path d={edge(x1, n.y + H / 2, x2, INVOICE.y + H / 2)}
                className={`rg__edge${on && link ? ' is-on' : ''}`}
                strokeWidth={on && link ? w : 1.5} />
              {link && (
                <text className="rg__elabel" textAnchor="middle"
                  x={(x1 + x2) / 2} y={(n.y + INVOICE.y) / 2 + H / 2 - 6}>
                  {link.n} {link.n === 1 ? 'line' : 'lines'}
                </text>
              )}
              <Node x={n.x} y={n.y} label={n.label} on={on}
                detail={doc?.detail ?? (on ? null : 'not here yet')} />
            </g>
          )
        })}
        <Node x={INVOICE.x} y={INVOICE.y} label="Invoice" on={!!invoice?.present}
          detail={invoice?.detail ?? null} spine />
      </svg>

      <ul className="rg__legend">
        {g.links.map(l => (
          <li key={l.kind}>
            <span className="rg__k">{LINK_LABEL[l.kind] ?? l.kind}</span>
            <span className="vc__muted vc__xs">
              {l.n} {l.n === 1 ? 'link' : 'links'}
              {l.certain > 0 && <> · {l.certain} exact</>}
              {/* The weakest link, because an average hides it and one bad
                  pairing on a large line is the thing worth looking at. */}
              {l.min_score !== null && <> · weakest {Math.round(l.min_score * 100)}%</>}
            </span>
          </li>
        ))}
        {g.links.length === 0 && (
          <li className="vc__muted vc__xs">Nothing linked yet — this case is still waiting for a document.</li>
        )}
      </ul>
    </div>
  )
}

const LINK_LABEL: Record<string, string> = {
  BILLS_AGAINST: 'Invoice line → PO line',
  CERTIFIES: 'Audit row → PO line',
  RECEIVED_FOR: 'Receipt → PO line',
  PAID_BY: 'Invoice → payment',
  COVERED_BY: 'Credit note → invoice line',
}

function Node({ x, y, label, detail, on, spine }: {
  x: number; y: number; label: string; detail?: string | null; on: boolean; spine?: boolean
}) {
  return (
    <g className={`rg__node${on ? ' is-on' : ''}${spine ? ' is-spine' : ''}`}>
      <rect x={x} y={y} width={W} height={H} rx={8} />
      <text x={x + W / 2} y={y + (detail ? 17 : 24)} textAnchor="middle" className="rg__t">{label}</text>
      {detail && (
        <text x={x + W / 2} y={y + 30} textAnchor="middle" className="rg__d">
          {detail.length > 17 ? `${detail.slice(0, 16)}…` : detail}
        </text>
      )}
    </g>
  )
}

/** A gentle curve rather than a straight line, so two edges meeting the same
 *  side of the invoice stay tellable apart. */
function edge(x1: number, y1: number, x2: number, y2: number): string {
  const mx = (x1 + x2) / 2
  return `M ${x1} ${y1} C ${mx} ${y1}, ${mx} ${y2}, ${x2} ${y2}`
}

/** The same picture in a sentence, for anyone not looking at it. */
function describe(g: CaseGraph): string {
  const here = g.documents.filter(d => d.present).map(d => d.label)
  const links = g.links.map(l => `${LINK_LABEL[l.kind] ?? l.kind}: ${l.n}`)
  return `Documents on this case: ${here.join(', ') || 'none yet'}. `
    + (links.length ? `Links found — ${links.join('; ')}.` : 'No links found yet.')
}
