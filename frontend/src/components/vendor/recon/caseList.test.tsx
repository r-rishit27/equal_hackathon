import { render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'

import { CaseList } from './CaseList'
import type { ReconCaseSummary } from '../../../api/recon'

const c = (p: Partial<ReconCaseSummary>): ReconCaseSummary => ({
  id: 'c1', ref: 'RC-0003', supplier_id: 'v1', vendor_name: 'Bosch', bill_id: null,
  invoice_no: '26GJ/KMW/SI15224', po_number: 'PPO00030541-1', store_sn: '9648', status: 'NEEDS_REVIEW',
  docs: { po: true, invoice: true, evidence: 0, pod: true, memo: false },
  po_total: '572400', billed_total: '572400', expected_total: '572400',
  money_at_risk: '0', under_billed: '0', counts: { BLOCKER: 0, REVIEW: 1, INFO: 0 },
  computed_at: null, acknowledged_by: null, acknowledged_at: null, ...p,
})

const show = (cases: ReconCaseSummary[], filtered = false) =>
  render(<MemoryRouter><CaseList cases={cases} filtered={filtered} /></MemoryRouter>)

describe('CaseList', () => {
  it('is the front door to a reconciliation', () => {
    // Before this, the only way in was finding a document that happened to
    // belong to the case and clicking the invoice number in its row.
    show([c({})])
    const link = screen.getAllByRole('link', { name: /26GJ\/KMW\/SI15224/ })[0]
    expect(decodeURIComponent(link.getAttribute('href') ?? '')).toContain('open=recon:c1')
  })

  it('shows what is at stake, and a dash when nothing is', () => {
    show([c({ money_at_risk: '31350' }), c({ id: 'c2', invoice_no: 'IS-2', money_at_risk: '0' })])
    expect(screen.getByText('₹31,350.00')).toBeInTheDocument()
    // A zero printed in the same weight as a real exposure reads as one.
    const rows = screen.getAllByRole('row')
    expect(within(rows[2]).getAllByText('—').length).toBeGreaterThan(0)
  })

  it('takes the weakest leg as the coverage, not the average', () => {
    // A reconciliation is only as covered as its thinnest supporting
    // document; averaging 100% and 40% to 70% hides the gap.
    show([c({ leg_cover: { po: 1, evidence: 0.4, pod: null, payment: null } })])
    expect(screen.getByText('40%')).toBeInTheDocument()
    expect(screen.queryByText('70%')).not.toBeInTheDocument()
  })

  it('shows a dash for matching when nothing has been paired', () => {
    show([c({ confidence: null, leg_cover: {} })])
    expect(screen.getAllByText('—').length).toBeGreaterThan(0)
    expect(screen.queryByText('0%')).not.toBeInTheDocument()
  })

  it('labels the way through, rather than leaving a chevron to be hovered', () => {
    // An unexplained icon is a thing you hover to find out what it does.
    show([c({})])
    const btn = screen.getByRole('link', { name: /Recon/ })
    expect(btn).toHaveAttribute('title', 'Open the line-by-line reconciliation')
    expect(decodeURIComponent(btn.getAttribute('href') ?? '')).toContain('open=recon:c1')
  })

  it('says the list is narrowed when the dashboard is filtering it', () => {
    show([c({})], true)
    expect(screen.getByText(/Invoices matching · 1/)).toBeInTheDocument()
  })

  it('explains an empty list rather than showing an empty table', () => {
    show([], true)
    expect(screen.getByText('Nothing matches that')).toBeInTheDocument()
  })
})

describe('a bill that was deleted', () => {
  it('says so instead of showing whatever the engine last concluded', () => {
    // "Needs review" on a bill nobody is paying sends a reviewer to look at
    // something that has been withdrawn.
    show([c({ status: 'NEEDS_REVIEW', bill_deleted: true, money_at_risk: '1128945' })])
    expect(screen.getByText('Bill deleted')).toBeInTheDocument()
    expect(screen.queryByText('Needs review')).not.toBeInTheDocument()
  })

  it('has no exposure, because there is nothing to pay', () => {
    show([c({ bill_deleted: true, money_at_risk: '1128945' })])
    expect(screen.queryByText(/11,28,945/)).not.toBeInTheDocument()
  })

  it('is still listed, so its documents stay reachable', () => {
    show([c({ bill_deleted: true })])
    expect(screen.getAllByRole('link', { name: /26GJ\/KMW\/SI15224/ })[0]).toBeInTheDocument()
  })
})
