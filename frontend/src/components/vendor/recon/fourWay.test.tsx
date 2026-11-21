import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { FourWay } from './FourWay'
import * as api from '../../../api/recon'
import type { FourWayPanel } from '../../../api/recon'

const ok = (field: any) => ({ field, state: 'MATCH' as const, invoice: '100', other: '100' })

function panel(over: Partial<FourWayPanel> = {}): FourWayPanel {
  return {
    pair: 'INVOICE_VS_PO', title: 'Invoice vs PO', ask: 'Was it ordered, at this rate?',
    available: true, absent_reason: '',
    counts: { MATCH: 1, DIFFERS: 0, MISSING: 0, NA: 0 },
    lines: [{ description: 'Piping 25 mm', key: 'rl:1', state: 'MATCH',
              checks: [ok('qty'), ok('rate'), ok('amount'), ok('description')] }],
    ...over,
  }
}

async function show(panels: FourWayPanel[]) {
  vi.spyOn(api, 'fetchFourWay').mockResolvedValue(panels)
  render(<FourWay caseId="c1" />)
  await screen.findByLabelText(panels[0].title)
}

describe('FourWay', () => {
  beforeEach(() => vi.restoreAllMocks())

  it('asks the question each card answers', async () => {
    await show([panel()])
    expect(screen.getByText('Was it ordered, at this rate?')).toBeInTheDocument()
  })

  it('says so plainly when everything agrees', async () => {
    await show([panel()])
    expect(screen.getByText('All 1 agree')).toBeInTheDocument()
  })

  it('hides the lines that agree, so only what needs attention is listed', async () => {
    // A list where every row looks equally important is a list nobody reads.
    await show([panel()])
    expect(screen.queryByText('Piping 25 mm')).not.toBeInTheDocument()
  })

  it('shows the count on the card and the numbers only when asked', async () => {
    await show([panel({
      counts: { MATCH: 0, DIFFERS: 1, MISSING: 0, NA: 0 },
      lines: [{ description: 'Piping 25 mm', key: 'rl:1', state: 'DIFFERS',
                checks: [ok('qty'), { field: 'rate', state: 'DIFFERS', invoice: '700', other: '620' }] }],
    })])
    // The dashboard is four numbers; the lines behind one are detail.
    expect(screen.getByText('1 differ')).toBeInTheDocument()
    expect(screen.queryByText(/700 ≠ 620/)).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /Show the 1 line/ }))
    expect(screen.getByText(/700 ≠ 620/)).toBeInTheDocument()
  })

  it('separates missing from differing', async () => {
    await show([panel({
      counts: { MATCH: 0, DIFFERS: 0, MISSING: 1, NA: 0 },
      lines: [{ description: 'Scaffolding', key: 'rl:2', state: 'MISSING',
                checks: [{ field: 'qty', state: 'MISSING', invoice: '1', other: null }] }],
    })])
    expect(screen.getByText('1 missing')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /Show the 1 line/ }))
    expect(screen.getByText(/not there/)).toBeInTheDocument()
  })

  it('keeps the lines that agree out of the way entirely', async () => {
    // Only what needs attention is reachable from the card; a clean line has
    // nothing to say and should not lengthen the list behind the number.
    await show([panel({
      counts: { MATCH: 1, DIFFERS: 1, MISSING: 0, NA: 0 },
      lines: [
        { description: 'Piping 25 mm', key: 'rl:1', state: 'MATCH', checks: [ok('qty')] },
        { description: 'AHU 8.5 TR', key: 'rl:2', state: 'DIFFERS',
          checks: [{ field: 'qty', state: 'DIFFERS', invoice: '3', other: '2' }] },
      ],
    })])
    expect(screen.getByText('1 agree')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /Show the 1 line/ }))
    expect(screen.getByText('AHU 8.5 TR')).toBeInTheDocument()
    expect(screen.queryByText('Piping 25 mm')).not.toBeInTheDocument()
  })

  it('does not render NA checks as if something were wrong', async () => {
    // An auditor certifies quantities, not prices: rate is not applicable, and
    // showing it as missing would read as a fault in the audit report.
    await show([panel({
      pair: 'INVOICE_VS_AUDIT', title: 'Invoice vs audit report',
      counts: { MATCH: 0, DIFFERS: 1, MISSING: 0, NA: 0 },
      lines: [{ description: 'Piping', key: 'rl:1', state: 'DIFFERS',
                checks: [{ field: 'qty', state: 'DIFFERS', invoice: '100', other: '90' },
                         { field: 'rate', state: 'NA', invoice: null, other: null }] }],
    })])
    await userEvent.click(screen.getByRole('button', { name: /Show the 1 line/ }))
    const row = screen.getByText('Piping').closest('li')!
    expect(within(row).queryByText('Rate')).not.toBeInTheDocument()
  })

  it('an unavailable panel explains itself instead of vanishing', async () => {
    await show([panel({
      pair: 'INVOICE_VS_GRN', title: 'Invoice vs GRN', available: false,
      absent_reason: 'No goods receipt loaded — the GRN lives in Dynamics', lines: [],
    })])
    expect(screen.getByText(/the GRN lives in Dynamics/)).toBeInTheDocument()
  })

  it('renders all four cards in a fixed order', async () => {
    await show([panel(), panel({ pair: 'INVOICE_VS_AUDIT', title: 'Invoice vs audit report' }),
                panel({ pair: 'INVOICE_VS_GRN', title: 'Invoice vs GRN' }),
                panel({ pair: 'INVOICE_VS_PAYMENT', title: 'Invoice vs payment' })])
    const titles = screen.getAllByRole('region').map(r => r.getAttribute('aria-label'))
    expect(titles).toEqual(['Invoice vs PO', 'Invoice vs audit report', 'Invoice vs GRN', 'Invoice vs payment'])
  })

  it('surfaces a failed load', async () => {
    vi.spyOn(api, 'fetchFourWay').mockRejectedValue(new Error('nope'))
    render(<FourWay caseId="c1" />)
    expect(await screen.findByRole('alert')).toHaveTextContent('Could not load the comparison')
  })
})

describe('evidence chain', () => {
  beforeEach(() => vi.restoreAllMocks())

  const differing = panel({
    counts: { MATCH: 0, DIFFERS: 1, MISSING: 0, NA: 0 },
    lines: [{ description: 'Piping 25 mm', key: 'rl:1', state: 'DIFFERS',
              checks: [{ field: 'rate', state: 'DIFFERS', invoice: '700', other: '620' }] }],
  })

  it('a disagreement can be traced to the documents behind it', async () => {
    vi.spyOn(api, 'fetchFourWay').mockResolvedValue([differing])
    vi.spyOn(api, 'fetchEvidencePath').mockResolvedValue({
      start: 'rl:1',
      reachable: [
        { node: 'pol:9', path: ['rl:1', 'pol:9'], via: ['BILLS_AGAINST'], hops: 1 },
        { node: 'ev:4', path: ['rl:1', 'pol:9', 'ev:4'], via: ['BILLS_AGAINST', 'CERTIFIES'], hops: 2 },
      ],
    })
    render(<FourWay caseId="c1" />)
    await userEvent.click(await screen.findByRole('button', { name: /Show the 1 line/ }))
    await userEvent.click(screen.getByRole('button', { name: 'Piping 25 mm' }))
    // Relationships and node kinds read as words, never as raw keys or uuids.
    // Both hops start with "bills against" — the second continues through it.
    expect(await screen.findAllByText(/bills against/)).toHaveLength(2)
    expect(screen.getByText(/bills against → certified by/)).toBeInTheDocument()
    expect(screen.getByText('PO line')).toBeInTheDocument()
    expect(screen.getByText('Audit row')).toBeInTheDocument()
    expect(screen.queryByText(/pol:9/)).not.toBeInTheDocument()
  })

  it('says so when a line is linked to nothing yet', async () => {
    vi.spyOn(api, 'fetchFourWay').mockResolvedValue([differing])
    vi.spyOn(api, 'fetchEvidencePath').mockResolvedValue({ start: 'rl:1', reachable: [] })
    render(<FourWay caseId="c1" />)
    await userEvent.click(await screen.findByRole('button', { name: /Show the 1 line/ }))
    await userEvent.click(screen.getByRole('button', { name: 'Piping 25 mm' }))
    expect(await screen.findByText(/Nothing else is linked/)).toBeInTheDocument()
  })

  it('a line that agrees is not a question, so it is not clickable', async () => {
    vi.spyOn(api, 'fetchFourWay').mockResolvedValue([panel({
      counts: { MATCH: 1, DIFFERS: 1, MISSING: 0, NA: 0 },
      lines: [{ description: 'Clean line', key: 'rl:2', state: 'MATCH', checks: [ok('qty')] },
              { description: 'Bad line', key: 'rl:3', state: 'DIFFERS',
                checks: [{ field: 'qty', state: 'DIFFERS', invoice: '2', other: '1' }] }],
    })])
    render(<FourWay caseId="c1" />)
    await userEvent.click(await screen.findByRole('button', { name: /Show the 1 line/ }))
    expect(screen.queryByRole('button', { name: 'Clean line' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Bad line' })).toBeInTheDocument()
  })

  it('shows what a comparison proves, so "all agree" is not read as more than it is', async () => {
    await show([panel({
      pair: 'INVOICE_VS_GRN', title: 'Invoice vs delivery proof', ask: 'Was it received?',
      note: 'Checked against the delivery proof: it confirms the consignment and its value, not item quantities.',
    })])
    expect(screen.getByText(/not item quantities/)).toBeInTheDocument()
  })

  it('puts an assumption a person must agree with above the tally, not behind it', async () => {
    await show([panel({
      pair: 'INVOICE_VS_GRN', title: 'Invoice vs delivery proof', ask: 'Was it received?',
      confirm: 'The waybill reads 266J/KM4/S115224, not 26GJ/KMW/SI15224 — characters a scanner confuses; the declared value matches. Confirm it is this consignment before relying on it.',
    })])
    const card = screen.getByLabelText('Invoice vs delivery proof')
    const note = within(card).getByRole('note')
    expect(note).toHaveTextContent(/Confirm it is this consignment/)
    // Before the verdict: a reviewer reading "all agree" first has already been
    // told the machine was certain when it was only persuaded.
    const order = Array.from(card.querySelectorAll('.fw__confirm, .fw__tally'))
    expect(order[0]).toHaveClass('fw__confirm')
  })

  it('says nothing extra when the panel assumed nothing', async () => {
    await show([panel()])
    expect(within(screen.getByLabelText('Invoice vs PO')).queryByRole('note')).not.toBeInTheDocument()
  })
})
