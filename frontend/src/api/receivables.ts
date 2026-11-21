import axios from 'axios'
import type { InvoicePayload } from './invoices'

/**
 * Receivables + cash application — /api/ar (docs/receivables/02_LLD.md §8).
 * Money stays a string end to end: Decimals on the server, formatted only for display.
 */

export type PaymentStatus =
  | 'unmatched' | 'needs_review' | 'partially_applied' | 'applied' | 'exception' | 'not_receipt' | 'reversed'
export type ArInvoiceStatus = 'open' | 'partially_paid' | 'paid' | 'disputed' | 'written_off' | 'void'
export type ReasonCode =
  | 'TDS' | 'DISCOUNT' | 'BANK_CHARGES' | 'ROUNDING' | 'SHORT_SUPPLY' | 'DAMAGE' | 'RATE_DIFF'
  | 'DEBIT_NOTE' | 'FX' | 'DISPUTE' | 'OTHER'
export type ExceptionCode =
  | 'DISPUTE' | 'DUPLICATE' | 'AWAITING_REMITTANCE' | 'WRONG_CUSTOMER' | 'FX' | 'REFUND_DUE'
  | 'BOUNCE_SUSPECTED' | 'OTHER'

export const REASON_LABELS: Record<ReasonCode, string> = {
  TDS: 'TDS', DISCOUNT: 'Discount', BANK_CHARGES: 'Bank charges', ROUNDING: 'Rounding',
  SHORT_SUPPLY: 'Short supply', DAMAGE: 'Damage', RATE_DIFF: 'Rate difference', DEBIT_NOTE: 'Debit / credit note',
  FX: 'Exchange difference', DISPUTE: 'Disputed', OTHER: 'Other',
}
export const EXCEPTION_LABELS: Record<ExceptionCode, string> = {
  DISPUTE: 'Customer dispute', DUPLICATE: 'Duplicate payment', AWAITING_REMITTANCE: 'Waiting for remittance',
  WRONG_CUSTOMER: 'Not our customer / wrong account', FX: 'Exchange difference', REFUND_DUE: 'Refund due',
  BOUNCE_SUSPECTED: 'Possible bounce / recall', OTHER: 'Other',
}
export const FLAG_LABELS: Record<string, string> = {
  CLUE_CONFLICT: 'The quoted invoice and the amount point at different invoices',
  POSSIBLE_DUPLICATE: 'Looks like a repeat of a payment already received',
  AMBIGUOUS_PAYER: 'This payer name belongs to more than one customer',
  CROSS_CUSTOMER: 'Pays invoices of more than one customer',
  ADVANCE: 'Received before the invoice date',
  FOREIGN_CURRENCY: 'Invoice is in a foreign currency',
  REMITTANCE_DISAGREES: 'A remittance that arrived later names different invoices',
  DISPUTED_INVOICE: 'One of the invoices is on hold (disputed)',
  TDS_ON_GROSS: 'TDS seems to be on the GST-inclusive total, not the taxable value',
  POSSIBLE_BOUNCE: 'A later debit looks like this payment bounced or was recalled',
}

export interface Allocation {
  invoice_id: string
  invoice_number: string
  amount_applied: string
  tds_amount: string
  deduction_amount: string
  reason_code: ReasonCode | null
  reason_note: string | null
  tds_rate?: string | null
}
export interface Suggestion {
  kind: string
  confidence: string
  customer_id: string | null
  allocations: Allocation[]
  clues: string[]
  unapplied: string
}
export interface SuggestionEnvelope {
  customer_id: string | null
  customer_how: string | null
  customer_name: string | null
  best: Suggestion | null
  alternatives: Suggestion[]
  flags: string[]
  decision: { action: 'AUTO' | 'REVIEW' | 'UNMATCHED'; reason: string }
  remittance_id: string | null
}

export interface PaymentRow {
  id: string
  received_on: string
  amount: string
  method: string | null
  reference: string | null
  utr: string | null
  payer_name: string | null
  narration: string | null
  source: string
  status: PaymentStatus
  applied_amount: string
  unapplied: string
  match_confidence: string | null
  flags: string[]
  auto_applied: boolean
  reason_code: string | null
  note: string | null
  version: number
  suggestion_kind: string | null
  suggestion_reason: string | null
  suggestion_invoices: string | null
  customer_id: string | null
  customer_name: string | null
  customer_confirmed: boolean
  created_at: string
  applied_at: string | null
}

export interface Payment extends Omit<PaymentRow, 'suggestion_kind' | 'suggestion_reason' | 'suggestion_invoices' | 'unapplied' | 'customer_name' | 'customer_confirmed'> {
  suggestion: SuggestionEnvelope | null
  bank_account: string | null
  statement_id: string | null
  statement_line: number | null
}

export interface ArInvoiceRow {
  id: string
  invoice_number: string
  invoice_date: string | null
  due_date: string | null
  po_number: string | null
  currency: string
  taxable_amount: string | null
  tax_amount: string | null
  total_amount: string
  amount_received: string
  tds_amount: string
  deduction_amount: string
  outstanding: string
  status: ArInvoiceStatus
  customer_id: string
  customer_name: string
  days_overdue: number | null
  has_document: boolean
}

export interface ApplicationRow {
  id: string
  payment_id: string
  invoice_id: string
  invoice_number?: string
  amount_applied: string
  tds_amount: string
  deduction_amount: string
  reason_code: ReasonCode | null
  reason_note: string | null
  method: 'auto' | 'accepted' | 'manual'
  kind: string | null
  applied_by: string | null
  created_at: string
  reversed_at: string | null
  received_on?: string
  utr?: string | null
  payer_name?: string | null
}

export interface Remittance {
  id: string
  payer_name: string | null
  payment_reference: string | null
  payment_date: string | null
  total_amount: string | null
  lines: { invoice_number: string; amount_paid: number; deduction_amount: number; deduction_reason: string | null }[]
  status?: 'unlinked' | 'linked' | 'conflict'
  source: string
  source_file: string | null
  created_at: string
  payment_id?: string | null
  has_document?: boolean
}

export interface RemittanceDetail extends Remittance {
  raw_text: string | null
  payment_amount: string | null
  payment_received_on: string | null
  payment_status: PaymentStatus | null
  payment_utr: string | null
  customer_name: string | null
  created_by: string | null
}

export type StatementLineOutcome = 'new' | 'duplicate' | 'set_aside' | 'bounce' | 'debit' | 'ignored'
export interface StatementLine {
  line: number
  date: string
  narration: string | null
  reference: string | null
  credit: string | null
  debit: string | null
  outcome: StatementLineOutcome
  payment_id?: string
  payment_status?: PaymentStatus
  auto_applied?: boolean
  customer_name?: string | null
}
export interface StatementRow {
  id: string
  file_name: string
  file_format: 'csv' | 'xlsx' | 'pdf'
  bank_account: string | null
  period_from: string | null
  period_to: string | null
  credits: number
  imported: number
  duplicates: number
  set_aside: number
  bounces: number
  uploaded_by: string | null
  created_at: string
  has_document: boolean
}
export interface StatementDetail extends StatementRow { lines: StatementLine[] }

export interface PaymentDetail {
  payment: Payment
  customer: { id: string; name: string; gstin: string | null; tds_rate_hint: string | null; confirmed: boolean } | null
  open_invoices: ArInvoiceRow[]
  applications: ApplicationRow[]
  remittances: Remittance[]
  events: { action: string; actor: string; payload: Record<string, unknown> | null; at: string }[]
  statement: { id: string; file_name: string; created_at: string } | null
}

export interface CustomerRow {
  id: string
  name: string
  gstin: string | null
  pan: string | null
  email: string | null
  payment_terms_days: number | null
  tds_rate_hint: string | null
  open_count: number
  outstanding: string
  overdue: string
  unapplied: string
  last_payment: string | null
}
export interface CustomerDetail extends Omit<CustomerRow, 'open_count' | 'outstanding' | 'overdue' | 'unapplied' | 'last_payment'> {
  phone: string | null
  address: string | null
  aliases: { id: string; alias_raw: string | null; alias_norm: string; source: string; confirmations: number }[]
  invoices: ArInvoiceRow[]
  payments: PaymentRow[]
}

export interface ArSummary {
  days: number
  kpis: {
    match_rate: number | null
    exception_rate: number | null
    applied_cash_pct: number | null
    hours_to_apply: number | null
    dso: number | null
    suggestion_acceptance: number | null
    /** DSO as it stood a month ago, for the trend. */
    dso_previous: number | null
  }
  payments: { receipts: number; receipts_total: string; applied_total: string; auto_count: number; open_count: number }
  aging: { b0_30: string; b31_60: string; b61_plus: string; items: number }
  ar: { open_ar: string; overdue: string; tds_receivable: string; open_invoices: number }
  status_counts: Partial<Record<PaymentStatus, number>>
  /** The period before this one, for trends. */
  previous: { receipts: number; receipts_total: string; open_ar: string; billed_90: string }
  /** Unapplied cash the agent has matched and is waiting on a person to confirm. */
  unapplied_in_review: string
}

/** The review board: payments waiting on a person, grouped by customer with that customer's open invoices. */
export interface BoardInvoice {
  id: string
  invoice_number: string
  invoice_date: string | null
  due_date: string | null
  po_number: string | null
  total_amount: string
  amount_received: string
  tds_amount: string
  deduction_amount: string
  outstanding: string
  taxable_amount: string | null
  status: ArInvoiceStatus
  customer_id: string
  days_overdue: number | null
}
export interface BoardPayment {
  id: string
  received_on: string
  amount: string
  method: string | null
  reference: string | null
  utr: string | null
  payer_name: string | null
  source: string
  status: PaymentStatus
  version: number
  match_confidence: string | null
  flags: string[]
  statement_id: string | null
  best: Suggestion | null
  decision: SuggestionEnvelope['decision'] | null
  customer_id: string | null
  remittance_id: string | null
  remittance_total: string | null
}
export interface BoardGroup {
  customer: { id: string; name: string; payment_terms_days: number | null; open_ar: string; overdue: string } | null
  payments: BoardPayment[]
  invoices: BoardInvoice[]
}

export interface ArSettings {
  auto_apply_enabled: boolean
  auto_apply_threshold: string
  amount_tolerance: string
  writeoff_tolerance: string
  tds_rates: string[]
  trust_learned_tds: boolean
}

export interface Page<T> { items: T[]; total: number }

/** FastAPI's `detail`, or the axios message. */
export function apiError(e: unknown): string {
  const d = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
  if (typeof d === 'string') return d
  if (Array.isArray(d) && d[0]?.msg) return String(d[0].msg)
  return (e as Error)?.message || 'Something went wrong'
}

const q = (o: Record<string, unknown>) => {
  const p = new URLSearchParams()
  for (const [k, v] of Object.entries(o)) if (v !== undefined && v !== null && v !== '') p.set(k, String(v))
  const s = p.toString()
  return s ? `?${s}` : ''
}

// ── summary / settings ────────────────────────────────────────────────────────
export const fetchArSummary = (days = 30) => axios.get<ArSummary>(`/api/ar/summary${q({ days })}`).then(r => r.data)
export const fetchArSettings = () => axios.get<ArSettings>('/api/ar/settings').then(r => r.data)
export const saveArSettings = (s: ArSettings) => axios.put<ArSettings>('/api/ar/settings', s).then(r => r.data)

// ── invoices ─────────────────────────────────────────────────────────────────
export const ingestArInvoice = (payload: InvoicePayload) =>
  axios.post<{ invoice_id: string; customer_id: string; customer_created: boolean }>('/api/ar/invoices/ingest', { payload })
    .then(r => r.data)
export const fetchArInvoices = (o: { status?: string; customer_id?: string; q?: string; overdue?: boolean; limit?: number; offset?: number } = {}) =>
  axios.get<Page<ArInvoiceRow>>(`/api/ar/invoices${q(o)}`).then(r => r.data)
export const fetchArInvoice = (id: string) =>
  axios.get<ArInvoiceRow & { applications: ApplicationRow[]; payment_terms: string | null; customer_gstin: string | null }>(`/api/ar/invoices/${id}`).then(r => r.data)
export const setArInvoiceStatus = (id: string, status: 'disputed' | 'open' | 'void', note?: string) =>
  axios.patch(`/api/ar/invoices/${id}`, { status, note }).then(r => r.data)
export const arInvoiceDocumentUrl = (id: string) => `/api/ar/invoices/${id}/document`

// ── customers ────────────────────────────────────────────────────────────────
export const fetchCustomers = (o: { q?: string; limit?: number; offset?: number } = {}) =>
  axios.get<Page<CustomerRow>>(`/api/ar/customers${q(o)}`).then(r => r.data)
export const fetchCustomer = (id: string) => axios.get<CustomerDetail>(`/api/ar/customers/${id}`).then(r => r.data)
export const createCustomer = (b: { name: string; gstin?: string; email?: string; payment_terms_days?: number }) =>
  axios.post<{ customer_id: string; created: boolean }>('/api/ar/customers', b).then(r => r.data)
export const updateCustomer = (id: string, b: Record<string, string | number | null>) =>
  axios.patch(`/api/ar/customers/${id}`, b)
export const addCustomerAlias = (id: string, alias: string) => axios.post(`/api/ar/customers/${id}/aliases`, { alias })
export const removeCustomerAlias = (id: string, aliasId: string) => axios.delete(`/api/ar/customers/${id}/aliases/${aliasId}`)

// ── payments ─────────────────────────────────────────────────────────────────
export const fetchPayments = (o: { status?: string; customer_id?: string; q?: string; limit?: number; offset?: number } = {}) =>
  axios.get<Page<PaymentRow> & { counts: Partial<Record<PaymentStatus, number>> }>(`/api/ar/payments${q(o)}`).then(r => r.data)
export const fetchReviewBoard = (o: { status?: string; q?: string } = {}) =>
  axios.get<{ groups: BoardGroup[] }>(`/api/ar/review-board${q(o)}`).then(r => r.data)
export const fetchPayment = (id: string) => axios.get<PaymentDetail>(`/api/ar/payments/${id}`).then(r => r.data)
export const recordPayment = (b: {
  received_on: string; amount: string; method?: string; reference?: string; utr?: string; payer_name?: string
  customer_id?: string; narration?: string; force?: boolean
}) => axios.post<{ payment_id?: string; duplicate_warning?: PaymentRow[] }>('/api/ar/payments', b).then(r => r.data)
export function importStatement(file: File, bankAccount?: string) {
  const f = new FormData()
  f.append('file', file)
  if (bankAccount) f.append('bank_account', bankAccount)
  return axios.post<{ statement_id: string; credits: number; imported: number; set_aside: number; duplicates: number; possible_bounces: number; queued: number }>(
    '/api/ar/payments/import', f, { headers: { 'Content-Type': 'multipart/form-data' } }).then(r => r.data)
}
export const rematchPayment = (id: string) => axios.post(`/api/ar/payments/${id}/match`).then(r => r.data)
export interface AllocationIn {
  invoice_id: string; amount_applied: string; tds_amount: string; deduction_amount: string
  reason_code: ReasonCode | null; reason_note: string | null
}
export const applyPayment = (id: string, b: {
  allocations: AllocationIn[]; version: number; customer_id?: string | null; method: 'accepted' | 'manual'
  kind?: string | null; confidence?: string | null; allow_disputed?: boolean
}) => axios.post<{ status: PaymentStatus; applied: string; left_on_account: string }>(`/api/ar/payments/${id}/apply`, b).then(r => r.data)
export const unapplyPayment = (id: string, reason: string) => axios.post(`/api/ar/payments/${id}/unapply`, { reason }).then(r => r.data)
export const setPaymentStatus = (id: string, action: 'exception' | 'resolve' | 'not_receipt' | 'restore' | 'reverse',
  reason_code?: ExceptionCode, note?: string) =>
  axios.post(`/api/ar/payments/${id}/status`, { action, reason_code, note }).then(r => r.data)
export const choosePaymentCustomer = (id: string, customer_id: string | null) =>
  axios.post(`/api/ar/payments/${id}/customer`, { customer_id }).then(r => r.data)

// ── remittances ──────────────────────────────────────────────────────────────
export function addRemittance(input: { text?: string; file?: File }) {
  const f = new FormData()
  if (input.text) f.append('text', input.text)
  if (input.file) f.append('file', input.file)
  return axios.post<{ remittance_id: string; payment_id: string | null; parsed: Remittance }>('/api/ar/remittances', f,
    { headers: { 'Content-Type': 'multipart/form-data' } }).then(r => r.data)
}
export const fetchRemittances = (status?: string) =>
  axios.get<{ items: Remittance[] }>(`/api/ar/remittances${q({ status })}`).then(r => r.data)
export const fetchRemittance = (id: string) => axios.get<RemittanceDetail>(`/api/ar/remittances/${id}`).then(r => r.data)
export const remittanceDocumentUrl = (id: string) => `/api/ar/remittances/${id}/document`

// ── bank statements ──────────────────────────────────────────────────────────
export const fetchStatements = () => axios.get<{ items: StatementRow[] }>('/api/ar/statements').then(r => r.data)
export const fetchStatement = (id: string) => axios.get<StatementDetail>(`/api/ar/statements/${id}`).then(r => r.data)
export const statementDocumentUrl = (id: string) => `/api/ar/statements/${id}/document`
