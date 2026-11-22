/**
 * Cash flow map: where money comes from, where it sits, where it goes.
 *
 * Inflow categories on the left feed the bank in the middle; the bank pays out
 * to outflow categories on the right. Dashed connectors carry animated "coins"
 * so the direction of money reads at a glance. Thicker lines and more coins
 * mean bigger flows. Every number comes from the server's forecast; this
 * component only arranges it.
 */
import { useLayoutEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import {
  ArrowDownLeft, ArrowUpRight, Banknote, Building2, CircleDollarSign, Factory, HandCoins, Landmark, Receipt,
  RotateCcw, Settings2, ShieldCheck, Truck, Users, Wallet, Zap,
} from 'lucide-react'
import { CATEGORY_LABELS, compact, shortDay, stamp } from './format'
import { VIEWS, type ForecastResult, type SnapshotRef } from './types'
import './cash-flow-map.css'

type Dir = 'in' | 'out'
interface Flow {
  key: string
  dir: Dir
  cat: string
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
    cat: f.cat,
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
      cat: 'other',
      label: `${tail.length} more`,
      sub: tail.map(f => CATEGORY_LABELS[f.cat] ?? f.cat).join(' · '),
      paise,
      share: paise / total,
    })
  }
  return out
}

interface Wire {
  key: string
  dir: Dir
  d: string
  width: number
  coins: number
  dur: number
}

export default function CashFlowMap({ result, snapshot, scenario }: { result: ForecastResult; snapshot: SnapshotRef; scenario: boolean }) {
  const ins = useMemo(() => flows(result, 'in'), [result])
  const outs = useMemo(() => flows(result, 'out'), [result])
  const [hover, setHover] = useState<string | null>(null)

  const wrap = useRef<HTMLDivElement>(null)
  const hub = useRef<HTMLDivElement>(null)
  const cards = useRef(new Map<string, HTMLElement>())
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
      // Stacked layout on narrow screens: no wires.
      if (c.left - box.left < 40) return setWires([])
      const all = Math.max(1, ...[...ins, ...outs].map(f => f.paise))
      const wiresFor = (list: Flow[], dir: Dir): Wire[] =>
        list.flatMap((f, i) => {
          const el = cards.current.get(f.key)
          if (!el) return []
          const r = el.getBoundingClientRect()
          const cy = r.top + r.height / 2 - box.top
          const slot = list.length === 1 ? 0.5 : 0.22 + (0.56 * i) / (list.length - 1)
          const hy = c.top - box.top + c.height * slot
          const [x1, y1, x2, y2] =
            dir === 'in'
              ? [r.right - box.left, cy, c.left - box.left, hy]
              : [c.right - box.left, hy, r.left - box.left, cy]
          const mx = (x1 + x2) / 2
          const weight = f.paise / all
          return [
            {
              key: f.key,
              dir,
              d: `M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2},${y2}`,
              width: 1.25 + weight * 2.75,
              coins: Math.max(1, Math.round(weight * 4)),
              dur: 3.2 - weight * 1.2,
            },
          ]
        })
      setWires([...wiresFor(ins, 'in'), ...wiresFor(outs, 'out')])
    }
    measure()
    const ro = new ResizeObserver(measure)
    ro.observe(root)
    return () => ro.disconnect()
  }, [ins, outs])

  const totalIn = result.metrics.total_inflow_paise
  const totalOut = result.metrics.total_outflow_paise
  const net = totalIn - totalOut
  const end = result.days[result.days.length - 1]?.date ?? snapshot.end
  const lowBelow = result.metrics.minimum_closing_paise < result.reserve_paise
  const inPct = totalIn + totalOut ? (100 * totalIn) / (totalIn + totalOut) : 50
  const viewLabel = VIEWS.find(v => v.key === result.view)?.label ?? result.view

  const bind = (key: string) => ({
    ref: (el: HTMLElement | null) => {
      if (el) cards.current.set(key, el)
      else cards.current.delete(key)
    },
    onMouseEnter: () => setHover(key),
    onMouseLeave: () => setHover(null),
  })

  return (
    <section className="cfm" aria-labelledby="cfm-title">
      <header className="cfm__bar">
        <div className="cfm__bar-left">
          <h2 id="cfm-title">How cash moves</h2>
          <span className="cfm__live">
            <i aria-hidden="true" /> Live
          </span>
          <span className="cf-muted cf-small">
            Today → {shortDay(end)} · {result.days.length} days{scenario ? ' · with scenario' : ''}
          </span>
        </div>
        <span className="cf-muted cf-small cfm__bar-right">Synced {stamp(snapshot.as_of)}</span>
      </header>

      <div className="cfm__stage" ref={wrap}>
        <svg className="cfm__wires" width={size.w} height={size.h} aria-hidden="true">
          {wires.map(w => {
            const state = hover == null ? '' : hover === w.key ? ' is-on' : ' is-off'
            return (
              <g key={w.key} className={`cfm__wire cfm__wire--${w.dir}${state}`}>
                <path d={w.d} className="cfm__track" strokeWidth={w.width} />
                <path d={w.d} className="cfm__dash" strokeWidth={w.width} style={{ animationDuration: `${w.dur}s` }} />
                {Array.from({ length: w.coins }, (_, i) => (
                  <circle key={i} r={2.5 + w.width / 2} className="cfm__coin">
                    <animateMotion dur={`${w.dur}s`} begin={`${(-w.dur * i) / w.coins}s`} repeatCount="indefinite" path={w.d} />
                  </circle>
                ))}
              </g>
            )
          })}
        </svg>

        <div className="cfm__col">
          <p className="cfm__eyebrow cfm__eyebrow--in">
            <ArrowDownLeft size={12} /> Money coming in
          </p>
          {ins.length ? (
            ins.map(f => <FlowCard key={f.key} f={f} bind={bind(f.key)} dim={hover != null && hover !== f.key} />)
          ) : (
            <div className="cfm-card cfm-card--empty">No collections counted in the {viewLabel.toLowerCase()} view.</div>
          )}
        </div>

        <div className="cfm__hub" ref={hub}>
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
                  {snapshot.balances.length} account{snapshot.balances.length === 1 ? '' : 's'} · as of {stamp(snapshot.as_of)}
                </span>
              </div>
            </div>
            <table className="cfm__table">
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
                  <td>Coming in</td>
                  <td className="cf-num">{compact(totalIn, { sign: true })}</td>
                </tr>
                <tr className="cfm__row-out">
                  <td className="cfm__mono">
                    <ArrowUpRight size={12} />
                  </td>
                  <td>Going out</td>
                  <td className="cf-num">{compact(-totalOut)}</td>
                </tr>
                <tr className={lowBelow ? 'cfm__row-low is-bad' : 'cfm__row-low'}>
                  <td />
                  <td>Lowest · {shortDay(result.metrics.minimum_date)}</td>
                  <td className="cf-num">{compact(result.metrics.minimum_closing_paise)}</td>
                </tr>
              </tbody>
              <tfoot>
                <tr>
                  <td colSpan={2}>
                    {shortDay(end)} <span className="cfm__pill">Forecasting…</span>
                  </td>
                  <td className="cf-num">{compact(result.metrics.closing_paise)}</td>
                </tr>
              </tfoot>
            </table>
          </div>

          <div className="cfm__split" aria-label={`${compact(totalIn)} in versus ${compact(totalOut)} out`}>
            <div className="cfm__split-bar">
              <i className="cfm__split-in" style={{ width: `${inPct}%` }} />
              <i className="cfm__split-out" style={{ width: `${100 - inPct}%` }} />
            </div>
            <div className="cfm__split-legend cf-small">
              <span className="cf-in">In {compact(totalIn)}</span>
              <span className={net >= 0 ? 'cf-good' : 'cf-bad'}>Net {compact(net, { sign: true })}</span>
              <span className="cfm__out-text">Out {compact(totalOut)}</span>
            </div>
          </div>
        </div>

        <div className="cfm__col">
          <p className="cfm__eyebrow cfm__eyebrow--out">
            Money going out <ArrowUpRight size={12} />
          </p>
          {outs.length ? (
            outs.map(f => <FlowCard key={f.key} f={f} bind={bind(f.key)} dim={hover != null && hover !== f.key} />)
          ) : (
            <div className="cfm-card cfm-card--empty">No payments due in this horizon.</div>
          )}
        </div>
      </div>
    </section>
  )
}

function FlowCard({
  f,
  bind,
  dim,
}: {
  f: Flow
  bind: {
    ref: (el: HTMLElement | null) => void
    onMouseEnter: () => void
    onMouseLeave: () => void
  }
  dim: boolean
}) {
  return (
    <article className={`cfm-card cfm-card--${f.dir}${dim ? ' is-dim' : ''}`} {...bind}>
      <div className="cfm-card__head">
        <span className={`cfm-card__icon cfm-cat--${f.cat}`}>{ICONS[f.cat] ?? ICONS.other}</span>
        <div className="cfm-card__titles">
          <strong>{f.label}</strong>
          <span className="cf-muted cf-small">{f.sub}</span>
        </div>
      </div>
      <div className="cfm-card__value">
        <span className="cfm-card__amount">
          {f.dir === 'in' ? '+' : '−'}
          {compact(f.paise)}
        </span>
        <span className="cf-muted cf-small">{Math.round(f.share * 100)}% of money {f.dir}</span>
      </div>
      <span className="cfm-card__meter" aria-hidden="true">
        <i style={{ width: `${Math.max(4, f.share * 100)}%` }} />
      </span>
    </article>
  )
}
