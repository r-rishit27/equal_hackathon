import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { expect, it, vi } from 'vitest'
import WorkspaceSearch from './WorkspaceSearch'

vi.mock('../auth/AuthContext', () => ({
  useAuth: () => ({ user: { role: 'admin' } }),
}))

vi.mock('../auth/EntitlementsContext', () => ({
  useEntitlements: () => ({ has: (service: string) => ['bills', 'receivables', 'upload_ocr'].includes(service) }),
}))

it('opens with the search field focused and routes to a licensed result from the keyboard', async () => {
  const user = userEvent.setup()
  render(<MemoryRouter initialEntries={['/bills']}>
    <WorkspaceSearch />
    <Routes>
      <Route path="/receivables/invoices" element={<h1>Sales invoices page</h1>} />
      <Route path="/bills" element={<h1>Bills page</h1>} /></Routes>
  </MemoryRouter>)

  await user.keyboard('{Control>}k{/Control}')
  const dialog = screen.getByRole('dialog', { name: 'Search workspace' })
  const input = within(dialog).getByRole('searchbox')
  expect(input).toHaveFocus()
  expect(within(dialog).queryByRole('button', { name: 'Reckon Copilot' })).toBeNull()
  await user.type(input, 'sales invoices')
  expect(input).toHaveFocus()
  expect(within(dialog).getByRole('button', { name: 'Upload Sales Invoices' })).toBeVisible()
  await user.keyboard('{Enter}')
  expect(screen.queryByRole('dialog')).toBeNull()
  expect(screen.getByRole('heading', { name: 'Sales invoices page' })).toBeVisible()
})

it('reports no matches and restores focus on Escape', async () => {
  const user = userEvent.setup()
  render(<MemoryRouter><WorkspaceSearch /></MemoryRouter>)
  const trigger = screen.getByRole('button', { name: 'Search workspace' })
  await user.click(trigger)
  await user.type(screen.getByRole('searchbox'), 'nova')
  expect(screen.getByRole('status')).toHaveTextContent('No matching pages')
  await user.keyboard('{Escape}')
  expect(trigger).toHaveFocus()
})
