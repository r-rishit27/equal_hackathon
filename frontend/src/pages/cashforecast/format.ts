/**
 * Money and date formatting for the cash forecast (docs/cashflow-forecast/06_UI_SPEC.md §4.1, §8.3).
 *
 * - Sentences round to whole rupees, half up: ₹48,70,432.
 * - The ledger, drawers and exports show exact paise so every row reconciles: 48,70,431.84.
 * - KPIs and chart axes use compact lakh / crore: ₹48.70 L, ₹2.23 Cr.
 * All arithmetic is integer paise; formatting is string work, never float maths.
 */

function group(rupees: bigint): string {
  const s = rupees.toString()
  if (s.length <= 3) return s
  const tail = s.slice(-3)
  let head = s.slice(0, -3)
  const parts: string[] = []
  while (head.length > 2) {
    parts.unshift(head.slice(-2))
    head = head.slice(0, -2)
  }
  if (head) parts.unshift(head)
  return [...parts, tail].join(',')
}

const MINUS = '−'

/** Whole rupees, half up: 487043184 → "₹48,70,432". */
export function rupees(paise: number, opts: { sign?: boolean; symbol?: boolean } = {}): string {
  const neg = paise < 0
  const abs = BigInt(Math.abs(Math.trunc(paise)))
  const whole = (abs + 50n) / 100n
  const sign = neg && whole > 0n ? MINUS : opts.sign && !neg ? '+' : ''
  return `${sign}${opts.symbol === false ? '' : '₹'}${group(whole)}`
}

/** Exact, with paise: 487043184 → "48,70,431.84". */
export function exact(paise: number, opts: { symbol?: boolean; sign?: boolean } = {}): string {
  const neg = paise < 0
  const abs = BigInt(Math.abs(Math.trunc(paise)))
  const sign = neg ? MINUS : opts.sign && paise > 0 ? '+' : ''
  const p = (abs % 100n).toString().padStart(2, '0')
  return `${sign}${opts.symbol ? '₹' : ''}${group(abs / 100n)}.${p}`
}

/** Compact lakh / crore: "₹48.70 L", "₹2.23 Cr", "₹46,000". */
export function compact(paise: number, opts: { sign?: boolean } = {}): string {
  const neg = paise < 0
  const r = Math.abs(paise) / 100
  const sign = neg ? MINUS : opts.sign && paise > 0 ? '+' : ''
  if (r >= 1e7) return `${sign}₹${(r / 1e7).toFixed(2)} Cr`
  if (r >= 1e5) return `${sign}₹${(r / 1e5).toFixed(2)} L`
  return sign + rupees(Math.abs(paise))
}

/** Words for screen readers: "48 lakh 70 thousand 432 rupees". */
export function spoken(paise: number): string {
  const neg = paise < 0
  let r = Number((BigInt(Math.abs(Math.trunc(paise))) + 50n) / 100n)
  const parts: string[] = []
  const take = (unit: number, word: string) => {
    const n = Math.floor(r / unit)
    if (n) parts.push(`${n} ${word}`)
    r %= unit
  }
  take(1e7, 'crore')
  take(1e5, 'lakh')
  take(1e3, 'thousand')
  if (r || !parts.length) parts.push(String(r))
  return `${neg ? 'minus ' : ''}${parts.join(' ')} rupees`
}

const DAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

function parts(iso: string) {
  const [y, m, d] = iso.slice(0, 10).split('-').map(Number)
  const dow = new Date(Date.UTC(y, m - 1, d)).getUTCDay()
  return { y, m, d, dow }
}

/** "Mon 30 Nov". */
export function day(iso: string): string {
  const { m, d, dow } = parts(iso)
  return `${DAYS[dow]} ${d} ${MONTHS[m - 1]}`
}

/** "30 Nov". */
export function shortDay(iso: string): string {
  const { m, d } = parts(iso)
  return `${d} ${MONTHS[m - 1]}`
}

/** "20 Nov 18:30" in the business timezone. */
export function stamp(iso: string, timeZone = 'Asia/Kolkata'): string {
  const dt = new Date(iso)
  const date = dt.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', timeZone })
  const time = dt.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', hour12: false, timeZone })
  return `${date} ${time}`
}

export function addDays(iso: string, n: number): string {
  const { y, m, d } = parts(iso)
  return new Date(Date.UTC(y, m - 1, d + n)).toISOString().slice(0, 10)
}

/** Rupee input ("48,70,431.84") → paise, or null when unparseable. */
export function toPaise(input: string): number | null {
  const clean = input.replace(/[₹,\s]/g, '').replace('−', '-')
  if (!/^-?\d+(\.\d{1,2})?$/.test(clean)) return null
  const [whole, frac = ''] = clean.replace('-', '').split('.')
  const p = Number(whole) * 100 + Number(frac.padEnd(2, '0'))
  return clean.startsWith('-') ? -p : p
}

export const CATEGORY_LABELS: Record<string, string> = {
  customer: 'Collections',
  supplier: 'Suppliers',
  payroll: 'Payroll',
  statutory: 'Statutory',
  rent: 'Rent',
  debt: 'Debt (EMI)',
  utilities: 'Utilities',
  operations: 'Operations',
  insurance: 'Insurance',
  capex: 'Capex',
  refund: 'Refunds',
  financing: 'Financing',
  other: 'Other',
}
