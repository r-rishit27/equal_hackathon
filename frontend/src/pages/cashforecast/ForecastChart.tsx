/**
 * Daily closing balance as a step line (docs/cashflow-forecast/06_UI_SPEC.md §6).
 * Hand-built SVG like reportCharts.tsx: no chart dependency, colour via classes.
 * The ledger table below the chart is the full-data equivalent for assistive tech.
 */
import { useId, useMemo, useState, type KeyboardEvent } from 'react'
import type { DayRow } from './types'
import { compact, day, exact, rupees, shortDay } from './format'

const W = 960
const H = 300
const PAD = { top: 16, right: 16, bottom: 34, left: 64 }

function niceStep(span: number): number {
  const raw = span / 5
  const mag = 10 ** Math.floor(Math.log10(Math.max(raw, 1)))
  const n = raw / mag
  return (n <= 1 ? 1 : n <= 2 ? 2 : n <= 5 ? 5 : 10) * mag
}

export default function ForecastChart({
  baseline,
  scenario,
  reserve,
  selected,
  onSelectDay,
  summary,
}: {
  baseline: DayRow[]
  scenario?: DayRow[] | null
  reserve: number
  selected?: string | null
  onSelectDay: (date: string) => void
  summary: string
}) {
  const [focus, setFocus] = useState<number | null>(null)
  const descId = useId()
  const geo = useMemo(() => {
    const values = [...baseline, ...(scenario ?? [])].map(d => d.closing_paise)
    values.push(reserve, baseline[0]?.opening_paise ?? 0)
    const lo = Math.min(0, ...values)
    const hi = Math.max(...values)
    const step = niceStep((hi - lo) * 1.1 || 1)
    const min = Math.floor((lo - (lo < 0 ? (hi - lo) * 0.05 : 0)) / step) * step
    const max = Math.ceil((hi * 1.05) / step) * step
    const n = baseline.length
    const iw = W - PAD.left - PAD.right
    const ih = H - PAD.top - PAD.bottom
    const x = (i: number) => PAD.left + (iw * i) / Math.max(n, 1)
    const y = (v: number) => PAD.top + ih - ((v - min) / (max - min || 1)) * ih
    const ticks: number[] = []
    for (let v = min; v <= max + 1; v += step) ticks.push(v)
    return { x, y, ticks, iw, n }
  }, [baseline, scenario, reserve])

  const path = (rows: DayRow[]) => {
    if (!rows.length) return ''
    let d = `M${geo.x(0)},${geo.y(rows[0].opening_paise)}`
    rows.forEach((r, i) => {
      d += ` H${geo.x(i)} V${geo.y(r.closing_paise)} H${geo.x(i + 1)}`
    })
    return d
  }

  const active = focus ?? (selected ? baseline.findIndex(d => d.date === selected) : -1)
  const tip = active >= 0 ? baseline[active] : null
  const tipScenario = active >= 0 && scenario ? scenario[active] : null
  const colW = geo.iw / Math.max(geo.n, 1)

  const onKey = (e: KeyboardEvent<SVGSVGElement>) => {
    const cur = active < 0 ? 0 : active
    if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') {
      e.preventDefault()
      const step = e.key === 'ArrowRight' ? 1 : -1
      let i = cur + step
      while (i >= 0 && i < baseline.length && !baseline[i].banking_day) i += step
      if (i >= 0 && i < baseline.length) setFocus(i)
    } else if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault()
      if (baseline[cur]) onSelectDay(baseline[cur].date)
    }
  }

  return (
    <figure className="cf-chart">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        role="img"
        aria-label={summary}
        aria-describedby={descId}
        tabIndex={0}
        onKeyDown={onKey}
        onFocus={() => setFocus(f => f ?? baseline.findIndex(d => d.banking_day))}
        onBlur={() => setFocus(null)}
        onMouseLeave={() => setFocus(null)}
      >
        {baseline.map((d, i) =>
          d.banking_day ? null : (
            <rect key={d.date} className="cf-chart__band" x={geo.x(i)} y={PAD.top} width={colW} height={H - PAD.top - PAD.bottom} />
          ),
        )}
        {geo.ticks.map(v => (
          <g key={v}>
            <line className={v === 0 ? 'cf-chart__zero' : 'cf-chart__grid'} x1={PAD.left} x2={W - PAD.right} y1={geo.y(v)} y2={geo.y(v)} />
            <text className="cf-chart__axis" x={PAD.left - 8} y={geo.y(v) + 4} textAnchor="end">
              {compact(v)}
            </text>
          </g>
        ))}
        <line className="cf-chart__reserve" x1={PAD.left} x2={W - PAD.right} y1={geo.y(reserve)} y2={geo.y(reserve)} />
        <text className="cf-chart__reserve-label" x={W - PAD.right - 4} y={geo.y(reserve) - 6} textAnchor="end">
          Reserve {compact(reserve)}
        </text>
        {baseline.map((d, i) =>
          i % 2 === 0 || i === baseline.length - 1 ? (
            <text key={d.date} className="cf-chart__axis" x={geo.x(i) + colW / 2} y={H - PAD.bottom + 16} textAnchor="middle">
              {i === 0 || d.date.endsWith('-01') ? shortDay(d.date) : Number(d.date.slice(8))}
            </text>
          ) : null,
        )}
        <path className={scenario ? 'cf-chart__line cf-chart__line--muted' : 'cf-chart__line'} d={path(baseline)} />
        {scenario && <path className="cf-chart__line cf-chart__line--scenario" d={path(scenario)} />}
        {(scenario ?? baseline).map((d, i) =>
          d.below_reserve && d.banking_day ? (
            <path
              key={d.date}
              className="cf-chart__breach"
              d={`M${geo.x(i) + colW / 2},${geo.y(d.closing_paise) - 6} l6,6 l-6,6 l-6,-6 z`}
            />
          ) : null,
        )}
        {active >= 0 && <line className="cf-chart__guide" x1={geo.x(active) + colW / 2} x2={geo.x(active) + colW / 2} y1={PAD.top} y2={H - PAD.bottom} />}
        {baseline.map((d, i) => (
          // Pointer hit areas; keyboard users move with the arrow keys on the svg.
          <rect
            key={d.date}
            className="cf-chart__hit"
            x={geo.x(i)}
            y={PAD.top}
            width={colW}
            height={H - PAD.top - PAD.bottom}
            onMouseEnter={() => setFocus(i)}
            onClick={() => onSelectDay(d.date)}
          />
        ))}
      </svg>
      {tip && (
        <div className="cf-chart__tip" aria-live="polite">
          <strong>{day(tip.date)}</strong> · closing ₹{exact(tip.closing_paise)}
          {tipScenario && tipScenario.closing_paise !== tip.closing_paise && <> → scenario ₹{exact(tipScenario.closing_paise)}</>}
          {' · '}in {compact(tip.inflow_paise)} · out {compact(tip.outflow_paise)}
          {(tipScenario ?? tip).below_reserve && <> · below reserve by {rupees(reserve - (tipScenario ?? tip).closing_paise)}</>}
        </div>
      )}
      <figcaption id={descId} className="cf-chart__legend">
        <span className="cf-legend cf-legend--line">{scenario ? 'Baseline' : 'Closing balance'}</span>
        {scenario && <span className="cf-legend cf-legend--scenario">Scenario</span>}
        <span className="cf-legend cf-legend--reserve">Reserve</span>
        <span className="cf-legend cf-legend--breach">Below reserve</span>
        <span className="cf-legend cf-legend--band">Non-banking day</span>
        <span className="cf-chart__hint">Use the arrow keys to move between days and Enter to open one. Daily totals; timing within a day isn't modelled.</span>
      </figcaption>
    </figure>
  )
}
