import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render as rtlRender, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter, useLocation } from 'react-router-dom'
import type { ReactElement } from 'react'
import userEvent from '@testing-library/user-event'
import type { LineResult, ReconCase, ReconCaseSummary, ReconDocument } from '../../../api/recon'

const api = vi.hoisted(() => ({
  fetchReconDocuments: vi.fn(),
  fetchReconCases: vi.fn(),
  fetchReconCase: vi.fn(),
  uploadReconDocuments: vi.fn(),
  linkSegment: vi.fn(async () => ({ case_id: 'c1' })),
  ignoreSegment: vi.fn(async () => {}),
  overrideMatch: vi.fn(),
  correctEvidence: vi.fn(),
  acknowledgeCase: vi.fn(async () => {}),
  reviewLine: vi.fn(async () => {}),
  rerunCase: vi.fn(),
  detachSegment: vi.fn(),
  fetchCaseDocuments: vi.fn(async () => [] as unknown[]),
  fetchReconFileView: vi.fn(),
  deleteReconDocument: vi.fn(async () => ({ deleted: 'd', cases: [] })),
  rereadReconDocument: vi.fn(async () => {}),
  confirmCheck: vi.fn(async () => {}),
}))
vi.mock('../../../api/recon', async orig => ({ ...(await orig<typeof import('../../../api/recon')>()), ...api }))
vi.mock('react-pdf', () => ({ Document: () => null, Page: () => null, pdfjs: { GlobalWorkerOptions: {} } }))
vi.mock('../../../api/authedFiles', () => ({
  downloadAuthed: vi.fn(async () => {}),
  useAuthedObjectUrl: () => ({ url: null, loading: false, error: false }),
}))

import ReconDocViewer from './ReconDocViewer'
import ReconFolder from './ReconFolder'

/** Where the app navigated to — record cards open by URL (?open=recon:<id>). */
function Where() { const l = useLocation(); return <output data-testid="where">{l.pathname}{l.search}</output> }
const render = (ui: ReactElement) => rtlRender(<MemoryRouter initialEntries={['/vendors/s/documents?folder=recon']}>{ui}<Where /></MemoryRouter>)
const where = () => decodeURIComponent(screen.getByTestId('where').textContent ?? '')
import ReconCaseView from './ReconCaseView'
import { filterLines, filterMoney, inr, primaryStatus, qty } from './reconFormat'

const summary: ReconCaseSummary = {
  id: 'c1', ref: 'RC-0012', supplier_id: 'v1', vendor_name: 'Inner Space', bill_id: 'b1', invoice_no: 'IS-HO-26-27-109', po_number: 'PPO00023557-1', store_sn: '9621', status: 'NEEDS_REVIEW',
  docs: { po: true, invoice: true, evidence: 1, pod: false, memo: false }, po_total: '626693.90', billed_total: '610335.20',
  expected_total: '579763.90', money_at_risk: '31350.00', under_billed: '778.70', counts: { BLOCKER: 1, REVIEW: 3, INFO: 9 },
  computed_at: null, acknowledged_by: null, acknowledged_at: null,
}

function line(p: Partial<LineResult>): LineResult {
  return {
    id: 'l' + Math.random(), ord: 1, kind: 'po', description: 'Item', po_key: 'pol:1', invoice_key: 'rl:1', evidence_key: 'ev:e1',
    invoice_text: 'Item', evidence_text: 'Item', unit: 'NO', po_qty: '1', verified_qty: '1', received_qty: null, vendor_qty: null, billed_qty: '1',
    expected_qty: '1', po_rate: '10', billed_rate: '10', expected_amt: '10.00', billed_amt: '10.00', delta: '0.00', verdict: 'VERIFIED',
    statuses: ['MATCHED'], severity: 'OK', match_method: 'SCORE', match_score: 0.9, conflicts: [], remark: null, is_charge: false,
    needs_review_cell: false, reviewed: null, evidence_crop: null, ...p,
  }
}

const transport = line({ id: 'lt', description: 'Transportatio n with Loading Unloading', verified_qty: '0', billed_qty: '1',
  expected_qty: '0', po_rate: '31350', billed_rate: '31350', expected_amt: '0.00', billed_amt: '31350.00', delta: '31350.00',
  statuses: ['NOT_DONE'], severity: 'BLOCKER', verdict: 'NOT_DONE' })
const capped = line({ id: 'lc', description: 'LED Strip Fixing Charges', po_qty: '60', verified_qty: '66', billed_qty: '60',
  statuses: ['OVER_EXECUTED_CAPPED'], severity: 'INFO' })
const extra = line({ id: 'lx', kind: 'additional', po_key: null, invoice_key: null, description: 'See Through channel 10 Fit',
  statuses: ['ADDITIONAL_ON_SITE'], severity: 'REVIEW' })

const fullCase: ReconCase = {
  summary, lines: [transport, capped, extra],
  header: [
    { code: 'invoice_arithmetic', label: 'Invoice arithmetic', severity: 'REVIEW', passed: false, detail: 'line amounts add up to ₹5,45,973.90' },
    { code: 'tax_regime', label: 'GST type and amount', severity: 'OK', passed: true, detail: '' },
  ],
  attached: [], approvals: [], events: [], ack_note: null,
}

describe('reconFormat', () => {
  it('formats money with Indian grouping and quantities without trailing zeros', () => {
    expect(inr('1128945.59')).toBe('11,28,945.59')
    expect(inr(null)).toBe('—')
    expect(qty('11.100')).toBe('11.1')
    expect(qty('1531')).toBe('1,531')
  })
  it('picks the most important status and filters', () => {
    expect(primaryStatus({ statuses: ['UNDER_USED', 'OVER_VERIFIED', 'AUDITOR_REMARK'] })).toBe('OVER_VERIFIED')
    expect(filterLines([transport, capped, extra], 'flagged').map(l => l.id)).toEqual(['lt', 'lx'])
    expect(filterLines([transport, capped, extra], 'blockers').map(l => l.id)).toEqual(['lt'])
    expect(filterLines([transport, capped, extra], 'extra').map(l => l.id)).toEqual(['lx'])
  })
  it('separates what the payer is exposed to from what the vendor lost', () => {
    // 'Flagged' lumps these two together, which makes a payable invoice look
    // like a problem. Over-billing is a reason to hold; under-billing is not.
    const short = line({ id: 'lu', description: 'Vinyl pasting', delta: '-1850.00',
      statuses: ['UNDER_BILLED'], severity: 'REVIEW' })
    const wording = line({ id: 'ld', description: 'ACP cladding', delta: '0.00',
      statuses: ['DESCRIPTION_CONFLICT'], severity: 'REVIEW' })
    const all = [transport, short, wording, capped]
    expect(filterLines(all, 'over').map(l => l.id)).toEqual(['lt'])
    expect(filterLines(all, 'under').map(l => l.id)).toEqual(['lu'])
    // Flagged, but nothing is at stake either way: it needs reading, not money.
    expect(filterLines(all, 'check').map(l => l.id)).toEqual(['ld'])
    // The three partition 'flagged', so no line is counted twice or lost.
    expect(filterLines(all, 'flagged').length).toBe(3)
  })
  it('shows money only on the two chips that mean money', () => {
    const short = line({ id: 'lu', delta: '-1850.00', statuses: ['UNDER_BILLED'], severity: 'REVIEW' })
    expect(filterMoney([transport, short], 'over')).toBe(31350)
    // Unsigned: the chip says how much, the label says whose way it runs.
    expect(filterMoney([transport, short], 'under')).toBe(1850)
    expect(filterMoney([transport, short], 'all')).toBeNull()
  })
})

const seg = (p: Partial<ReconDocument['segments'][number]>): ReconDocument['segments'][number] => ({
  id: 's', kind: 'PV_SECTION', llm_label: null, pages: [1], status: 'LINKED', section_title: null, vendor_name: null, store_sn: null,
  confidence: 0.9, case_id: null, candidates: [], needs_review_cells: 0, warnings: [], summary: null, ...p,
})
const file = (p: Partial<ReconDocument>): ReconDocument => ({
  id: 'd', file_name: 'f.pdf', recon_status: 'READY', recon_stage: 'done', progress: null, error: null, uploaded_at: '2026-11-12',
  uploaded_by: 'bata', segments: [], ...p,
})

describe('ReconFolder', () => {
  beforeEach(() => {
    Object.values(api).forEach(f => f.mockClear())
  })

  it('gives the dashboard a real control, not a heading that happens to click', async () => {
    api.fetchReconDocuments.mockResolvedValue([
      file({ id: 'd1', file_name: 'PO.pdf', segments: [seg({ id: 's1', kind: 'PURCHASE_ORDER', case_id: 'c1' })] })])
    api.fetchReconCases.mockResolvedValue([{ ...summary, docs: { po: true, invoice: true, evidence: 1, pod: false, memo: false } }])
    render(<ReconFolder supplierId="s" brandId={null} notify={() => {}} />)
    const btn = await screen.findByRole('button', { name: /Reconciliation dashboard/ })
    // Open by default: a finance manager opens this screen to see where the
    // money stands, not to click a toggle first.
    expect(btn).toHaveAttribute('aria-expanded', 'true')
    await userEvent.click(btn)
    expect(btn).toHaveAttribute('aria-expanded', 'false')
  })

  it('says how much of the invoice each document accounts for', async () => {
    api.fetchReconDocuments.mockResolvedValue([
      file({ id: 'd1', file_name: 'PO.pdf', segments: [seg({ id: 's1', kind: 'PURCHASE_ORDER', case_id: 'c1' })] })])
    api.fetchReconCases.mockResolvedValue([{
      ...summary, docs: { po: true, invoice: true, evidence: 1, pod: false, memo: false },
      leg_cover: { po: 0.94, evidence: 1, pod: null, payment: null },
    }])
    render(<ReconFolder supplierId="s" brandId={null} notify={() => {}} />)
    const pos = (await screen.findByText('Purchase orders')).closest('details') as HTMLElement
    expect(within(pos).getByText('94%')).toBeInTheDocument()
  })

  it('lists every uploaded file with what it was read as, its invoice and its check', async () => {
    api.fetchReconDocuments.mockResolvedValue([
      file({ id: 'd1', file_name: 'Report 9621.pdf', segments: [
        seg({ id: 's1', status: 'UNLINKED', section_title: 'FAMILY- INTERIOR PO', pages: [3, 4], candidates: [
          { target_type: 'po', target_id: 'p9', label: 'PO PPO00099999-1 (no invoice yet)', score: 0.7, signals: { store: 1 }, case_id: null, bill_id: null, po_id: 'p9' }] }),
        seg({ id: 's2', status: 'IGNORED' })] }),
      file({ id: 'd2', file_name: 'IS-HO-109.pdf', segments: [seg({ id: 's3', kind: 'TAX_INVOICE', case_id: 'c1' })] }),
      file({ id: 'd3', file_name: 'Show purchase order.pdf', segments: [seg({ id: 's9', kind: 'PURCHASE_ORDER', status: 'WAITING' })] }),
    ])
    api.fetchReconCases.mockResolvedValue([{ ...summary, docs: { po: true, invoice: true, evidence: 1, pod: false, memo: false } }])
    render(<ReconFolder supplierId="s" brandId={null} notify={() => {}} />)
    // Filed by what each document was read as, so the three land in three
    // folders rather than one list. Nothing was re-read to do it: the kinds
    // were already on the segments.
    const audit = (await screen.findByText('Audit reports')).closest('details') as HTMLElement
    const invoices = screen.getByText('Invoices').closest('details') as HTMLElement
    const pos = screen.getByText('Purchase orders').closest('details') as HTMLElement
    expect(within(audit).getByText('Report 9621.pdf')).toBeInTheDocument()
    expect(within(invoices).getByText('IS-HO-109.pdf')).toBeInTheDocument()
    expect(within(pos).getByText('Show purchase order.pdf')).toBeInTheDocument()
    const table = within(audit).getByRole('table')
    expect(within(table).getByText('+1 set aside')).toBeInTheDocument()
    expect(within(table).getByText('Not linked')).toBeInTheDocument()
    expect(within(pos).getByText('Waiting for its invoice')).toBeInTheDocument()
    expect(within(invoices).getByText('3-way')).toBeInTheDocument()
    expect(within(invoices).getByText('₹31,350.00 at risk')).toBeInTheDocument()
    // Needs you: pick the invoice an unlinked section belongs to.
    expect(screen.getByText('Which invoice is this for?')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /PO PPO00099999-1/ }))
    expect(api.linkSegment).toHaveBeenCalledWith('s1', { po_id: 'p9' })
    // The invoice link opens its reconciliation card (a real link: ?open=recon:<id>), not the file.
    const link = within(invoices).getByRole('link', { name: /IS-HO-26-27-109/ })
    expect(link).toHaveTextContent('RC-0012')
    expect(decodeURIComponent(link.getAttribute('href') ?? '')).toContain('open=recon:c1')
    await userEvent.click(link)
    expect(where()).toContain('open=recon:c1')
    expect(api.fetchReconFileView).not.toHaveBeenCalled()
  })

  it('polls while a file is being read and stops when it is done', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    const reading: ReconDocument = file({ id: 'd2', file_name: 'PO.pdf', recon_status: 'RUNNING', recon_stage: 'extracting',
      progress: { segment: 1, segments: 2 } })
    api.fetchReconDocuments.mockResolvedValueOnce([reading]).mockResolvedValue([{ ...reading, recon_status: 'READY' }])
    api.fetchReconCases.mockResolvedValue([])
    render(<ReconFolder supplierId="s" brandId={null} notify={() => {}} />)
    expect(await screen.findByText('Reading the details', { exact: false })).toBeInTheDocument()
    await vi.advanceTimersByTimeAsync(3100)
    await waitFor(() => expect(api.fetchReconDocuments).toHaveBeenCalledTimes(2))
    await vi.advanceTimersByTimeAsync(6000)
    expect(api.fetchReconDocuments).toHaveBeenCalledTimes(2)
    vi.useRealTimers()
  })

  it('says receipt is confirmed only at consignment level when a POD stands in', async () => {
    // A delivery proof confirms that a consignment of a stated value reached an
    // address. It never confirms that six of an item arrived, and a tick alone
    // would imply it did.
    const part = { id: 'sp', role: 'pod' as const, kind: 'POD' as const, title: 'Delivery proof',
      source: 'upload' as const, file_name: 'POD.png', doc_id: 'dp', pages: [1], link_method: null,
      download: null, file_type: 'image' as const, warnings: [],
      case: { id: 'c1', invoice_no: 'AMP/26-27/070', po_number: 'PPO00024046-1', store_sn: '8255',
              status: 'NEEDS_REVIEW' as const,
              coverage: { po: true, invoice: true, evidence: false, pod: true }, ways: 3,
              totals: { po_total: '754596.00', expected_total: '636740.50', billed_total: '634890.50',
                        money_at_risk: '0.00', under_billed: '0.00' },
              counts: {}, checks: [] },
      fields: [], tables: [] }
    render(<ReconDocViewer title="POD.png" parts={[part as never]} onClose={() => {}} />)
    expect(await screen.findByText(/consignment level, not per item/)).toBeInTheDocument()
    expect(screen.getByTitle(/not item quantities/)).toBeInTheDocument()
  })

  it("states the delivery proof's own verdict, next to the delivery proof", async () => {
    // It was reaching the screen only inside a run-on list of passed checks at
    // the bottom of the case, so against a POD the page looked unreconciled.
    const part = { id: 'sp', role: 'pod' as const, kind: 'POD' as const, title: 'Delivery proof',
      source: 'upload' as const, file_name: 'POD.png', doc_id: 'dp', pages: [1], link_method: null,
      download: null, file_type: 'image' as const, warnings: [],
      case: { id: 'c1', invoice_no: '26GJ/KMW/SI15224', po_number: 'PPO00030541-1', store_sn: '9648',
              status: 'NEEDS_REVIEW' as const,
              coverage: { po: true, invoice: true, evidence: false, pod: true }, ways: 3,
              totals: { po_total: '572400.00', expected_total: '572400.00', billed_total: '572400.00',
                        invoice_total: '675432.00', money_at_risk: '0.00', under_billed: '0.00' },
              counts: {},
              checks: [{ code: 'pod_matches', label: 'Delivery proof matches invoice',
                         severity: 'OK' as const, passed: true, detail: '' }] },
      fields: [], tables: [] }
    render(<ReconDocViewer title="POD.png" parts={[part as never]} onClose={() => {}} />)
    expect(await screen.findByText(/Reconciled against the delivery proof/)).toBeInTheDocument()
    // The gross figure appears in the verdict and again as its own total.
    expect(screen.getAllByText(/6,75,432/).length).toBeGreaterThan(0)
  })

  it('says plainly when the delivery proof does not match', async () => {
    const part = { id: 'sp', role: 'pod' as const, kind: 'POD' as const, title: 'Delivery proof',
      source: 'upload' as const, file_name: 'POD.png', doc_id: 'dp', pages: [1], link_method: null,
      download: null, file_type: 'image' as const, warnings: [],
      case: { id: 'c1', invoice_no: 'X', po_number: 'P', store_sn: '1',
              status: 'NEEDS_REVIEW' as const,
              coverage: { po: true, invoice: true, evidence: false, pod: true }, ways: 3,
              totals: { po_total: '1', expected_total: '1', billed_total: '1',
                        invoice_total: '1', money_at_risk: '0', under_billed: '0' },
              counts: {},
              checks: [{ code: 'pod_matches', label: 'Delivery proof matches invoice',
                         severity: 'BLOCKER' as const, passed: false, detail: 'POD value differs' }] },
      fields: [], tables: [] }
    render(<ReconDocViewer title="POD.png" parts={[part as never]} onClose={() => {}} />)
    expect(await screen.findByText(/does not match/)).toBeInTheDocument()
    expect(screen.getAllByText(/POD value differs/).length).toBeGreaterThan(0)
  })

  it('does not say that when the site audit covers receipt at item level', async () => {
    const part = { id: 'se', role: 'evidence' as const, kind: 'PV_SECTION' as const, title: 'Site audit',
      source: 'upload' as const, file_name: 'PV.pdf', doc_id: 'dv', pages: [1], link_method: null,
      download: null, file_type: 'pdf' as const, warnings: [],
      case: { id: 'c1', invoice_no: 'AMP/26-27/070', po_number: 'PPO00024046-1', store_sn: '8255',
              status: 'NEEDS_REVIEW' as const,
              coverage: { po: true, invoice: true, evidence: true, pod: true }, ways: 4,
              totals: { po_total: '754596.00', expected_total: '636740.50', billed_total: '634890.50',
                        money_at_risk: '0.00', under_billed: '0.00' },
              counts: {}, checks: [] },
      fields: [], tables: [] }
    render(<ReconDocViewer title="PV.pdf" parts={[part as never]} onClose={() => {}} />)
    expect(await screen.findByText('4-way check')).toBeInTheDocument()
    expect(screen.queryByText(/consignment level, not per item/)).not.toBeInTheDocument()
  })

  it('opens a file with what was read and, beside each line, how it compares', async () => {
    api.fetchReconDocuments.mockResolvedValue([file({ id: 'd2', file_name: 'Invoice 070.pdf', segments: [seg({ id: 'si', kind: 'TAX_INVOICE', case_id: 'c1' })] })])
    api.fetchReconCases.mockResolvedValue([summary])
    const ctx = { id: 'c1', invoice_no: 'AMP/26-27/070', po_number: 'PPO00024046-1', store_sn: '8255', status: 'NEEDS_REVIEW' as const,
      coverage: { po: true, invoice: true, evidence: true, pod: false }, ways: 3,
      totals: { po_total: '754596.00', expected_total: '636740.50', billed_total: '634890.50', money_at_risk: '0.00', under_billed: '1850.00' },
      counts: { REVIEW: 1 }, checks: [{ code: 'payment_terms', label: 'Payment terms', severity: 'REVIEW' as const, passed: false, detail: 'PO 60/40, invoice 100%' }] }
    const cmp = (p: Record<string, unknown>) => ({ id: 'r', kind: 'po', po_qty: '2', po_rate: '1850', billed_qty: '2', billed_rate: '1850',
      verified_qty: '2', vendor_qty: null, expected_qty: '2', expected_amt: '3700.00', billed_amt: '3700.00', delta: '0.00', statuses: ['MATCHED'],
      severity: 'OK', verdict: 'VERIFIED', conflicts: [], match_method: 'SCORE', match_score: 0.9, remark: null, reviewed: false, ...p })
    api.fetchReconFileView.mockResolvedValue({
      id: 'd2', file_name: 'Invoice 070.pdf', uploaded_at: null, uploaded_by: 'bata', recon_status: 'READY', error: null,
      download: '/x', file_type: null, parts: [
        { id: 'si', role: 'invoice', kind: 'TAX_INVOICE', title: 'Invoice AMP/26-27/070', source: 'upload', file_name: 'Invoice 070.pdf',
          doc_id: 'd2', pages: [1, 2], link_method: 'auto', warnings: [], download: null, file_type: null, status: 'LINKED', case: ctx,
          fields: [{ label: 'Invoice total', value: '749171.00', fmt: 'money' }],
          tables: [{ title: 'Invoice lines', columns: [{ key: 'description', label: 'Item', fmt: 'text' }, { key: 'qty', label: 'Qty', fmt: 'qty' }, { key: 'rate', label: 'Rate', fmt: 'money' }],
            rows: [
              { _key: 'rl:1', description: 'Fire panel', qty: '1', rate: '9000', _cmp: cmp({ po_qty: '1', po_rate: '8500', billed_rate: '9000', expected_amt: '8500.00', delta: '500.00', statuses: ['RATE_HIGHER'], severity: 'REVIEW' }) },
              { _key: 'rl:2', description: 'Smoke detector', qty: '2', rate: '1850', _cmp: cmp({}) },
            ] }] },
        { id: 'sx', role: 'evidence', kind: 'PV_SECTION', title: 'Annexure-1: Civil', source: 'upload', file_name: 'Invoice 070.pdf', doc_id: 'd2',
          pages: [3], link_method: null, warnings: [], download: null, file_type: null, status: 'IGNORED', vendor_name: 'INNERSPACE', case: null,
          fields: [], tables: [] },
      ] })
    render(<ReconFolder supplierId="s" brandId={null} notify={() => {}} />)
    await userEvent.click(await screen.findByRole('row', { name: 'Open Invoice 070.pdf' }))
    const dlg = await screen.findByRole('dialog', { name: 'Invoice 070.pdf' })
    expect(await within(dlg).findByText('3-way check')).toBeInTheDocument()
    // What a tick means, not just that there is one. The delivery proof's
    // limits are the ones worth spelling out.
    expect(within(dlg).getByTitle(/Quantities verified on site/)).toBeInTheDocument()
    // One coloured group per source: this invoice, then the PO and the site audit, then the result.
    const groups = within(dlg).getAllByRole('columnheader').filter(h => h.className.includes('rc__src') && h.getAttribute('colspan'))
    expect(groups.map(h => h.textContent)).toEqual(['Invoice · this document', 'PO', 'Site audit', 'Result'])
    expect(groups.map(h => h.className.match(/rc__src--(\w+)/)?.[1])).toEqual(['invoice', 'po', 'evidence', 'result'])
    // The PO's rate is marked where the invoice's rate is above it.
    const cells = within(dlg).getAllByText('₹8,500.00').map(e => e.closest('td')!)
    const poRate = cells.find(td => td.className.includes('rc__src--po'))!
    expect(poRate.className).toContain('rc__diff')
    expect(cells.find(td => td.className.includes('rc__src--result'))).toBeTruthy()   // expected ₹ sits in the result group
    expect(within(dlg).getByText('Rate above PO')).toBeInTheDocument()
    expect(within(dlg).getByText('Payment terms')).toBeInTheDocument()
    expect(within(dlg).getByText('₹749,171.00'.replace('749,171', '7,49,171'))).toBeInTheDocument()
    // Only what needs a look.
    await userEvent.click(within(dlg).getByRole('tab', { name: 'To check 1' }))
    expect(within(dlg).queryByText('Smoke detector')).not.toBeInTheDocument()
    // Another vendor's section is there, set aside, with nothing to compare.
    await userEvent.click(within(dlg).getByRole('tab', { name: /set aside/ }))
    expect(within(dlg).getByText(/Set aside \(INNERSPACE\)/)).toBeInTheDocument()
    await userEvent.click(within(dlg).getByRole('tab', { name: /^Invoice/ }))
    await userEvent.click(within(dlg).getByRole('button', { name: /Full reconciliation/ }))
    expect(where()).toContain('open=recon:c1')
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })
})

describe('ReconFolder delete and read again', () => {
  beforeEach(() => { Object.values(api).forEach(f => f.mockClear()) })

  it('says plainly when a file could not be read, and offers to read it again or delete it', async () => {
    api.fetchReconCases.mockResolvedValue([])
    api.fetchReconDocuments.mockResolvedValue([file({ id: 'df', file_name: 'Yelanka 1859.pdf', recon_status: 'FAILED',
      error: 'value too long for type character varying(15)' })])
    render(<ReconFolder supplierId="s" brandId={null} notify={() => {}} />)
    expect((await screen.findAllByText(/a reading problem on our side/)).length).toBeGreaterThan(0)
    expect(screen.queryByText(/character varying/)).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /^Read again$/ }))
    expect(api.rereadReconDocument).toHaveBeenCalledWith('df')
  })

  it('does not offer to read again when the bytes were never reachable', async () => {
    // A storage problem and a parse failure look identical in the list but need
    // opposite actions. "Read again" on a file we never had can never succeed.
    api.fetchReconCases.mockResolvedValue([])
    api.fetchReconDocuments.mockResolvedValue([file({ id: 'ds', file_name: 'Show purchase order.pdf',
      recon_status: 'FAILED',
      error: 'This file was stored on another machine, so it cannot be read from here.' })])
    render(<ReconFolder supplierId="s" brandId={null} notify={() => {}} />)
    await screen.findAllByText(/stored on another machine/)
    expect(screen.queryByRole('button', { name: /^Read again$/ })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /^Upload again$/ })).toBeInTheDocument()
  })

  it('offers upload again when nothing was stored at all', async () => {
    api.fetchReconCases.mockResolvedValue([])
    api.fetchReconDocuments.mockResolvedValue([file({ id: 'dn', file_name: 'empty.pdf',
      recon_status: 'FAILED', error: 'No file was stored for this document' })])
    render(<ReconFolder supplierId="s" brandId={null} notify={() => {}} />)
    await screen.findAllByText(/No file was stored/)
    expect(screen.queryByRole('button', { name: /^Read again$/ })).not.toBeInTheDocument()
  })

  it('asks before deleting, naming the invoice the file is on, then deletes', async () => {
    api.fetchReconCases.mockResolvedValue([summary])
    api.fetchReconDocuments.mockResolvedValue([file({ id: 'd2', file_name: 'IS-HO-109.pdf', segments: [seg({ id: 's3', kind: 'TAX_INVOICE', case_id: 'c1' })] })])
    render(<ReconFolder supplierId="s" brandId={null} notify={() => {}} />)
    const table = await screen.findByRole('table')
    await userEvent.click(within(table).getByRole('button', { name: 'Delete IS-HO-109.pdf' }))
    const dlg = await screen.findByRole('dialog')
    expect(within(dlg).getByText(/used on IS-HO-26-27-109/)).toBeInTheDocument()
    expect(api.deleteReconDocument).not.toHaveBeenCalled()
    await userEvent.click(within(dlg).getByRole('button', { name: 'Delete' }))
    await waitFor(() => expect(api.deleteReconDocument).toHaveBeenCalledWith('d2'))
    expect(api.fetchReconFileView).not.toHaveBeenCalled()        // the row's buttons don't open the file
  })
})

describe('ReconCaseView', () => {
  it('offers a way back to the dashboard, not just a close cross', async () => {
    // The card opens over the Recon folder; until now the only exit was the
    // cross, so the dashboard and the other documents were reachable only by
    // guessing that.
    api.fetchReconCase.mockResolvedValue(fullCase)
    const onClose = vi.fn()
    render(<ReconCaseView caseId="c1" notify={() => {}} onClose={onClose} />)
    await userEvent.click(await screen.findByRole('button', { name: /Dashboard/ }))
    expect(onClose).toHaveBeenCalled()
  })


  it('says which lines were left out of the billing, and why', async () => {
    // Dropping a line in silence is how an understated bill gets paid.
    api.fetchReconCase.mockResolvedValue({
      ...fullCase,
      summary: { ...summary, rollup_lines: [
        { sno: 1, description: 'Supply Installation of HVAC Work', amount: '466769.65' },
        { sno: 2, description: 'Supply & Installation of Sprinkler', amount: '282401.14' }] },
    })
    render(<ReconCaseView caseId="c1" notify={() => {}} onClose={() => {}} />)
    await userEvent.click(await screen.findByRole('tab', { name: '2 · Reconciliation' }))
    expect(await screen.findByText(/2 lines are a section heading/)).toBeInTheDocument()
    expect(screen.getByText(/4,66,769.65/)).toBeInTheDocument()
    expect(screen.getByText(/the work is charged on the detail lines/)).toBeInTheDocument()
  })


  it('shows how sure each pairing is, because every figure rests on it', async () => {
    // A 62% match means the difference beside it may be between two unrelated
    // items. It was computed all along and shown only inside an expanded row.
    api.fetchReconCase.mockResolvedValue({
      ...fullCase,
      lines: [line({ id: 'lm', description: 'Weak pairing', match_method: 'SCORE', match_score: 0.62,
                     severity: 'REVIEW', statuses: ['DESCRIPTION_CONFLICT'] })],
    })
    render(<ReconCaseView caseId="c1" notify={() => {}} onClose={() => {}} />)
    await userEvent.click(await screen.findByRole('tab', { name: '2 · Reconciliation' }))
    const table = await screen.findByRole('table')
    expect(within(table).getByText('62%')).toBeInTheDocument()
  })

  it('does not put a percentage on a pairing that is not a judgement', async () => {
    api.fetchReconCase.mockResolvedValue({
      ...fullCase,
      lines: [line({ id: 'le', description: 'Exact pairing', match_method: 'EXACT', match_score: 1,
                     severity: 'REVIEW', statuses: ['DESCRIPTION_CONFLICT'] })],
    })
    render(<ReconCaseView caseId="c1" notify={() => {}} onClose={() => {}} />)
    await userEvent.click(await screen.findByRole('tab', { name: '2 · Reconciliation' }))
    const table = await screen.findByRole('table')
    expect(within(table).getByText('Exact')).toBeInTheDocument()
    expect(within(table).queryByText('100%')).not.toBeInTheDocument()
  })


  it('shows what the site report says the work is worth, not only how much of it', async () => {
    api.fetchReconCase.mockResolvedValue({
      ...fullCase,
      lines: [line({ id: 'lv', description: 'Flush Door', verified_qty: '3',
                     verified_rate: '6365.00', verified_amt: '19095.00' })],
    })
    render(<ReconCaseView caseId="c1" notify={() => {}} onClose={() => {}} />)
    await userEvent.click(await screen.findByRole('tab', { name: '2 · Reconciliation' }))
    const table = await screen.findByRole('table')
    expect(within(table).getByText('6,365.00')).toBeInTheDocument()
    expect(within(table).getByText('19,095.00')).toBeInTheDocument()
  })

  it('explains a rate printed against no quantity instead of looking like a bug', async () => {
    // The vendor listed the item, priced it, and billed none of it. The screen
    // is faithful to the paper; it just has to say so.
    api.fetchReconCase.mockResolvedValue({
      ...fullCase,
      lines: [line({ id: 'l0', description: 'Main Incomer MCCB', billed_qty: '0',
                     billed_rate: '13680.00', billed_amt: '0.00' })],
    })
    render(<ReconCaseView caseId="c1" notify={() => {}} onClose={() => {}} />)
    await userEvent.click(await screen.findByRole('tab', { name: '2 · Reconciliation' }))
    const cell = (await screen.findByText('13,680.00')).closest('td')
    expect(cell).toHaveAttribute('title', expect.stringContaining('bills no quantity'))
    expect(cell).toHaveClass('vc__muted')
  })


  it('shows the receipt in money, not only in units', async () => {
    // A reviewer reconciling against a delivery proof is comparing VALUES.
    // The figure was already driving the ±₹100 check; it was simply not shown.
    api.fetchReconCase.mockResolvedValue({
      ...fullCase,
      lines: [line({ id: 'lr', description: '4 TR Cassette Unit', received_qty: '6',
                     received_amt: '675432.00', receipt_basis: 'single_line_consignment' })],
    })
    render(<ReconCaseView caseId="c1" notify={() => {}} onClose={() => {}} />)
    await userEvent.click(await screen.findByRole('tab', { name: '2 · Reconciliation' }))
    const table = await screen.findByRole('table')
    expect(within(table).getByText('6,75,432.00')).toBeInTheDocument()
  })


  it('lets a reviewer answer a check that asked for a judgement', async () => {
    // The engine accepted a waybill on an inference and said so. Without a way
    // to answer, the flag would sit on the case forever and be learned as noise.
    api.fetchReconCase.mockResolvedValue({
      ...fullCase,
      header: [{ code: 'pod_invoice_ref_match', label: 'POD names the invoice', severity: 'REVIEW',
                 passed: false, detail: 'confirm this waybill is for this invoice',
                 evidence: { confirmable: '266J/AM4/S115224|26GJ/KMW/SI15224' } }],
    })
    render(<ReconCaseView caseId="c1" notify={() => {}} onClose={() => {}} />)
    await userEvent.click(await screen.findByRole('tab', { name: '2 · Reconciliation' }))
    await userEvent.click(await screen.findByRole('button', { name: 'Yes, confirm' }))
    // The answer carries what was on screen, so a re-read of the document asks again.
    expect(api.confirmCheck).toHaveBeenCalledWith('c1', 'pod_invoice_ref_match',
      '266J/AM4/S115224|26GJ/KMW/SI15224')
  })

  it('offers no such button on a check nobody may wave through', async () => {
    api.fetchReconCase.mockResolvedValue(fullCase)   // invoice_arithmetic, not confirmable
    render(<ReconCaseView caseId="c1" notify={() => {}} onClose={() => {}} />)
    await userEvent.click(await screen.findByRole('tab', { name: '2 · Reconciliation' }))
    await screen.findByText('Invoice arithmetic')
    expect(screen.queryByRole('button', { name: 'Yes, confirm' })).not.toBeInTheDocument()
  })

  it('opens as a card headed by its case number, invoice and vendor', async () => {
    api.fetchReconCase.mockResolvedValue(fullCase)
    const onClose = vi.fn()
    render(<ReconCaseView caseId="c1" notify={() => {}} onClose={onClose} />)
    expect(await screen.findByText('Invoice IS-HO-26-27-109')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /RC-0012/ })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Inner Space' })).toBeInTheDocument()
    expect(screen.getByText('PO PPO00023557-1 · Store 9621')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Close' }))
    expect(onClose).toHaveBeenCalled()
  })


  it('shows totals, failed checks and flagged lines first', async () => {
    api.fetchReconCase.mockResolvedValue(fullCase)
    render(<ReconCaseView caseId="c1" notify={() => {}} onClose={() => {}} />)
    await userEvent.click(await screen.findByRole('tab', { name: '2 · Reconciliation' }))
    expect(await screen.findByText('Invoice arithmetic')).toBeInTheDocument()
    const table = screen.getByRole('table')
    expect(within(table).getByText('Transportatio n with Loading Unloading')).toBeInTheDocument()
    expect(within(table).queryByText('LED Strip Fixing Charges')).not.toBeInTheDocument()   // INFO, hidden under Flagged
    await userEvent.click(screen.getByRole('tab', { name: /All/ }))
    expect(within(table).getByText('LED Strip Fixing Charges')).toBeInTheDocument()
    expect(within(table).getByText('Capped at PO')).toBeInTheDocument()
  })

  it('needs a note to acknowledge with an open blocker', async () => {
    api.fetchReconCase.mockResolvedValue(fullCase)
    render(<ReconCaseView caseId="c1" notify={() => {}} onClose={() => {}} />)
    await userEvent.click(await screen.findByRole('tab', { name: '2 · Reconciliation' }))
    await userEvent.click(await screen.findByRole('button', { name: /Acknowledge/ }))
    const dlg = screen.getByRole('dialog', { name: 'Acknowledge this reconciliation' })
    const go = within(dlg).getByRole('button', { name: /Acknowledge/ })
    expect(go).toBeDisabled()
    await userEvent.type(within(dlg).getByLabelText('Acknowledgement note'), 'Transport approved by RM')
    await userEvent.click(go)
    expect(api.acknowledgeCase).toHaveBeenCalledWith('c1', 'Transport approved by RM', true)
  })

  it('changes a match from the line detail', async () => {
    api.fetchReconCase.mockResolvedValue({ ...fullCase, lines: [transport, capped] })
    api.overrideMatch.mockResolvedValue({ ...fullCase })
    render(<ReconCaseView caseId="c1" notify={() => {}} onClose={() => {}} />)
    await userEvent.click(await screen.findByRole('tab', { name: '2 · Reconciliation' }))
    await userEvent.click(await screen.findByText('Transportatio n with Loading Unloading'))
    await userEvent.click(screen.getByRole('button', { name: 'Change match' }))
    const dlg = screen.getByRole('dialog', { name: 'Which PO line is this?' })
    await userEvent.click(within(dlg).getByRole('button', { name: 'Not in this PO' }))
    expect(api.overrideMatch).toHaveBeenCalledWith('c1', 'rl:1', null)
  })
})

describe('ReconCaseView documents step', () => {
  const po = { id: 'sp', role: 'po', kind: 'PURCHASE_ORDER', title: 'PO PPO00024046-1', source: 'upload', file_name: 'Show purchase order.pdf',
    doc_id: 'd1', pages: [1, 2], link_method: 'auto', warnings: [], download: null, file_type: null,
    fields: [{ label: 'PO total', value: '754596.00', fmt: 'money' }, { label: 'Store', value: '8255 · Phoenix', fmt: 'text' },
      { label: 'Payment terms', value: '60% Advance', fmt: 'text' }],
    tables: [{ title: 'PO lines', columns: [{ key: 'description', label: 'Item', fmt: 'text' }, { key: 'qty', label: 'Qty', fmt: 'qty' }],
      rows: [{ description: 'Supply and Installation MCP Hooter', qty: '2.000' }] }] }
  const audit = { id: 'se', role: 'evidence', kind: 'PV_SECTION', title: 'AHU', source: 'upload', file_name: 'JPC report.pdf', doc_id: 'd2',
    pages: [5], link_method: 'auto', warnings: [], download: null, file_type: null,
    fields: [{ label: 'Auditor', value: 'J P Chawla & Co. LLP', fmt: 'text' }],
    tables: [{ title: 'Audit rows', columns: [{ key: 'item', label: 'Item', fmt: 'text' }, { key: 'audit_qty', label: 'Audited', fmt: 'qty' }],
      rows: [{ item: 'MCP Hooter', audit_qty: '1', audit_raw: null, _flag: 'Two readings disagree', _alts: ['1', '7'] }] }] }

  it('opens on a card per document, and a card opens the document beside what was read from it', async () => {
    api.fetchReconCase.mockResolvedValue(fullCase)
    api.fetchCaseDocuments.mockResolvedValue([po, audit])
    render(<ReconCaseView caseId="c1" notify={() => {}} onClose={() => {}} />)
    // The card opens on the reconciliation now, so step 1 is a click away
    // rather than the landing place.
    await userEvent.click(await screen.findByRole('tab', { name: '1 · Documents read' }))
    // Cards: key values only; the reconciliation isn't shown here.
    expect(await screen.findByText('₹7,54,596.00')).toBeInTheDocument()
    expect(screen.getByText('8255 · Phoenix')).toBeInTheDocument()
    expect(screen.queryByText('Payment terms')).not.toBeInTheDocument()
    expect(screen.getByText('1 to check')).toBeInTheDocument()
    expect(screen.getByText(/Not on this invoice yet: invoice/)).toBeInTheDocument()
    expect(screen.queryByText('Invoice arithmetic')).not.toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: /Open Purchase order/ }))
    const dlg = screen.getByRole('dialog', { name: 'IS-HO-26-27-109 · PPO00023557-1' })
    expect(within(dlg).getByText('60% Advance')).toBeInTheDocument()
    expect(within(dlg).getByText('Supply and Installation MCP Hooter')).toBeInTheDocument()
    await userEvent.click(within(dlg).getByRole('tab', { name: /AHU/ }))
    expect(within(dlg).getByText('Two readings disagree')).toBeInTheDocument()
    expect(within(dlg).getByText('read as 1 / 7')).toBeInTheDocument()
    await userEvent.keyboard('{Escape}')
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'See reconciliation' }))
    expect(await screen.findByText('Invoice arithmetic')).toBeInTheDocument()
  })
})
