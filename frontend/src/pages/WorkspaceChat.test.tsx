import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import { ConversationProvider, WorkspaceChat } from './WorkspaceChat'

afterEach(() => vi.unstubAllGlobals())

it('sends a document and reply language and retains context for a follow-up', async () => {
  const fetcher = vi.fn().mockImplementation(async () => Response.json({
    message: 'Checked the bill.', context_id: 'turn-one',
    sources: [{ id: 'S1', title: 'Bill details', domain: 'bills', path: '/bills/123', values: {} }],
  }))
  vi.stubGlobal('fetch', fetcher)
  render(<MemoryRouter><ConversationProvider><WorkspaceChat /></ConversationProvider></MemoryRouter>)
  fireEvent.change(screen.getByLabelText('Reply language'), {target: {value: 'Hindi'}})
  const file = new File(['invoice_total\n15'], 'invoice.csv', {type: 'text/csv'})
  fireEvent.change(screen.getByLabelText('Attach a finance document'), {target: {files: [file]}})
  fireEvent.click(screen.getByLabelText('Send message'))
  await screen.findByText('Checked the bill.')
  fireEvent.click(screen.getByText('Sources (1)'))
  expect(screen.getByRole('link', {name: /Bill details/})).toHaveAttribute('href', '/bills/123')
  const data = fetcher.mock.calls[0][1].body as FormData
  expect((data.get('document') as File).name).toBe('invoice.csv')
  const first = JSON.parse(String(data.get('payload')))
  expect(first.language).toBe('Hindi')
  fireEvent.change(screen.getByLabelText('Message Reckon Copilot'), {target: {value: 'Explain that difference'}})
  fireEvent.click(screen.getByLabelText('Send message'))
  expect(JSON.parse(fetcher.mock.calls[1][1].body.get('payload'))).toMatchObject({
    question: 'Explain that difference', context_id: 'turn-one', previous_questions: [first.question],
  })
  await screen.findAllByText('Checked the bill.')
})

it('links inline citations and carries the selected bill into the next turn', async () => {
  const fetcher = vi.fn().mockImplementation(async () => Response.json({
    message: 'Review this bill [S1].', context_id: 'queue', more_bills: true,
    sources: [{id: 'S1', title: 'INV-1', domain: 'approvals', path: '/bills/123', values: {stage:'Pending'}}],
  }))
  vi.stubGlobal('fetch', fetcher)
  render(<MemoryRouter><ConversationProvider><WorkspaceChat /></ConversationProvider></MemoryRouter>)
  fireEvent.click(screen.getByRole('button', {name: 'Which bills need attention?'}))
  expect(await screen.findByRole('link', {name: 'Open INV-1'})).toHaveAttribute('href','/bills/123')
  fireEvent.click(screen.getByText('Sources (1)'))
  fireEvent.click(screen.getByRole('button', {name:'Review bill history'}))
  expect(JSON.parse(fetcher.mock.calls[1][1].body.get('payload')).bill_id).toBe('123')
  await screen.findAllByText('Sources (1)')
})
