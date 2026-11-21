/** How a playground contract term reads on screen — shared by the bill panel and the run panel. */

/** "5" with a unit of "% of the total invoice amount…" reads as 5%. */
export function termValue(value: string | number, unit?: string | null): string {
  const u = (unit ?? '').trim()
  return u.startsWith('%') ? `${value}%` : u && u.length <= 12 ? `${value} ${u}` : String(value)
}

/** routing_fee → Routing fee */
export function termLabel(field: string): string {
  const s = field.replace(/_/g, ' ')
  return s.charAt(0).toUpperCase() + s.slice(1)
}
