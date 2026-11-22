import axios from 'axios'

// WhatsApp Agent — docs/whatsapp-agent/03-lld.md §7. Tenant comes from the JWT;
// brand_id only narrows vendor-scoped rows to the brand picked in the top bar.

export type WaConnectionState = 'AWAITING_TEST' | 'ACTIVE' | 'PAUSED' | 'NEEDS_ATTENTION' | 'DISCONNECTED'

export interface WaConnection {
  id: string
  state: WaConnectionState
  account_sid: string
  sender: string
  uses_server_credentials: boolean
  inbound_enabled: boolean
  outbound_enabled: boolean
  signature_failures: number
  last_inbound_at: string | null
  last_processed_at: string | null
  webhook_url: string
  status_callback_url: string
}

export interface WaStatus {
  agent: 'whatsapp_agent'
  connection: WaConnection | null
  server_credentials_available: boolean
  server_sender: string | null
  worker_enabled: boolean
  watched_contacts: number
  pending_drafts: number
  inbound_24h: number
  queue: { queued: number; retrying: number; held: number; dead: number; oldest_at: string | null }
}

export interface WaJob {
  id: string
  index: number
  state: 'PENDING' | 'HELD' | 'CLAIMED' | 'RETRY_WAIT' | 'DONE' | 'DEAD' | 'QUARANTINED'
  decision: string | null
  failure_code: string | null
  detail: string | null
  draft_id: string | null
  attempts: number
}

export interface WaEvent {
  id: string
  received_at: string
  sender: string | null
  supplier_id: string | null
  supplier_name: string | null
  contact_name: string | null
  text: string
  num_media: number
  outcome: string
  reason: string | null
  jobs: WaJob[]
}

export interface WaContact {
  id: string
  supplier_id: string
  name: string
  role: string | null
  supplier_name: string | null
  phone: string | null
  watch_enabled: boolean
  consent: 'UNKNOWN' | 'OPTED_IN' | 'OPTED_OUT'
  last_inbound_at: string | null
  window_open: boolean
}

export interface WaMessage {
  id: string
  direction: 'inbound' | 'outbound'
  body: string | null
  num_media: number
  outcome: string
  reason: string | null
  status: string | null
  error: string | null
  sent_by: string | null
  at: string
  contact_id: string | null
  jobs: { id: string; decision: string | null; state: string; draft_id: string | null; detail: string | null }[]
}

const brandParams = (brandId?: string | null) => (brandId ? { brand_id: brandId } : {})

export async function fetchWaStatus(brandId?: string | null): Promise<WaStatus> {
  const { data } = await axios.get<WaStatus>('/api/agent/whatsapp/status', { params: brandParams(brandId) })
  return data
}

export async function connectWa(body: {
  use_server_credentials: boolean
  account_sid?: string
  auth_token?: string
  sender?: string
}): Promise<{ connection: WaConnection }> {
  const { data } = await axios.put('/api/agent/whatsapp/connection', body)
  return data
}

export async function disconnectWa(): Promise<void> {
  await axios.delete('/api/agent/whatsapp/connection')
}

export async function updateWaSettings(body: {
  inbound_enabled?: boolean
  outbound_enabled?: boolean
  backlog_action?: 'drain' | 'discard'
}): Promise<{ connection: WaConnection; backlog_changed: number }> {
  const { data } = await axios.patch('/api/agent/whatsapp/settings', body)
  return data
}

export async function fetchWaEvents(brandId?: string | null, limit = 50): Promise<WaEvent[]> {
  const { data } = await axios.get<WaEvent[]>('/api/agent/whatsapp/events', { params: { ...brandParams(brandId), limit } })
  return data
}

export async function refreshWa(): Promise<{ drained: number; throttled: boolean }> {
  const { data } = await axios.post('/api/agent/whatsapp/refresh')
  return data
}

export async function retryWaJob(jobId: string): Promise<void> {
  await axios.post(`/api/agent/whatsapp/jobs/${jobId}/retry`)
}

export async function draftWaJobAnyway(jobId: string): Promise<void> {
  await axios.post(`/api/agent/whatsapp/jobs/${jobId}/draft-anyway`)
}

export async function fetchWaContacts(brandId?: string | null): Promise<WaContact[]> {
  const { data } = await axios.get<WaContact[]>('/api/agent/whatsapp/contacts', { params: brandParams(brandId) })
  return data
}

export async function setWaWatch(supplierId: string, contactId: string, enabled: boolean, phone?: string | null) {
  const { data } = await axios.patch<{ watch_enabled: boolean; phone: string }>(
    `/api/vendors/${supplierId}/contacts/${contactId}/whatsapp-watch`,
    { enabled, phone: phone || undefined },
  )
  return data
}

export async function fetchWaConversation(supplierId: string, contactId?: string): Promise<WaMessage[]> {
  const { data } = await axios.get<{ messages: WaMessage[] }>(`/api/vendors/${supplierId}/whatsapp/conversations`, {
    params: contactId ? { contact_id: contactId } : {},
  })
  return data.messages
}

export async function sendWaReply(supplierId: string, contactId: string, body: string, opKey: string) {
  const { data } = await axios.post(`/api/vendors/${supplierId}/whatsapp/reply`, {
    contact_id: contactId,
    body,
    op_key: opKey,
  })
  return data as { id: string; status: string | null; error: string | null }
}

/** Server error text from an axios failure: string detail, {message}, or a fallback. */
export function errorText(err: unknown, fallback: string): string {
  const detail = (err as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (detail && typeof detail === 'object' && 'message' in detail) return String((detail as { message: unknown }).message)
  return fallback
}
