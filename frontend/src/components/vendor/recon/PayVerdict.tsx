import { AlertTriangle, CheckCircle2, Clock } from 'lucide-react'

import { inr } from './reconFormat'

/**
 * The payment decision, first and in money.
 *
 * Whoever opens this is deciding one thing: can this invoice be paid, and if
 * not, what is stopping it and how much is involved. Everything else — line
 * counts, status chips, the per-line table — is detail they reach for only
 * after that answer.
 *
 * The distinction that matters and that the old header lost: **over-billed and
 * under-billed are not the same kind of news.** Money billed above what the PO
 * and the site report support is the payer's exposure. Money the vendor failed
 * to bill is the vendor's loss — worth knowing, never a reason to hold payment.
 * A screen that totals them together as "27 to review" makes a payable invoice
 * look like a problem.
 */
type Summary = {
  status: string
  money_at_risk: string | number
  under_billed: string | number
  billed_total: string | number | null
  counts?: Partial<Record<string, number>>
}

const n = (v: string | number | null | undefined) => Number(v ?? 0)

export function PayVerdict({ s, onShowFlagged }: { s: Summary; onShowFlagged?: () => void }) {
  const risk = n(s.money_at_risk)
  const under = n(s.under_billed)
  const blockers = s.counts?.BLOCKER ?? 0
  const waiting = s.status.startsWith('AWAITING')

  const verdict = blockers > 0
    ? { tone: 'bad' as const, icon: AlertTriangle,
        head: `Hold — ${blockers} blocker${blockers > 1 ? 's' : ''}`,
        body: 'Something must be resolved before this is paid.' }
    : waiting
      ? { tone: 'wait' as const, icon: Clock,
          head: waitingHead(s.status),
          body: 'Not a problem with the invoice — a document is still to come.' }
      : risk > 0
        ? { tone: 'bad' as const, icon: AlertTriangle,
            head: `Billed ${inr(risk)} above what is supported`,
            body: 'Check these lines before paying.' }
        : { tone: 'ok' as const, icon: CheckCircle2,
            head: `Clear to pay ${inr(n(s.billed_total))}`,
            body: 'Nothing is billed above what the PO and the site report support.' }

  const Icon = verdict.icon
  return (
    <section className={`pv pv--${verdict.tone}`} aria-label="Payment decision">
      <Icon size={20} className="pv__icon" aria-hidden />
      <div className="pv__text">
        <h3 className="pv__head">{verdict.head}</h3>
        <p className="pv__body">{verdict.body}</p>
      </div>
      {under > 0 && (
        <div className="pv__aside">
          <span className="pv__aside-k">Vendor under-billed</span>
          <span className="pv__aside-v">{inr(under)}</span>
          <span className="pv__aside-n">their loss, not yours</span>
        </div>
      )}
      {risk > 0 && onShowFlagged && (
        <button type="button" className="vc__btn vc__btn--sm" onClick={onShowFlagged}>
          Show the lines
        </button>
      )}
    </section>
  )
}

function waitingHead(status: string): string {
  switch (status) {
    case 'AWAITING_PO': return 'Waiting for the purchase order'
    case 'AWAITING_INVOICE': return 'Waiting for the invoice'
    case 'AWAITING_RECEIPT': return 'Waiting for the audit report'
    case 'AWAITING_CREDIT_NOTE': return 'Waiting for a credit note from the vendor'
    default: return 'Waiting on a document'
  }
}
