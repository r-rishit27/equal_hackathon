import { applyPayment, fetchPayment, type AllocationIn, type PaymentRow } from '../../api/receivables'
import { fromPaise, toPaise } from './format'

/** How sure the agent must be before its match can be confirmed from the list, unopened. */
export const LIST_CONFIRM_MIN = 0.9

/** A row the list may confirm as-is: waiting on a person, sure, and with nothing to warn about. */
export const confirmableFromList = (r: PaymentRow) =>
  r.status === 'needs_review' && !r.flags?.length && Number(r.match_confidence ?? 0) >= LIST_CONFIRM_MIN
  && !!r.suggestion_invoices

/**
 * Confirm the agent's best match exactly as suggested — the same request the
 * payment panel sends when its Confirm button is pressed on an untouched
 * suggestion. Anything that needs a decision (a deduction with no reason, a
 * disputed invoice) is refused so the person opens it instead.
 */
export async function confirmSuggested(paymentId: string) {
  const d = await fetchPayment(paymentId)
  const p = d.payment
  const best = p.suggestion?.best
  if (p.status !== 'needs_review' || !best?.allocations.length) throw new Error('Nothing to confirm — open it to review')
  const allocations: AllocationIn[] = best.allocations.map(a => ({
    invoice_id: a.invoice_id,
    amount_applied: fromPaise(toPaise(a.amount_applied)),
    tds_amount: fromPaise(toPaise(a.tds_amount)),
    deduction_amount: fromPaise(toPaise(a.deduction_amount)),
    reason_code: a.reason_code ?? (toPaise(a.tds_amount) ? 'TDS' : null),
    reason_note: a.reason_note ?? null,
  }))
  if (allocations.some(a => toPaise(a.deduction_amount) > 0 && !a.reason_code))
    throw new Error('A deduction needs a reason — open it to review')
  return applyPayment(paymentId, {
    allocations, version: p.version, method: 'accepted',
    customer_id: best.customer_id ?? d.customer?.id ?? null,
    kind: best.kind, confidence: best.confidence,
  })
}
