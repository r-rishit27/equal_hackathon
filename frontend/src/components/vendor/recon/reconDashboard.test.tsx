import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { ReconDashboard, matchesFilter } from './ReconDashboard'
import type { ReconCaseSummary } from '../../../api/recon'

const c = (p: Partial<ReconCaseSummary>): ReconCaseSummary => ({
  id: 'c' + Math.random(), ref: 'RC-0001', supplier_id: 'v1', vendor_name: 'V', bill_id: null,
  invoice_no: 'I-1', po_number: 'P-1', store_sn: '1', status: 'NEEDS_REVIEW',
  docs: { po: true, invoice: true, evidence: 0, pod: false, memo: false },
  po_total: '100', billed_total: '100', expected_total: '100',
  money_at_risk: '0', under_billed: '0', counts: { BLOCKER: 0, REVIEW: 0, INFO: 0 },
  computed_at: null, acknowledged_by: null, acknowledged_at: null, ...p,
})

describe('ReconDashboard', () => {
  it('leads with the exposure, because that is what stops a payment', async () => {
    render(<ReconDashboard cases={[c({ money_at_risk: '31350' }), c({})]} active={null} onPick={() => {}} />)
    expect(screen.getByText('₹31,350.00')).toBeInTheDocument()
    expect(screen.getByText(/Billed above what is supported/)).toBeInTheDocument()
  })

  it('says so plainly when nothing is over-billed', () => {
    render(<ReconDashboard cases={[c({}), c({})]} active={null} onPick={() => {}} />)
    expect(screen.getByText('All clear')).toBeInTheDocument()
  })

  it('separates the vendor’s own shortfall from the exposure', () => {
    render(<ReconDashboard cases={[c({ under_billed: '1850' })]} active={null} onPick={() => {}} />)
    expect(screen.getByText(/under-billed ₹1,850.00, their loss/)).toBeInTheDocument()
  })

  it('counts a leg against its own whole, so the gap names the missing document', () => {
    render(<ReconDashboard active={null} onPick={() => {}}
      cases={[c({ docs: { po: true, invoice: true, evidence: 1, pod: false, memo: false } }),
              c({ docs: { po: true, invoice: true, evidence: 0, pod: false, memo: false } })]} />)
    const audit = screen.getByRole('button', { name: /Audit report/ })
    expect(audit).toHaveTextContent('1/2')
    // The title says what to chase, not just what is present.
    expect(audit).toHaveAttribute('title', '1 invoice without one')
  })

  it('every panel is a filter — a dashboard that only points is telling you to go looking', async () => {
    const onPick = vi.fn()
    render(<ReconDashboard cases={[c({ status: 'NEEDS_REVIEW' })]} active={null} onPick={onPick} />)
    await userEvent.click(screen.getByRole('button', { name: /Needs review/ }))
    expect(onPick).toHaveBeenCalledWith('review')
  })

  it('clicking the active filter again clears it', async () => {
    const onPick = vi.fn()
    render(<ReconDashboard cases={[c({})]} active="review" onPick={onPick} />)
    await userEvent.click(screen.getByRole('button', { name: /Needs review/ }))
    expect(onPick).toHaveBeenCalledWith(null)
  })

  it('a status with no cases cannot be selected', () => {
    render(<ReconDashboard cases={[c({ status: 'NEEDS_REVIEW' })]} active={null} onPick={() => {}} />)
    expect(screen.getByRole('button', { name: /Signed off/ })).toBeDisabled()
  })

  it('leaves a case with nothing paired out of the confidence chart', () => {
    // It is waiting for a PO. Plotting it at 0% would put it beside a case
    // whose matching is genuinely untrustworthy, which is a different problem.
    render(<ReconDashboard active={null} onPick={() => {}}
      cases={[c({ status: 'AWAITING_PO', confidence: null })]} />)
    expect(screen.getByText(/still waiting for a PO/)).toBeInTheDocument()
  })

  it('bands the confidence it does have', () => {
    render(<ReconDashboard active={null} onPick={() => {}}
      cases={[c({ confidence: '0.42' }), c({ confidence: '0.91' }), c({ confidence: '0.95' })]} />)
    const low = screen.getByRole('button', { name: /Under 50%/ })
    const high = screen.getByRole('button', { name: /85% and up/ })
    expect(low).toHaveTextContent('1')
    expect(high).toHaveTextContent('2')
  })

  it('shows nothing at all when there is nothing to show', () => {
    const { container } = render(<ReconDashboard cases={[]} active={null} onPick={() => {}} />)
    expect(container).toBeEmptyDOMElement()
  })

  it('the status split is readable without colour', () => {
    // Amber measures under 3:1 on white, so every segment is also named,
    // counted and given an icon in the list beside the bar.
    render(<ReconDashboard cases={[c({ status: 'AWAITING_PO' })]} active={null} onPick={() => {}} />)
    const img = screen.getByRole('img')
    expect(img).toHaveAccessibleName(/Waiting on a document: 1/)
  })
})

describe('matchesFilter', () => {
  it('is the one definition both the panels and the list use', () => {
    const waiting = c({ status: 'AWAITING_RECEIPT' })
    expect(matchesFilter(waiting, 'waiting')).toBe(true)
    expect(matchesFilter(waiting, 'ready')).toBe(false)
    expect(matchesFilter(waiting, null)).toBe(true)
  })

  it('excludes an unpaired case from every confidence band', () => {
    const none = c({ confidence: null })
    expect(matchesFilter(none, 'conf:low')).toBe(false)
    expect(matchesFilter(none, 'conf:high')).toBe(false)
  })

  it('bands are half-open, so 0.85 is high and not mid', () => {
    expect(matchesFilter(c({ confidence: '0.85' }), 'conf:high')).toBe(true)
    expect(matchesFilter(c({ confidence: '0.85' }), 'conf:good')).toBe(false)
  })
})
