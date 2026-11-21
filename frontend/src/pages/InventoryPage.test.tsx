import { act, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import InventoryPage from './InventoryPage'

vi.mock('../auth/AuthContext', () => ({ useAuth: () => ({ user: { company_id: 'tenant' } }) }))
afterEach(() => vi.unstubAllGlobals())

it('filters invoice lines by vendor and allocates billed units once', async () => {
  const line = { id: 'line-a', supplier_id: 'a', supplier: 'Vendor A', item: 'Cable',
    bill_date: '2026-09-08', unit: 'm', billed_units: '8.75', price: '42.50', payment_terms_days: 30 }
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () =>
    [line, { ...line, id: 'line-b', supplier_id: 'b', supplier: 'Vendor B', item: 'Pipe' }] }))
  render(<InventoryPage />)
  const vendor = await screen.findByLabelText('Vendor')
  const item = screen.getByLabelText('Invoice line item')
  expect(item).toBeDisabled()
  fireEvent.click(vendor)
  fireEvent.click(screen.getByRole('option', { name: 'Vendor A' }))
  expect(within(item).queryByRole('option', { name: /Pipe/ })).toBeNull()
  fireEvent.change(item, { target: { value: 'line-a' } })
  expect(screen.getByLabelText('Stock on hand')).toHaveValue(8.75)
  expect(screen.getByLabelText(/Unit rate/)).toHaveValue(42.5)
  fireEvent.change(screen.getByLabelText('Use billed quantity as'), { target: { value: 'inbound' } })
  expect(screen.getByLabelText('Stock on hand')).toHaveValue(null)
  expect(screen.getByLabelText(/Firm inbound units/)).toHaveValue(8.75)
  fireEvent.click(vendor)
  const search = screen.getByRole('combobox', { name: 'Search vendors' })
  fireEvent.change(search, { target: { value: 'vendor b' } })
  fireEvent.keyDown(search, { key: 'Enter' })
  expect(screen.queryByLabelText('Stock on hand')).toBeNull()
})

it('clears the current recommendation and ignores responses for an earlier bill line', async () => {
  const line = { id: 'first', supplier_id: 'v', supplier: 'Vendor', item: 'Cable', bill_date: '2026-09-08',
    unit: 'm', billed_units: 10, price: 20, payment_terms_days: 30 }
  const projection = { units: 2, spend_paise: 4000, remaining_paise: 0, additional_demand_covered: 2,
    price_basis: 'historical', reasons: [], days: [
      { date: '2026-11-21', incoming: 0, closing: 1, unmet: 0, no_order_closing: 1 },
      { date: '2026-11-22', incoming: 2, closing: 2, unmet: 0, no_order_closing: 0 },
    ] }
  let finish!: (value: Response) => void
  vi.stubGlobal('fetch', vi.fn()
    .mockResolvedValueOnce(Response.json([line, { ...line, id: 'second', item: 'Wire' }]))
    .mockResolvedValueOnce(Response.json(projection))
    .mockReturnValueOnce(new Promise<Response>(resolve => { finish = resolve })))
  render(<InventoryPage />)
  fireEvent.click(await screen.findByRole('button', { name: 'Select Vendor, 2 invoice lines' }))
  const picker = screen.getByLabelText('Invoice line item')
  fireEvent.change(picker, { target: { value: 'first' } })
  fireEvent.submit(screen.getByText('Optimize stock order').closest('form')!)
  await screen.findByRole('region', { name: 'Recommended order' })
  const day = screen.getByRole('button', { name: /without order 0, with order 2 m/ })
  fireEvent.click(day)
  expect(day).toHaveAttribute('aria-pressed', 'true')
  expect(screen.getByText(/2 on hand at close/)).toBeInTheDocument()
  fireEvent.change(picker, { target: { value: 'second' } })
  expect(screen.queryByRole('region', { name: 'Recommended order' })).toBeNull()
  fireEvent.submit(screen.getByText('Optimize stock order').closest('form')!)
  fireEvent.click(screen.getByLabelText('Vendor'))
  fireEvent.click(screen.getByRole('button', { name: 'Clear selection' }))
  await act(async () => finish(Response.json(projection)))
  expect(screen.queryByRole('region', { name: 'Recommended order' })).toBeNull()
})

it('allows a failed price lookup to be retried and handles an empty tenant', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce(new Response(null, { status: 503 }))
    .mockResolvedValueOnce(Response.json([])))
  render(<InventoryPage />)
  expect(await screen.findByRole('alert')).toHaveTextContent('Unable to load supplier prices')
  fireEvent.click(screen.getByRole('button', { name: 'Retry' }))
  expect(await screen.findByText(/No priced INR bill lines/)).toBeInTheDocument()
  expect(screen.queryByLabelText('Vendor')).toBeNull()
  expect(screen.queryByRole('region', { name: 'Recommended order' })).toBeNull()
})
