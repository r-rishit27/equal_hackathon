import { fireEvent, render, screen, within } from '@testing-library/react'
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
