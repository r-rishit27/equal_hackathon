import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import axios from 'axios'
import { afterEach, expect, it, vi } from 'vitest'
import AgentHubPage from './AgentHubPage'
import { ToastProvider } from '../ui'

const session = vi.hoisted(() => ({ role: 'admin' }))
vi.mock('../auth/AuthContext', () => ({ useAuth: () => ({ user: session, activeBrand: null }) }))
vi.mock('../auth/EntitlementsContext', () => ({ useEntitlements: () => ({ has: () => true }) }))
vi.mock('../components/InvoiceProcessing', () => ({ default: () => null }))

afterEach(() => { cleanup(); vi.restoreAllMocks(); session.role = 'admin' })

function open(connected = true) {
  const connection = { id: 'sender', state: 'ACTIVE', inbound_enabled: true, outbound_enabled: true }
  vi.spyOn(axios, 'get').mockImplementation(async url => ({ data: url.endsWith('/status')
    ? { connection: connected ? connection : null, worker_enabled: true, queue: {} }
    : [] }))
  const patch = vi.spyOn(axios, 'patch').mockResolvedValue({ data: {
    connection: { ...connection, inbound_enabled: false }, backlog_changed: 0,
  } })
  render(<MemoryRouter><ToastProvider><AgentHubPage /></ToastProvider></MemoryRouter>)
  return patch
}

it('pauses only inbound processing and updates the detail panel after the server confirms', async () => {
  const patch = open()
  const toggle = screen.getByRole('switch', { name: 'WhatsApp intake' })
  await waitFor(() => expect(toggle).toBeChecked())
  await userEvent.click(toggle)
  expect(patch).toHaveBeenCalledWith('/api/agent/whatsapp/settings', { inbound_enabled: false })
  expect(toggle).not.toBeChecked()
  expect(screen.queryByText('Status callback URL')).toBeNull()
  expect(screen.getByRole('link', { name: 'Manage connection' })).toHaveAttribute('href', '/integrations#whatsapp')
})

it('directs an unconnected workspace to setup and disables intake', async () => {
  open(false)
  await screen.findByRole('link', { name: 'Connection setup' })
  expect(screen.getByRole('switch', { name: 'WhatsApp intake' })).toBeDisabled()
})

it('shows the saved setting read-only for non-admins', async () => {
  session.role = 'accountant'
  open()
  const toggle = screen.getByRole('switch', { name: 'WhatsApp intake' })
  await waitFor(() => expect(toggle).toBeChecked())
  expect(toggle).toBeDisabled()
})
