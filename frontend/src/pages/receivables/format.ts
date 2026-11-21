import { formatMoney } from '../../ui'

/** Money arrives as strings (Decimals on the server); format only for display. */
export function money(v: string | number | null | undefined): string {
  if (v === null || v === undefined || v === '') return '—'
  const n = typeof v === 'number' ? v : Number(v)
  return Number.isFinite(n) ? formatMoney(n, { precise: true }) : '—'
}

export function pct(v: number | null | undefined): string {
  return v === null || v === undefined ? '—' : `${Math.round(v * 100)}%`
}

/** Paise-exact arithmetic on decimal strings, so allocation totals don't drift. */
export function toPaise(v: string | number | null | undefined): number {
  if (v === null || v === undefined || v === '') return 0
  const n = Number(String(v).replace(/,/g, ''))
  return Number.isFinite(n) ? Math.round(n * 100) : 0
}

export function fromPaise(p: number): string {
  return (p / 100).toFixed(2)
}

/** How a match was found, in plain words. */
export const KIND_LABELS: Record<string, string> = {
  remittance: 'From remittance',
  remittance_adjusted: 'From remittance, adjusted',
  remittance_partial: 'From remittance, part-paid',
  reference_exact: 'Invoice no. in narration',
  reference_tds: 'Invoice no. in narration, less TDS',
  reference_partial: 'Invoice no. in narration, part-paid',
  reference_overpaid: 'Invoice no. in narration, overpaid',
  amount_exact: 'Exact amount',
  amount_exact_ambiguous: 'Exact amount, several invoices fit',
  amount_tds: 'Amount less TDS',
  oldest_first: 'Oldest invoices first',
  combination: 'Invoices add up to the amount',
  combination_ambiguous: 'Invoices add up, several ways',
  oldest_partial: 'Part-payment, oldest first',
  overpaid: 'Overpaid',
  amount_only: 'Amount only, payer unknown',
}

/** Older matches were saved with the agent's raw wording; read them the way new ones are written. */
export const tidy = (c: string) => c
  .replace(/^Customer identified by known payer name$/, 'Known payer name')
  .replace(/^Customer identified by (.+)$/, 'Customer: $1')
  .replace(/^(The )?[Rr]emittance accounts for the whole payment$/, 'Advice covers the full amount')
  .replace(/^(The )?[Rr]emittance accounts for (.+) of (.+)$/, 'Advice covers $2 of $3')
  .replace(/^(The )?[Cc]ustomer set off (.+) against (.+)$/, '$3 set off: $2')
  .replace(/^Matches of this kind always need a person to confirm$|^'[a-z_]+' needs a person to confirm$/, 'Needs your confirmation')
  .replace(/^'(.+?)' read as (\S+)$/, '$1 → $2')
  .replace(/^'(.+?)' looks like a typo for (\S+)$/, '$1 → $2 (typo)')
  .replace(/^Customer identified by payer name/, 'Payer name')
  .replace(/(\d+) line\(s\)/g, (_, n) => `${n} line${n === '1' ? '' : 's'}`)
  .replace(/^'[a-z_]+' needs a person to confirm$/, 'Matches of this kind always need a person to confirm')
  .replace(/^Confidence ([\d.]+) is below the auto-apply bar ([\d.]+)$/,
    (_, a, b) => `${Math.round(Number(a) * 100)}% sure — below the ${Math.round(Number(b) * 100)}% needed to apply on its own`)
  .replace(/(^|[\s(])(\d{4,}\.\d{2})(?=[\s),;]|$)/g, (_, pre, n) => `${pre}${money(n)}`)

