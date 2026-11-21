/** Types mirroring backend_ocr/app/cashflow/service.py serialisers (docs/cashflow-forecast/04_LLD.md §7). */

export type View = 'expected' | 'downside' | 'no_collections'
export const VIEWS: { key: View; label: string }[] = [
  { key: 'expected', label: 'Expected' },
  { key: 'downside', label: 'Downside' },
  { key: 'no_collections', label: 'No new collections' },
]

export type Freshness = 'fresh' | 'stale' | 'expired'

export interface SnapshotBalance {
  bank_account_id: string
  account_name: string
  account_mask: string | null
  balance_paise: number
  as_of: string
  source: string
  freshness: Freshness
}

export interface Coverage {
  state: 'complete' | 'partial'
  failed_sources: string[]
  missing_balances: string[]
  needs_setup: string[]
  event_count: number
  exclusion_count: number
}

export interface SnapshotRef {
  snapshot_id: string
  revision: number
  as_of: string
  start: string
  end: string
  horizon_days: number
  reserve_paise: number
  od_headroom_paise: number
  content_hash: string
  changed: boolean | null
  coverage: Coverage
  is_fixture: boolean
  today: string
  balances: SnapshotBalance[]
}

export interface DayRow {
  date: string
  banking_day: boolean
  opening_paise: number
  inflow_paise: number
  outflow_paise: number
  closing_paise: number
  below_reserve: boolean
  event_count: number
}

export interface Metrics {
  minimum_closing_paise: number
  minimum_date: string
  first_reserve_breach_date: string | null
  first_negative_date: string | null
  days_below_reserve: number
  total_inflow_paise: number
  total_outflow_paise: number
  closing_paise: number
  beyond_horizon_inflow_paise: number
  beyond_horizon_outflow_paise: number
  runway_days: number | null
}

export interface ForecastResult {
  view: View
  opening_paise: number
  reserve_paise: number
  days: DayRow[]
  metrics: Metrics
  category_totals: Record<string, number>
}

export interface Forecast extends ForecastResult {
  snapshot: SnapshotRef
}

export interface PaymentWindow {
  earliest: string
  latest: string
  agreed_with: string | null
  evidence: string | null
}

export interface CashEvent {
  event_key: string
  source_type: string
  source_id: string
  label: string
  counterparty: string | null
  counterparty_id: string | null
  document_number: string | null
  direction: 'in' | 'out'
  amount_paise: number
  category: string
  confidence: string
  date: string | null
  date_basis: string
  tds_note: string | null
  nominal_date: string | null
  window: PaymentWindow | null
  fixed: boolean
  link_path: string | null
  moved_by_scenario: boolean
}

export interface DayDetail {
  day: DayRow
  inflows: CashEvent[]
  outflows: CashEvent[]
}

export interface Exclusion {
  source_type: string
  source_id: string
  label: string
  amount_paise: number
  reason: string
  detail: string
  views: string[]
  link_path: string | null
}

export type Override =
  | { op: 'shift_event'; event_key: string; to_date: string; reason?: string }
  | { op: 'delay_customer'; customer_id: string; days: number; reason?: string }
  | { op: 'haircut_customer'; customer_id: string; percent: number; reason?: string }
  | { op: 'exclude_event'; event_key: string; reason?: string }
  | {
      op: 'add_item'
      label: string
      direction: 'in' | 'out'
      amount_paise: number
      on_date: string
      category: string
      confidence: 'committed' | 'estimated'
      reason?: string
    }

export interface Refusal {
  index: number
  code: string
  message: string
  details: Record<string, unknown>
}

export interface Applied {
  index: number
  op: string
  kind: 'decision' | 'assumption'
  affected_event_keys: string[]
}

export interface Preview {
  baseline: ForecastResult
  scenario: ForecastResult
  delta: {
    minimum_change_paise: number
    closing_change_paise: number
    baseline_first_breach: string | null
    scenario_first_breach: string | null
    closing_diff_paise: number[]
  }
  applied: Applied[]
}

export interface Scenario {
  id: string
  name: string
  description: string | null
  snapshot_id: string
  revision: number
  view: View
  overrides: Override[]
  status: 'ok' | 'needs_review'
  version: number
  created_by: string
  created_at: string
  updated_at: string
  rebase?: { revision: number; snapshot_id: string; items: { index: number; status: string; message?: string }[] }
}

export type PlanState = 'draft' | 'submitted' | 'approved' | 'returned' | 'withdrawn' | 'superseded'

export interface Plan {
  id: string
  scenario_id: string
  scenario_name: string | null
  version: number
  state: PlanState
  snapshot_id: string
  revision: number
  view: View
  overrides: Override[]
  metrics: Metrics
  baseline_metrics: Metrics
  note: string | null
  submitted_by: string | null
  submitted_at: string | null
  created_by: string
  created_at: string
  updated_at: string
  decisions?: { id: string; decision: string; note: string | null; decided_by: string; decided_at: string; validated_on_revision: number }[]
  history?: { action: string; actor: string; created_at: string }[]
  changes?: PlanChange[]
}

export interface PlanChange {
  index: number
  op: Override['op']
  kind: 'decision' | 'assumption'
  reason: string | null
  label?: string
  amount_paise?: number
  direction?: 'in' | 'out'
  link_path?: string | null
  from_date?: string | null
  to_date?: string
  window_latest?: string
  agreed_with?: string | null
  evidence?: string | null
}

export interface Me {
  actor: string
  role: string
  can: { view: boolean; edit: boolean; approve: boolean; settings: boolean }
}

export interface Account {
  bank_account_id: string
  account_name: string
  account_mask: string | null
  account_type: string
  od_limit_paise: number
  include_in_forecast: boolean
  balance_paise: number | null
  as_of: string | null
  source: string | null
}

export interface RecurringItem {
  id: string
  name: string
  category: string
  direction: 'in' | 'out'
  amount_paise: number | null
  frequency: 'weekly' | 'monthly' | 'quarterly'
  anchor: string
  quarter_months: number[] | null
  business_day_rule: 'next_banking_day' | 'previous_banking_day'
  confidence: 'committed' | 'estimated'
  statutory: boolean
  start_date: string
  end_date: string | null
  version: number
}

export interface Adjustment {
  id: string
  name: string
  category: string
  direction: 'in' | 'out'
  amount_paise: number
  on_date: string
  confidence: 'committed' | 'estimated'
  note: string | null
  plan_id: string | null
}

export interface Settings {
  reserve_paise: number
  horizon_days: number
  timezone: string
  default_view: View
  include_pending_approval_ap: boolean
  overdue_fallback_days: number
  downside_exclude_overdue_after_days: number
  min_customer_history: number
  allow_self_approval: boolean
  publish_daily: boolean
  holidays: { date: string; name: string }[]
}

export interface WindowRow {
  id: string
  invoice_id: string
  earliest_date: string
  latest_date: string
  agreed_with: string
  evidence: string
}

export interface PromiseRow {
  id: string
  invoice_id: string
  promised_date: string
  promised_amount_paise: number
  source: string
  note: string | null
}
