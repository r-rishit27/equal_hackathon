/**
 * Client for /api/finance-desk/cash-forecast. Plain fetch: window.fetch is
 * patched app-wide (api/invoices.ts) to attach the session token.
 */
import type {
  Account, Adjustment, DayDetail, Exclusion, Forecast, Me, Override, Plan, Preview, PromiseRow, RecurringItem,
  Scenario, Settings, SnapshotRef, View, WindowRow, CashEvent,
} from './types'

export const BASE = (import.meta.env.VITE_API_URL ?? '') + '/api/finance-desk/cash-forecast'

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public details: Record<string, unknown> = {},
  ) {
    super(message)
  }
}

async function request<T>(path: string, init: RequestInit & { json?: unknown } = {}): Promise<T> {
  const { json, headers, ...rest } = init
  const response = await fetch(BASE + path, {
    ...rest,
    headers: { ...(json !== undefined ? { 'Content-Type': 'application/json' } : {}), ...(headers ?? {}) },
    body: json !== undefined ? JSON.stringify(json) : rest.body,
  })
  if (response.status === 204) return undefined as T
  let body: unknown = null
  try {
    body = await response.json()
  } catch {
    /* empty or non-JSON body */
  }
  if (!response.ok) {
    const b = (body ?? {}) as { code?: string; message?: string; details?: Record<string, unknown>; detail?: unknown }
    const fallback =
      response.status === 403
        ? 'Cash forecast is available to finance roles.'
        : typeof b.detail === 'string'
          ? b.detail
          : Array.isArray(b.detail)
            ? 'Check the highlighted values and try again.'
            : 'Something went wrong. Try again.'
    throw new ApiError(
      response.status,
      b.code ?? (response.status === 403 ? 'INSUFFICIENT_ROLE' : response.status === 422 ? 'VALIDATION_ERROR' : 'ERROR'),
      b.message ?? fallback,
      b.details ?? {},
    )
  }
  return body as T
}

const q = (params: Record<string, string>) => '?' + new URLSearchParams(params).toString()

export const api = {
  me: () => request<Me>('/me'),
  latest: () => request<SnapshotRef>('/snapshots/latest'),
  refresh: () => request<SnapshotRef>('/snapshots', { method: 'POST' }),
  forecast: (snapshotId: string, view: View) => request<Forecast>('/forecast' + q({ snapshot_id: snapshotId, view })),
  preview: (snapshotId: string, revision: number, view: View, overrides: Override[], signal?: AbortSignal) =>
    request<Preview>('/forecast/preview', {
      method: 'POST',
      json: { snapshot_id: snapshotId, revision, view, overrides },
      signal,
    }),
  day: (snapshotId: string, view: View, date: string, overrides: Override[]) =>
    request<DayDetail>(`/days/${date}`, { method: 'POST', json: { snapshot_id: snapshotId, view, overrides } }),
  events: (snapshotId: string, view: View) => request<CashEvent[]>('/events' + q({ snapshot_id: snapshotId, view })),
  exclusions: (snapshotId: string) => request<Exclusion[]>('/exclusions' + q({ snapshot_id: snapshotId })),
  exportUrl: (snapshotId: string, view: View) => BASE + '/export.csv' + q({ snapshot_id: snapshotId, view }),

  scenarios: () => request<Scenario[]>('/scenarios'),
  scenario: (id: string) => request<Scenario>(`/scenarios/${id}`),
  createScenario: (body: { name: string; snapshot_id: string; view: View; overrides: Override[]; description?: string }) =>
    request<Scenario>('/scenarios', { method: 'POST', json: body }),
  updateScenario: (
    id: string,
    body: { name: string; snapshot_id: string; view: View; overrides: Override[]; expected_version: number },
  ) => request<Scenario>(`/scenarios/${id}`, { method: 'PATCH', json: body }),
  deleteScenario: (id: string) => request<void>(`/scenarios/${id}`, { method: 'DELETE' }),

  plans: (state?: string) => request<Plan[]>('/plans' + (state ? q({ state }) : '')),
  plan: (id: string) => request<Plan>(`/plans/${id}`),
  createPlan: (scenarioId: string, note: string) =>
    request<Plan>('/plans', { method: 'POST', json: { scenario_id: scenarioId, note, submit: true } }),
  withdrawPlan: (id: string, version: number) =>
    request<Plan>(`/plans/${id}/withdraw`, { method: 'POST', json: { expected_version: version } }),
  decide: (id: string, decision: 'approve' | 'return', version: number, note: string, key: string) =>
    request<{ plan: Plan; decision: string; validated_on_revision: number }>(`/plans/${id}/decision`, {
      method: 'POST',
      json: { decision, expected_version: version, note: note || null },
      headers: { 'Idempotency-Key': key },
    }),

  settings: () => request<Settings>('/settings'),
  saveSettings: (body: Partial<Settings>) => request<Settings>('/settings', { method: 'PUT', json: body }),
  accounts: () => request<Account[]>('/accounts'),
  patchAccount: (id: string, body: { include_in_forecast?: boolean; od_limit_paise?: number }) =>
    request<Account>(`/accounts/${id}`, { method: 'PATCH', json: body }),
  addBalance: (bankAccountId: string, balancePaise: number, asOf: string) =>
    request<{ id: string }>('/balances', {
      method: 'POST',
      json: { bank_account_id: bankAccountId, balance_paise: balancePaise, as_of: asOf },
    }),
  recurring: () => request<RecurringItem[]>('/recurring'),
  createRecurring: (body: Omit<RecurringItem, 'id' | 'version'>) =>
    request<RecurringItem>('/recurring', { method: 'POST', json: body }),
  updateRecurring: (id: string, body: Omit<RecurringItem, 'id' | 'version'> & { expected_version: number }) =>
    request<RecurringItem>(`/recurring/${id}`, { method: 'PATCH', json: body }),
  deleteRecurring: (id: string) => request<void>(`/recurring/${id}`, { method: 'DELETE' }),
  seedTemplates: () => request<RecurringItem[]>('/setup/seed-templates', { method: 'POST' }),
  adjustments: () => request<Adjustment[]>('/adjustments'),
  createAdjustment: (body: Omit<Adjustment, 'id' | 'plan_id'>) =>
    request<Adjustment>('/adjustments', { method: 'POST', json: body }),
  deleteAdjustment: (id: string) => request<void>(`/adjustments/${id}`, { method: 'DELETE' }),
  windows: () => request<WindowRow[]>('/payment-windows'),
  createWindow: (body: { invoice_id: string; latest_date: string; agreed_with: string; evidence: string }) =>
    request<{ id: string }>('/payment-windows', { method: 'POST', json: body }),
  deleteWindow: (id: string) => request<void>(`/payment-windows/${id}`, { method: 'DELETE' }),
  promises: () => request<PromiseRow[]>('/promises'),
  createPromise: (body: {
    invoice_id: string
    promised_date: string
    promised_amount_paise: number
    source: string
    note?: string
  }) => request<{ id: string }>('/promises', { method: 'POST', json: body }),
  deletePromise: (id: string) => request<void>(`/promises/${id}`, { method: 'DELETE' }),
}

/** A bill row's invoice id: schedule events carry the bill in their link path. */
export function billIdOf(e: CashEvent): string | null {
  if (e.source_type === 'bill') return e.source_id
  const m = e.link_path?.match(/^\/bills\/([^/?]+)/)
  return m ? m[1] : null
}
