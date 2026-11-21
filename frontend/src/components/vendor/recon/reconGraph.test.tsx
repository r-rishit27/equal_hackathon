import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const api = vi.hoisted(() => ({ fetchCaseGraph: vi.fn() }))
vi.mock('../../../api/recon', async orig => ({
  ...(await orig<typeof import('../../../api/recon')>()), ...api,
}))

import { ReconGraph } from './ReconGraph'
import type { CaseGraph } from '../../../api/recon'

const graph = (over: Partial<CaseGraph> = {}): CaseGraph => ({
  built_at: '2026-11-20T09:00:00Z',
  documents: [
    { role: 'po', label: 'Purchase order', present: true, detail: 'PPO00030541-1' },
    { role: 'invoice', label: 'Invoice', present: true, detail: '26GJ/KMW/SI15224' },
    { role: 'evidence', label: 'Audit report', present: false, detail: null },
    { role: 'pod', label: 'Delivery proof', present: true, detail: null },
    { role: 'payment', label: 'Payment', present: false, detail: null },
  ],
  links: [{ kind: 'BILLS_AGAINST', n: 36, avg_score: 0.957, min_score: 0.85, confirmed: 0, certain: 18 }],
  cover: {},
  ...over,
})

describe('ReconGraph', () => {
  beforeEach(() => vi.restoreAllMocks())

  it('draws what the matcher concluded, not when it last ran', async () => {
    api.fetchCaseGraph.mockResolvedValue(graph())
    render(<ReconGraph caseId="c1" />)
    expect(await screen.findByText('36 lines')).toBeInTheDocument()
    expect(screen.getByText('Invoice line → PO line')).toBeInTheDocument()
  })

  it('names the weakest link, which an average would hide', async () => {
    // One bad pairing on a large line is the thing worth looking at.
    api.fetchCaseGraph.mockResolvedValue(graph())
    render(<ReconGraph caseId="c1" />)
    expect(await screen.findByText(/weakest 85%/)).toBeInTheDocument()
  })

  it('draws a document that has not arrived rather than leaving it out', async () => {
    // The gap is the point: it says which document to go and find.
    api.fetchCaseGraph.mockResolvedValue(graph())
    render(<ReconGraph caseId="c1" />)
    expect(await screen.findByText('Audit report')).toBeInTheDocument()
    expect(screen.getAllByText('not here yet').length).toBe(2)   // audit + payment
  })

  it('is readable without seeing it', async () => {
    api.fetchCaseGraph.mockResolvedValue(graph())
    render(<ReconGraph caseId="c1" />)
    const img = await screen.findByRole('img')
    expect(img).toHaveAccessibleName(/Purchase order, Invoice, Delivery proof/)
    expect(img).toHaveAccessibleName(/Invoice line → PO line: 36/)
  })

  it('says plainly when nothing is linked yet', async () => {
    api.fetchCaseGraph.mockResolvedValue(graph({ links: [] }))
    render(<ReconGraph caseId="c1" />)
    expect(await screen.findByText(/Nothing linked yet/)).toBeInTheDocument()
  })

  it('does not break the case when the graph cannot be drawn', async () => {
    api.fetchCaseGraph.mockRejectedValue(new Error('nope'))
    render(<ReconGraph caseId="c1" />)
    expect(await screen.findByText(/Could not draw the linkage/)).toBeInTheDocument()
  })
})
