import { act, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import { fetchEntitlements } from '../api/entitlements'
import { EntitlementsProvider, useEntitlements } from './EntitlementsContext'
import { normalizeEntitlements } from './entitlements'

const identity = vi.hoisted(() => ({ company_id: 'full-tenant' }))
vi.mock('./AuthContext', () => ({ useAuth: () => ({ user: identity }) }))
vi.mock('../api/entitlements', () => ({ fetchEntitlements: vi.fn() }))

function Access() {
  const { has, status } = useEntitlements()
  return <output>{status} {has('fact_graph') ? 'Copilot available' : 'Copilot hidden'}</output>
}

beforeEach(() => {
  sessionStorage.clear()
  identity.company_id = 'full-tenant'
  vi.resetAllMocks()
})

it('hides the previous tenant’s features as soon as the workspace changes', async () => {
  const full = normalizeEntitlements({ company_id: 'full-tenant', services: { fact_graph: { enabled: true } } })
  const core = normalizeEntitlements({ company_id: 'core-tenant', services: { bills: { enabled: true } } })
  let resolveCore!: (plan: typeof core) => void
  vi.mocked(fetchEntitlements).mockResolvedValueOnce(full).mockImplementationOnce(
    () => new Promise(resolve => { resolveCore = resolve }),
  )

  const { rerender } = render(<EntitlementsProvider><Access /></EntitlementsProvider>)
  await screen.findByText('ready Copilot available')
  identity.company_id = 'core-tenant'
  rerender(<EntitlementsProvider><Access /></EntitlementsProvider>)
  expect(screen.getByText('loading Copilot hidden')).toBeVisible()
  await act(async () => resolveCore(core))
  expect(screen.getByText('ready Copilot hidden')).toBeVisible()
})

it('rejects a response for a different tenant', async () => {
  vi.mocked(fetchEntitlements).mockResolvedValue(normalizeEntitlements({
    company_id: 'another-tenant', services: { fact_graph: { enabled: true } },
  }))
  render(<EntitlementsProvider><Access /></EntitlementsProvider>)
  await waitFor(() => expect(screen.getByText('error Copilot hidden')).toBeVisible())
})
