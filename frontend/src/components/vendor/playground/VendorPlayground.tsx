/**
 * The agentic playground — a canvas where a vendor's documents, a model, a
 * calculation and an output are wired into something that runs.
 *
 * Built on pointer events and absolutely-positioned nodes over an SVG edge
 * layer rather than a flow library: the app carries no such dependency today,
 * and the parts that actually matter here (grid snapping, the drag-to-connect
 * affordance, the look) are the parts a library would have to be fought over
 * anyway.
 *
 * The graph is saved per vendor on the server, debounced, and run there too:
 * a run reaches the vendor's documents, the model key and the mail server, so
 * it happens where those already are rather than in the tab that drew it.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  Bell, FileBarChart, FileCheck2, FileText, Mail, Play, Plug, Receipt,
  Sigma, Sparkles, Table2, Trash2, Maximize2, Crosshair, AlertTriangle, X, Info,
  Plus, ChevronUp, ChevronDown, Copy, Sun, Moon,
} from 'lucide-react'
import {
  EMPTY, GROUPS, NODE_SPECS, SPEC, newNode, newStep, parseSteps, problems,
  runOrder, rid, stepProblems, writeSteps,
  type Flow, type FlowNode, type NodeKind, type Step,
} from './nodeTypes'
import { Link } from 'react-router-dom'
import { fetchVendorFlow, runVendorFlow, saveVendorFlow, type FlowRun } from '../../../api/vendorCard'
import { termLabel, termValue } from '../../playgroundTerms'
import { reviewPath } from '../../../routes/paths'
import './playground.css'

const inr = (v: number) => `₹${v.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`

const ICONS: Record<string, typeof Bell> = {
  FileCheck2, Table2, FileText, Receipt, Sparkles, Sigma, Plug, FileBarChart, Mail, Bell,
}

const NODE_W = 190
const GRID = 16
const MIN_Z = 0.4
const MAX_Z = 1.8

const snap = (v: number) => Math.round(v / GRID) * GRID
const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v))

function storeKey(supplierId: string) {
  return `vc.playground.${supplierId}`
}

function load(supplierId: string): Flow {
  try {
    const raw = localStorage.getItem(storeKey(supplierId))
    if (!raw) return EMPTY
    const f = JSON.parse(raw) as Flow
    if (!Array.isArray(f?.nodes) || !Array.isArray(f?.edges)) return EMPTY
    // Drop anything referring to a node kind this build no longer has.
    const nodes = f.nodes.filter(n => SPEC[n.kind])
    const ids = new Set(nodes.map(n => n.id))
    return { nodes, edges: f.edges.filter(e => ids.has(e.from) && ids.has(e.to)) }
  } catch {
    return EMPTY
  }
}

function save(supplierId: string, flow: Flow) {
  try {
    localStorage.setItem(storeKey(supplierId), JSON.stringify(flow))
  } catch {
    /* private window, or storage full — the canvas still works for this session */
  }
}

/**
 * The one line shown on the node itself. A Formula's config is JSON, so the
 * generic "first non-empty field" would print a serialised array onto the
 * canvas; it gets summarised by its steps instead.
 */
function nodeSummary(n: FlowNode): string {
  const spec = SPEC[n.kind]
  const list = spec.fields.find(f => f.kind === 'formulas')
  const totals = spec.fields.find(f => f.kind === 'aggregates')
  if (list) {
    const steps = parseSteps(n.config[list.key]).filter(st => st.expr.trim())
    if (!steps.length) return spec.blurb
    const nAgg = totals ? parseSteps(n.config[totals.key]).filter(a => a.expr.trim()).length : 0
    const cols = `${steps.length} column${steps.length === 1 ? '' : 's'}`
    return nAgg ? `${cols} + ${nAgg} total${nAgg === 1 ? '' : 's'}` : cols
  }
  return spec.fields.map(f => n.config[f.key]).find(v => (v ?? '').trim()) || spec.blurb
}

/** How many of a node's settings are actually filled in. */
function filledCount(n: FlowNode): number {
  return SPEC[n.kind].fields.filter(f =>
    f.kind === 'formulas'
      ? parseSteps(n.config[f.key]).some(st => st.expr.trim())
      : (n.config[f.key] ?? '').trim(),
  ).length
}

/** Where a node's ports sit, in canvas coordinates. */
const portOut = (n: FlowNode) => ({ x: n.x + NODE_W, y: n.y + 30 })
const portIn = (n: FlowNode) => ({ x: n.x, y: n.y + 30 })

/** A cubic bezier that leaves horizontally, so edges read as flow not geometry. */
function path(a: { x: number; y: number }, b: { x: number; y: number }): string {
  const dx = Math.max(36, Math.abs(b.x - a.x) * 0.5)
  return `M ${a.x} ${a.y} C ${a.x + dx} ${a.y}, ${b.x - dx} ${b.y}, ${b.x} ${b.y}`
}

/**
 * The Formula node's step list.
 *
 * Several named calculations worked top to bottom, each able to use the ones
 * above it. Order is therefore meaningful, not cosmetic — moving a step above
 * the one it depends on breaks it, which is why the reordering controls sit
 * next to the warnings rather than somewhere tidier.
 */
function FormulaSteps({ value, onChange, mode = 'column' }: {
  value: string
  onChange: (next: string) => void
  mode?: 'column' | 'aggregate'
}) {
  const steps = parseSteps(value)
  const issues = stepProblems(steps)
  const agg = mode === 'aggregate'

  const put = (next: Step[]) => onChange(writeSteps(next))
  const edit = (id: string, patch: Partial<Step>) =>
    put(steps.map(s => (s.id === id ? { ...s, ...patch } : s)))
  const drop = (id: string) => put(steps.filter(s => s.id !== id))
  const move = (i: number, by: -1 | 1) => {
    const j = i + by
    if (j < 0 || j >= steps.length) return
    const next = [...steps]
    ;[next[i], next[j]] = [next[j], next[i]]
    put(next)
  }

  return (
    <div className="pg__steps">
      {steps.map((st, i) => (
        <div key={st.id} className="pg__step">
          <div className="pg__step-h">
            <span className="pg__step-n">{i + 1}</span>
            <input
              className="pg__step-name"
              value={st.name}
              placeholder={agg ? 'name, e.g. Total GR' : 'column name, e.g. GR@100%'}
              aria-label={`Step ${i + 1} name`}
              onChange={e => edit(st.id, { name: e.target.value })}
            />
            <button type="button" title="Move up" aria-label={`Move step ${i + 1} up`}
                    disabled={i === 0} onClick={() => move(i, -1)}><ChevronUp size={12} /></button>
            <button type="button" title="Move down" aria-label={`Move step ${i + 1} down`}
                    disabled={i === steps.length - 1} onClick={() => move(i, 1)}><ChevronDown size={12} /></button>
            <button type="button" title="Remove" aria-label={`Remove step ${i + 1}`}
                    className="pg__step-x" onClick={() => drop(st.id)}><X size={12} /></button>
          </div>
          <textarea
            className="pg__step-expr"
            rows={2}
            value={st.expr}
            aria-label={`Step ${i + 1} expression`}
            placeholder={agg
              ? (i === 0 ? 'sum(GR@100%)' : '(1 - contract["% Routing"]) * sum(GR@100%)')
              : (i === 0 ? 'ratecard["Bill Rate"] / ratecard["Working Days in Month"]' : 'GR@100% * 0.952')}
            onChange={e => edit(st.id, { expr: e.target.value })}
          />
        </div>
      ))}

      <button type="button" className="pg__step-add" onClick={() => put([...steps, newStep()])}>
        <Plus size={12} />{agg ? 'Add sheet total' : 'Add column'}
      </button>

      {issues.length > 0 && (
        <ul className="pg__step-bad">
          {issues.map((t, i) => <li key={i}>{t}</li>)}
        </ul>
      )}

      {!agg && steps.length > 0 && !issues.length && steps.some(st => st.expr.trim()) && (
        <p className="pg__step-ok">
          Adds {steps.filter(st => st.expr.trim()).length} column
          {steps.filter(st => st.expr.trim()).length === 1 ? '' : 's'} to the sheet.
        </p>
      )}
    </div>
  )
}

export interface VendorPlaygroundProps {
  supplierId: string
  vendorName: string
  notify?: (msg: string, tone?: 'info' | 'error') => void
  /** A run can file a report or a calculated copy; the card reloads its list. */
  onProduced?: () => void
}

export default function VendorPlayground({ supplierId, vendorName, notify, onProduced }: VendorPlaygroundProps) {
  const [flow, setFlow] = useState<Flow>(EMPTY)
  const [loading, setLoading] = useState(true)
  const [running, setRunning] = useState(false)
  const [lastRun, setLastRun] = useState<FlowRun | null>(null)
  const dirty = useRef(false)
  const [sel, setSel] = useState<string | null>(null)
  const [view, setView] = useState({ x: 40, y: 40, z: 1 })
  const [linking, setLinking] = useState<{ from: string; x: number; y: number } | null>(null)
  const [showIssues, setShowIssues] = useState(true)
  // Per-viewer preference, so localStorage is the right home for it — unlike
  // the flow itself, nobody else needs to see which surface you prefer.
  const [theme, setTheme] = useState<'dark' | 'light'>(() => {
    try {
      return localStorage.getItem('vc.playground.theme') === 'light' ? 'light' : 'dark'
    } catch {
      return 'dark'
    }
  })

  useEffect(() => {
    try {
      localStorage.setItem('vc.playground.theme', theme)
    } catch {
      /* private window — the choice just does not outlive the session */
    }
  }, [theme])
  const wrapRef = useRef<HTMLDivElement>(null)

  // Each vendor keeps its own canvas; switching cards loads that vendor's.
  useEffect(() => {
    let alive = true
    setLoading(true)
    setSel(null)
    setLastRun(null)
    dirty.current = false
    fetchVendorFlow(supplierId)
      .then(g => { if (alive) setFlow({ nodes: g.nodes as Flow['nodes'], edges: g.edges }) })
      .catch(() => { if (alive) setFlow(load(supplierId)) })   // fall back to anything drawn offline
      .finally(() => { if (alive) setLoading(false) })
    return () => { alive = false }
  }, [supplierId])

  // Saved on a debounce rather than on every keystroke: a node drag fires a
  // state change per pointer move, and each one is not worth a request.
  useEffect(() => {
    if (loading || !dirty.current) return
    const t = setTimeout(() => {
      saveVendorFlow(supplierId, flow).catch(() => save(supplierId, flow))
    }, 800)
    return () => clearTimeout(t)
  }, [supplierId, flow, loading])

  // Every mutation goes through setFlow, so marking it here covers them all.
  const edit = useCallback((fn: (f: Flow) => Flow) => {
    dirty.current = true
    setFlow(fn)
  }, [])

  const issues = useMemo(() => problems(flow), [flow])
  const errors = issues.filter(i => i.severity === 'error')
  const byNode = useMemo(() => {
    const m = new Map<string, 'error' | 'warning'>()
    for (const p of issues) {
      if (!p.nodeId) continue
      if (p.severity === 'error' || !m.has(p.nodeId)) m.set(p.nodeId, p.severity)
    }
    return m
  }, [issues])

  const node = (id: string | null) => flow.nodes.find(n => n.id === id) ?? null
  const selected = node(sel)

  /** Screen point -> canvas point. */
  const toCanvas = useCallback((clientX: number, clientY: number) => {
    const r = wrapRef.current?.getBoundingClientRect()
    if (!r) return { x: 0, y: 0 }
    return { x: (clientX - r.left - view.x) / view.z, y: (clientY - r.top - view.y) / view.z }
  }, [view])

  // ── adding ────────────────────────────────────────────────────────────────

  const add = useCallback((kind: NodeKind, at?: { x: number; y: number }) => {
    const p = at ?? { x: (-view.x + 160) / view.z, y: (-view.y + 120) / view.z }
    const n = newNode(kind, snap(p.x), snap(p.y))
    edit(f => ({ ...f, nodes: [...f.nodes, n] }))
    setSel(n.id)
  }, [view])

  const onPaletteDragStart = (e: React.DragEvent, kind: NodeKind) => {
    e.dataTransfer.setData('text/x-node', kind)
    e.dataTransfer.effectAllowed = 'copy'
  }

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault()
    const kind = e.dataTransfer.getData('text/x-node') as NodeKind
    if (!kind || !SPEC[kind]) return
    const p = toCanvas(e.clientX, e.clientY)
    add(kind, { x: p.x - NODE_W / 2, y: p.y - 24 })
  }

  // ── moving nodes, panning, connecting ─────────────────────────────────────

  const dragNode = (e: React.PointerEvent, id: string) => {
    if (e.button !== 0) return
    e.stopPropagation()
    setSel(id)
    const n = node(id)
    if (!n) return
    const start = toCanvas(e.clientX, e.clientY)
    const off = { x: start.x - n.x, y: start.y - n.y }
    const el = e.currentTarget as HTMLElement
    el.setPointerCapture(e.pointerId)

    const move = (ev: PointerEvent) => {
      const p = toCanvas(ev.clientX, ev.clientY)
      edit(f => ({
        ...f,
        nodes: f.nodes.map(m => m.id === id ? { ...m, x: snap(p.x - off.x), y: snap(p.y - off.y) } : m),
      }))
    }
    const up = () => {
      el.releasePointerCapture?.(e.pointerId)
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', up)
    }
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', up)
  }

  /** Arrow keys move a focused node by one grid step, Shift by four. */
  const nudge = (e: React.KeyboardEvent, id: string) => {
    const step = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] }[e.key]
    if (!step) return
    e.preventDefault()
    const k = GRID * (e.shiftKey ? 4 : 1)
    edit(f => ({
      ...f,
      nodes: f.nodes.map(m => m.id === id ? { ...m, x: m.x + step[0] * k, y: m.y + step[1] * k } : m),
    }))
  }

  const panStart = (e: React.PointerEvent) => {
    if (e.button !== 0) return
    setSel(null)
    const from = { x: e.clientX, y: e.clientY, vx: view.x, vy: view.y }
    const move = (ev: PointerEvent) =>
      setView(v => ({ ...v, x: from.vx + (ev.clientX - from.x), y: from.vy + (ev.clientY - from.y) }))
    const up = () => {
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', up)
    }
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', up)
  }

  const linkStart = (e: React.PointerEvent, id: string) => {
    e.stopPropagation()
    const p = toCanvas(e.clientX, e.clientY)
    setLinking({ from: id, x: p.x, y: p.y })
    const move = (ev: PointerEvent) => {
      const q = toCanvas(ev.clientX, ev.clientY)
      setLinking(l => l && { ...l, x: q.x, y: q.y })
    }
    const up = (ev: PointerEvent) => {
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', up)
      const target = (ev.target as HTMLElement)?.closest('[data-node-id]') as HTMLElement | null
      const to = target?.dataset.nodeId
      setLinking(null)
      if (!to || to === id) return
      if (!SPEC[node(to)!.kind].inputs) return
      edit(f =>
        f.edges.some(x => x.from === id && x.to === to)
          ? f
          : { ...f, edges: [...f.edges, { id: rid(), from: id, to }] })
    }
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', up)
  }

  const onWheel = (e: React.WheelEvent) => {
    if (!e.ctrlKey && !e.metaKey) return
    e.preventDefault()
    const r = wrapRef.current?.getBoundingClientRect()
    if (!r) return
    const mx = e.clientX - r.left, my = e.clientY - r.top
    setView(v => {
      const z = clamp(v.z * (e.deltaY < 0 ? 1.1 : 1 / 1.1), MIN_Z, MAX_Z)
      // keep the point under the cursor fixed
      return { z, x: mx - (mx - v.x) * (z / v.z), y: my - (my - v.y) * (z / v.z) }
    })
  }

  // ── removing ──────────────────────────────────────────────────────────────

  const removeNode = useCallback((id: string) => {
    edit(f => ({
      nodes: f.nodes.filter(n => n.id !== id),
      edges: f.edges.filter(e => e.from !== id && e.to !== id),
    }))
    setSel(s => (s === id ? null : s))
  }, [])

  const removeEdge = (id: string) => edit(f => ({ ...f, edges: f.edges.filter(e => e.id !== id) }))

  /**
   * Copy a node, settings and all, offset so it does not land on the original.
   *
   * Worth having for the Formula node above all: its configuration is several
   * expressions someone worked out, and the common next step is a near-identical
   * calculation — a second rate card, last quarter, a different routing share.
   * Edges are deliberately not copied: the copy is a starting point, and
   * silently re-wiring it into the same flow would run it twice.
   */
  const duplicate = useCallback((id: string) => {
    edit(f => {
      const src = f.nodes.find(n => n.id === id)
      if (!src) return f
      const copy: FlowNode = {
        ...src,
        id: rid(),
        x: src.x + GRID * 2,
        y: src.y + GRID * 2,
        config: { ...src.config },
      }
      setSel(copy.id)
      return { ...f, nodes: [...f.nodes, copy] }
    })
  }, [])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement
      if (t?.matches('input, textarea, select')) return
      if ((e.key === 'Delete' || e.key === 'Backspace') && sel) { e.preventDefault(); removeNode(sel) }
      if (e.key.toLowerCase() === 'd' && (e.ctrlKey || e.metaKey) && sel) { e.preventDefault(); duplicate(sel) }
      if (e.key === 'Escape') setSel(null)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [sel, removeNode, duplicate])

  // ── view helpers ──────────────────────────────────────────────────────────

  const fit = () => {
    if (!flow.nodes.length) return setView({ x: 40, y: 40, z: 1 })
    const xs = flow.nodes.map(n => n.x), ys = flow.nodes.map(n => n.y)
    const minX = Math.min(...xs) - 60, minY = Math.min(...ys) - 60
    const maxX = Math.max(...xs) + NODE_W + 60, maxY = Math.max(...ys) + 160
    const r = wrapRef.current?.getBoundingClientRect()
    if (!r) return
    const z = clamp(Math.min(r.width / (maxX - minX), r.height / (maxY - minY)), MIN_Z, 1)
    setView({ z, x: -minX * z + (r.width - (maxX - minX) * z) / 2, y: -minY * z + 20 })
  }

  const setCfg = (id: string, key: string, value: string) =>
    edit(f => ({ ...f, nodes: f.nodes.map(n => n.id === id ? { ...n, config: { ...n.config, [key]: value } } : n) }))

  const run = async () => {
    if (errors.length) {
      notify?.(`${errors.length} thing${errors.length > 1 ? 's' : ''} to fix before this can run.`, 'error')
      setShowIssues(true)
      return
    }
    setRunning(true)
    setLastRun(null)
    try {
      // Saved first, so what ran is what is on file — a run that filed a
      // report against a flow nobody can look up afterwards is not auditable.
      await saveVendorFlow(supplierId, flow).catch(() => {})
      const res = await runVendorFlow(supplierId, flow)
      setLastRun(res)
      const made = res.outputs.length
      if (res.status === 'ok') {
        notify?.(made ? `Done — ${made} thing${made > 1 ? 's' : ''} produced.` : 'Done.', 'info')
      } else if (res.status === 'partial') {
        notify?.('Some steps did not finish — see the panel.', 'error')
      } else {
        notify?.('Nothing ran. See the panel for why.', 'error')
      }
      if (made) onProduced?.()
    } catch (e) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      notify?.(msg || 'The run could not be started.', 'error')
    } finally {
      setRunning(false)
    }
  }

  return (
    <div className="pg" data-theme={theme}>
      {/* ── palette ─────────────────────────────────────────────────────── */}
      <aside className="pg__palette" aria-label="Node palette">
        <p className="pg__palette-hint">Drag onto the canvas, or click to drop one in.</p>
        {GROUPS.map(g => (
          <section key={g.id} className="pg__pgroup">
            <h4 className={`pg__pgroup-h pg__pgroup-h--${g.id}`}>{g.label}</h4>
            {NODE_SPECS.filter(s => s.group === g.id).map(s => {
              const Icon = ICONS[s.icon]
              return (
                <button
                  key={s.kind} type="button" draggable
                  onDragStart={e => onPaletteDragStart(e, s.kind)}
                  onClick={() => add(s.kind)}
                  className={`pg__chip pg__chip--${s.group}`}
                  title={s.blurb}
                >
                  <span className="pg__chip-ic"><Icon size={14} /></span>
                  <span className="pg__chip-t">{s.label}</span>
                </button>
              )
            })}
          </section>
        ))}
      </aside>

      {/* ── canvas ──────────────────────────────────────────────────────── */}
      <div className="pg__stage">
        <div className="pg__bar">
          <span className="pg__bar-t">Playground — {vendorName}</span>
          <span className="pg__bar-sp" />
          {issues.length > 0 && (
            <button type="button" className={`pg__ib${errors.length ? ' pg__ib--err' : ''}`} onClick={() => setShowIssues(v => !v)}>
              <AlertTriangle size={13} />{issues.length}
            </button>
          )}
          <button type="button" className="pg__tb"
                  onClick={() => setTheme(t => (t === 'dark' ? 'light' : 'dark'))}
                  title={theme === 'dark' ? 'Switch to light' : 'Switch to dark'}
                  aria-pressed={theme === 'light'}>
            {theme === 'dark' ? <Sun size={14} /> : <Moon size={14} />}
          </button>
          <button type="button" className="pg__tb" onClick={fit} title="Fit to view"><Maximize2 size={14} /></button>
          <button type="button" className="pg__tb" onClick={() => setView({ x: 40, y: 40, z: 1 })} title="Reset view"><Crosshair size={14} /></button>
          <button type="button" className="pg__run" onClick={run}
                  disabled={!flow.nodes.length || running || loading}>
            <Play size={13} />{running ? 'Running…' : 'Run'}
          </button>
        </div>

        {/* A pan-and-drop surface, not a control: giving it a button role would
            announce something keyboard users cannot operate anyway. Everything
            actionable inside it — nodes, ports, wires — is separately focusable. */}
        {/* eslint-disable-next-line jsx-a11y/no-static-element-interactions */}
        <div
          ref={wrapRef}
          className="pg__canvas"
          onPointerDown={panStart}
          onWheel={onWheel}
          onDragOver={e => { e.preventDefault(); e.dataTransfer.dropEffect = 'copy' }}
          onDrop={onDrop}
          style={{ backgroundPosition: `${view.x}px ${view.y}px`, backgroundSize: `${GRID * view.z}px ${GRID * view.z}px` }}
        >
          <div className="pg__world" style={{ transform: `translate(${view.x}px, ${view.y}px) scale(${view.z})` }}>
            <svg className="pg__wires" aria-hidden="true">
              <defs>
                <linearGradient id="pg-wire" x1="0" x2="1">
                  <stop offset="0%" stopColor="var(--pg-wire-a)" />
                  <stop offset="100%" stopColor="var(--pg-wire-b)" />
                </linearGradient>
              </defs>
              {flow.edges.map(e => {
                const a = node(e.from), b = node(e.to)
                if (!a || !b) return null
                const d = path(portOut(a), portIn(b))
                return (
                  <g key={e.id} className="pg__wire">
                    <path d={d} className="pg__wire-hit" onClick={() => removeEdge(e.id)}>
                      <title>Click to disconnect</title>
                    </path>
                    <path d={d} className="pg__wire-line" />
                    <circle r="3" className="pg__wire-dot">
                      <animateMotion dur="2.4s" repeatCount="indefinite" path={d} />
                    </circle>
                  </g>
                )
              })}
              {linking && node(linking.from) && (
                <path d={path(portOut(node(linking.from)!), linking)} className="pg__wire-line pg__wire-line--live" />
              )}
            </svg>

            {flow.nodes.map(n => {
              const spec = SPEC[n.kind]
              const Icon = ICONS[spec.icon]
              const bad = byNode.get(n.id)
              const filled = filledCount(n)
              return (
                <div
                  key={n.id}
                  data-node-id={n.id}
                  className={[
                    'pg__node', `pg__node--${spec.group}`,
                    sel === n.id ? 'is-sel' : '',
                    bad === 'error' ? 'is-err' : bad === 'warning' ? 'is-warn' : '',
                  ].join(' ').trim()}
                  style={{ left: n.x, top: n.y, width: NODE_W }}
                  onPointerDown={e => dragNode(e, n.id)}
                  role="button"
                  tabIndex={0}
                  aria-label={`${spec.label} node${sel === n.id ? ', selected' : ''}`}
                  onFocus={() => setSel(n.id)}
                  onKeyDown={e => nudge(e, n.id)}
                >
                  <header className="pg__node-h">
                    <span className="pg__node-ic"><Icon size={13} /></span>
                    <span className="pg__node-t">{spec.label}</span>
                    <button type="button" className="pg__node-x" title="Duplicate"
                            onPointerDown={e => e.stopPropagation()}
                            onClick={() => duplicate(n.id)}><Copy size={11} /></button>
                    <button type="button" className="pg__node-x" title="Remove"
                            onPointerDown={e => e.stopPropagation()}
                            onClick={() => removeNode(n.id)}><X size={12} /></button>
                  </header>
                  <p className="pg__node-b">{nodeSummary(n)}</p>
                  <footer className="pg__node-f">
                    <span className="pg__node-meta">{filled}/{spec.fields.length} set</span>
                    {bad && <span className={`pg__node-flag pg__node-flag--${bad}`}><AlertTriangle size={10} /></span>}
                  </footer>

                  {!!spec.inputs && <span className="pg__port pg__port--in" aria-hidden="true" />}
                  {!!spec.outputs && (
                    <span
                      className="pg__port pg__port--out"
                      title="Drag to connect"
                      onPointerDown={e => linkStart(e, n.id)}
                    />
                  )}
                </div>
              )
            })}
          </div>

          {!flow.nodes.length && (
            <div className="pg__empty">
              <Sparkles size={22} />
              <p className="pg__empty-t">Nothing wired up yet</p>
              <p className="pg__empty-s">
                Drag a source from the left — a contract or a rate card — then send it through
                an LLM or a formula, and finish with a report or an email.
              </p>
            </div>
          )}

          {lastRun && (
            <div className={`pg__run-res pg__run-res--${lastRun.status}`} role="status">
              <header>
                <span>{lastRun.status === 'ok' ? 'Run finished'
                  : lastRun.status === 'partial' ? 'Finished with problems' : 'Run failed'}</span>
                <button type="button" onClick={() => setLastRun(null)} aria-label="Hide"><X size={12} /></button>
              </header>
              <ul className="pg__run-steps">
                {lastRun.steps.map((st, i) => (
                  <li key={i} className={`pg__run-step pg__run-step--${st.status}`}>
                    <b>{st.kind}</b>
                    <span>{st.detail || st.status}</span>
                  </li>
                ))}
              </ul>
              {lastRun.outputs.length > 0 && (
                <ul className="pg__run-out">
                  {lastRun.outputs.map((o, i) => (
                    <li key={i}><b>{o.name}</b> — {o.how}</li>
                  ))}
                </ul>
              )}
              {lastRun.checks && (lastRun.checks.recon || lastRun.checks.terms.some(t => t.status === 'changed')) && (
                <ul className="pg__run-out pg__run-checks">
                  {lastRun.checks.terms.filter(t => t.status === 'changed').map(t => (
                    <li key={t.field} className="pg__run-check pg__run-check--warn">
                      <b>{termLabel(t.field)}</b> — calculated at {termValue(t.value, t.unit)};{' '}
                      {t.contract_file || 'the latest contract'} says {termValue(t.contract_value ?? '', t.unit)}.
                      Choose which to use in <Link to={reviewPath()}>Review Hub</Link>, then run again.
                    </li>
                  ))}
                  {lastRun.checks.recon && (() => {
                    const r = lastRun.checks.recon
                    return (
                      <li className={`pg__run-check pg__run-check--${r.status === 'match' ? 'ok' : 'warn'}`}>
                        <b>Bill {r.invoice_number || ''}</b> —{' '}
                        {r.status === 'match'
                          ? <>{r.total_name} {inr(r.sheet_total)} matches the bill before GST.</>
                          : <>{r.total_name} {inr(r.sheet_total)} vs {inr(r.before_tax)} on the bill before GST
                              {' '}({r.difference > 0 ? '+' : '−'}{inr(Math.abs(r.difference))}). Raised in Review Hub.</>}
                      </li>
                    )
                  })()}
                </ul>
              )}
            </div>
          )}

          {showIssues && issues.length > 0 && (
            <div className="pg__issues" role="status">
              <header className="pg__issues-h">
                <AlertTriangle size={12} />
                <span>{errors.length ? `${errors.length} to fix` : 'Suggestions'}</span>
                <button type="button" onClick={() => setShowIssues(false)} aria-label="Hide"><X size={12} /></button>
              </header>
              <ul>
                {issues.slice(0, 6).map((p, i) => (
                  <li key={i} className={`pg__issue pg__issue--${p.severity}`}>
                    {p.nodeId
                      ? <button type="button" onClick={() => setSel(p.nodeId!)}>{p.text}</button>
                      : <span>{p.text}</span>}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      </div>

      {/* ── inspector ───────────────────────────────────────────────────── */}
      <aside className="pg__insp" aria-label="Node settings">
        {!selected ? (
          <div className="pg__insp-none">
            <Info size={16} />
            <p>Pick a node to set it up.</p>
            <p className="pg__insp-tip">
              Drag the dot on a node's right edge onto another node to connect them.
              Click a wire to cut it. Ctrl+scroll zooms.
            </p>
          </div>
        ) : (
          <>
            <header className="pg__insp-h">
              <span className={`pg__insp-ic pg__insp-ic--${SPEC[selected.kind].group}`}>
                {(() => { const I = ICONS[SPEC[selected.kind].icon]; return <I size={14} /> })()}
              </span>
              <div>
                <h4>{SPEC[selected.kind].label}</h4>
                <p>{SPEC[selected.kind].blurb}</p>
              </div>
            </header>

            <div className="pg__fields">
              {SPEC[selected.kind].fields.map(f => {
                const id = `pg-${selected.id}-${f.key}`
                const val = selected.config[f.key] ?? ''
                const missing = f.kind !== 'formulas' && f.kind !== 'aggregates'
                  && (SPEC[selected.kind].required ?? []).includes(f.key) && !val.trim()
                return (
                  <div key={f.key} className="pg__field">
                    <label htmlFor={id}>
                      {f.label}
                      {missing && <span className="pg__req">required</span>}
                    </label>
                    {f.kind === 'formulas' || f.kind === 'aggregates' ? (
                      <FormulaSteps
                        value={val}
                        mode={f.kind === 'aggregates' ? 'aggregate' : 'column'}
                        onChange={v => setCfg(selected.id, f.key, v)}
                      />
                    ) : f.kind === 'area' ? (
                      <textarea id={id} rows={4} value={val} placeholder={f.placeholder}
                                onChange={e => setCfg(selected.id, f.key, e.target.value)} />
                    ) : f.kind === 'select' ? (
                      <select id={id} value={val} onChange={e => setCfg(selected.id, f.key, e.target.value)}>
                        {f.options?.map(o => <option key={o}>{o}</option>)}
                      </select>
                    ) : (
                      <input id={id} type={f.kind === 'url' ? 'url' : 'text'} value={val} placeholder={f.placeholder}
                             onChange={e => setCfg(selected.id, f.key, e.target.value)} />
                    )}
                    {f.hint && <p className="pg__hint">{f.hint}</p>}
                  </div>
                )
              })}
            </div>

            <footer className="pg__insp-f">
              <button type="button" className="pg__dup" onClick={() => duplicate(selected.id)}>
                <Copy size={13} />Duplicate with these settings
              </button>
              <button type="button" className="pg__del" onClick={() => removeNode(selected.id)}>
                <Trash2 size={13} />Remove node
              </button>
            </footer>
          </>
        )}
      </aside>
    </div>
  )
}
