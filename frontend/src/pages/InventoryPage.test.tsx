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
  fireEvent.change(vendor, { target: { value: 'a' } })
  expect(within(item).queryByRole('option', { name: /Pipe/ })).toBeNull()
  fireEvent.change(item, { target: { value: 'line-a' } })
  expect(screen.getByLabelText('Stock on hand')).toHaveValue(8.75)
  expect(screen.getByLabelText(/Unit rate/)).toHaveValue(42.5)
  fireEvent.change(screen.getByLabelText('Use billed quantity as'), { target: { value: 'inbound' } })
  expect(screen.getByLabelText('Stock on hand')).toHaveValue(null)
  expect(screen.getByLabelText(/Firm inbound units/)).toHaveValue(8.75)
  fireEvent.change(vendor, { target: { value: 'b' } })
  expect(screen.queryByLabelText('Stock on hand')).toBeNull()
})

it('clears the current recommendation and ignores responses for an earlier bill line', async () => {
  const line = { id: 'first', supplier_id: 'v', supplier: 'Vendor', item: 'Cable', bill_date: '2026-09-08',
    unit: 'm', billed_units: 10, price: 20, payment_terms_days: 30 }
  const projection = { units: 2, spend_paise: 4000, remaining_paise: 0, additional_demand_covered: 2,
    price_basis: 'historical', reasons: [], days: [] }
  let finish!: (value: Response) => void
  vi.stubGlobal('fetch', vi.fn()
    .mockResolvedValueOnce(Response.json([line, { ...line, id: 'second', item: 'Wire' }]))
    .mockResolvedValueOnce(Response.json(projection))
    .mockReturnValueOnce(new Promise<Response>(resolve => { finish = resolve })))
  render(<InventoryPage />)
  fireEvent.change(await screen.findByLabelText('Vendor'), { target: { value: 'v' } })
  const picker = screen.getByLabelText('Invoice line item')
  fireEvent.change(picker, { target: { value: 'first' } })
  fireEvent.submit(screen.getByText('Optimize stock order').closest('form')!)
  await screen.findByRole('region', { name: 'Recommended order' })
  fireEvent.change(picker, { target: { value: 'second' } })
  expect(screen.queryByRole('region', { name: 'Recommended order' })).toBeNull()
  fireEvent.submit(screen.getByText('Optimize stock order').closest('form')!)
  fireEvent.change(screen.getByLabelText('Vendor'), { target: { value: '' } })
  await act(async () => finish(Response.json(projection)))
  expect(screen.queryByRole('region', { name: 'Recommended order' })).toBeNull()
})
