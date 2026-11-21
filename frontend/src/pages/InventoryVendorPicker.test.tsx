import { fireEvent, render, screen } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import InventoryVendorPicker from './InventoryVendorPicker'

it('handles duplicate vendor names, empty searches, cancellation and keyboard selection', () => {
  const choose = vi.fn()
  render(<InventoryVendorPicker vendors={[['a11111111', 'Same vendor'], ['b22222222', 'Same vendor']]}
    selected="" onSelect={choose} />)
  const trigger = screen.getByLabelText('Vendor')
  fireEvent.click(trigger)
  let input = screen.getByRole('combobox')
  expect(input).toHaveFocus()
  expect(screen.getAllByRole('option')).toHaveLength(2)
  expect(screen.getByText(/22222222/)).toBeInTheDocument()
  fireEvent.change(input, { target: { value: 'missing vendor' } })
  expect(screen.getByRole('status')).toHaveTextContent('No matching vendors')
  fireEvent.keyDown(input, { key: 'Enter' })
  expect(choose).not.toHaveBeenCalled()
  fireEvent.keyDown(input, { key: 'Escape' })
  expect(trigger).toHaveFocus()
  fireEvent.click(trigger)
  input = screen.getByRole('combobox')
  fireEvent.keyDown(input, { key: 'ArrowDown' })
  fireEvent.keyDown(input, { key: 'Enter' })
  expect(choose).toHaveBeenCalledWith('b22222222')
  expect(screen.queryByRole('listbox')).toBeNull()
})
