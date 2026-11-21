import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import { ApprovalAssistant as CopilotPage } from './CopilotPage'

vi.mock('../auth/AuthContext', () => ({ useAuth: () => ({ user: { company_id: 'a', username: 'u', role: 'approver' } }) }))
afterEach(() => vi.unstubAllGlobals())

it('opens a cited bill and scopes a follow-up to that bill', async () => {
  const fetcher = vi.fn().mockImplementation(() => Promise.resolve(Response.json({
    answer: 'One pending bill.', partial: false, evidence: [{
      id: 'bill-id', citation: 'B1', invoice_number: 'INV-1', stage: 'Controller', step_role: 'finance_controller',
      supplier: 'Supplier', graph_link: true, latest_action: 'submit', action_at: null, due_date: null,
    }],
  })))
  vi.stubGlobal('fetch', fetcher)
  render(<MemoryRouter><CopilotPage /></MemoryRouter>)
  fireEvent.click(screen.getByText('Which bills are in my approval queue?'))
  expect(await screen.findByRole('link', { name: /INV-1/ })).toHaveAttribute('href', '/bills/bill-id')
  fireEvent.click(screen.getByText('Focus on bill'))
  expect(JSON.parse(fetcher.mock.lastCall![1].body)).toEqual({
    question: 'Show supplier relationships for pending bills.', bill_id: 'bill-id',
  })
  await screen.findByRole('link', { name: /INV-1/ })
})

it('shows a safe access-denied response', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(null, { status: 403 })))
  render(<MemoryRouter><CopilotPage /></MemoryRouter>)
  fireEvent.click(screen.getByText('Which pending bills are overdue?'))
  expect(await screen.findByRole('alert')).toHaveTextContent('does not have approval Copilot access')
  expect(screen.queryByRole('link')).toBeNull()
})
