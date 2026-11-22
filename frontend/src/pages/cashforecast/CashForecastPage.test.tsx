/**
 * Cash flow forecast page against the golden synthetic tenant
 * (docs/cashflow-forecast/dummy-data/seed/expected_forecast.json).
 */
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import CashForecastPage from './CashForecastPage'
import { compact, exact, rupees, toPaise } from './format'

type GoldenView = {
  opening_paise: number
  reserve_paise: number
  days: { date: string; banking_day: boolean }[]
  minimum_closing_paise: number
  minimum_date: string
  first_reserve_breach_date: string | null
  first_negative_date: string | null
  [k: string]: unknown
}
type GoldenEvent = {
  event_key: string
  source_type: string
  source_id: string
  label: string
  direction: 'in' | 'out'
  amount_paise: number
  date: string
  confidence: string
  views: string[]
  category: string
  counterparty: string | null
  date_basis: string
  payment_window: { earliest: string; latest: string } | null
}

const golden = JSON.parse(
  readFileSync(resolve(__dirname, '../../../../docs/cashflow-forecast/dummy-data/seed/expected_forecast.json'), 'utf8'),
) as { views: Record<string, GoldenView>; events: GoldenEvent[]; category_totals: Record<string, Record<string, number>>; od_headroom_paise: number }

const SNAP = {
  snapshot_id: 'snap-1',
  revision: 1,
  as_of: '2026-11-20T18:30:00+05:30',
  start: '2026-11-21',
  end: '2026-12-20',
  horizon_days: 30,
  reserve_paise: 150000000,
  od_headroom_paise: golden.od_headroom_paise,
  content_hash: 'h',
  changed: null,
  coverage: { state: 'complete', failed_sources: [], missing_balances: [], needs_setup: [], event_count: 229, exclusion_count: 7 },
  is_fixture: true,
  today: '2026-11-21',
  balances: [
    { bank_account_id: 'a', account_name: 'HDFC Current - Operations', account_mask: 'XXXXXX4821', balance_paise: 435148250, as_of: '2026-11-20T18:30:00+05:30', source: 'statement', freshness: 'fresh' },
    { bank_account_id: 'b', account_name: 'SBI Current - Collections', account_mask: 'XXXXXXX0937', balance_paise: 51894934, as_of: '2026-11-20T18:30:00+05:30', source: 'statement', freshness: 'fresh' },
  ],
}

function forecastFor(view: string) {
  const g = golden.views[view]
  const keys = [
    'minimum_closing_paise', 'minimum_date', 'first_reserve_breach_date', 'first_negative_date', 'days_below_reserve',
    'total_inflow_paise', 'total_outflow_paise', 'closing_paise', 'beyond_horizon_inflow_paise', 'beyond_horizon_outflow_paise',
  ]
  const metrics: Record<string, unknown> = Object.fromEntries(keys.map(k => [k, g[k]]))
  metrics.runway_days = g.first_negative_date
    ? (Date.parse(g.first_negative_date) - Date.parse(SNAP.start)) / 86400000
    : null
  return { view, opening_paise: g.opening_paise, reserve_paise: g.reserve_paise, days: g.days, metrics, category_totals: golden.category_totals[view], snapshot: SNAP }
}

function dayFor(view: string, date: string) {
  const evs = golden.events
    .filter(e => e.date === date && e.views.includes(view))
    .map(e => ({
      event_key: e.event_key, source_type: e.source_type, source_id: e.source_id, label: e.label, counterparty: e.counterparty,
      counterparty_id: null, document_number: null, direction: e.direction, amount_paise: e.amount_paise, category: e.category,
      confidence: e.confidence, date: e.date, date_basis: e.date_basis, tds_note: null, nominal_date: null,
      window: e.payment_window ? { ...e.payment_window, agreed_with: null, evidence: null } : null,
      fixed: ['payroll', 'statutory', 'debt'].includes(e.category) || e.source_type === 'disbursement',
      link_path: null, moved_by_scenario: false,
    }))
    .sort((a, b) => b.amount_paise - a.amount_paise)
  const row = golden.views[view].days.find(d => d.date === date)
  return { day: row, inflows: evs.filter(e => e.direction === 'in'), outflows: evs.filter(e => e.direction === 'out') }
}

const json = (body: unknown, status = 200) => Promise.resolve(new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }))

function mockApi(role: 'accountant' | 'auditor', overrides: Partial<Record<string, (init?: RequestInit) => Promise<Response>>> = {}) {
  const can = role === 'auditor' ? { view: true, edit: false, approve: false, settings: false } : { view: true, edit: true, approve: false, settings: false }
  const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), 'http://x')
    const path = url.pathname.replace('/api/finance-desk/cash-forecast', '')
    if (overrides[path]) return overrides[path]!(init)
    if (path === '/me') return json({ actor: role, role, can })
    if (path === '/snapshots/latest') return json(SNAP)
    if (path === '/forecast') return json(forecastFor(url.searchParams.get('view') ?? 'expected'))
    if (path.startsWith('/days/')) {
      const body = JSON.parse(String(init?.body ?? '{}')) as { view: string }
      return json(dayFor(body.view, path.slice(6)))
    }
    if (path === '/events') return json([])
    if (path === '/scenarios' || path === '/plans') return json([])
    return json({ code: 'NOT_FOUND', message: 'not mocked' }, 404)
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

function renderPage(url = '/finance-desk/cash-forecast') {
  return render(
    <MemoryRouter initialEntries={[url]}>
      <CashForecastPage />
    </MemoryRouter>,
  )
}

afterEach(() => vi.unstubAllGlobals())

describe('format helpers', () => {
  it('rounds sentences half up, keeps paise in the ledger and uses lakh/crore in KPIs', () => {
    expect(rupees(487043184)).toBe('₹48,70,432')
    expect(exact(487043184)).toBe('48,70,431.84')
    expect(compact(487043184)).toBe('₹48.70 L')
    expect(compact(2225665100)).toBe('₹2.23 Cr')
    expect(rupees(-324406426)).toBe('−₹32,44,064')
    expect(toPaise('43,51,482.50')).toBe(435148250)
  })
})

describe('CashForecastPage', () => {
  it('answers the question in one sentence and shows the evidence', async () => {
    mockApi('accountant')
    renderPage()
    expect(await screen.findByText('Cash drops to ₹9,99,874 on Mon 30 Nov, ₹5,00,126 below your ₹15,00,000 reserve.')).toBeInTheDocument()
    expect(within(screen.getByTestId('kpi-Cash today')).getByText('₹48.70 L')).toBeInTheDocument()
    expect(within(screen.getByTestId('kpi-Lowest')).getByText('₹10.00 L')).toBeInTheDocument()
    expect(within(screen.getByTestId('kpi-First breach')).getByText('Mon 30 Nov')).toBeInTheDocument()
    expect(within(screen.getByTestId('kpi-CC headroom')).getByText('₹40.00 L')).toBeInTheDocument()
    await waitFor(() => expect(within(screen.getByTestId('kpi-Runway, no collections')).getByText('5 days')).toBeInTheDocument())
    // The line under the sentence names what lands on the lowest day.
    expect(await screen.findByText(/land the same day\./)).toHaveTextContent('Six supplier bills (₹22.66 L), Salaries (₹21.80 L) and Annual insurance renewal - stock and fleet (₹6.85 L) land the same day.')
  })

  it('shows exact paise in the ledger so every row reconciles', async () => {
    mockApi('accountant')
    renderPage()
    const table = await screen.findByRole('table', { name: /Daily opening/ })
    const rows = within(table).getAllByRole('row').slice(1)
    expect(rows).toHaveLength(golden.views.expected.days.filter(d => d.banking_day).length)
    for (const row of rows) {
      const [open, inflow, outflow, close] = within(row).getAllByRole('cell').slice(0, 4).map(c => c.textContent ?? '')
      const p = (s: string) => (s === '—' ? 0 : toPaise(s)!)
      expect(p(open) + p(inflow) - p(outflow)).toBe(p(close.replace(/[^\d.,]/g, '')))
    }
    const payday = rows.find(r => r.textContent?.includes('Mon 30 Nov'))!
    expect(payday).toHaveTextContent('42,83,944.24')
    expect(payday).toHaveTextContent('9,99,874.24')
    expect(payday).toHaveTextContent('Below')
  })

  it('switches view on the same snapshot', async () => {
    const fetchMock = mockApi('accountant')
    renderPage()
    await screen.findByText(/Cash drops to/)
    fireEvent.click(screen.getByRole('radio', { name: 'Downside' }))
    expect(await screen.findByText('Cash runs out on Mon 30 Nov. Lowest −₹32,44,064 on Mon 30 Nov.')).toBeInTheDocument()
    expect(fetchMock.mock.calls.some(([u]) => String(u).includes('view=downside') && String(u).includes('snapshot_id=snap-1'))).toBe(true)
  })

  it('opens a day and explains a refused change in words', async () => {
    mockApi('accountant', {
      '/forecast/preview': () =>
        json(
          {
            code: 'OVERRIDE_REFUSED',
            message: "1 change can't be applied.",
            details: {
              refusals: [{ index: 0, code: 'OUTSIDE_PAYMENT_WINDOW', message: 'Raigad Kraft Paper Mills agreed to payment no later than 2 Dec 2026.', details: {} }],
            },
          },
          422,
        ),
    })
    renderPage('/finance-desk/cash-forecast?day=2026-11-30')
    const drawer = await screen.findByRole('dialog', { name: /Mon 30 Nov/ })
    const raigad = (await within(drawer).findByText(/RAI\/2610\/203/)).closest('li')!
    expect(within(raigad).getByText('Window to 2 Dec')).toBeInTheDocument()
    fireEvent.click(within(raigad).getByRole('button', { name: 'Move' }))
    const date = within(drawer).getByLabelText('New date')
    // The picker stops at the agreed window; the server refuses it too if it gets through.
    expect(date).toHaveAttribute('max', '2026-12-02')
    fireEvent.change(date, { target: { value: '2026-12-03' } })
    fireEvent.submit(date.closest('form')!)
    expect(await screen.findByText('Raigad Kraft Paper Mills agreed to payment no later than 2 Dec 2026.', {}, { timeout: 2000 })).toBeInTheDocument()
    expect(screen.getByText('DECISION')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Submit as plan/ })).toBeDisabled()
  })

  it('gives an auditor a read-only page', async () => {
    mockApi('auditor')
    renderPage('/finance-desk/cash-forecast?day=2026-11-30')
    const drawer = await screen.findByRole('dialog', { name: /Mon 30 Nov/ })
    await within(drawer).findByText(/RAI\/2610\/203/)
    expect(within(drawer).queryByRole('button', { name: 'Move' })).toBeNull()
    expect(screen.queryByRole('button', { name: /Refresh/ })).toBeNull()
    expect(screen.queryByRole('button', { name: /New scenario/ })).toBeNull()
  })

  it('asks for a balance when there is none', async () => {
    mockApi('accountant', {
      '/snapshots/latest': () => json({ code: 'NO_OPENING_BALANCE', message: "Add today's bank balance to see your forecast.", details: {} }, 422),
      '/accounts': () => json([]),
    })
    renderPage()
    expect(await screen.findByText('Add today’s bank balance to see your forecast.')).toBeInTheDocument()
    expect(screen.getByRole('form', { name: 'Add a bank balance' })).toBeInTheDocument()
  })
})
