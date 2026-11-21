/** Plain-language copy derived from forecast results (UI spec §8). */
import { CATEGORY_LABELS, compact, day, rupees } from './format'
import type { CashEvent, ForecastResult, Override } from './types'

/** The one-line answer (UI spec §8.1). */
export function summarySentence(f: ForecastResult): string {
  const m = f.metrics
  const reserve = rupees(f.reserve_paise)
  if (f.view === 'no_collections') {
    return m.first_negative_date
      ? `Without new collections, cash runs out in ${m.runway_days} days, on ${day(m.first_negative_date)}.`
      : `Without new collections, cash stays above zero. Lowest ${rupees(m.minimum_closing_paise)} on ${day(m.minimum_date)}.`
  }
  if (m.first_negative_date) return `Cash runs out on ${day(m.first_negative_date)}. Lowest ${rupees(m.minimum_closing_paise)} on ${day(m.minimum_date)}.`
  if (m.first_reserve_breach_date)
    return `Cash drops to ${rupees(m.minimum_closing_paise)} on ${day(m.minimum_date)}, ${rupees(f.reserve_paise - m.minimum_closing_paise)} below your ${reserve} reserve.`
  return `Stays above your ${reserve} reserve. Lowest ${rupees(m.minimum_closing_paise)} on ${day(m.minimum_date)}.`
}

const PLURAL: Record<string, string> = {
  supplier: 'supplier bills',
  customer: 'customer receipts',
  statutory: 'statutory dues',
  utilities: 'utility bills',
  payroll: 'payroll runs',
}
const WORDS = ['zero', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten']
const count = (n: number) => WORDS[n] ?? String(n)

export function driverLine(events: CashEvent[]): string {
  const out = events.filter(e => e.direction === 'out')
  const groups = new Map<string, { total: number; n: number; label: string }>()
  for (const e of out) {
    const g = groups.get(e.category) ?? { total: 0, n: 0, label: e.label }
    g.total += e.amount_paise
    g.n += 1
    groups.set(e.category, g)
  }
  const top = [...groups.entries()].sort((a, b) => b[1].total - a[1].total).slice(0, 3)
  if (!top.length) return ''
  const words = top.map(([cat, g]) =>
    g.n === 1
      ? `${g.label.replace(/\s*\([^)]*\)\s*$/, '')} (${compact(g.total)})`
      : `${count(g.n)} ${PLURAL[cat] ?? `${(CATEGORY_LABELS[cat] ?? cat).toLowerCase()} items`} (${compact(g.total)})`,
  )
  const list = words.length > 1 ? `${words.slice(0, -1).join(', ')} and ${words[words.length - 1]}` : words[0]
  return `${list.charAt(0).toUpperCase()}${list.slice(1)} land the same day.`
}

export function kindOf(o: Override, events: Map<string, CashEvent>): 'decision' | 'assumption' {
  if (o.op === 'shift_event') return events.get(o.event_key)?.direction === 'in' ? 'assumption' : 'decision'
  if (o.op === 'add_item') return o.confidence === 'committed' ? 'decision' : 'assumption'
  return 'assumption'
}

