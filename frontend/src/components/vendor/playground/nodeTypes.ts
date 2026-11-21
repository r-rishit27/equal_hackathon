/**
 * The node catalogue — what can be dropped on the playground canvas, and what
 * each kind needs configured before it could run.
 *
 * Kept as data rather than components so the palette, the canvas and the
 * inspector all read from one list: a new node kind is one entry here, not
 * three edits that can drift apart.
 *
 * Ports are deliberately coarse — one input, one output, no typed sockets.
 * A graph that refuses connections it cannot prove are valid is frustrating to
 * draw with; `problems()` reports what is wrong instead, so the canvas stays
 * permissive and the warnings stay honest.
 */

export type NodeKind =
  | 'contract' | 'ratecard' | 'document' | 'bills'   // sources
  | 'llm' | 'formula' | 'mcp'                        // compute
  | 'report' | 'email' | 'notify'                    // outputs

export type Group = 'source' | 'compute' | 'output'

export interface FieldSpec {
  key: string
  label: string
  kind: 'text' | 'area' | 'select' | 'url' | 'formulas' | 'aggregates'
  placeholder?: string
  options?: string[]
  hint?: string
}

export interface NodeSpec {
  kind: NodeKind
  label: string
  group: Group
  /** One line, shown under the title on the node and in the palette tooltip. */
  blurb: string
  icon: string            // lucide-react name, resolved in the component
  inputs: number
  outputs: number
  fields: FieldSpec[]
  /** Config keys that must be non-empty for the node to be runnable. */
  required?: string[]
}

export const NODE_SPECS: NodeSpec[] = [
  // ── Sources ───────────────────────────────────────────────────────────────
  {
    kind: 'contract', label: 'Contract / IO', group: 'source',
    blurb: 'A contract, insertion order or SOW on file for this vendor',
    icon: 'FileCheck2', inputs: 0, outputs: 1,
    fields: [
      { key: 'pick', label: 'Which document', kind: 'select', options: ['Latest contract', 'All contracts & IOs', 'Choose on run'] },
    ],
  },
  {
    kind: 'ratecard', label: 'Rate card', group: 'source',
    blurb: 'A rate card spreadsheet — its rows, not just its text',
    icon: 'Table2', inputs: 0, outputs: 1,
    fields: [
      { key: 'pick', label: 'Which rate card', kind: 'select', options: ['Latest rate card', 'All rate cards', 'Choose on run'] },
      { key: 'sheet', label: 'Sheet name', kind: 'text', placeholder: 'leave blank for the first sheet' },
    ],
  },
  {
    kind: 'document', label: 'Document', group: 'source',
    blurb: 'Any other filed document — certificates, letters, annexures',
    icon: 'FileText', inputs: 0, outputs: 1,
    fields: [
      { key: 'folder', label: 'Folder', kind: 'text', placeholder: 'e.g. Certificates' },
    ],
  },
  {
    kind: 'bills', label: 'Bills', group: 'source',
    blurb: "This vendor's invoices over a period",
    icon: 'Receipt', inputs: 0, outputs: 1,
    fields: [
      { key: 'range', label: 'Period', kind: 'select', options: ['This financial year', 'Last 12 months', 'Last quarter', 'All time'] },
      { key: 'status', label: 'Status', kind: 'select', options: ['All', 'Paid', 'Outstanding', 'Overdue'] },
    ],
  },

  // ── Compute ───────────────────────────────────────────────────────────────
  {
    kind: 'llm', label: 'LLM', group: 'compute',
    blurb: 'Reads what reaches it and answers in words',
    icon: 'Sparkles', inputs: 1, outputs: 1,
    fields: [
      { key: 'model', label: 'Model', kind: 'select', options: ['gpt-4o', 'gpt-4o-mini'] },
      {
        key: 'prompt', label: 'Instruction', kind: 'area',
        placeholder: 'Compare the rate card against the rates actually billed and list every mismatch.',
        hint: 'What reaches this node is supplied as context — refer to it directly.',
      },
    ],
    required: ['prompt'],
  },
  {
    kind: 'formula', label: 'Formula', group: 'compute',
    blurb: 'Calculations you write — totals, variances, thresholds',
    icon: 'Sigma', inputs: 1, outputs: 1,
    fields: [
      {
        key: 'steps', label: 'Columns to add', kind: 'formulas',
        hint: 'Worked once per row and appended to the rate card as a new column. '
            + 'A step can use any column named above it.',
      },
      {
        key: 'aggregates', label: 'Sheet totals', kind: 'aggregates',
        hint: 'One value for the whole sheet. Wrap a column in sum(), avg(), min(), '
            + 'max() or count() — a column holds a value per row, so it needs a total.',
      },
      {
        key: 'writeback', label: 'Where the columns go', kind: 'select',
        // A copy first, and by default: amending in place rewrites the file
        // the vendor sent, and a calculation re-run with a corrected formula
        // would then overwrite its own previous answer with no way back.
        options: [
          'Save a copy with the new columns',
          'Amend the rate card in place',
          'Keep the results in the flow only',
        ],
        hint: 'A copy leaves the original file untouched and is filed beside it in Documents. '
            + 'Amending in place changes the uploaded sheet itself.',
      },
      {
        key: 'copy_name', label: 'Name the copy', kind: 'text',
        placeholder: '{file} — calculated {date}',
        hint: '{file} is the original name, {date} today, {vendor} the vendor. Used only when a copy is saved.',
      },
    ],
    required: ['steps'],
  },
  {
    kind: 'mcp', label: 'MCP server', group: 'compute',
    blurb: 'Calls out to an MCP endpoint and brings the answer back',
    icon: 'Plug', inputs: 1, outputs: 1,
    fields: [
      { key: 'url', label: 'Server URL', kind: 'url', placeholder: 'https://mcp.example.com/sse' },
      { key: 'tool', label: 'Tool', kind: 'text', placeholder: 'leave blank to let the model choose' },
      { key: 'auth', label: 'Auth header', kind: 'text', placeholder: 'Bearer … (optional)' },
    ],
    required: ['url'],
  },

  // ── Outputs ───────────────────────────────────────────────────────────────
  {
    kind: 'report', label: 'Report', group: 'output',
    blurb: 'Collects everything upstream into one document',
    icon: 'FileBarChart', inputs: 1, outputs: 1,
    fields: [
      { key: 'title', label: 'Title', kind: 'text', placeholder: 'Rate card compliance — {vendor}' },
      { key: 'format', label: 'Format', kind: 'select', options: ['PDF', 'Excel', 'Markdown'] },
    ],
    required: ['title'],
  },
  {
    kind: 'email', label: 'Email', group: 'output',
    blurb: "Mails the result to the vendor's contact, report attached",
    icon: 'Mail', inputs: 1, outputs: 0,
    fields: [
      {
        key: 'to', label: 'To', kind: 'text',
        placeholder: "leave blank to use the vendor's contact",
        hint: "Blank sends to this vendor's configured point of contact, so it keeps working "
            + 'when that person changes. Several addresses can be separated by commas.',
      },
      { key: 'subject', label: 'Subject', kind: 'text', placeholder: 'Rate card review — {vendor}' },
      {
        key: 'body', label: 'Covering note', kind: 'area',
        placeholder: 'Optional — anything a Report node produced is attached.',
      },
    ],
    required: ['subject'],
  },
  {
    kind: 'notify', label: 'Notification', group: 'output',
    blurb: 'Raises it in the app instead of by mail',
    icon: 'Bell', inputs: 1, outputs: 0,
    fields: [
      { key: 'text', label: 'Message', kind: 'text', placeholder: 'Rate card variance found for {vendor}' },
      { key: 'level', label: 'Importance', kind: 'select', options: ['Info', 'Warning', 'Urgent'] },
    ],
    required: ['text'],
  },
]

export const SPEC: Record<NodeKind, NodeSpec> =
  Object.fromEntries(NODE_SPECS.map(s => [s.kind, s])) as Record<NodeKind, NodeSpec>

export const GROUPS: { id: Group; label: string }[] = [
  { id: 'source', label: 'Sources' },
  { id: 'compute', label: 'Compute' },
  { id: 'output', label: 'Outputs' },
]

// ── The graph ───────────────────────────────────────────────────────────────

export interface FlowNode {
  id: string
  kind: NodeKind
  x: number
  y: number
  config: Record<string, string>
}

export interface FlowEdge {
  id: string
  from: string
  to: string
}

export interface Flow {
  nodes: FlowNode[]
  edges: FlowEdge[]
}

export const EMPTY: Flow = { nodes: [], edges: [] }

/** Defaults so a freshly dropped node is already sensible. */
export function newNode(kind: NodeKind, x: number, y: number, id = rid()): FlowNode {
  const config: Record<string, string> = {}
  for (const f of SPEC[kind].fields) {
    if (f.kind === 'select' && f.options?.length) config[f.key] = f.options[0]
    if (f.kind === 'formulas' || f.kind === 'aggregates') config[f.key] = writeSteps([newStep()])
  }
  return { id, kind, x, y, config }
}

export function rid(): string {
  return Math.random().toString(36).slice(2, 10)
}


// ── Formula steps ───────────────────────────────────────────────────────────
// A Formula node holds an ordered list rather than one expression, so a long
// calculation can be written the way it is reasoned about: name a piece, then
// build on it. Stored JSON-encoded in `config.steps` to keep FlowNode.config a
// flat string map — the alternative was a union type threaded through
// everything that touches a node for the benefit of one field.

export interface Step {
  id: string
  name: string
  expr: string
}

export function parseSteps(raw: string | undefined): Step[] {
  if (!raw) return []
  try {
    const v = JSON.parse(raw)
    if (!Array.isArray(v)) return []
    return v
      .filter(s => s && typeof s === 'object')
      .map(s => ({ id: String(s.id ?? rid()), name: String(s.name ?? ''), expr: String(s.expr ?? '') }))
  } catch {
    // Older flows stored a single expression. Carry it over rather than
    // silently dropping a calculation someone wrote.
    return [{ id: rid(), name: 'result', expr: raw }]
  }
}

export const writeSteps = (steps: Step[]): string => JSON.stringify(steps)

export const newStep = (name = '', expr = ''): Step => ({ id: rid(), name, expr })

/**
 * Which of `names` the expression actually uses.
 *
 * Matches the known names rather than tokenising the expression, because the
 * names come from a finance team, not a programmer: "GR@100%", "% Routing"
 * and "Provision fees" are all real, and no identifier pattern covers a name
 * with a space in it. Two rules make the match safe:
 *
 *  - longest first, so `GR@100%` is claimed before a shorter `GR` can be;
 *  - a hit must not run into a neighbouring name character, so `GR` does not
 *    match inside `GR@100%`.
 *
 * Quoted text is skipped: `ratecard["Bill Rate"]` names a column of the source
 * sheet, not a step, and a step called `Rate` must not match inside it.
 */
export function namesUsedIn(expr: string, names: string[]): string[] {
  const code = expr.replace(/"[^"]*"|'[^']*'/g, ' ')
  const hit: string[] = []
  const ordered = [...new Set(names.map(n => n.trim()).filter(Boolean))]
    .sort((a, b) => b.length - a.length)
  let left = code
  for (const name of ordered) {
    const esc = name.replace(/[^A-Za-z0-9]/g, c => '\\' + c)
    const re = new RegExp(String.raw`(^|[^\w@%])` + esc + String.raw`($|[^\w@%])`)
    if (re.test(left)) {
      hit.push(name)
      // Blank it so a shorter name cannot also claim the same text.
      left = left.replace(new RegExp(esc, 'g'), ' '.repeat(name.length))
    }
  }
  return hit
}

/**
 * Functions that turn a column into one number.
 *
 * The distinction they draw is the whole point of the two sections: a column
 * holds a value per row, so naming one at sheet level is ambiguous — "GR@100%"
 * is 18 numbers, not one. Wrapping it says which single number is meant.
 */
export const AGG_FUNCS = ['sum', 'avg', 'average', 'mean', 'min', 'max', 'count', 'median', 'first', 'last'] as const

/**
 * Blanks out `sum( … )` spans, so whatever identifiers remain are the ones
 * used directly at sheet level. Scans for the matching bracket rather than
 * regex-matching the call, so `sum(a * max(b, c))` is removed whole.
 */
export function stripAggregateCalls(expr: string): string {
  const re = new RegExp(String.raw`\b(?:${AGG_FUNCS.join('|')})\s*\(`, 'i')
  let out = expr
  for (let guard = 0; guard < 64; guard++) {
    const m = re.exec(out)
    if (!m) break
    let depth = 0
    let i = m.index + m[0].length - 1
    for (; i < out.length; i++) {
      if (out[i] === '(') depth++
      else if (out[i] === ')' && --depth === 0) break
    }
    out = out.slice(0, m.index) + ' '.repeat(Math.min(i, out.length - 1) - m.index + 1) + out.slice(i + 1)
  }
  return out
}

/**
 * What is wrong with the sheet-level section, given the columns above it.
 *
 * Beyond the ordering and naming rules every step list has, two directions are
 * checked, both of which would otherwise produce a number that looks right:
 *
 *  - a column used at sheet level without a total around it — 18 values where
 *    one was expected;
 *  - a column that reads a sheet total, which is circular, since the total is
 *    computed from every row of that same column.
 */
export function aggregateProblems(columns: Step[], aggs: Step[]): string[] {
  const colNames = new Set(columns.map(c => c.name.trim()).filter(Boolean))
  const aggNames = new Set(aggs.map(a => a.name.trim()).filter(Boolean))
  const out = stepProblems(aggs)

  for (const a of aggs) {
    if (!a.expr.trim()) continue
    // Both name sets are offered to the matcher so the longer one wins: in
    // `Total GR / 2` the column `GR` must not be claimed out of the middle of
    // the total named `Total GR`. Only the column hits are then reported.
    const used = namesUsedIn(stripAggregateCalls(a.expr), [...aggNames, ...colNames])
    for (const ref of used) {
      if (colNames.has(ref)) out.push(`"${ref}" is a column — wrap it in sum(…) or another total`)
    }
  }

  for (const c of columns) {
    if (!c.expr.trim()) continue
    for (const ref of namesUsedIn(c.expr, [...aggNames])) {
      out.push(`Column "${c.name.trim() || c.expr}" uses the sheet total "${ref}", which is worked out from it`)
    }
  }
  return out
}

/** What is wrong with one Formula node's step list. */
export function stepProblems(steps: Step[]): string[] {
  const out: string[] = []
  const names = steps.map(s => s.name.trim())

  const seen = new Map<string, number>()
  for (const n of names.filter(Boolean)) {
    const hit = seen.get(n)
    if (hit) out.push(`"${n}" is defined twice`)
    seen.set(n, (hit ?? 0) + 1)
  }

  steps.forEach((s, i) => {
    if (!s.expr.trim()) {
      out.push(`${names[i] ? `"${names[i]}"` : `Step ${i + 1}`} has no expression`)
      return
    }
    const used = namesUsedIn(s.expr, names)
    const above = new Set(names.slice(0, i).filter(Boolean))
    for (const ref of used) {
      if (ref === names[i]) out.push(`"${ref}" refers to itself`)
      else if (!above.has(ref)) out.push(`"${names[i] || `Step ${i + 1}`}" uses "${ref}" before it is worked out`)
    }
  })
  return out
}

// ── What's wrong with it ────────────────────────────────────────────────────

export interface Problem {
  nodeId?: string
  text: string
  severity: 'error' | 'warning'
}

/**
 * Reported rather than enforced. The canvas lets you draw a half-finished
 * graph on purpose — you are usually mid-thought — so this is what a run
 * would complain about, surfaced while there is still something to fix.
 */
export function problems(flow: Flow): Problem[] {
  const out: Problem[] = []
  const { nodes, edges } = flow
  if (!nodes.length) return out

  const incoming = new Map<string, number>()
  const outgoing = new Map<string, number>()
  for (const e of edges) {
    outgoing.set(e.from, (outgoing.get(e.from) ?? 0) + 1)
    incoming.set(e.to, (incoming.get(e.to) ?? 0) + 1)
  }

  for (const n of nodes) {
    const spec = SPEC[n.kind]
    for (const key of spec.required ?? []) {
      const field = spec.fields.find(f => f.key === key)
      if (field?.kind === 'formulas') {
        const steps = parseSteps(n.config[key])
        if (!steps.length || steps.every(st => !st.expr.trim())) {
          out.push({ nodeId: n.id, severity: 'error', text: `${spec.label}: no calculation yet` })
        }
        for (const text of stepProblems(steps)) {
          out.push({ nodeId: n.id, severity: 'error', text: `${spec.label}: ${text}` })
        }
        // Sheet totals are optional, but they are checked against the columns
        // above them, so they are validated from here rather than on their own.
        const aggField = spec.fields.find(f => f.kind === 'aggregates')
        if (aggField) {
          const aggs = parseSteps(n.config[aggField.key]).filter(a => a.name.trim() || a.expr.trim())
          for (const text of aggregateProblems(steps, aggs)) {
            out.push({ nodeId: n.id, severity: 'error', text: `${spec.label}: ${text}` })
          }
        }
        continue
      }
      if (field?.kind === 'aggregates') continue   // handled alongside the columns
      if (!(n.config[key] ?? '').trim()) {
        out.push({ nodeId: n.id, severity: 'error', text: `${spec.label}: ${field?.label ?? key} is empty` })
      }
    }
    if (spec.inputs > 0 && !incoming.get(n.id)) {
      out.push({ nodeId: n.id, severity: 'warning', text: `${spec.label} has nothing connected into it` })
    }
    if (spec.outputs > 0 && !outgoing.get(n.id) && spec.group !== 'output') {
      out.push({ nodeId: n.id, severity: 'warning', text: `${spec.label} leads nowhere` })
    }
  }

  if (!nodes.some(n => SPEC[n.kind].group === 'output')) {
    out.push({ severity: 'warning', text: 'Nothing is produced — add a Report, Email or Notification' })
  }
  for (const id of cycleNodes(flow)) {
    out.push({ nodeId: id, severity: 'error', text: `${SPEC[nodes.find(n => n.id === id)!.kind].label} is part of a loop` })
  }
  return out
}

/** Nodes caught in a cycle; a run would never terminate on these. */
export function cycleNodes(flow: Flow): string[] {
  const next = new Map<string, string[]>()
  for (const e of flow.edges) next.set(e.from, [...(next.get(e.from) ?? []), e.to])

  const WHITE = 0, GREY = 1, BLACK = 2
  const mark = new Map<string, number>(flow.nodes.map(n => [n.id, WHITE]))
  const bad = new Set<string>()

  const walk = (id: string, trail: string[]) => {
    mark.set(id, GREY)
    for (const to of next.get(id) ?? []) {
      if (mark.get(to) === GREY) {
        // everything from `to` onwards in the trail is on the cycle
        const at = trail.indexOf(to)
        for (const n of trail.slice(at === -1 ? 0 : at)) bad.add(n)
        bad.add(to)
      } else if (mark.get(to) === WHITE) {
        walk(to, [...trail, to])
      }
    }
    mark.set(id, BLACK)
  }
  for (const n of flow.nodes) if (mark.get(n.id) === WHITE) walk(n.id, [n.id])
  return [...bad]
}

/** Execution order, sources first. Empty when the graph has a cycle. */
export function runOrder(flow: Flow): string[] {
  if (cycleNodes(flow).length) return []
  const deps = new Map<string, Set<string>>(flow.nodes.map(n => [n.id, new Set()]))
  for (const e of flow.edges) deps.get(e.to)?.add(e.from)

  const done: string[] = []
  const left = new Set(flow.nodes.map(n => n.id))
  while (left.size) {
    const ready = [...left].filter(id => [...(deps.get(id) ?? [])].every(d => done.includes(d) || !left.has(d)))
    if (!ready.length) break
    for (const id of ready) { done.push(id); left.delete(id) }
  }
  return done
}
