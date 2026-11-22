/**
 * Cash flow map: where money comes from, where it sits, where it goes — and
 * how that plays out day by day.
 *
 * Inflow categories on the left feed the bank in the middle; the bank pays out
 * to outflow categories on the right. A playback steps through the forecast
 * one day at a time: on each day, coins travel along the wires of exactly the
 * categories that move money that day, the card totals count up, and the bank
 * balance ticks to that day's closing figure.
 *
 * Every number comes from the server. The bank line is the forecast's own day
 * rows; per-category amounts come from the dated events (bucketed the way the
 * engine buckets them) and are only shown when they reconcile to the
 * forecast's category totals. Otherwise the cards show totals and the coins are
 * decoration.
 */
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import {
  ArrowDownLeft, ArrowUpRight, Banknote, Building2, CircleDollarSign, Factory, HandCoins, Landmark, Pause, Play,
  Receipt, RotateCcw, Settings2, ShieldCheck, Truck, Users, Wallet, Zap,
} from 'lucide-react'
import { api } from './api'
import { CATEGORY_LABELS, compact, day, shortDay, stamp } from './format'
import { VIEWS, type CashEvent, type ForecastResult, type SnapshotRef } from './types'
import './cash-flow-map.css'

type Dir = 'in' | 'out'
interface Flow {
  key: string
  dir: Dir
  cats: string[]
  icon: string
  label: string
  sub: string
  paise: number
  share: number
}

const ICONS: Record<string, ReactNode> = {
  customer: <HandCoins size={16} />,
  supplier: <Truck size={16} />,
  payroll: <Users size={16} />,
  statutory: <Receipt size={16} />,
  rent: <Building2 size={16} />,
  debt: <Landmark size={16} />,
  utilities: <Zap size={16} />,
  operations: <Settings2 size={16} />,
  insurance: <ShieldCheck size={16} />,
  capex: <Factory size={16} />,
  refund: <RotateCcw size={16} />,
  financing: <Banknote size={16} />,
  other: <CircleDollarSign size={16} />,
}

const SUBS: Record<string, [string, string]> = {
  // [as inflow, as outflow]
  customer: ['Customer invoices · expected receipts', 'Customer payments'],
  supplier: ['Supplier credits', 'Vendor bills · agreed terms'],
  payroll: ['Payroll reversals', 'Salaries & reimbursements'],
  statutory: ['Tax refunds', 'GST · TDS · PF / ESI'],
  rent: ['Sub-lease income', 'Office & warehouse lease'],
  debt: ['Loan disbursals', 'Loan EMIs'],
  utilities: ['Deposits returned', 'Power · internet · phone'],
  operations: ['Operating income', 'Day-to-day running costs'],
  insurance: ['Claims received', 'Policy premiums'],
  capex: ['Asset sales', 'Equipment & fit-outs'],
  refund: ['Refunds owed to you', 'Refunds to customers'],
  financing: ['Loans · credit drawdowns', 'Repayments'],
  other: ['Everything else', 'Everything else'],
}

const MAX_CARDS = 4
const SPEEDS = [1, 2, 4]

function flows(result: ForecastResult, dir: Dir): Flow[] {
  const list = Object.entries(result.category_totals)
    .filter(([k, v]) => k.startsWith(`${dir}:`) && v > 0)
    .map(([k, v]) => ({ cat: k.slice(dir.length + 1), paise: v }))
    .sort((a, b) => b.paise - a.paise)
  const total = list.reduce((s, f) => s + f.paise, 0) || 1
  const head = list.length > MAX_CARDS ? list.slice(0, MAX_CARDS - 1) : list
  const tail = list.length > MAX_CARDS ? list.slice(MAX_CARDS - 1) : []
  const out: Flow[] = head.map(f => ({
    key: `${dir}:${f.cat}`,
    dir,
    cats: [f.cat],
    icon: f.cat,
    label: CATEGORY_LABELS[f.cat] ?? f.cat,
    sub: (SUBS[f.cat] ?? SUBS.other)[dir === 'in' ? 0 : 1],
    paise: f.paise,
    share: f.paise / total,
  }))
  if (tail.length) {
    const paise = tail.reduce((s, f) => s + f.paise, 0)
    out.push({
      key: `${dir}:__rest`,
      dir,
      cats: tail.map(f => f.cat),
      icon: 'other',
      label: `${tail.length} more`,
      sub: tail.map(f => CATEGORY_LABELS[f.cat] ?? f.cat).join(' · '),
      paise,
      share: paise / total,
    })
  }
  return out
}

/** Per-card, per-day amounts, plus the events landing on each day. */
interface Timeline {
  exact: boolean
  perDay: Record<string, number[]>
  byDay: CashEvent[][]
}

function timeline(result: ForecastResult, all: Flow[], events: CashEvent[] | null): Timeline {
  const n = result.days.length
  const index = new Map(result.days.map((d, i) => [d.date, i]))
  const start = result.days[0]?.date ?? ''
  const end = result.days[n - 1]?.date ?? ''
  const cardOf = new Map<string, string>()
  all.forEach(f => f.cats.forEach(c => cardOf.set(`${f.dir}:${c}`, f.key)))
  const perDay: Record<string, number[]> = Object.fromEntries(all.map(f => [f.key, new Array<number>(n).fill(0)]))
  const byDay: CashEvent[][] = Array.from({ length: n }, () => [])

  for (const e of events ?? []) {
    if (!e.date || e.date > end) continue
    const i = e.date < start ? 0 : index.get(e.date)
    const card = cardOf.get(`${e.direction}:${e.category}`)
    if (i == null || !card) continue
    perDay[card][i] += e.amount_paise
    byDay[i].push(e)
  }
  byDay.forEach(list => list.sort((a, b) => b.amount_paise - a.amount_paise))

  const exact = all.length > 0 && all.every(f => perDay[f.key].reduce((s, v) => s + v, 0) === f.paise)
  if (exact) return { exact, perDay, byDay }

  // Events don't reconcile (scenario preview, or not loaded): spread each day's
  // bank movement across cards by share so the coins still move on the right
  // days. These figures drive animation only, never a displayed number.
  for (const f of all) {
    perDay[f.key] = result.days.map(d => (f.dir === 'in' ? d.inflow_paise : d.outflow_paise) * f.share)
  }
  return { exact: false, perDay, byDay: byDay.map(() => []) }
}

/** Eases a displayed number toward its target. */
function useTween(target: number, ms = 450): number {
  const [value, setValue] = useState(target)
  const from = useRef(target)
  useEffect(() => {
    if (typeof requestAnimationFrame === 'undefined' || from.current === target) {
      from.current = target
      setValue(target)
      return
    }
    const a = from.current
    const t0 = performance.now()
    let id = 0
    const step = (now: number) => {
      const k = Math.max(0, Math.min(1, (now - t0) / ms))
      const x = a + (target - a) * (1 - (1 - k) ** 3)
      from.current = x
      setValue(x)
      if (k < 1) id = requestAnimationFrame(step)
    }
    id = requestAnimationFrame(step)
    // Frames can be throttled (background tab); always land on the exact figure.
    const done = setTimeout(() => {
      cancelAnimationFrame(id)
      from.current = target
      setValue(target)
    }, ms + 60)
    return () => {
      cancelAnimationFrame(id)
      clearTimeout(done)
    }
  }, [target, ms])
  return value
}

const reducedMotion = () => typeof window !== 'undefined' && !!window.matchMedia?.('(prefers-reduced-motion: reduce)').matches

interface Wire {
  key: string
  dir: Dir
  d: string
  width: number
}

interface Coin {
  el: SVGCircleElement
  path: SVGPathElement
  len: number
  t0: number
  dur: number
  dir: Dir
}

export default function CashFlowMap({ result, snapshot, scenario }: { result: ForecastResult; snapshot: SnapshotRef; scenario: boolean }) {
  const ins = useMemo(() => flows(result, 'in'), [result])
  const outs = useMemo(() => flows(result, 'out'), [result])
  const all = useMemo(() => [...ins, ...outs], [ins, outs])
  const days = result.days
  const n = days.length
  const [hover, setHover] = useState<string | null>(null)

  // ── Events for per-category timing (baseline only; a preview moves events) ──
  const [events, setEvents] = useState<CashEvent[] | null>(null)
  useEffect(() => {
    setEvents(null)
    if (scenario) return
    let live = true
    api
      .events(snapshot.snapshot_id, result.view)
      .then(e => live && setEvents(e))
      .catch(() => undefined)
    return () => {
      live = false
    }
  }, [snapshot.snapshot_id, result.view, scenario])
  const tl = useMemo(() => timeline(result, all, events), [result, all, events])

  // ── Playback: step −1 is "today, before anything lands"; n − 1 is the last day ──
  const [step, setStep] = useState(n - 1)
  const [playing, setPlaying] = useState(false)
  const [speed, setSpeed] = useState(1)
  const interval = Math.min(900, Math.max(250, 18000 / Math.max(1, n))) / speed
  useEffect(() => setStep(s => Math.min(s, n - 1)), [n])
  useEffect(() => {
    if (!playing) return
    const id = setInterval(() => {
      setStep(s => {
        if (s >= n - 1) {
          setPlaying(false)
          return s
        }
        return s + 1
      })
    }, interval)
    return () => clearInterval(id)
  }, [playing, interval, n])

  const play = () => {
    if (step >= n - 1) setStep(-1)
    setPlaying(true)
  }

  // Start once, the first time the map scrolls into view.
  const section = useRef<HTMLElement>(null)
  useEffect(() => {
    const el = section.current
    if (!el || typeof IntersectionObserver === 'undefined' || reducedMotion()) return
    const io = new IntersectionObserver(
      entries => {
        if (!entries.some(e => e.isIntersecting)) return
        io.disconnect()
        setStep(-1)
        setPlaying(true)
      },
      { threshold: 0.35 },
    )
    io.observe(el)
    return () => io.disconnect()
  }, [])

  // ── Wires ──
  const wrap = useRef<HTMLDivElement>(null)
  const hub = useRef<HTMLDivElement>(null)
  const cards = useRef(new Map<string, HTMLElement>())
  const paths = useRef(new Map<string, SVGPathElement>())
  const [wires, setWires] = useState<Wire[]>([])
  const [size, setSize] = useState({ w: 0, h: 0 })

  useLayoutEffect(() => {
    const root = wrap.current
    const center = hub.current
    if (!root || !center) return
    const measure = () => {
      const box = root.getBoundingClientRect()
      const c = center.getBoundingClientRect()
      setSize({ w: box.width, h: box.height })
      if (c.left - box.left < 40) return setWires([]) // stacked layout: no wires
      const max = Math.max(1, ...all.map(f => f.paise))
      const wiresFor = (list: Flow[], dir: Dir): Wire[] =>
        list.flatMap((f, i) => {
          const el = cards.current.get(f.key)
          if (!el) return []
          const r = el.getBoundingClientRect()
          const cy = r.top + r.height / 2 - box.top
          const slot = list.length === 1 ? 0.5 : 0.22 + (0.56 * i) / (list.length - 1)
          const hy = c.top - box.top + c.height * slot
          const [x1, y1, x2, y2] =
            dir === 'in' ? [r.right - box.left, cy, c.left - box.left, hy] : [c.right - box.left, hy, r.left - box.left, cy]
          const mx = (x1 + x2) / 2
          return [{ key: f.key, dir, d: `M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2},${y2}`, width: 1.25 + (f.paise / max) * 2.75 }]
        })
      setWires([...wiresFor(ins, 'in'), ...wiresFor(outs, 'out')])
    }
    measure()
    const ro = new ResizeObserver(measure)
    ro.observe(root)
    ro.observe(center)
    cards.current.forEach(el => ro.observe(el))
    return () => ro.disconnect()
  }, [all, ins, outs])

  // ── Coins: spawned per day for the categories that move money that day ──
  const layer = useRef<SVGGElement>(null)
  const balanceEl = useRef<HTMLTableRowElement>(null)
  const coins = useRef<Coin[]>([])
  const frame = useRef(0)

  const bump = useCallback((dir: Dir) => {
    const el = balanceEl.current
    if (!el) return
    el.classList.remove('is-bump-in', 'is-bump-out')
    void el.offsetWidth // restart the CSS animation
    el.classList.add(`is-bump-${dir}`)
  }, [])

  const tick = useCallback(
    (now: number) => {
      coins.current = coins.current.filter(c => {
        const k = (now - c.t0) / c.dur
        if (k < 0) return true
        if (k >= 1) {
          c.el.remove()
          if (c.dir === 'in') bump('in')
          return false
        }
        const e = k < 0.5 ? 2 * k * k : 1 - (-2 * k + 2) ** 2 / 2
        const pt = c.path.getPointAtLength(e * c.len)
        c.el.setAttribute('cx', String(pt.x))
        c.el.setAttribute('cy', String(pt.y))
        c.el.style.opacity = String(Math.min(1, k * 6, (1 - k) * 6))
        return true
      })
      frame.current = coins.current.length ? requestAnimationFrame(tick) : 0
    },
    [bump],
  )

  useEffect(() => {
    const g = layer.current
    if (step < 0 || !g || !wires.length || reducedMotion() || typeof requestAnimationFrame === 'undefined') return
    const maxCell = Math.max(1, ...all.flatMap(f => tl.perDay[f.key]))
    const now = performance.now()
    const dur = Math.max(450, interval * 1.15)
    let anyOut = false
    for (const f of all) {
      const amount = tl.perDay[f.key][step]
      const path = paths.current.get(f.key)
      if (!amount || !path || amount <= 0) continue
      const weight = amount / maxCell
      const count = 1 + Math.round(weight * 4)
      const len = path.getTotalLength()
      for (let i = 0; i < count; i++) {
        const el = document.createElementNS('http://www.w3.org/2000/svg', 'circle')
        el.setAttribute('r', String(2.5 + weight * 3))
        el.setAttribute('class', `cfm__coin cfm__coin--${f.dir}`)
        el.style.opacity = '0'
        g.appendChild(el)
        coins.current.push({ el, path, len, t0: now + i * Math.min(110, dur / (count + 2)), dur, dir: f.dir })
      }
      if (f.dir === 'out') anyOut = true
    }
    if (anyOut) bump('out')
    if (!frame.current && coins.current.length) frame.current = requestAnimationFrame(tick)
  }, [step, wires.length, all, tl, interval, tick, bump])

  useEffect(
    () => () => {
      cancelAnimationFrame(frame.current)
      coins.current.forEach(c => c.el.remove())
      coins.current = []
    },
    [],
  )

  // ── Figures at the current step ──
  const upto = days.slice(0, step + 1)
  const cumIn = upto.reduce((s, d) => s + d.inflow_paise, 0)
  const cumOut = upto.reduce((s, d) => s + d.outflow_paise, 0)
  const balance = step < 0 ? result.opening_paise : days[step].closing_paise
  const lowest = upto.reduce((m, d) => (d.closing_paise < m.paise ? { paise: d.closing_paise, date: d.date } : m), {
    paise: result.opening_paise,
    date: '',
  })
  const today = step >= 0 ? days[step] : null
  const todayNet = today ? today.inflow_paise - today.outflow_paise : 0
  const below = balance < result.reserve_paise
  const end = days[n - 1]?.date ?? snapshot.end
  const viewLabel = VIEWS.find(v => v.key === result.view)?.label ?? result.view

  const tBalance = useTween(balance)
  const tIn = useTween(cumIn)
  const tOut = useTween(cumOut)
  const inPct = cumIn + cumOut ? (100 * cumIn) / (cumIn + cumOut) : 50
  const landing = step >= 0 ? tl.byDay[step].slice(0, 3) : []
  const landingMore = step >= 0 ? tl.byDay[step].length - landing.length : 0

  const bind = (key: string) => ({
    ref: (el: HTMLElement | null) => {
      if (el) cards.current.set(key, el)
      else cards.current.delete(key)
    },
    onMouseEnter: () => setHover(key),
    onMouseLeave: () => setHover(null),
  })

  const card = (f: Flow) => {
    const series = tl.perDay[f.key]
    const sofar = series.slice(0, step + 1).reduce((s, v) => s + v, 0)
    return (
      <FlowCard
        key={f.key}
        f={f}
        exact={tl.exact}
        sofar={tl.exact ? sofar : f.paise}
        todayPaise={tl.exact && step >= 0 ? series[step] : 0}
        step={step}
        bind={bind(f.key)}
        dim={hover != null && hover !== f.key}
      />
    )
  }

  return (
    <section className="cfm" aria-labelledby="cfm-title" ref={section}>
      <header className="cfm__bar">
        <div className="cfm__bar-left">
          <h2 id="cfm-title">How cash moves</h2>
          <span className={`cfm__live${playing ? '' : ' is-paused'}`}>
            <i aria-hidden="true" /> {playing ? 'Playing' : 'Live'}
          </span>
          <span className="cf-muted cf-small">
            Today → {shortDay(end)} · {n} days{scenario ? ' · with scenario' : ''}
          </span>
        </div>
        <span className="cf-muted cf-small cfm__bar-right">Synced {stamp(snapshot.as_of)}</span>
      </header>

      <div className="cfm__stage" ref={wrap}>
        <svg className="cfm__wires" width={size.w} height={size.h} aria-hidden="true">
          {wires.map(w => {
            const active = step >= 0 && (tl.perDay[w.key]?.[step] ?? 0) > 0
            const state = hover == null ? '' : hover === w.key ? ' is-on' : ' is-off'
            return (
              <g key={w.key} className={`cfm__wire cfm__wire--${w.dir}${state}${active ? ' is-active' : ''}`}>
                <path d={w.d} className="cfm__track" strokeWidth={w.width} />
                <path
                  d={w.d}
                  className="cfm__dash"
                  strokeWidth={w.width}
                  ref={el => {
                    if (el) paths.current.set(w.key, el)
                    else paths.current.delete(w.key)
                  }}
                />
              </g>
            )
          })}
          <g ref={layer} />
        </svg>

        <div className="cfm__col">
          <p className="cfm__eyebrow cfm__eyebrow--in">
            <ArrowDownLeft size={12} /> Money coming in
          </p>
          {ins.length ? ins.map(card) : <div className="cfm-card cfm-card--empty">No collections counted in the {viewLabel.toLowerCase()} view.</div>}
        </div>

        <div className={`cfm__hub${below ? ' is-below' : ''}`} ref={hub}>
          <div className="cfm__hub-head">
            <span className="cfm__tag cfm__tag--brand">
              <Wallet size={12} /> Bank
            </span>
            <strong>Cash position</strong>
            <span className="cf-muted cf-small cfm__hub-note">every receipt and payment, dated</span>
          </div>
          <div className="cfm__tags">
            <span className="cfm__tag">{viewLabel} view</span>
            <span className="cfm__tag">Reserve {compact(result.reserve_paise)}</span>
            <span className="cfm__tag">Revision {snapshot.revision}</span>
          </div>

          <div className="cfm__ledger">
            <div className="cfm__ledger-head">
              <span className="cfm__ledger-icon">
                <Landmark size={14} />
              </span>
              <div>
                <strong>Bank accounts</strong>
                <span className="cf-muted cf-small">
                  {snapshot.balances.length} account{snapshot.balances.length === 1 ? '' : 's'} · opening, {stamp(snapshot.as_of)}
                </span>
              </div>
            </div>
            <table className="cfm__table">
              <colgroup>
                <col className="cfm__col-acct" />
                <col />
                <col className="cfm__col-amt" />
              </colgroup>
              <thead>
                <tr>
                  <th scope="col">Acct</th>
                  <th scope="col">Name</th>
                  <th scope="col" className="cf-num">
                    Balance
                  </th>
                </tr>
              </thead>
              <tbody>
                {snapshot.balances.map(b => (
                  <tr key={b.bank_account_id}>
                    <td className="cfm__mono">{b.account_mask ?? '—'}</td>
                    <td>{b.account_name}</td>
                    <td className="cf-num">{compact(b.balance_paise)}</td>
                  </tr>
                ))}
                <tr className="cfm__row-strong">
                  <td />
                  <td>Cash today</td>
                  <td className="cf-num">{compact(result.opening_paise)}</td>
                </tr>
                <tr className="cfm__row-in">
                  <td className="cfm__mono">
                    <ArrowDownLeft size={12} />
                  </td>
                  <td>Came in so far</td>
                  <td className="cf-num">{compact(Math.round(tIn), { sign: true })}</td>
                </tr>
                <tr className="cfm__row-out">
                  <td className="cfm__mono">
                    <ArrowUpRight size={12} />
                  </td>
                  <td>Went out so far</td>
                  <td className="cf-num">{compact(-Math.round(tOut))}</td>
                </tr>
                <tr className={lowest.paise < result.reserve_paise ? 'cfm__row-low is-bad' : 'cfm__row-low'}>
                  <td />
                  <td>Lowest so far{lowest.date ? ` · ${shortDay(lowest.date)}` : ''}</td>
                  <td className="cf-num">{compact(lowest.paise)}</td>
                </tr>
              </tbody>
              <tfoot>
                <tr ref={balanceEl} className="cfm__balance">
                  <td colSpan={2} className="cfm__balance-label">
                    <span className="cfm__balance-date">{today ? day(today.date) : 'Today, opening'}</span>
                    {today && todayNet !== 0 && (
                      <span key={step} className={`cfm__delta ${todayNet > 0 ? 'is-in' : 'is-out'}`}>
                        {compact(todayNet, { sign: true })} today
                      </span>
                    )}
                  </td>
                  <td className={`cf-num cfm__balance-value${below ? ' is-bad' : ''}`}>{compact(Math.round(tBalance))}</td>
                </tr>
              </tfoot>
            </table>
          </div>

          {tl.exact && (
            <div className="cfm__landing" aria-live="off">
              <p className="cfm__landing-title">
                <span>{today ? `Landing ${shortDay(today.date)}` : 'Press play to watch each day land'}</span>
                {landingMore > 0 && <span>+{landingMore} more</span>}
              </p>
              <ul key={step}>
                {today && !landing.length && <li className="cf-muted cf-small">Nothing moves today.</li>}
                {landing.map(e => (
                  <li key={e.event_key} className={`cfm__land cfm__land--${e.direction}`}>
                    {e.direction === 'in' ? <ArrowDownLeft size={12} /> : <ArrowUpRight size={12} />}
                    <span className="cfm__land-label">
                      {e.counterparty ?? e.label}
                      {e.document_number ? <span className="cf-muted"> · {e.document_number}</span> : null}
                    </span>
                    <span className="cfm__land-amt">
                      {e.direction === 'in' ? '+' : '−'}
                      {compact(e.amount_paise)}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          <div className="cfm__split" aria-label={`${compact(cumIn)} in versus ${compact(cumOut)} out so far`}>
            <div className="cfm__split-bar">
              <i className="cfm__split-in" style={{ width: `${inPct}%` }} />
              <i className="cfm__split-out" style={{ width: `${100 - inPct}%` }} />
            </div>
            <div className="cfm__split-legend cf-small">
              <span className="cf-in">In {compact(cumIn)}</span>
              <span className={cumIn - cumOut >= 0 ? 'cf-good' : 'cf-bad'}>Net {compact(cumIn - cumOut, { sign: true })}</span>
              <span className="cfm__out-text">Out {compact(cumOut)}</span>
            </div>
          </div>
        </div>

        <div className="cfm__col">
          <p className="cfm__eyebrow cfm__eyebrow--out">
            Money going out <ArrowUpRight size={12} />
          </p>
          {outs.length ? outs.map(card) : <div className="cfm-card cfm-card--empty">No payments due in this horizon.</div>}
        </div>
      </div>

      <Scrubber
        result={result}
        step={step}
        playing={playing}
        speed={speed}
        onPlay={play}
        onPause={() => setPlaying(false)}
        onSeek={s => {
          setPlaying(false)
          setStep(s)
        }}
        onSpeed={() => setSpeed(s => SPEEDS[(SPEEDS.indexOf(s) + 1) % SPEEDS.length])}
      />
    </section>
  )
}

function FlowCard({
  f,
  exact,
  sofar,
  todayPaise,
  step,
  bind,
  dim,
}: {
  f: Flow
  exact: boolean
  sofar: number
  todayPaise: number
  step: number
  bind: { ref: (el: HTMLElement | null) => void; onMouseEnter: () => void; onMouseLeave: () => void }
  dim: boolean
}) {
  const shown = useTween(sofar)
  const progress = exact ? sofar / (f.paise || 1) : f.share
  return (
    <article className={`cfm-card cfm-card--${f.dir}${dim ? ' is-dim' : ''}`} {...bind}>
      {todayPaise > 0 && <span key={step} className="cfm-card__flash" aria-hidden="true" />}
      <div className="cfm-card__head">
        <span className={`cfm-card__icon cfm-cat--${f.icon}`}>{ICONS[f.icon] ?? ICONS.other}</span>
        <div className="cfm-card__titles">
          <strong>{f.label}</strong>
          <span className="cf-muted cf-small">{f.sub}</span>
        </div>
      </div>
      <div className="cfm-card__value">
        <span className="cfm-card__amount">
          {f.dir === 'in' ? '+' : '−'}
          {compact(Math.round(shown))}
        </span>
        {todayPaise > 0 && (
          <span key={`chip-${step}`} className="cfm-card__today">
            {f.dir === 'in' ? '+' : '−'}
            {compact(todayPaise)} today
          </span>
        )}
      </div>
      <span className="cf-muted cf-small cfm-card__of">
        {exact ? `of ${compact(f.paise)} · ${Math.round(f.share * 100)}% of money ${f.dir}` : `${Math.round(f.share * 100)}% of money ${f.dir}`}
      </span>
      <span className="cfm-card__meter" aria-hidden="true">
        <i style={{ width: `${Math.max(exact ? 0 : 4, progress * 100)}%` }} />
      </span>
    </article>
  )
}

/** Play controls over a sparkline of the closing balance. */
function Scrubber({
  result,
  step,
  playing,
  speed,
  onPlay,
  onPause,
  onSeek,
  onSpeed,
}: {
  result: ForecastResult
  step: number
  playing: boolean
  speed: number
  onPlay: () => void
  onPause: () => void
  onSeek: (s: number) => void
  onSpeed: () => void
}) {
  const days = result.days
  const n = days.length
  // Points: index 0 is the opening balance, 1..n the daily closings.
  const values = [result.opening_paise, ...days.map(d => d.closing_paise)]
  const lo = Math.min(...values, result.reserve_paise)
  const hi = Math.max(...values, result.reserve_paise)
  const W = 1000
  const H = 64
  const x = (i: number) => (i / Math.max(1, n)) * W
  const y = (v: number) => H - 6 - ((v - lo) / (hi - lo || 1)) * (H - 12)
  const line = values.map((v, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(' ')
  const area = `${line} L${W},${H} L0,${H} Z`
  const cx = x(step + 1)
  const cy = y(values[step + 1])
  const ry = y(result.reserve_paise)
  const lowIdx = days.findIndex(d => d.date === result.metrics.minimum_date)

  return (
    <div className="cfm__scrub">
      <div className="cfm__scrub-controls">
        <button type="button" className="cfm__btn cfm__btn--primary" onClick={playing ? onPause : onPlay} aria-label={playing ? 'Pause' : 'Play'}>
          {playing ? <Pause size={14} /> : <Play size={14} />}
        </button>
        <button type="button" className="cfm__btn" onClick={onSpeed} aria-label={`Speed ${speed}x`}>
          {speed}×
        </button>
      </div>
      <div className="cfm__scrub-track">
        <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" aria-hidden="true">
          <defs>
            <clipPath id="cfm-played">
              <rect x="0" y="0" width={cx} height={H} />
            </clipPath>
          </defs>
          <path d={area} className="cfm__spark-area" />
          <path d={line} className="cfm__spark-line" />
          <g clipPath="url(#cfm-played)">
            <path d={area} className="cfm__spark-area is-played" />
            <path d={line} className="cfm__spark-line is-played" />
          </g>
          {result.reserve_paise > 0 && <line x1="0" x2={W} y1={ry} y2={ry} className="cfm__spark-reserve" />}
          <line x1={cx} x2={cx} y1="0" y2={H} className="cfm__spark-cursor" />
        </svg>
        <span className="cfm__spark-dot" style={{ left: `${(cx / W) * 100}%`, top: `${(cy / H) * 100}%` }} />
        {lowIdx >= 0 && (
          <span className="cfm__spark-low" style={{ left: `${(x(lowIdx + 1) / W) * 100}%` }}>
            Lowest
          </span>
        )}
        <input
          type="range"
          min={-1}
          max={n - 1}
          step={1}
          value={step}
          onChange={e => onSeek(Number(e.target.value))}
          aria-label="Forecast day"
          aria-valuetext={step < 0 ? 'Today, opening balance' : `${day(days[step].date)}, closing ${compact(days[step].closing_paise)}`}
          className="cfm__scrub-range"
        />
        <div className="cfm__scrub-axis cf-small cf-muted">
          <span>Today</span>
          <span>{days[n - 1] ? shortDay(days[n - 1].date) : ''}</span>
        </div>
      </div>
      <div className="cfm__scrub-day">
        <span className="cf-muted cf-small">{step < 0 ? 'Start' : `Day ${step + 1} of ${n}`}</span>
        <strong>{step < 0 ? 'Opening' : day(days[step].date)}</strong>
      </div>
    </div>
  )
}
