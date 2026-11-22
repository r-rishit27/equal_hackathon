/**
 * Cash flow forecast (docs/cashflow-forecast/06_UI_SPEC.md, S-01).
 *
 * The server owns every number: this page never computes a balance. It shows
 * one sentence that answers "are we OK?", then the evidence behind it.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { AlertTriangle, CheckCircle2, Download, LineChart, RefreshCw, SlidersHorizontal } from 'lucide-react'
import { Badge, Button, EmptyState, ErrorState, Skeleton } from '../../ui'
import { api, ApiError } from './api'
import ForecastChart from './ForecastChart'
import CashFlowMap from './CashFlowMap'
import { DayDrawer, ExclusionsDrawer } from './Drawers'
import InputsDrawer, { BalanceForm, type InputsTab } from './InputsDrawer'
import ScenarioPanel from './ScenarioPanel'
import PlansPanel from './PlansPanel'
import { CATEGORY_LABELS, compact, day, exact, rupees, shortDay, spoken, stamp } from './format'
import { driverLine, summarySentence } from './copy'
import {
  VIEWS, type Account, type CashEvent, type DayRow, type Forecast, type ForecastResult, type Me, type Override,
  type Preview, type Refusal, type Scenario, type SnapshotRef, type View,
} from './types'
import './cash-forecast.css'

type Fatal = { kind: 'access' } | { kind: 'not_set_up'; canEdit: boolean } | { kind: 'no_balance' } | { kind: 'error'; message: string }

export default function CashForecastPage() {
  const [params, setParams] = useSearchParams()
  const view = (VIEWS.some(v => v.key === params.get('view')) ? params.get('view') : 'expected') as View
  const openDay = params.get('day')
  const setParam = useCallback(
    (key: string, value: string | null) =>
      setParams(
        p => {
          const next = new URLSearchParams(p)
          if (value) next.set(key, value)
          else next.delete(key)
          return next
        },
        { replace: key === 'day' },
      ),
    [setParams],
  )

  const [me, setMe] = useState<Me | null>(null)
  const [snapshot, setSnapshot] = useState<SnapshotRef | null>(null)
  const [fatal, setFatal] = useState<Fatal | null>(null)
  const [forecast, setForecast] = useState<Forecast | null>(null)
  const [floor, setFloor] = useState<Forecast | null>(null)
  const [accounts, setAccounts] = useState<Account[]>([])
  const [loadError, setLoadError] = useState('')
  const [refreshing, setRefreshing] = useState(false)
  const [notice, setNotice] = useState('')
  const [overrides, setOverrides] = useState<Override[]>([])
  const [preview, setPreview] = useState<Preview | null>(null)
  const [refusals, setRefusals] = useState<Refusal[]>([])
  const [previewing, setPreviewing] = useState(false)
  const [scenarios, setScenarios] = useState<Scenario[]>([])
  const [activeScenario, setActiveScenario] = useState<Scenario | null>(null)
  const [exclusionsOpen, setExclusionsOpen] = useState(false)
  const [inputs, setInputs] = useState<{ open: boolean; tab: InputsTab }>({ open: false, tab: 'balances' })
  const [showAll, setShowAll] = useState(false)
  const [plansKey, setPlansKey] = useState(0)
  const [minDayEvents, setMinDayEvents] = useState<CashEvent[]>([])
  const [attempt, setAttempt] = useState(0)

  // ── Initial load ──────────────────────────────────────────────────────
  useEffect(() => {
    let live = true
    setFatal(null)
    Promise.all([api.me(), api.latest()])
      .then(([m, s]) => {
        if (!live) return
        setMe(m)
        setSnapshot(s)
      })
      .catch(async (e: unknown) => {
        if (!live) return
        if (!(e instanceof ApiError)) return setFatal({ kind: 'error', message: 'Couldn’t load the forecast. Your inputs are safe. Try again.' })
        if (e.status === 403 || e.status === 401) return setFatal({ kind: 'access' })
        const m = await api.me().catch(() => null)
        if (!live) return
        setMe(m)
        if (e.code === 'NO_OPENING_BALANCE') {
          setFatal({ kind: 'no_balance' })
          api.accounts().then(a => live && setAccounts(a)).catch(() => undefined)
        } else if (e.code === 'NO_SNAPSHOT') setFatal({ kind: 'not_set_up', canEdit: !!m?.can.edit })
        else setFatal({ kind: 'error', message: e.message })
      })
    api.scenarios().then(s => live && setScenarios(s)).catch(() => undefined)
    return () => {
      live = false
    }
  }, [attempt])

  // ── Forecast for the active view (and the no-collections floor for the runway KPI) ──
  useEffect(() => {
    if (!snapshot) return
    let live = true
    setLoadError('')
    api
      .forecast(snapshot.snapshot_id, view)
      .then(f => live && setForecast(f))
      .catch((e: unknown) => live && setLoadError(e instanceof ApiError ? e.message : 'Couldn’t load the forecast.'))
    api
      .forecast(snapshot.snapshot_id, 'no_collections')
      .then(f => live && setFloor(f))
      .catch(() => undefined)
    return () => {
      live = false
    }
  }, [snapshot, view])

  // ── Debounced scenario preview; the latest request wins ──
  const previewSeq = useRef(0)
  useEffect(() => {
    if (!snapshot || !overrides.length) {
      setPreview(null)
      setRefusals([])
      return
    }
    const seq = ++previewSeq.current
    const controller = new AbortController()
    setPreviewing(true)
    const t = setTimeout(() => {
      api
        .preview(snapshot.snapshot_id, snapshot.revision, view, overrides, controller.signal)
        .then(p => {
          if (seq !== previewSeq.current) return
          setPreview(p)
          setRefusals([])
        })
        .catch((e: unknown) => {
          if (seq !== previewSeq.current || controller.signal.aborted) return
          if (e instanceof ApiError && e.code === 'OVERRIDE_REFUSED') setRefusals((e.details.refusals as Refusal[]) ?? [])
          else if (e instanceof ApiError) setNotice(e.message)
        })
        .finally(() => seq === previewSeq.current && setPreviewing(false))
    }, 250)
    return () => {
      clearTimeout(t)
      controller.abort()
    }
  }, [snapshot, view, overrides])

  const shown: ForecastResult | null = preview?.scenario ?? forecast
  const metrics = shown?.metrics

  // Events on the lowest day, for the "what lands that day" line.
  const minDate = metrics?.first_reserve_breach_date || metrics?.first_negative_date ? metrics?.minimum_date : null
  const safeOverrides = useMemo(() => (refusals.length ? [] : overrides), [refusals, overrides])
  useEffect(() => {
    if (!snapshot || !minDate) return setMinDayEvents([])
    let live = true
    api
      .day(snapshot.snapshot_id, view, minDate, safeOverrides)
      .then(d => live && setMinDayEvents([...d.outflows, ...d.inflows]))
      .catch(() => live && setMinDayEvents([]))
    return () => {
      live = false
    }
  }, [snapshot, view, minDate, safeOverrides])

  const refresh = async () => {
    setRefreshing(true)
    try {
      const s = await api.refresh()
      setNotice(s.changed ? `Updated to revision ${s.revision}.` : `No changes since ${stamp(snapshot?.as_of ?? s.as_of)}.`)
      setSnapshot(s)
      setFatal(null)
    } catch (e) {
      if (e instanceof ApiError && e.code === 'NO_OPENING_BALANCE') setFatal({ kind: 'no_balance' })
      else setNotice(e instanceof ApiError ? e.message : 'Couldn’t refresh.')
    } finally {
      setRefreshing(false)
    }
  }

  const exportCsv = async () => {
    if (!snapshot) return
    try {
      const res = await fetch(api.exportUrl(snapshot.snapshot_id, view))
      if (!res.ok) throw new Error()
      const url = URL.createObjectURL(await res.blob())
      const a = document.createElement('a')
      a.href = url
      a.download = `cash-forecast_${snapshot.start}_${view}_rev${snapshot.revision}.csv`
      a.click()
      URL.revokeObjectURL(url)
    } catch {
      setNotice('Couldn’t export the forecast.')
    }
  }

  const moveEvent = (e: CashEvent, toDate: string) => {
    setOverrides(prev => [...prev.filter(o => !('event_key' in o && o.event_key === e.event_key)), { op: 'shift_event', event_key: e.event_key, to_date: toDate }])
    setParam('day', null)
  }

  const selectScenario = (s: Scenario | null) => {
    setActiveScenario(s)
    if (!s) return
    setOverrides(s.overrides)
    if (s.view !== view) setParam('view', s.view)
    api.scenario(s.id).then(full => setActiveScenario(full)).catch(() => undefined)
  }

  // ── Degraded states (UF-10) ──────────────────────────────────────────
  if (fatal) {
    return (
      <main className="cf-page">
        <PageTitle />
        {fatal.kind === 'access' && (
          <EmptyState icon={<LineChart size={20} />} title="Cash forecast is available to finance roles." message="Ask your admin for access." />
        )}
        {fatal.kind === 'not_set_up' && (
          <EmptyState
            icon={<LineChart size={20} />}
            title={fatal.canEdit ? 'Set up your cash forecast' : 'Your finance team hasn’t set up the cash forecast yet.'}
            message={fatal.canEdit ? 'Add today’s bank balance and your recurring obligations to build the first forecast.' : 'Ask your accountant or admin.'}
          />
        )}
        {fatal.kind === 'no_balance' && (
          <section className="cf-card cf-setup">
            <h2>Add today’s bank balance to see your forecast.</h2>
            <p className="cf-muted">The forecast starts from a dated balance. Statement imports fill this in automatically.</p>
            {me?.can.edit ? (
              <BalanceForm
                accounts={accounts}
                onSaved={() => {
                  setNotice('Balance saved.')
                  void refresh()
                }}
              />
            ) : (
              <p>Ask your accountant to add a balance.</p>
            )}
          </section>
        )}
        {fatal.kind === 'error' && <ErrorState message={fatal.message} onRetry={() => setAttempt(n => n + 1)} />}
        {notice && <p role="status">{notice}</p>}
      </main>
    )
  }

  if (!snapshot || !me || !forecast) {
    return (
      <main className="cf-page" aria-busy="true">
        <PageTitle />
        {loadError ? (
          <ErrorState message={loadError} onRetry={() => setAttempt(n => n + 1)} />
        ) : (
          <>
            <div className="cf-kpis">
              {Array.from({ length: 6 }, (_, i) => (
                <div className="cf-kpi" key={i}>
                  <Skeleton height={14} width="60%" />
                  <Skeleton height={24} width="80%" />
                </div>
              ))}
            </div>
            <Skeleton height={300} />
          </>
        )}
      </main>
    )
  }

  const canEdit = me.can.edit
  const expired = snapshot.balances.some(b => b.freshness === 'expired')
  const stale = snapshot.balances.filter(b => b.freshness === 'stale')
  const sentence = summarySentence(shown!)
  const breach = metrics!.first_reserve_breach_date || metrics!.first_negative_date
  const breachRow = shown!.days.find(d => d.date === metrics!.first_reserve_breach_date)
  const net = metrics!.total_inflow_paise - metrics!.total_outflow_paise
  const rows = (preview?.scenario.days ?? forecast.days).filter(d => showAll || d.banking_day)
  const reserve = snapshot.reserve_paise

  return (
    <main className="cf-page">
      <header className="cf-header">
        <div>
          <p className="cf-crumb">Insights / Cash flow forecast</p>
          <h1>Cash flow forecast</h1>
          <p className="cf-muted">
            Next {snapshot.horizon_days} days · {shortDay(snapshot.start)} – {shortDay(snapshot.end)} · Revision {snapshot.revision}
            {snapshot.is_fixture && (
              <>
                {' '}
                · <Badge tone="warn">Synthetic demo data</Badge>
              </>
            )}
          </p>
        </div>
        <div className="cf-header__actions">
          <div className="cf-views" role="radiogroup" aria-label="Forecast view">
            {VIEWS.map(v => (
              <button
                key={v.key}
                type="button"
                role="radio"
                aria-checked={view === v.key}
                className="cf-view"
                tabIndex={view === v.key ? 0 : -1}
                onClick={() => setParam('view', v.key)}
                onKeyDown={e => {
                  if (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft') return
                  const i = VIEWS.findIndex(x => x.key === view)
                  const next = VIEWS[(i + (e.key === 'ArrowRight' ? 1 : VIEWS.length - 1)) % VIEWS.length]
                  setParam('view', next.key)
                }}
              >
                {v.label}
              </button>
            ))}
          </div>
          {canEdit && (
            <Button variant="secondary" size="sm" iconLeft={<RefreshCw size={14} />} loading={refreshing} onClick={refresh}>
              Refresh
            </Button>
          )}
          <Button variant="secondary" size="sm" iconLeft={<Download size={14} />} onClick={exportCsv}>
            Export
          </Button>
          <Button variant="secondary" size="sm" iconLeft={<SlidersHorizontal size={14} />} onClick={() => setInputs({ open: true, tab: 'balances' })}>
            Inputs
          </Button>
        </div>
      </header>

      <div className="cf-status" role="status" aria-live="polite">
        {notice}
      </div>

      <section className="cf-freshness" aria-label="Bank balances">
        {snapshot.balances.map(b => (
          <button key={b.bank_account_id} type="button" className={`cf-chip cf-chip--${b.freshness}`} onClick={() => setInputs({ open: true, tab: 'balances' })}>
            <span className="cf-dot" aria-hidden="true" />
            <span>
              {b.account_name} {b.account_mask ?? ''}
            </span>
            <strong>{rupees(b.balance_paise)}</strong>
            <span className="cf-muted">
              {stamp(b.as_of)} · {b.source}
              {b.freshness !== 'fresh' && ` · ${b.freshness === 'stale' ? 'stale' : 'update needed'}`}
            </span>
          </button>
        ))}
        <button type="button" className="cf-linkish" onClick={() => setExclusionsOpen(true)}>
          Coverage: {snapshot.coverage.state} · {snapshot.coverage.event_count} items · {snapshot.coverage.exclusion_count} excluded ›
        </button>
      </section>

      {expired && (
        <p className="cf-banner cf-banner--danger" role="alert">
          <AlertTriangle size={16} /> Balances are over 3 banking days old. Plans can’t be submitted or approved until you update them.{' '}
          {canEdit && <Button size="sm" variant="secondary" onClick={() => setInputs({ open: true, tab: 'balances' })}>Add balance</Button>}
        </p>
      )}
      {!expired && stale.length > 0 && (
        <p className="cf-banner cf-banner--warn">
          <AlertTriangle size={16} /> {stale.map(b => b.account_name).join(', ')} balance is 2–3 banking days old.
        </p>
      )}
      {snapshot.coverage.state === 'partial' && (
        <p className="cf-banner cf-banner--warn" role="alert">
          <AlertTriangle size={16} />
          {snapshot.coverage.failed_sources.length > 0 && ` ${snapshot.coverage.failed_sources.join(', ')} couldn’t be read; figures exclude them.`}
          {snapshot.coverage.missing_balances.length > 0 && ` No balance for ${snapshot.coverage.missing_balances.join(', ')}.`} Plans are blocked until
          this is fixed.
        </p>
      )}
      {snapshot.coverage.needs_setup.length > 0 && (
        <p className="cf-banner cf-banner--info">
          {snapshot.coverage.needs_setup.join(', ')} {snapshot.coverage.needs_setup.length === 1 ? 'has' : 'have'} no amount. The forecast may be optimistic.{' '}
          {canEdit && <Button size="sm" variant="secondary" onClick={() => setInputs({ open: true, tab: 'recurring' })}>Set up</Button>}
        </p>
      )}

      <section className={`cf-summary ${breach ? 'cf-summary--bad' : 'cf-summary--ok'}`} aria-label="Summary">
        {breach ? <AlertTriangle size={20} aria-hidden="true" /> : <CheckCircle2 size={20} aria-hidden="true" />}
        <div>
          <p className="cf-summary__lead">{sentence}</p>
          {breach && minDayEvents.length > 0 && <p className="cf-summary__sub">{driverLine(minDayEvents)}</p>}
          {breach && (
            <div className="cf-form-actions cf-form-actions--start">
              <Button size="sm" variant="secondary" onClick={() => setParam('day', metrics!.minimum_date)}>
                See {shortDay(metrics!.minimum_date)}
              </Button>
              {canEdit && !overrides.length && (
                <Button size="sm" variant="ghost" onClick={() => document.getElementById('cf-scn-title')?.scrollIntoView({ behavior: 'smooth' })}>
                  Try a fix
                </Button>
              )}
            </div>
          )}
        </div>
      </section>

      <CashFlowMap result={shown!} snapshot={snapshot} scenario={!!preview} />

      <section className="cf-kpis" aria-label="Key figures">
        <Kpi label="Cash today" value={compact(forecast.opening_paise)} spokenValue={spoken(forecast.opening_paise)} sub={stamp(snapshot.as_of)} />
        <Kpi
          label="Lowest"
          value={compact(metrics!.minimum_closing_paise)}
          spokenValue={spoken(metrics!.minimum_closing_paise)}
          sub={`${day(metrics!.minimum_date)}${metrics!.minimum_closing_paise < reserve ? ' · below reserve' : ''}`}
          tone={metrics!.minimum_closing_paise < reserve ? 'danger' : undefined}
          onClick={() => setParam('day', metrics!.minimum_date)}
        />
        <Kpi
          label="First breach"
          value={metrics!.first_reserve_breach_date ? day(metrics!.first_reserve_breach_date) : 'None'}
          sub={breachRow ? `▼ ${compact(reserve - breachRow.closing_paise)} below reserve` : `Reserve ${compact(reserve)}`}
          tone={metrics!.first_reserve_breach_date ? 'danger' : undefined}
          onClick={metrics!.first_reserve_breach_date ? () => setParam('day', metrics!.first_reserve_breach_date) : undefined}
        />
        <Kpi
          label="Runway, no collections"
          value={floor ? (floor.metrics.runway_days != null ? `${floor.metrics.runway_days} days` : `${snapshot.horizon_days}+ days`) : '…'}
          sub={floor?.metrics.first_negative_date ? `ends ${shortDay(floor.metrics.first_negative_date)}` : 'no shortfall in horizon'}
          tone={floor?.metrics.runway_days != null && floor.metrics.runway_days < 7 ? 'warn' : undefined}
        />
        <Kpi
          label={`${snapshot.horizon_days}-day net`}
          value={compact(net, { sign: true })}
          sub={`in ${compact(metrics!.total_inflow_paise)} · out ${compact(metrics!.total_outflow_paise)}`}
        />
        <Kpi label="CC headroom" value={compact(snapshot.od_headroom_paise)} sub="not counted in balance" />
      </section>

      <section className="cf-card" aria-label="Daily closing balance">
        <ForecastChart
          baseline={forecast.days}
          scenario={preview?.scenario.days}
          reserve={reserve}
          selected={openDay}
          onSelectDay={d => setParam('day', d)}
          summary={sentence}
        />
      </section>

      <div className="cf-grid">
        <Drivers result={shown!} />
        <div className="cf-stack">
          <ScenarioPanel
            snapshot={snapshot}
            view={view}
            overrides={overrides}
            onChange={setOverrides}
            preview={preview}
            previewing={previewing}
            refusals={refusals}
            canEdit={canEdit}
            scenarios={scenarios}
            active={activeScenario}
            onSelect={s => {
              selectScenario(s)
              if (!s) setOverrides([])
            }}
            onSaved={s => {
              setActiveScenario(s)
              setScenarios(list => [s, ...list.filter(x => x.id !== s.id)])
            }}
            onSubmitted={m => {
              setNotice(m)
              setPlansKey(k => k + 1)
            }}
          />
          <PlansPanel
            me={me}
            reloadKey={plansKey}
            onDecided={m => {
              setNotice(m)
              setPlansKey(k => k + 1)
            }}
          />
        </div>
      </div>

      <section className="cf-card" aria-labelledby="cf-ledger-title">
        <div className="cf-card__head">
          <h2 id="cf-ledger-title">Day by day{preview ? ' · with scenario' : ''}</h2>
          <label className="cf-check">
            <input type="checkbox" checked={showAll} onChange={e => setShowAll(e.target.checked)} /> Show non-banking days
          </label>
        </div>
        <div className="cf-scroll">
          <table className="cf-table cf-ledger">
            <caption className="cf-sr">Daily opening, receipts, payments and closing balance in rupees</caption>
            <thead>
              <tr>
                <th scope="col">Date</th>
                <th scope="col" className="cf-num">Opening</th>
                <th scope="col" className="cf-num">In</th>
                <th scope="col" className="cf-num">Out</th>
                <th scope="col" className="cf-num">Closing</th>
                <th scope="col" className="cf-num">vs reserve</th>
              </tr>
            </thead>
            <tbody>
              {rows.map(d => (
                <LedgerRow key={d.date} d={d} reserve={reserve} onOpen={() => setParam('day', d.date)} />
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <DayDrawer
        date={openDay}
        view={view}
        snapshotId={snapshot.snapshot_id}
        overrides={safeOverrides}
        canEdit={canEdit}
        start={snapshot.start}
        onClose={() => setParam('day', null)}
        onMove={moveEvent}
        onSaved={m => setNotice(m)}
      />
      <ExclusionsDrawer open={exclusionsOpen} snapshotId={snapshot.snapshot_id} onClose={() => setExclusionsOpen(false)} />
      <InputsDrawer
        open={inputs.open}
        tab={inputs.tab}
        onTab={t => setInputs({ open: true, tab: t })}
        me={me}
        onClose={() => setInputs(s => ({ ...s, open: false }))}
        onChanged={m => setNotice(m)}
      />
    </main>
  )
}

function PageTitle() {
  return (
    <header className="cf-header">
      <div>
        <p className="cf-crumb">Insights / Cash flow forecast</p>
        <h1>Cash flow forecast</h1>
      </div>
    </header>
  )
}

function Kpi({
  label,
  value,
  sub,
  tone,
  onClick,
  spokenValue,
}: {
  label: string
  value: string
  sub: string
  tone?: 'danger' | 'warn'
  onClick?: () => void
  spokenValue?: string
}) {
  const body = (
    <>
      <span className="cf-kpi__label">{label}</span>
      <span className="cf-kpi__value" aria-label={spokenValue}>
        {value}
      </span>
      <span className="cf-kpi__sub">{sub}</span>
    </>
  )
  const cls = `cf-kpi${tone ? ` cf-kpi--${tone}` : ''}`
  return onClick ? (
    <button type="button" className={cls} onClick={onClick} data-testid={`kpi-${label}`}>
      {body}
    </button>
  ) : (
    <div className={cls} data-testid={`kpi-${label}`}>
      {body}
    </div>
  )
}

function LedgerRow({ d, reserve, onOpen }: { d: DayRow; reserve: number; onOpen: () => void }) {
  return (
    <tr className={d.below_reserve ? 'cf-row--below' : d.banking_day ? '' : 'cf-row--off'}>
      <th scope="row">
        <button type="button" className="cf-linkish" onClick={onOpen}>
          {d.below_reserve && <span aria-hidden="true">◆ </span>}
          {day(d.date)}
        </button>
      </th>
      <td className="cf-num">{exact(d.opening_paise)}</td>
      <td className="cf-num cf-in">{d.inflow_paise ? exact(d.inflow_paise) : '—'}</td>
      <td className="cf-num">{d.outflow_paise ? exact(d.outflow_paise) : '—'}</td>
      <td className="cf-num">
        <strong>{exact(d.closing_paise)}</strong>
      </td>
      <td className="cf-num">
        {exact(d.closing_paise - reserve, { sign: true })}
        {d.below_reserve && <span className="cf-below"> Below</span>}
      </td>
    </tr>
  )
}

function Drivers({ result }: { result: ForecastResult }) {
  const entries = Object.entries(result.category_totals)
    .map(([k, v]) => {
      const [dir, cat] = k.split(':')
      return { key: k, dir, label: CATEGORY_LABELS[cat] ?? cat, value: dir === 'in' ? v : -v, cat }
    })
    .sort((a, b) => Math.abs(b.value) - Math.abs(a.value))
  const max = Math.max(1, ...entries.map(e => Math.abs(e.value)))
  const m = result.metrics
  return (
    <section className="cf-card cf-drivers" aria-labelledby="cf-drivers-title">
      <h2 id="cf-drivers-title">What drives the next {result.days.length} days</h2>
      <ul>
        {entries.map(e => (
          <li key={e.key} className={`cf-driver cf-driver--${e.cat}`}>
            <span className="cf-driver__label">{e.label}</span>
            <span className="cf-driver__value">{rupees(e.value, { sign: true })}</span>
            <span className="cf-driver__bar" aria-hidden="true">
              <i style={{ width: `${(100 * Math.abs(e.value)) / max}%` }} />
            </span>
          </li>
        ))}
      </ul>
      {(m.beyond_horizon_inflow_paise > 0 || m.beyond_horizon_outflow_paise > 0) && (
        <p className="cf-muted cf-small">
          After {shortDay(result.days[result.days.length - 1].date)}: {compact(m.beyond_horizon_inflow_paise, { sign: true })} in ·{' '}
          {compact(-m.beyond_horizon_outflow_paise)} out
        </p>
      )}
    </section>
  )
}
