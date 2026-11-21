import { render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { CaseVitals } from './CaseVitals'
import type { LineResult, ReconCaseSummary, ReconSegment } from '../../../api/recon'

const summary = (p: Partial<ReconCaseSummary> = {}): ReconCaseSummary => ({
  id: 'c1', ref: 'RC-0003', supplier_id: 'v1', vendor_name: 'Bosch', bill_id: null,
  invoice_no: '26GJ/KMW/SI15224', po_number: 'P-1', store_sn: '9648', status: 'NEEDS_REVIEW',
  docs: { po: true, invoice: true, evidence: 0, pod: true, memo: false },
  po_total: '572400', billed_total: '572400', expected_total: '572400',
  money_at_risk: '0', under_billed: '0', counts: { BLOCKER: 0, REVIEW: 1, INFO: 0 },
  computed_at: null, acknowledged_by: null, acknowledged_at: null, ...p,
})

const line = (p: Partial<LineResult>): LineResult => ({
  id: 'l' + Math.random(), ord: 1, kind: 'po', description: 'Item', po_key: 'pol:1', invoice_key: 'rl:1',
  evidence_key: null, invoice_text: 'Item', evidence_text: null, unit: 'NO', po_qty: '1', verified_qty: null,
  received_qty: null, vendor_qty: null, billed_qty: '1', expected_qty: '1', po_rate: '10', billed_rate: '10',
  expected_amt: '10', billed_amt: '10', delta: '0', verdict: null, statuses: ['MATCHED'], severity: 'OK',
  match_method: 'EXACT', match_score: 1, conflicts: [], remark: null, is_charge: false,
  needs_review_cell: false, reviewed: null, evidence_crop: null, ...p,
})

const seg = (p: Partial<ReconSegment> = {}): ReconSegment => ({
  id: 's' + Math.random(), kind: 'PV_SECTION', llm_label: null, pages: [1], status: 'LINKED',
  section_title: null, vendor_name: null, store_sn: null, confidence: 1, case_id: 'c1',
  candidates: [], needs_review_cells: 0, warnings: [], summary: null, ...p,
})

describe('CaseVitals', () => {
  it('says how much of the bill each document accounts for', () => {
    render(<CaseVitals attached={[seg()]} lines={[line({})]}
      s={summary({ leg_cover: { po: 0.86, evidence: null, pod: 1, payment: null } })} />)
    expect(screen.getByText('86%')).toBeInTheDocument()
    expect(screen.getByText('100%')).toBeInTheDocument()
  })

  it('shows a dash for a document that has not arrived, never a nought', () => {
    // Not arrived is not nought. 0% accuses a missing report of covering
    // nothing; a dash asks for it.
    render(<CaseVitals attached={[seg()]} lines={[line({})]}
      s={summary({ leg_cover: { po: 0.86, evidence: null, pod: null, payment: null } })} />)
    expect(screen.queryByText('0%')).not.toBeInTheDocument()
    expect(screen.getAllByText('—').length).toBeGreaterThan(0)
  })

  it('bands the pairings so the headline figure can be read behind', () => {
    render(<CaseVitals attached={[seg()]}
      lines={[line({ match_method: 'EXACT' }), line({ match_method: 'SCORE', match_score: 0.9 }),
              line({ match_method: 'SCORE', match_score: 0.75 })]}
      s={summary({ confidence: '0.91' })} />)
    expect(screen.getByText('91%')).toBeInTheDocument()
    expect(screen.getByText('Exact')).toBeInTheDocument()
    expect(screen.getByText('Strong')).toBeInTheDocument()
    expect(screen.getByText('Fair')).toBeInTheDocument()
  })

  it('every billed line lands in exactly one band', () => {
    const lines = [line({ match_method: 'EXACT' }), line({ match_method: 'SCORE', match_score: 0.9 }),
                   line({ match_method: 'NONE', match_score: 0, po_key: null })]
    render(<CaseVitals attached={[seg()]} lines={lines} s={summary({ confidence: '0.6' })} />)
    const panel = screen.getByText('Exact').closest('.cv__panel') as HTMLElement
    const counts = Array.from(panel.querySelectorAll('.cv__bar-v')).map(e => Number(e.textContent))
    expect(counts.reduce((a, b) => a + b, 0)).toBe(3)
  })

  it('says nothing is paired rather than printing 0%', () => {
    render(<CaseVitals attached={[seg()]} lines={[]} s={summary({ confidence: null })} />)
    expect(screen.getByText(/still waiting for its PO/)).toBeInTheDocument()
  })

  it('counts the cells a reader could not settle alone', () => {
    render(<CaseVitals lines={[line({})]} s={summary({ confidence: '1' })}
      attached={[seg({ needs_review_cells: 4 }), seg({ needs_review_cells: 2 })]} />)
    const panel = screen.getByText(/How the documents read/).closest('.cv__panel') as HTMLElement
    expect(within(panel).getByText('6')).toBeInTheDocument()
    expect(within(panel).getByText(/read twice/)).toBeInTheDocument()
  })

  it('says so plainly when nothing was left in doubt', () => {
    render(<CaseVitals lines={[line({})]} s={summary({ confidence: '1' })} attached={[seg()]} />)
    expect(screen.getByText(/nothing left in doubt/)).toBeInTheDocument()
  })
})
