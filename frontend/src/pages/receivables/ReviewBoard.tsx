import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { Check, ChevronDown, ChevronRight, ExternalLink, FileText, Landmark, Undo2, X } from 'lucide-react'
import { Button, formatDate, useToast } from '../../ui'
import {
  apiError, applyPayment, unapplyPayment,
  type AllocationIn, type BoardGroup, type BoardInvoice, type BoardPayment, type ReasonCode,
} from '../../api/receivables'
import { arCustomerPath, arInvoicePath } from '../../routes/paths'
import { KIND_LABELS, fromPaise, money, tidy, toPaise } from './format'

/**
 * The review board: everything waiting on a person, one card per customer.
 * Invoices on the left, payments on the right, and a line for every amount the
 * agent applied from a payment to an invoice — so a payment split across
 * invoices, an invoice paid in parts, and many-to-many all read at a glance.
 *
 * Lines can be removed, added (drag from a card's edge) or moved (drag the
 * amount). Clicking a line opens the full payment card at that invoice; clicking
 * an invoice, payment or customer shows a short summary.
 */

/** One payment → invoice allocation. Amounts are paise. */
interface Edge {
  p: string
  i: string
  amt: number
  tds: number
  ded: number
  code: ReasonCode | ''
  note: string
  by: 'agent' | 'user'
}
type Status = 'sure' | 'check' | 'user'
type Hot = { k: 'i' | 'p'; id: string } | { k: 'e'; id: string } | null

const SURE = 0.95
const key = (e: Pick<Edge, 'p' | 'i'>) => `${e.p}>${e.i}`

function agentEdges(p: BoardPayment): Edge[] {
  return (p.best?.allocations ?? []).map(a => ({
    p: p.id, i: a.invoice_id, amt: toPaise(a.amount_applied), tds: toPaise(a.tds_amount), ded: toPaise(a.deduction_amount),
    code: (a.reason_code ?? '') as ReasonCode | '', note: a.reason_note ?? '', by: 'agent',
  }))
}

/** Edges as the request the payment card sends. */
function toAllocations(edges: Edge[]): AllocationIn[] {
  return edges.map(e => ({
    invoice_id: e.i,
    amount_applied: fromPaise(e.amt),
    tds_amount: fromPaise(e.tds),
    deduction_amount: fromPaise(e.ded),
    reason_code: (e.code || (e.tds ? 'TDS' : null)) as ReasonCode | null,
    reason_note: e.note || null,
  }))
}

const pctOf = (p: BoardPayment) => Math.round(Number(p.match_confidence ?? 0) * 100)
const bankOf = (p: BoardPayment): { tone: 'ok' | 'warn' | 'bad' | 'none'; label: string } =>
  p.flags?.includes('POSSIBLE_BOUNCE') ? { tone: 'bad', label: 'Possible bounce' }
  : p.flags?.includes('POSSIBLE_DUPLICATE') ? { tone: 'warn', label: 'Possible duplicate' }
  : p.source === 'statement' ? { tone: 'ok', label: 'On the statement' }
  : { tone: 'none', label: 'Entered by hand' }
const remitOf = (p: BoardPayment): { tone: 'ok' | 'warn' | 'none'; label: string } =>
  !p.remittance_id ? { tone: 'none', label: 'Not received' }
  : p.remittance_total != null && Math.abs(toPaise(p.remittance_total) - toPaise(p.amount)) > 100 ? { tone: 'warn', label: 'Total differs' }
  : { tone: 'ok', label: 'Matches' }
const short = (paise: number) => `₹${Math.round(paise / 100).toLocaleString('en-IN')}`
const titleCase = (s: string) => s.toLowerCase().replace(/\b\w/g, c => c.toUpperCase()).replace(/ Private Limited$| Pvt\.? Ltd\.?$/i, '')
const initials = (s: string) => s.replace(/[^A-Za-z ]/g, '').split(/\s+/).filter(Boolean).slice(0, 2).map(w => w[0]).join('').toUpperCase()

export default function ReviewBoard({ groups, canPost, onOpenEdge, onChanged, toolbar }: {
  groups: BoardGroup[]
  /** Sits at the start of the hint row (the Board | List switch). */
  toolbar?: ReactNode
  canPost: boolean
  /** Open the full payment card on this invoice, carrying the board's lines for that payment. */
  onOpenEdge: (paymentId: string, invoiceId: string | null, allocations: AllocationIn[] | null) => void
  onChanged: () => void
}) {
  // Lines a person changed, per payment, kept until that payment changes on the server.
  const [overrides, setOverrides] = useState<Record<string, { version: number; edges: Edge[] }>>({})
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set())
  const [showOther, setShowOther] = useState<Set<string>>(new Set())
  const [busy, setBusy] = useState<string | null>(null)
  const toast = useToast()

  // Drop edits for payments that were applied or re-matched since.
  useEffect(() => {
    const live = new Map(groups.flatMap(g => g.payments.map(p => [p.id, p.version] as const)))
    setOverrides(o => {
      const n = Object.fromEntries(Object.entries(o).filter(([id, v]) => live.get(id) === v.version))
      return Object.keys(n).length === Object.keys(o).length ? o : n
    })
  }, [groups])

  const edgesFor = useCallback((p: BoardPayment) => {
    const o = overrides[p.id]
    return o && o.version === p.version ? o.edges : agentEdges(p)
  }, [overrides])

  /** Replace some payments' lines in one step; returns an undo. */
  const edit = useCallback((g: BoardGroup, next: Record<string, Edge[]>) => {
    const before = overrides
    setOverrides(o => {
      const n = { ...o }
      for (const [pid, es] of Object.entries(next)) {
        const p = g.payments.find(x => x.id === pid)!
        n[pid] = { version: p.version, edges: es }
      }
      return n
    })
    return () => setOverrides(before)
  }, [overrides])

  const confirmGroup = async (g: BoardGroup, gkey: string) => {
    const pays = g.payments.filter(p => edgesFor(p).length)
    const all = g.payments.flatMap(edgesFor)
    // Refuse anything the server would: an invoice paid past what it owes, a payment spent twice, a deduction with no reason.
    const inv = new Map(g.invoices.map(i => [i.id, i]))
    const over = [...new Set(all.map(e => e.i))].find(id => {
      const i = inv.get(id)
      return i && all.filter(e => e.i === id).reduce((s, e) => s + e.amt + e.tds + e.ded, 0) > toPaise(i.outstanding)
    })
    if (over) return toast.warn(`${inv.get(over)!.invoice_number} is over-applied`, 'Remove or move one of its lines first.')
    const spent = pays.find(p => edgesFor(p).reduce((s, e) => s + e.amt, 0) > toPaise(p.amount))
    if (spent) return toast.warn(`The ${formatDate(spent.received_on)} payment is applied past its amount`, 'Lower one of its lines first.')
    if (all.some(e => e.ded && !e.code)) return toast.warn('A deduction needs a reason', 'Open the line to pick one.')
    if (!pays.length) return toast.warn('Link each payment to an invoice first')
    setBusy(gkey)
    const done: string[] = []
    let failed = ''
    for (const p of pays) {
      const changed = !!overrides[p.id]
      try {
        await applyPayment(p.id, {
          allocations: toAllocations(edgesFor(p)), version: p.version, method: changed ? 'manual' : 'accepted',
          customer_id: g.customer?.id ?? p.customer_id, kind: changed ? null : p.best?.kind ?? null,
          confidence: changed ? null : p.best?.confidence ?? null, allow_disputed: true,
        })
        done.push(p.id)
      } catch (e) { failed = apiError(e); break }
    }
    setBusy(null)
    const amt = g.payments.filter(p => done.includes(p.id)).reduce((s, p) => s + toPaise(p.amount), 0)
    if (done.length) {
      toast.show({
        tone: 'success',
        title: `${money(fromPaise(amt))} applied · ${titleCase(g.customer?.name ?? 'customer')}`,
        message: done.length > 1 ? `${done.length} payments` : undefined,
        action: {
          label: 'Undo',
          onClick: () => {
            Promise.all(done.map(id => unapplyPayment(id, 'Undone right after confirming')))
              .then(() => { toast.success('Undone — back in review'); onChanged() })
              .catch(e => toast.error('Couldn’t undo', apiError(e)))
          },
        },
      })
    }
    if (failed) toast.error(done.length ? 'Some payments were not applied' : 'Not applied', failed)
    onChanged()
  }

  return (
    <div className="rb">
      <div className="rb-hint">
        {toolbar}
        <span className="rb-hint__t">Click a line to review it · drag from a card’s edge to link · drag an amount to move it</span>
        <span className="rb-legend" aria-hidden="true">
          <span><i className="s-sure" />Agent, sure</span><span><i className="s-check" />Agent, to review</span><span><i className="s-user" />Changed by you</span>
        </span>
      </div>
      {groups.map(g => {
        const gkey = g.customer?.id ?? 'unknown'
        return (
          <Group key={gkey} g={g} edgesFor={edgesFor} changed={g.payments.some(p => !!overrides[p.id])}
            collapsed={collapsed.has(gkey)} showOther={showOther.has(gkey)} canPost={canPost} busy={busy === gkey}
            onToggle={() => setCollapsed(s => toggled(s, gkey))} onOther={() => setShowOther(s => toggled(s, gkey))}
            onReset={() => {
              const before = overrides
              setOverrides(o => Object.fromEntries(Object.entries(o).filter(([id]) => !g.payments.some(p => p.id === id))))
              toast.show({ tone: 'info', title: `Back to the agent’s match for ${titleCase(g.customer?.name ?? 'this customer')}`,
                action: { label: 'Undo', onClick: () => setOverrides(before) } })
            }}
            onEdit={(next, msg) => {
              const undo = edit(g, next)
              toast.show({ tone: 'info', title: msg, action: { label: 'Undo', onClick: undo } })
            }}
            onWarn={m => toast.warn(m)}
            onConfirm={() => void confirmGroup(g, gkey)}
            onOpenEdge={(pid, iid) => {
              const p = g.payments.find(x => x.id === pid)!
              onOpenEdge(pid, iid, overrides[pid] ? toAllocations(edgesFor(p)) : null)
            }} />
        )
      })}
    </div>
  )
}

const toggled = (s: Set<string>, k: string) => { const n = new Set(s); if (n.has(k)) n.delete(k); else n.add(k); return n }

// ── One customer ─────────────────────────────────────────────────────────────

interface Geo { paths: { k: string; s: Status; d: string; a: [number, number]; b: [number, number] }[]; labels: { e: Edge; s: Status; x: number; y: number }[] }

function Group({ g, edgesFor, changed, collapsed, showOther, canPost, busy, onToggle, onOther, onReset, onEdit, onWarn, onConfirm, onOpenEdge }: {
  g: BoardGroup; edgesFor: (p: BoardPayment) => Edge[]; changed: boolean; collapsed: boolean; showOther: boolean
  canPost: boolean; busy: boolean
  onToggle: () => void; onOther: () => void; onReset: () => void
  onEdit: (next: Record<string, Edge[]>, msg: string) => void; onWarn: (m: string) => void
  onConfirm: () => void; onOpenEdge: (pid: string, iid: string | null) => void
}) {
  const edges = useMemo(() => g.payments.flatMap(edgesFor), [g.payments, edgesFor])
  const pay = useCallback((id: string) => g.payments.find(p => p.id === id)!, [g.payments])

  // Invoices the lines point at that are no longer open still need a card to land on.
  const invoices = useMemo(() => {
    const list: BoardInvoice[] = [...g.invoices]
    for (const p of g.payments) for (const a of p.best?.allocations ?? []) {
      if (!list.some(i => i.id === a.invoice_id)) list.push({
        id: a.invoice_id, invoice_number: a.invoice_number, invoice_date: null, due_date: null, po_number: null,
        total_amount: a.amount_applied, amount_received: a.amount_applied, tds_amount: '0', deduction_amount: '0',
        outstanding: '0', taxable_amount: null, status: 'paid', customer_id: g.customer?.id ?? '', days_overdue: null,
      })
    }
    return list
  }, [g])
  const inv = useCallback((id: string) => invoices.find(i => i.id === id)!, [invoices])
  const onI = (id: string) => edges.filter(e => e.i === id)
  const onP = (id: string) => edges.filter(e => e.p === id)
  const invLeft = (i: BoardInvoice) => toPaise(i.outstanding) - onI(i.id).reduce((s, e) => s + e.amt + e.tds + e.ded, 0)
  const payLeft = (p: BoardPayment) => toPaise(p.amount) - onP(p.id).reduce((s, e) => s + e.amt, 0)
  const status = (e: Edge): Status => e.by === 'user' ? 'user' : Number(pay(e.p).match_confidence ?? 0) >= SURE ? 'sure' : 'check'

  const linked = invoices.filter(i => onI(i.id).length)
  const others = invoices.filter(i => !onI(i.id).length)
  const shownInv = showOther ? [...linked, ...others] : linked
  // Payments sit beside the invoices they pay, so lines cross as little as possible.
  const order = new Map(shownInv.map((i, n) => [i.id, n]))
  const shownPay = [...g.payments].sort((a, b) => bary(a) - bary(b))
  function bary(p: BoardPayment) { const es = onP(p.id); return es.length ? es.reduce((s, e) => s + (order.get(e.i) ?? 99), 0) / es.length : 999 }

  const received = g.payments.reduce((s, p) => s + toPaise(p.amount), 0)
  const notApplied = g.payments.reduce((s, p) => s + Math.max(0, payLeft(p)), 0)
  const applied = edges.reduce((s, e) => s + e.amt, 0)
  const invoiced = linked.reduce((s, i) => s + toPaise(i.total_amount), 0)
  const toReview = g.payments.filter(p => !onP(p.id).length || payLeft(p) !== 0 || Number(p.match_confidence ?? 0) < SURE || p.flags?.length).length
  const ready = g.payments.filter(p => onP(p.id).length).length
  const name = g.customer?.name ?? 'Customer not identified'

  // ── geometry ──
  const bodyRef = useRef<HTMLDivElement>(null)
  const [geo, setGeo] = useState<Geo>({ paths: [], labels: [] })
  const sig = JSON.stringify([edges.map(e => [e.p, e.i, e.amt, e.by]), showOther, collapsed, shownPay.map(p => p.id)])
  const measure = useCallback(() => {
    const body = bodyRef.current
    if (!body) return
    const B = body.getBoundingClientRect()
    const rect = (k: string) => {
      const n = body.querySelector<HTMLElement>(`[data-node="${k}"]`)
      if (!n) return null
      const r = n.getBoundingClientRect()
      return { l: r.left - B.left, r: r.right - B.left, t: r.top - B.top, h: r.height }
    }
    const ends = edges.map(e => ({ e, ri: rect(`i:${e.i}`), rp: rect(`p:${e.p}`) })).filter(x => x.ri && x.rp) as
      { e: Edge; ri: NonNullable<ReturnType<typeof rect>>; rp: NonNullable<ReturnType<typeof rect>> }[]
    // A card's lines spread along its edge, in the order of the cards they go to.
    const slot = new Map<string, number>()
    for (const side of ['i', 'p'] as const) {
      const by = new Map<string, typeof ends>()
      for (const x of ends) by.set(x.e[side], [...(by.get(x.e[side]) ?? []), x])
      for (const arr of by.values()) {
        arr.sort((a, b) => side === 'i' ? a.rp.t - b.rp.t : a.ri.t - b.ri.t)
        arr.forEach((x, n) => { const r = side === 'i' ? x.ri : x.rp; slot.set(side + key(x.e), r.t + r.h * (n + 1) / (arr.length + 1)) })
      }
    }
    const paths: Geo['paths'] = []
    const labels: (Geo['labels'][number] & { bz: number[] })[] = []
    for (const { e, ri, rp } of ends) {
      const x1 = ri.r, y1 = slot.get('i' + key(e))!, x2 = rp.l, y2 = slot.get('p' + key(e))!
      const dx = (x2 - x1) / 2
      const s = status(e)
      paths.push({ k: key(e), s, d: `M${x1},${y1} C${x1 + dx},${y1} ${x2 - dx},${y2} ${x2},${y2}`, a: [x1, y1], b: [x2, y2] })
      const bz = [x1, y1, x1 + dx, y1, x2 - dx, y2, x2, y2]
      const [x, y] = bez(bz, 0.5)
      labels.push({ e, s, x, y, bz })
    }
    // Two amounts that would sit on top of each other slide apart along their lines.
    labels.sort((a, b) => a.y - b.y)
    for (let n = 1; n < labels.length; n++) {
      const a = labels[n - 1], b = labels[n]
      if (Math.abs(a.y - b.y) < 28 && Math.abs(a.x - b.x) < 110) {
        ;[a.x, a.y] = bez(a.bz, 0.3)
        ;[b.x, b.y] = bez(b.bz, 0.7)
      }
    }
    setGeo({ paths, labels })
  }, [sig]) // eslint-disable-line react-hooks/exhaustive-deps -- sig covers what the layout reads
  useLayoutEffect(() => { if (!collapsed) measure() }, [measure, collapsed])
  useEffect(() => {
    const body = bodyRef.current
    if (!body || typeof ResizeObserver === 'undefined') return
    const ro = new ResizeObserver(() => measure())
    ro.observe(body)
    return () => ro.disconnect()
  }, [measure, collapsed])

  // ── hover ──
  const [hot, setHot] = useState<Hot>(null)
  const hotEdges = useMemo(() => {
    if (!hot) return null
    const es = hot.k === 'e' ? edges.filter(e => key(e) === hot.id) : edges.filter(e => e[hot.k] === hot.id)
    return es.length ? es : null
  }, [hot, edges])
  const hotKeys = hotEdges ? new Set(hotEdges.map(key)) : null
  const hotNodes = hotEdges ? new Set(hotEdges.flatMap(e => [`i:${e.i}`, `p:${e.p}`])) : null
  const nodeCls = (k: string) => hot && (hot.k + ':' + hot.id === k ? ' is-hot' : hotNodes && !hotNodes.has(k) ? ' is-dim' : '')
  const edgeCls = (k: string) => hotKeys ? (hotKeys.has(k) ? ' is-hot' : ' is-dim') : ''

  // ── drag: from a card's edge to link, or an amount to move its line ──
  const [temp, setTemp] = useState<string | null>(null)
  const [target, setTarget] = useState<string | null>(null)
  const drag = useRef<{ mode: 'new' | 'move'; from?: { k: 'i' | 'p'; id: string }; edge?: Edge; sx: number; sy: number; moved: boolean } | null>(null)
  const suppressClick = useRef(false)

  const targetAt = (x: number, y: number, d = drag.current) => {
    const el = document.elementFromPoint(x, y)?.closest<HTMLElement>('[data-node]')
    if (!el || !bodyRef.current?.contains(el) || !d) return null
    const [k, id] = el.dataset.node!.split(':') as ['i' | 'p', string]
    if (d.mode === 'new' && k === d.from!.k) return null
    return { k, id, node: el.dataset.node! }
  }
  const startAt = () => {
    const d = drag.current!, body = bodyRef.current!
    const B = body.getBoundingClientRect()
    if (d.mode === 'new') {
      const r = body.querySelector(`[data-dot="${d.from!.k}:${d.from!.id}"]`)!.getBoundingClientRect()
      return [r.left + r.width / 2 - B.left, r.top + r.height / 2 - B.top]
    }
    const r = body.querySelector(`[data-node="p:${d.edge!.p}"]`)!.getBoundingClientRect()
    return [r.left - B.left, r.top + r.height / 2 - B.top]
  }
  const onPointerDown = (ev: React.PointerEvent, start: NonNullable<typeof drag.current>) => {
    if (ev.button !== 0 || !canPost) return
    ev.preventDefault()
    drag.current = start
    const move = (e: PointerEvent) => {
      const d = drag.current
      if (!d) return
      if (!d.moved && Math.hypot(e.clientX - d.sx, e.clientY - d.sy) < 5) return
      if (!d.moved) { d.moved = true; document.body.classList.add('rb-grabbing'); setHot(null) }
      const B = bodyRef.current!.getBoundingClientRect()
      const [ax, ay] = startAt(), mx = e.clientX - B.left, my = e.clientY - B.top, dx = (mx - ax) / 2
      setTemp(`M${ax},${ay} C${ax + dx},${ay} ${mx - dx},${my} ${mx},${my}`)
      setTarget(targetAt(e.clientX, e.clientY)?.node ?? null)
    }
    const up = (e: PointerEvent) => {
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', up)
      document.body.classList.remove('rb-grabbing')
      const d = drag.current
      drag.current = null
      setTemp(null); setTarget(null)
      if (!d?.moved) {
        if (d?.mode === 'move' && d.edge) onOpenEdge(d.edge.p, d.edge.i)
        return
      }
      suppressClick.current = true
      setTimeout(() => { suppressClick.current = false }, 0)
      const t = targetAt(e.clientX, e.clientY, d)
      if (t) drop(d, t)
    }
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', up)
  }

  const drop = (d: NonNullable<typeof drag.current>, t: { k: 'i' | 'p'; id: string }) => {
    if (d.mode === 'new') {
      const pid = d.from!.k === 'p' ? d.from!.id : t.id
      const iid = d.from!.k === 'i' ? d.from!.id : t.id
      if (edges.some(e => e.p === pid && e.i === iid)) return onWarn('Those two are already linked')
      const p = pay(pid), i = inv(iid)
      const amt = Math.min(payLeft(p), invLeft(i))
      if (amt <= 0) return onWarn(payLeft(p) <= 0 ? 'This payment is fully applied — remove one of its lines first' : 'This invoice is already fully paid')
      onEdit({ [pid]: [...onP(pid), { p: pid, i: iid, amt, tds: 0, ded: 0, code: '', note: '', by: 'user' }] },
        `Applied ${money(fromPaise(amt))} to ${i.invoice_number}`)
      return
    }
    const e = d.edge!
    const np = t.k === 'p' ? t.id : e.p, ni = t.k === 'i' ? t.id : e.i
    if (np === e.p && ni === e.i) return
    if (edges.some(x => x !== e && x.p === np && x.i === ni)) return onWarn('Those two are already linked')
    const room = t.k === 'i'
      ? toPaise(inv(ni).outstanding) - edges.filter(x => x.i === ni && x !== e).reduce((s, x) => s + x.amt + x.tds + x.ded, 0)
      : toPaise(pay(np).amount) - edges.filter(x => x.p === np && x !== e).reduce((s, x) => s + x.amt, 0)
    const amt = Math.min(e.amt, room)
    if (amt <= 0) return onWarn(t.k === 'i' ? 'That invoice is already fully paid' : 'That payment is fully applied')
    const moved: Edge = { ...e, p: np, i: ni, amt, by: 'user', tds: t.k === 'i' ? 0 : e.tds, ded: t.k === 'i' ? 0 : e.ded }
    const next: Record<string, Edge[]> = { [e.p]: onP(e.p).filter(x => x !== e) }
    next[np] = [...(next[np] ?? onP(np)), moved]
    onEdit(next, `Moved ${money(fromPaise(amt))} to ${t.k === 'i' ? inv(ni).invoice_number : `the ${formatDate(pay(np).received_on)} payment`}`)
  }

  const cut = (e: Edge) => onEdit({ [e.p]: onP(e.p).filter(x => x !== e) },
    `Unlinked ${inv(e.i).invoice_number} from the ${formatDate(pay(e.p).received_on)} payment`)

  // ── summaries ──
  const [pop, setPop] = useState<{ k: 'i' | 'p' | 'c'; id: string; anchor: DOMRect } | null>(null)
  const openPop = (k: 'i' | 'p' | 'c', id: string, el: HTMLElement) => {
    if (suppressClick.current) return
    setPop({ k, id, anchor: el.getBoundingClientRect() })
  }

  return (
    <section className={`rb-grp${collapsed ? ' is-collapsed' : ''}`} aria-label={name}>
      <header className="rb-grp__head">
        <button type="button" className="rb-who" onClick={e => g.customer && openPop('c', g.customer.id, e.currentTarget)}>
          <span className="rb-ava" aria-hidden="true">{initials(name)}</span>
          <span className="rb-who__t">
            <span className="rb-who__name">{name}</span>
            <span className="rb-who__sub">
              {g.payments.length} payment{g.payments.length === 1 ? '' : 's'} · {linked.length} invoice{linked.length === 1 ? '' : 's'} · {toReview
                ? <span className="rb-need">{toReview} to review</span> : <span className="rb-ok">all matched</span>}
            </span>
          </span>
        </button>
        <dl className="rb-flow">
          <div><dt>Invoiced</dt><dd>{money(fromPaise(invoiced))}</dd></div>
          <div><dt>Cash received</dt><dd>{money(fromPaise(received))}</dd></div>
          <div><dt>Cash applied</dt><dd>{money(fromPaise(applied))}</dd></div>
          {notApplied > 0 && <div className="is-warn"><dt>Not applied</dt><dd>{money(fromPaise(notApplied))}</dd></div>}
        </dl>
        <div className="rb-acts">
          {changed && <Button size="sm" variant="ghost" iconLeft={<Undo2 size={13} />} onClick={onReset} title="Undo your changes for this customer">Agent’s match</Button>}
          {canPost && ready > 0 && (
            <Button size="sm" variant="primary" iconLeft={<Check size={13} />} loading={busy} onClick={onConfirm}>Confirm {ready}</Button>
          )}
          <button type="button" className="rb-caret" onClick={onToggle} aria-expanded={!collapsed} aria-label={collapsed ? `Show ${name}` : `Hide ${name}`}>
            <ChevronDown size={16} />
          </button>
        </div>
      </header>

      {!collapsed && (
        // eslint-disable-next-line jsx-a11y/no-static-element-interactions -- hover only highlights; every control inside is a button
        <div className="rb-body" ref={bodyRef} onMouseLeave={() => setHot(null)}>
          <div className="rb-col">
            <div className="rb-col__h">Invoices <span>{money(fromPaise(shownInv.reduce((s, i) => s + toPaise(i.outstanding), 0)))} open</span></div>
            <div className="rb-stack">
              {linked.map(i => <InvNode key={i.id} i={i} left={invLeft(i)} lines={onI(i.id).length} cls={nodeCls(`i:${i.id}`) || ''}
                drop={target === `i:${i.id}`} canPost={canPost}
                onHover={() => setHot({ k: 'i', id: i.id })} onClick={el => openPop('i', i.id, el)}
                onDot={ev => onPointerDown(ev, { mode: 'new', from: { k: 'i', id: i.id }, sx: ev.clientX, sy: ev.clientY, moved: false })} />)}
            </div>
            {others.length > 0 && (showOther ? (
              <>
                <div className="rb-others">Other open invoices — drag a payment onto one to apply</div>
                <div className="rb-stack">
                  {others.map(i => <InvNode key={i.id} i={i} left={invLeft(i)} lines={0} cls={nodeCls(`i:${i.id}`) || ''} other
                    drop={target === `i:${i.id}`} canPost={canPost}
                    onHover={() => setHot({ k: 'i', id: i.id })} onClick={el => openPop('i', i.id, el)}
                    onDot={ev => onPointerDown(ev, { mode: 'new', from: { k: 'i', id: i.id }, sx: ev.clientX, sy: ev.clientY, moved: false })} />)}
                </div>
                <button type="button" className="rb-more" onClick={onOther}>Hide other invoices</button>
              </>
            ) : <button type="button" className="rb-more" onClick={onOther}>+ {others.length} other open invoice{others.length === 1 ? '' : 's'}</button>)}
          </div>
          <div aria-hidden="true" />
          <div className="rb-col">
            <div className="rb-col__h">Payments <span>{money(fromPaise(received))}</span></div>
            <div className="rb-stack">
              {shownPay.map(p => <PayNode key={p.id} p={p} left={payLeft(p)} lines={onP(p.id).length} cls={nodeCls(`p:${p.id}`) || ''}
                drop={target === `p:${p.id}`} canPost={canPost}
                onHover={() => setHot({ k: 'p', id: p.id })} onClick={el => openPop('p', p.id, el)}
                onDot={ev => onPointerDown(ev, { mode: 'new', from: { k: 'p', id: p.id }, sx: ev.clientX, sy: ev.clientY, moved: false })} />)}
            </div>
          </div>

          <svg className="rb-wires" aria-hidden="true">
            {geo.paths.map(w => (
              <g key={w.k} className={edgeCls(w.k)}>
                <path className={`rb-wire s-${w.s}`} d={w.d} />
                <circle className={`rb-cap s-${w.s}`} cx={w.a[0]} cy={w.a[1]} r={3.5} />
                <circle className={`rb-cap s-${w.s}`} cx={w.b[0]} cy={w.b[1]} r={3.5} />
              </g>
            ))}
            {temp && <path className="rb-wire rb-wire--temp" d={temp} />}
          </svg>
          <div className="rb-labels">
            {geo.labels.map(({ e, s, x, y }) => (
              // eslint-disable-next-line jsx-a11y/no-static-element-interactions -- hover only highlights; the amount and × are buttons
              <span key={key(e)} className={`rb-lbl s-${s}${edgeCls(key(e))}`} style={{ left: x, top: y }}
                onMouseEnter={() => setHot({ k: 'e', id: key(e) })}>
                <button type="button" className="rb-lbl__amt" title={canPost ? 'Review this line · drag to move it' : 'Review this line'}
                  onPointerDown={ev => onPointerDown(ev, { mode: 'move', edge: e, sx: ev.clientX, sy: ev.clientY, moved: false })}
                  // Mouse opens on release (so a drag can start); keyboard and read-only users open on click.
                  onClick={ev => { if (!canPost || ev.detail === 0) onOpenEdge(e.p, e.i) }}>
                  {short(e.amt)}{e.ded > 0 && <span className="rb-lbl__ded">−{short(e.ded)}</span>}
                </button>
                {canPost && <button type="button" className="rb-lbl__x" onClick={() => cut(e)} aria-label={`Remove the ${short(e.amt)} line`} title="Remove this line"><X size={10} /></button>}
              </span>
            ))}
          </div>
        </div>
      )}

      {pop && createPortal(
        <Popover anchor={pop.anchor} side={pop.k === 'i' ? 'right' : pop.k === 'p' ? 'left' : 'below'} onClose={() => setPop(null)}>
          {pop.k === 'i' && <InvSummary i={inv(pop.id)} edges={onI(pop.id)} left={invLeft(inv(pop.id))} pay={pay} status={status}
            onOpen={pid => { setPop(null); onOpenEdge(pid, pop.id) }} />}
          {pop.k === 'p' && <PaySummary p={pay(pop.id)} edges={onP(pop.id)} left={payLeft(pay(pop.id))} inv={inv} status={status}
            onOpen={iid => { setPop(null); onOpenEdge(pop.id, iid) }} />}
          {pop.k === 'c' && g.customer && <CustomerSummary g={g} onOpen={pid => { setPop(null); onOpenEdge(pid, null) }} />}
        </Popover>, document.body)}
    </section>
  )
}

function bez(b: number[], t: number): [number, number] {
  const m = 1 - t
  const at = (k: number) => m * m * m * b[k] + 3 * m * m * t * b[2 + k] + 3 * m * t * t * b[4 + k] + t * t * t * b[6 + k]
  return [at(0), at(1)]
}

// ── Cards ────────────────────────────────────────────────────────────────────

/** The repeated prefix of an invoice number in grey, the part that tells them apart in bold. */
function InvNo({ no }: { no: string }) {
  const cut = no.length > 8 ? no.length - 5 : 0
  return <><span className="rb-pre">{no.slice(0, cut)}</span>{no.slice(cut)}</>
}

function InvNode({ i, left, lines, cls, other, drop, canPost, onHover, onClick, onDot }: {
  i: BoardInvoice; left: number; lines: number; cls: string; other?: boolean; drop: boolean; canPost: boolean
  onHover: () => void; onClick: (el: HTMLElement) => void; onDot: (ev: React.PointerEvent) => void
}) {
  const open = toPaise(i.outstanding), total = toPaise(i.total_amount)
  const state = !lines ? <span className="rb-st">{money(i.outstanding)} open</span>
    : left === 0 ? <span className="rb-st rb-st--ok"><Check size={12} /> Clears</span>
    : left < 0 ? <span className="rb-st rb-st--warn">Over by {money(fromPaise(-left))}</span>
    : <span className="rb-st rb-st--mid">{money(fromPaise(left))} stays open</span>
  return (
    <div className={`rb-node rb-node--inv${other ? ' is-other' : ''}${drop ? ' is-target' : ''}${cls}`} data-node={`i:${i.id}`}
      role="button" tabIndex={0} onMouseEnter={onHover} onClick={e => onClick(e.currentTarget)}
      onKeyDown={e => { if (e.key === 'Enter') onClick(e.currentTarget) }}>
      <div className="rb-node__r1">
        <span className="rb-node__id"><InvNo no={i.invoice_number} /></span>
        <span className="rb-node__amt">{money(i.total_amount)}</span>
      </div>
      <div className="rb-node__r2">
        <span>{i.status === 'disputed' ? <span className="rb-tag">Disputed</span> : null}
          {i.due_date ? `Due ${formatDate(i.due_date)}` : i.status === 'paid' ? 'No longer open' : 'No due date'}
          {i.days_overdue ? ` · ${i.days_overdue}d late` : ''}</span>
        {state}
      </div>
      {lines > 0 && left > 0 && total > 0 && (
        <div className="rb-meter"><span style={{ width: `${Math.min(100, ((total - open) + (open - left)) / total * 100)}%` }} /></div>
      )}
      {canPost && <span className="rb-dot" data-dot={`i:${i.id}`} title="Drag to a payment" onPointerDown={e => { e.stopPropagation(); onDot(e) }}
        onClick={e => e.stopPropagation()} aria-hidden="true" />}
    </div>
  )
}

function PayNode({ p, left, lines, cls, drop, canPost, onHover, onClick, onDot }: {
  p: BoardPayment; left: number; lines: number; cls: string; drop: boolean; canPost: boolean
  onHover: () => void; onClick: (el: HTMLElement) => void; onDot: (ev: React.PointerEvent) => void
}) {
  const bank = bankOf(p), remit = remitOf(p), pct = pctOf(p)
  const issue = !lines ? 'Not matched — drag onto an invoice' : left > 0 ? `${money(fromPaise(left))} not applied`
    : left < 0 ? `Over by ${money(fromPaise(-left))}` : bank.tone === 'bad' || bank.tone === 'warn' ? bank.label : ''
  return (
    <div className={`rb-node rb-node--pay${issue ? ' is-issue' : ''}${drop ? ' is-target' : ''}${cls}`} data-node={`p:${p.id}`}
      role="button" tabIndex={0} onMouseEnter={onHover} onClick={e => onClick(e.currentTarget)}
      onKeyDown={e => { if (e.key === 'Enter') onClick(e.currentTarget) }}>
      {canPost && <span className="rb-dot" data-dot={`p:${p.id}`} title="Drag to an invoice" onPointerDown={e => { e.stopPropagation(); onDot(e) }}
        onClick={e => e.stopPropagation()} aria-hidden="true" />}
      <div className="rb-node__r1">
        <span className="rb-node__id">{formatDate(p.received_on)}{p.method && <span className="rb-pre"> · {p.method}</span>}</span>
        <span className="rb-node__amt">{money(p.amount)}</span>
      </div>
      <div className="rb-node__r2">
        <span className="rb-ref">{p.utr ?? p.reference ?? p.payer_name ?? '—'}</span>
        <span className="rb-src">
          <span className={`t-${bank.tone}`} title={`Bank: ${bank.label}`}><Landmark size={14} /></span>
          <span className={`t-${remit.tone}`} title={`Remittance: ${remit.label}`}><FileText size={14} /></span>
          <span className={`rb-pct${pct >= SURE * 100 ? ' is-ok' : ''}`} title="Confidence score">{pct ? `${pct}%` : '—'}</span>
        </span>
      </div>
      {issue && <div className="rb-node__issue">{issue}</div>}
    </div>
  )
}

// ── Summaries ────────────────────────────────────────────────────────────────

function Popover({ anchor, side, onClose, children }: { anchor: DOMRect; side: 'left' | 'right' | 'below'; onClose: () => void; children: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null)
  const [pos, setPos] = useState<{ x: number; y: number } | null>(null)
  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return
    const w = el.offsetWidth, h = el.offsetHeight
    let x = side === 'right' ? anchor.right + 12 : side === 'left' ? anchor.left - w - 12 : anchor.left
    let y = side === 'below' ? anchor.bottom + 8 : anchor.top
    x = Math.max(12, Math.min(x, innerWidth - w - 12))
    y = Math.max(12, Math.min(y, innerHeight - h - 12))
    setPos({ x, y })
  }, [anchor, side])
  useEffect(() => {
    const down = (e: MouseEvent) => { if (!ref.current?.contains(e.target as Node)) onClose() }
    const key = (e: KeyboardEvent) => { if (e.key === 'Escape') { e.stopPropagation(); onClose() } }
    const scroll = () => onClose()
    document.addEventListener('mousedown', down)
    document.addEventListener('keydown', key, true)
    window.addEventListener('scroll', scroll, true)
    return () => { document.removeEventListener('mousedown', down); document.removeEventListener('keydown', key, true); window.removeEventListener('scroll', scroll, true) }
  }, [onClose])
  return (
    <div ref={ref} className="rb-pop" role="dialog" style={{ left: pos?.x ?? -9999, top: pos?.y ?? 0, transformOrigin: side === 'left' ? 'right top' : 'left top' }}>
      {children}
    </div>
  )
}

function InvSummary({ i, edges, left, pay, status, onOpen }: {
  i: BoardInvoice; edges: Edge[]; left: number; pay: (id: string) => BoardPayment; status: (e: Edge) => Status; onOpen: (pid: string) => void
}) {
  const ded = edges.reduce((s, e) => s + e.ded + e.tds, 0)
  return (
    <>
      <div className="rb-pop__eyebrow">Invoice{i.invoice_date ? ` · ${formatDate(i.invoice_date)}` : ''}</div>
      <div className="rb-pop__title">{i.invoice_number}</div>
      <div className="rb-pop__hero">{money(i.total_amount)}</div>
      <dl className="rb-kv">
        <dt>Due</dt><dd>{i.due_date ? formatDate(i.due_date) : '—'}{i.days_overdue ? ` · ${i.days_overdue}d late` : ''}</dd>
        <dt>Received before</dt><dd>{money(fromPaise(toPaise(i.total_amount) - toPaise(i.outstanding)))}</dd>
        <dt>In this review</dt><dd>{money(fromPaise(edges.reduce((s, e) => s + e.amt, 0)))}</dd>
        {ded > 0 && <><dt>TDS and deductions</dt><dd>{money(fromPaise(ded))}</dd></>}
        <dt>After this</dt>
        <dd className={left === 0 ? 'is-ok' : left < 0 ? 'is-warn' : 'is-strong'}>
          {left === 0 ? 'Clears' : left > 0 ? `${money(fromPaise(left))} stays open` : `Over by ${money(fromPaise(-left))}`}
        </dd>
      </dl>
      {edges.length ? (
        <div className="rb-links">
          <div className="rb-links__h">Paid by</div>
          {edges.map(e => { const p = pay(e.p); return (
            <button key={key(e)} type="button" className="rb-link" onClick={() => onOpen(p.id)}>
              <span className="rb-link__l"><i className={`rb-sw s-${status(e)}`} />{formatDate(p.received_on)}{p.method ? ` · ${p.method}` : ''}</span>
              <span><b>{money(fromPaise(e.amt))}</b><ChevronRight size={14} /></span>
            </button>
          ) })}
        </div>
      ) : <p className="rb-pop__note">Not linked to a payment. Drag a payment onto it to apply one.</p>}
      <div className="rb-pop__acts">
        <a className="u-btn u-btn--secondary u-btn--sm" href={arInvoicePath(i.id)} target="_blank" rel="noopener noreferrer"><ExternalLink size={13} /> Open invoice</a>
      </div>
    </>
  )
}

function PaySummary({ p, edges, left, inv, status, onOpen }: {
  p: BoardPayment; edges: Edge[]; left: number; inv: (id: string) => BoardInvoice; status: (e: Edge) => Status; onOpen: (iid: string | null) => void
}) {
  const bank = bankOf(p), remit = remitOf(p), pct = pctOf(p)
  const clues = (p.best?.clues ?? []).map(tidy).filter(c => !/^(The )?remittance advice lists \d+ lines?$/i.test(c)).slice(0, 4)
  return (
    <>
      <div className="rb-pop__eyebrow">{formatDate(p.received_on)}{p.method ? ` · ${p.method}` : ''} {p.utr ?? p.reference ?? ''}</div>
      <div className="rb-pop__hero">{money(p.amount)}</div>
      <div className="rb-proofs">
        <span className={`rb-proof t-${bank.tone}`}><Landmark size={13} /> {bank.label}</span>
        <span className={`rb-proof t-${remit.tone}`}><FileText size={13} /> {remit.tone === 'none' ? 'No remittance' : `Remittance ${remit.label.toLowerCase()}`}</span>
      </div>
      <dl className="rb-kv">
        <dt>Confidence score</dt><dd className={pct >= SURE * 100 ? 'is-ok' : 'is-strong'}>{pct ? `${pct}%` : 'No match'}</dd>
        {p.best?.kind && <><dt>Basis</dt><dd>{KIND_LABELS[p.best.kind] ?? p.best.kind}</dd></>}
      </dl>
      {clues.length > 0 && <ul className="rb-why">{clues.map((c, n) => <li key={n}>{c}</li>)}</ul>}
      {edges.length > 0 && (
        <div className="rb-links">
          <div className="rb-links__h">Applied to</div>
          {edges.map(e => (
            <button key={key(e)} type="button" className="rb-link" onClick={() => onOpen(e.i)}>
              <span className="rb-link__l"><i className={`rb-sw s-${status(e)}`} />{inv(e.i).invoice_number}</span>
              <span><b>{money(fromPaise(e.amt))}</b><ChevronRight size={14} /></span>
            </button>
          ))}
        </div>
      )}
      <dl className="rb-kv"><dt>Not applied</dt><dd className={left ? 'is-warn' : 'is-ok'}>{money(fromPaise(Math.max(0, left)))}</dd></dl>
      <div className="rb-pop__acts"><Button size="sm" variant="primary" onClick={() => onOpen(null)}>Review payment</Button></div>
    </>
  )
}

function CustomerSummary({ g, onOpen }: { g: BoardGroup; onOpen: (pid: string) => void }) {
  const c = g.customer!
  const rec = g.payments.reduce((s, p) => s + toPaise(p.amount), 0)
  return (
    <>
      <div className="rb-pop__eyebrow">Customer</div>
      <div className="rb-pop__title">{c.name}</div>
      <dl className="rb-kv">
        <dt>Open receivables</dt><dd>{money(c.open_ar)}</dd>
        <dt>Overdue</dt><dd className={toPaise(c.overdue) ? 'is-warn' : 'is-ok'}>{money(c.overdue)}</dd>
        {c.payment_terms_days != null && <><dt>Payment terms</dt><dd>{c.payment_terms_days} days</dd></>}
        <dt>In this review</dt><dd>{g.payments.length} payment{g.payments.length === 1 ? '' : 's'} · {money(fromPaise(rec))}</dd>
      </dl>
      <div className="rb-links">
        <div className="rb-links__h">Payments to review</div>
        {g.payments.map(p => (
          <button key={p.id} type="button" className="rb-link" onClick={() => onOpen(p.id)}>
            <span className="rb-link__l"><span className={`rb-pct${pctOf(p) >= SURE * 100 ? ' is-ok' : ''}`}>{pctOf(p) ? `${pctOf(p)}%` : '—'}</span>{formatDate(p.received_on)}{p.method ? ` · ${p.method}` : ''}</span>
            <span><b>{money(p.amount)}</b><ChevronRight size={14} /></span>
          </button>
        ))}
      </div>
      <div className="rb-pop__acts">
        <a className="u-btn u-btn--secondary u-btn--sm" href={arCustomerPath(c.id)} target="_blank" rel="noopener noreferrer"><ExternalLink size={13} /> Open customer</a>
      </div>
    </>
  )
}
