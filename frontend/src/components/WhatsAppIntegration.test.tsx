import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import axios from 'axios'
import { afterEach, expect, it, vi } from 'vitest'
import { ToastProvider } from '../ui'
import WhatsAppIntegration from './WhatsAppIntegration'

afterEach(() => { cleanup(); vi.restoreAllMocks() })

it('opens an existing sender without writing credentials or changing intake', async () => {
  const put = vi.spyOn(axios, 'put')
  const patch = vi.spyOn(axios, 'patch')
  const remove = vi.spyOn(axios, 'delete')
  vi.spyOn(axios, 'get').mockResolvedValue({ data: { worker_enabled: true, connection: {
    state: 'ACTIVE', sender: '+15550123', account_sid: 'AC...1234', inbound_enabled: true,
    outbound_enabled: true, webhook_url: '/example/inbound', status_callback_url: '/example/status',
  } } })
  render(<ToastProvider><WhatsAppIntegration /></ToastProvider>)
  await screen.findByText('Active')
  expect(screen.getByText('/example/inbound')).not.toBeVisible()
  await userEvent.click(screen.getByRole('button', { name: 'WhatsApp (Twilio)' }))
  expect(screen.getByRole('switch', { name: 'Process incoming invoices' })).toBeChecked()
  expect(screen.getByText('/example/inbound')).toBeVisible()
  expect(screen.getByText('/example/status')).toBeVisible()
  expect(screen.queryByLabelText('Auth token')).toBeNull()
  await userEvent.click(screen.getByRole('button', { name: 'Disconnect' }))
  expect(screen.getByText('Disconnect WhatsApp?')).toBeVisible()
  expect(put).not.toHaveBeenCalled()
  expect(patch).not.toHaveBeenCalled()
  expect(remove).not.toHaveBeenCalled()
})

it('submits new tenant credentials only after explicit setup', async () => {
  vi.spyOn(axios, 'get').mockResolvedValue({ data: { connection: null } })
  const put = vi.spyOn(axios, 'put').mockResolvedValue({ data: {} })
  render(<ToastProvider><WhatsAppIntegration /></ToastProvider>)
  await userEvent.click(screen.getByRole('button', { name: 'WhatsApp (Twilio)' }))
  await userEvent.type(await screen.findByLabelText('Account SID'), 'AC-example')
  const token = screen.getByLabelText('Auth token')
  expect(token).toHaveAttribute('type', 'password')
  await userEvent.type(token, 'example')
  await userEvent.type(screen.getByLabelText('WhatsApp sender'), '+15550123')
  await userEvent.click(screen.getByRole('button', { name: 'Connect Twilio' }))
  expect(put).toHaveBeenCalledWith('/api/agent/whatsapp/connection', {
    use_server_credentials: false, account_sid: 'AC-example', auth_token: 'example', sender: '+15550123',
  })
  expect(token).toHaveValue('')
})
