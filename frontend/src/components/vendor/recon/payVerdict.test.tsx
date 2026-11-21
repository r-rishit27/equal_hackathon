import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { PayVerdict } from './PayVerdict'

const base = { status: 'NEEDS_REVIEW', money_at_risk: '0', under_billed: '0',
               billed_total: '956733.55', counts: { BLOCKER: 0, REVIEW: 0, INFO: 0 } }

describe('PayVerdict', () => {
  it('leads with the amount that can be paid when nothing is over-billed', () => {
    render(<PayVerdict s={base} />)
    expect(screen.getByText(/Clear to pay/)).toBeInTheDocument()
  })

  it('does not treat under-billing as a reason to hold payment', () => {
    // The vendor billing less than supported is their loss. The old header
    // counted it toward "27 to review" and made a payable invoice look stuck.
    render(<PayVerdict s={{ ...base, under_billed: '215841.90' }} />)
    expect(screen.getByText(/Clear to pay/)).toBeInTheDocument()
    expect(screen.getByText(/their loss, not yours/)).toBeInTheDocument()
  })

  it('leads with the exposure when something is over-billed', () => {
    render(<PayVerdict s={{ ...base, money_at_risk: '11800' }} />)
    expect(screen.getByText(/above what is supported/)).toBeInTheDocument()
  })

  it('a blocker outranks the money', () => {
    render(<PayVerdict s={{ ...base, money_at_risk: '11800', counts: { BLOCKER: 1, REVIEW: 0, INFO: 0 } }} />)
    expect(screen.getByText(/Hold — 1 blocker/)).toBeInTheDocument()
  })

  it('waiting on a document is not framed as a fault', () => {
    render(<PayVerdict s={{ ...base, status: 'AWAITING_PO' }} />)
    expect(screen.getByText(/Waiting for the purchase order/)).toBeInTheDocument()
    expect(screen.getByText(/Not a problem with the invoice/)).toBeInTheDocument()
  })

  it('names what each waiting state is waiting for', () => {
    for (const [status, text] of [['AWAITING_RECEIPT', /audit report/],
                                  ['AWAITING_CREDIT_NOTE', /credit note/]] as const) {
      const { unmount } = render(<PayVerdict s={{ ...base, status }} />)
      expect(screen.getByText(text)).toBeInTheDocument()
      unmount()
    }
  })
})
