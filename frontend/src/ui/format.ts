/**
 * Locale-aware formatters.
 *
 * Centralised so a non-INR entity or a non-en-IN locale is a config change
 * rather than a hunt through ~40 inline `Intl.NumberFormat` calls — several of
 * which hardcoded `currency: 'INR'` even on the FX screens (audit finding E9).
 */

export const DEFAULT_LOCALE = 'en-IN'
export const DEFAULT_CURRENCY = 'INR'

const moneyCache = new Map<string, Intl.NumberFormat>()

function moneyFormatter(currency: string, maxFrac: number, locale: string): Intl.NumberFormat {
  const key = `${locale}|${currency}|${maxFrac}`
  let f = moneyCache.get(key)
  if (!f) {
    f = new Intl.NumberFormat(locale, {
      style: 'currency',
      currency,
      maximumFractionDigits: maxFrac,
      minimumFractionDigits: maxFrac === 0 ? 0 : 2,
    })
    moneyCache.set(key, f)
  }
  return f
}

export interface MoneyOptions {
  currency?: string
  locale?: string
  /** Whole rupees for dashboards; paise for anything reconciled or paid. */
  precise?: boolean
  /** Rendered when the value is null/undefined. */
  fallback?: string
}

export function formatMoney(value: number | null | undefined, opts: MoneyOptions = {}): string {
  const { currency = DEFAULT_CURRENCY, locale = DEFAULT_LOCALE, precise = false, fallback = '—' } = opts
  if (value === null || value === undefined || Number.isNaN(value)) return fallback
  return moneyFormatter(currency, precise ? 2 : 0, locale).format(value)
}

/** Compact form for axis labels and dense tiles: ₹1.2Cr, ₹3.4L, ₹56K. */
export function formatMoneyCompact(value: number | null | undefined, opts: MoneyOptions = {}): string {
  const { currency = DEFAULT_CURRENCY, fallback = '—' } = opts
  if (value === null || value === undefined || Number.isNaN(value)) return fallback
  const sym = currency === 'INR' ? '₹' : ''
  const abs = Math.abs(value)
  const sign = value < 0 ? '-' : ''
  // Indian numbering: crore (10^7) and lakh (10^5) are what finance teams read.
  if (abs >= 1e7) return `${sign}${sym}${(abs / 1e7).toFixed(abs >= 1e8 ? 0 : 1)}Cr`
  if (abs >= 1e5) return `${sign}${sym}${(abs / 1e5).toFixed(abs >= 1e6 ? 0 : 1)}L`
  if (abs >= 1e3) return `${sign}${sym}${(abs / 1e3).toFixed(0)}K`
  return `${sign}${sym}${abs.toFixed(0)}`
}

const CURRENCY_SYMBOLS: Record<string, string> = {
  USD: '$',
  EUR: '€',
  GBP: '£',
  JPY: '¥',
  INR: '₹',
  AED: 'د.إ',
  SGD: 'S$',
}

export function currencySymbol(code: string | null | undefined): string {
  return CURRENCY_SYMBOLS[code ?? ''] ?? ''
}

export function formatDate(
  value: string | Date | null | undefined,
  opts: { locale?: string; fallback?: string; withYear?: boolean } = {},
): string {
  const { locale = DEFAULT_LOCALE, fallback = '—', withYear = true } = opts
  if (!value) return fallback
  const d = value instanceof Date ? value : new Date(value)
  if (Number.isNaN(d.getTime())) return fallback
  return d.toLocaleDateString(locale, {
    day: '2-digit',
    month: 'short',
    ...(withYear ? { year: 'numeric' } : {}),
  })
}

export function formatDateTime(
  value: string | Date | null | undefined,
  opts: { locale?: string; fallback?: string } = {},
): string {
  const { locale = DEFAULT_LOCALE, fallback = '—' } = opts
  if (!value) return fallback
  const d = value instanceof Date ? value : new Date(value)
  if (Number.isNaN(d.getTime())) return fallback
  return d.toLocaleString(locale, {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

/** "3 days ago" / "in 5 days". Anchored so it can be tested deterministically. */
export function formatRelativeDays(
  value: string | Date | null | undefined,
  now: Date = new Date(),
): string | null {
  if (!value) return null
  const d = value instanceof Date ? value : new Date(value)
  if (Number.isNaN(d.getTime())) return null
  const startOf = (x: Date) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime()
  const days = Math.round((startOf(d) - startOf(now)) / 86_400_000)
  if (days === 0) return 'today'
  if (days === 1) return 'tomorrow'
  if (days === -1) return 'yesterday'
  return days > 0 ? `in ${days} days` : `${Math.abs(days)} days ago`
}

/** Turn PENDING_ACCOUNTANT into "Pending Accountant". */
export function humanise(value: string | null | undefined, fallback = '—'): string {
  if (!value) return fallback
  return value
    .replace(/_/g, ' ')
    .toLowerCase()
    .replace(/\b\w/g, c => c.toUpperCase())
}
