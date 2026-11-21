/**
 * The playground's graph rules.
 *
 * The canvas is deliberately permissive — it lets you draw a half-finished
 * flow, because you are usually mid-thought — so correctness lives here, in
 * what gets reported and in what order a run would take. These are the parts
 * that would quietly mislead if they were wrong: a flow that claims to be
 * valid while a required field is empty, or a run order that starts in the
 * middle.
 */
import { describe, expect, it } from 'vitest'
import {
  EMPTY, NODE_SPECS, SPEC, cycleNodes, newNode, newStep, parseSteps, problems,
  runOrder, namesUsedIn, stepProblems, stripAggregateCalls, aggregateProblems, writeSteps,
  type Flow, type FlowNode, type NodeKind,
} from './nodeTypes'

function flow(nodes: FlowNode[], pairs: [string, string][] = []): Flow {
  return { nodes, edges: pairs.map(([from, to], i) => ({ id: `e${i}`, from, to })) }
}

const at = (kind: NodeKind, id: string, cfg: Record<string, string> = {}): FlowNode =>
  ({ ...newNode(kind, 0, 0, id), config: { ...newNode(kind, 0, 0, id).config, ...cfg } })

const ok = {
  llm: { prompt: 'summarise it' },
  formula: { steps: writeSteps([newStep('total', 'sum(bills.amount)')]) },
  mcp: { url: 'https://mcp.example.com' },
  report: { title: 'Report' },
  email: { to: 'a@b.com', subject: 'Hi' },
  notify: { text: 'Heads up' },
}

// ── the catalogue holds together ────────────────────────────────────────────

describe('catalogue', () => {
  it('every spec is reachable by its kind', () => {
    for (const s of NODE_SPECS) expect(SPEC[s.kind]).toBe(s)
  })

  it('no two nodes share a kind', () => {
    const kinds = NODE_SPECS.map(s => s.kind)
    expect(new Set(kinds).size).toBe(kinds.length)
  })

  it('every required key names a field that actually exists', () => {
    for (const s of NODE_SPECS) {
      for (const key of s.required ?? []) {
        expect(s.fields.map(f => f.key), `${s.kind}.${key}`).toContain(key)
      }
    }
  })

  it('sources take no input and outputs produce nothing downstream', () => {
    for (const s of NODE_SPECS) {
      if (s.group === 'source') expect(s.inputs, s.kind).toBe(0)
      if (s.group !== 'source') expect(s.inputs, s.kind).toBeGreaterThan(0)
    }
  })

  it('a select field starts on one of its own options', () => {
    for (const s of NODE_SPECS) {
      const n = newNode(s.kind, 0, 0)
      for (const f of s.fields) {
        if (f.kind === 'select') expect(f.options).toContain(n.config[f.key])
      }
    }
  })
})

// ── what gets reported ──────────────────────────────────────────────────────

describe('problems', () => {
  it('says nothing about an empty canvas', () => {
    expect(problems(EMPTY)).toEqual([])
  })

  it('reports a required field left empty', () => {
    const p = problems(flow([at('contract', 'a'), at('llm', 'b')], [['a', 'b']]))
    expect(p.some(x => x.severity === 'error' && /Instruction is empty/.test(x.text))).toBe(true)
  })

  it('stops reporting it once filled', () => {
    const p = problems(flow([at('contract', 'a'), at('llm', 'b', ok.llm)], [['a', 'b']]))
    expect(p.filter(x => x.severity === 'error')).toEqual([])
  })

  it('warns when a node that needs an input has none', () => {
    const p = problems(flow([at('llm', 'b', ok.llm)]))
    expect(p.some(x => /nothing connected into it/.test(x.text))).toBe(true)
  })

  it('warns when a compute node leads nowhere', () => {
    const p = problems(flow([at('contract', 'a'), at('llm', 'b', ok.llm)], [['a', 'b']]))
    expect(p.some(x => /leads nowhere/.test(x.text))).toBe(true)
  })

  it('does not say an output node leads nowhere — it is the end', () => {
    const f = flow(
      [at('contract', 'a'), at('llm', 'b', ok.llm), at('email', 'c', ok.email)],
      [['a', 'b'], ['b', 'c']],
    )
    expect(problems(f).some(x => /leads nowhere/.test(x.text))).toBe(false)
  })

  it('warns when a flow produces nothing at all', () => {
    const f = flow([at('contract', 'a'), at('llm', 'b', ok.llm)], [['a', 'b']])
    expect(problems(f).some(x => /Nothing is produced/.test(x.text))).toBe(true)
  })

  it('a complete flow reports nothing', () => {
    const f = flow(
      [at('ratecard', 'a'), at('formula', 'b', ok.formula), at('report', 'c', ok.report), at('email', 'd', ok.email)],
      [['a', 'b'], ['b', 'c'], ['c', 'd']],
    )
    expect(problems(f)).toEqual([])
  })

  it('points each problem at the node it belongs to', () => {
    const p = problems(flow([at('contract', 'a'), at('llm', 'bad')], [['a', 'bad']]))
    expect(p.find(x => /Instruction/.test(x.text))?.nodeId).toBe('bad')
  })
})

// ── loops ───────────────────────────────────────────────────────────────────

describe('cycles', () => {
  it('finds none in a straight line', () => {
    expect(cycleNodes(flow([at('contract', 'a'), at('llm', 'b')], [['a', 'b']]))).toEqual([])
  })

  it('finds a two-node loop', () => {
    const c = cycleNodes(flow([at('llm', 'a'), at('formula', 'b')], [['a', 'b'], ['b', 'a']]))
    expect(new Set(c)).toEqual(new Set(['a', 'b']))
  })

  it('finds a longer loop', () => {
    const c = cycleNodes(flow(
      [at('llm', 'a'), at('formula', 'b'), at('mcp', 'c')],
      [['a', 'b'], ['b', 'c'], ['c', 'a']],
    ))
    expect(new Set(c)).toEqual(new Set(['a', 'b', 'c']))
  })

  it('leaves nodes outside the loop alone', () => {
    const c = cycleNodes(flow(
      [at('contract', 'src'), at('llm', 'a'), at('formula', 'b')],
      [['src', 'a'], ['a', 'b'], ['b', 'a']],
    ))
    expect(c).not.toContain('src')
  })

  it('a loop is an error, not a warning — a run would never finish', () => {
    const p = problems(flow([at('llm', 'a', ok.llm), at('formula', 'b', ok.formula)], [['a', 'b'], ['b', 'a']]))
    expect(p.some(x => x.severity === 'error' && /loop/.test(x.text))).toBe(true)
  })

  it('a diamond is not a loop', () => {
    const c = cycleNodes(flow(
      [at('contract', 'a'), at('llm', 'b'), at('formula', 'c'), at('report', 'd')],
      [['a', 'b'], ['a', 'c'], ['b', 'd'], ['c', 'd']],
    ))
    expect(c).toEqual([])
  })
})

// ── run order ───────────────────────────────────────────────────────────────

describe('runOrder', () => {
  it('puts a source before what reads it', () => {
    const o = runOrder(flow([at('llm', 'b'), at('contract', 'a')], [['a', 'b']]))
    expect(o.indexOf('a')).toBeLessThan(o.indexOf('b'))
  })

  it('orders a whole chain', () => {
    const o = runOrder(flow(
      [at('report', 'c'), at('contract', 'a'), at('email', 'd'), at('llm', 'b')],
      [['a', 'b'], ['b', 'c'], ['c', 'd']],
    ))
    expect(o).toEqual(['a', 'b', 'c', 'd'])
  })

  it('waits for both sides of a diamond before the join', () => {
    const o = runOrder(flow(
      [at('contract', 'a'), at('llm', 'b'), at('formula', 'c'), at('report', 'd')],
      [['a', 'b'], ['a', 'c'], ['b', 'd'], ['c', 'd']],
    ))
    expect(o.indexOf('d')).toBeGreaterThan(o.indexOf('b'))
    expect(o.indexOf('d')).toBeGreaterThan(o.indexOf('c'))
  })

  it('includes nodes that stand alone', () => {
    expect(runOrder(flow([at('contract', 'a'), at('bills', 'b')]))).toHaveLength(2)
  })

  it('refuses to order a graph with a loop', () => {
    expect(runOrder(flow([at('llm', 'a'), at('formula', 'b')], [['a', 'b'], ['b', 'a']]))).toEqual([])
  })

  it('covers every node exactly once', () => {
    const f = flow(
      [at('contract', 'a'), at('ratecard', 'b'), at('llm', 'c'), at('report', 'd')],
      [['a', 'c'], ['b', 'c'], ['c', 'd']],
    )
    const o = runOrder(f)
    expect(new Set(o).size).toBe(o.length)
    expect(o).toHaveLength(f.nodes.length)
  })
})

// ── several calculations in one node ────────────────────────────────────────
// Order is meaningful here: a step may use the names above it and nothing
// else. These pin the cases where a flow would look fine and compute nonsense.

describe('formula steps', () => {
  const steps = (...rows: [string, string][]) =>
    writeSteps(rows.map(([name, expr]) => ({ ...newStep(name, expr) })))

  const formulaNode = (raw: string) => at('formula', 'f', { steps: raw })

  it('round-trips through storage', () => {
    const raw = steps(['total', 'sum(bills.amount)'], ['variance', 'total - expected'])
    const back = parseSteps(raw)
    expect(back.map(s => [s.name, s.expr])).toEqual([
      ['total', 'sum(bills.amount)'],
      ['variance', 'total - expected'],
    ])
  })

  it('gives every step its own id so reordering is stable', () => {
    const parsed = parseSteps(steps(['a', '1'], ['b', '2']))
    expect(parsed[0].id).not.toBe(parsed[1].id)
  })

  it('a new Formula node opens with one empty step, not a blank box', () => {
    expect(parseSteps(newNode('formula', 0, 0).config.steps)).toHaveLength(1)
  })

  it('carries over a flow saved before steps existed', () => {
    // Older nodes stored a bare expression string, which is not JSON.
    const back = parseSteps('sum(bills.amount) - expected')
    expect(back).toHaveLength(1)
    expect(back[0].expr).toBe('sum(bills.amount) - expected')
  })

  it('survives a corrupt value rather than throwing', () => {
    expect(parseSteps('{"not":"an array"}')).toEqual([])
    expect(parseSteps(undefined)).toEqual([])
  })

  // ── references between steps ──────────────────────────────────────────────

  it('a later step may use an earlier name', () => {
    expect(stepProblems(parseSteps(steps(
      ['billed', 'sum(bills.amount)'],
      ['variance', 'billed - expected'],
    )))).toEqual([])
  })

  it('refuses a step that uses a name worked out below it', () => {
    const bad = stepProblems(parseSteps(steps(
      ['variance', 'billed - 100'],
      ['billed', 'sum(bills.amount)'],
    )))
    expect(bad.some(t => /uses "billed" before it is worked out/.test(t))).toBe(true)
  })

  it('refuses a step that refers to itself', () => {
    const bad = stepProblems(parseSteps(steps(['total', 'total + 1'])))
    expect(bad.some(t => /refers to itself/.test(t))).toBe(true)
  })

  it('catches a name defined twice', () => {
    const bad = stepProblems(parseSteps(steps(['total', '1'], ['total', '2'])))
    expect(bad.some(t => /defined twice/.test(t))).toBe(true)
  })

  it('reports a step left without an expression', () => {
    const bad = stepProblems(parseSteps(steps(['total', 'sum(x)'], ['variance', ''])))
    expect(bad.some(t => /no expression/.test(t))).toBe(true)
  })

  it('does not mistake a function call or a field path for a step name', () => {
    expect(stepProblems(parseSteps(steps(
      ['billed', 'sum(bills.amount) + max(ratecard.rate)'],
    )))).toEqual([])
  })

  // ── how it surfaces on the canvas ─────────────────────────────────────────

  it('an unfinished step list is an error on the node', () => {
    const p = problems(flow([at('contract', 'a'), formulaNode(steps(['total', '']))], [['a', 'f']]))
    expect(p.some(x => x.severity === 'error' && /no calculation yet/.test(x.text))).toBe(true)
  })

  it('a bad reference is reported against the node that holds it', () => {
    const f = flow(
      [at('contract', 'a'), formulaNode(steps(['v', 'billed - 1'], ['billed', 'sum(x)'])), at('report', 'r', ok.report)],
      [['a', 'f'], ['f', 'r']],
    )
    const p = problems(f).filter(x => x.severity === 'error')
    expect(p.length).toBeGreaterThan(0)
    expect(p.every(x => x.nodeId === 'f')).toBe(true)
  })

  it('a well-formed multi-step flow reports nothing', () => {
    const f = flow(
      [
        at('bills', 'a'),
        formulaNode(steps(['billed', 'sum(bills.amount)'], ['expected', 'sum(ratecard.rate)'], ['variance', 'billed - expected'])),
        at('report', 'r', ok.report),
      ],
      [['a', 'f'], ['f', 'r']],
    )
    expect(problems(f)).toEqual([])
  })
})

// ── names as people actually write them ─────────────────────────────────────
// Rate-card fields are named by the finance team, not by programmers:
// "GR@100%", "% Routing" and "Provision fees" are all real. Matching the known
// names rather than tokenising the expression is what makes those work — no
// identifier pattern covers a name with a space in it.

describe('real-world field names', () => {
  it('matches a name containing @ and %', () => {
    expect(namesUsedIn('GR@100% * 0.952', ['GR@100%'])).toEqual(['GR@100%'])
  })

  it('matches a name containing a space', () => {
    expect(namesUsedIn('Total GR / 2', ['Total GR'])).toEqual(['Total GR'])
  })

  it('does not let a shorter name match inside a longer one', () => {
    expect(namesUsedIn('GR@100% * 0.952', ['GR', 'GR@100%'])).toEqual(['GR@100%'])
  })

  it('still finds the shorter name when it stands alone', () => {
    expect(namesUsedIn('GR * 2', ['GR', 'GR@100%'])).toEqual(['GR'])
  })

  it('reads a quoted column name as a value, not as a step', () => {
    expect(namesUsedIn('ratecard["Bill Rate"] / 22', ['Rate', 'Bill Rate'])).toEqual([])
  })

  it('handles single quotes too', () => {
    expect(namesUsedIn("contract['% Routing'] * 2", ['% Routing'])).toEqual([])
  })

  it('finds a name outside the quotes', () => {
    expect(namesUsedIn('GR@100% * (1 - contract["% Routing"])', ['GR@100%'])).toEqual(['GR@100%'])
  })

  it('ignores a name that is merely part of a longer word', () => {
    expect(namesUsedIn('GROSS * 2', ['GR'])).toEqual([])
  })

  it('the per-row staffing calculation validates end to end', () => {
    const steps = parseSteps(writeSteps([
      newStep('GR@100%', 'ratecard["Bill Rate"] / ratecard["Working Days in Month"] * ratecard["No of Days"]'),
      newStep('GR', 'GR@100% * 0.952'),
      newStep('Provision', 'GR@100% * (1 - contract["% Routing"])'),
    ]))
    expect(stepProblems(steps)).toEqual([])
  })

  it('still catches those steps put in the wrong order', () => {
    const steps = parseSteps(writeSteps([
      newStep('GR', 'GR@100% * 0.952'),
      newStep('GR@100%', 'ratecard["Bill Rate"] / 22 * 15'),
    ]))
    expect(stepProblems(steps).some(t => /before it is worked out/.test(t))).toBe(true)
  })
})

// ── columns vs sheet totals ─────────────────────────────────────────────────
// A column holds a value per row; a sheet total is one number for the whole
// sheet. Mixing the two silently is the failure worth guarding: "GR@100%" at
// sheet level is 18 numbers where one was expected, and a column that reads a
// total is circular, because the total is worked out from that same column.

describe('aggregates', () => {
  const rows = [
    newStep('GR@100%', 'ratecard["Bill Rate"] / ratecard["Working Days in Month"] * ratecard["No of Days"]'),
    newStep('GR', 'GR@100% * 0.952'),
    newStep('Provision', 'GR@100% * (1 - contract["% Routing"])'),
  ]

  it('removes a whole aggregate call, nested ones included', () => {
    expect(stripAggregateCalls('sum(GR@100%)').trim()).toBe('')
    expect(stripAggregateCalls('sum(a * max(b, c)) + Rate')).not.toContain('max')
    expect(stripAggregateCalls('sum(a * max(b, c)) + Rate')).toContain('Rate')
  })

  it('leaves what sits outside the call', () => {
    const left = stripAggregateCalls('(1 - routing) * sum(GR@100%)')
    expect(left).toContain('routing')
    expect(left).not.toContain('GR@100%')
  })

  it('accepts a total over a column', () => {
    expect(aggregateProblems(rows, [newStep('Total GR', 'sum(GR@100%)')])).toEqual([])
  })

  it('accepts the provision fee written against the totals', () => {
    const aggs = [
      newStep('Total GR', 'sum(GR@100%)'),
      newStep('Provision fees', '(1 - contract["% Routing"]) * sum(GR@100%)'),
    ]
    expect(aggregateProblems(rows, aggs)).toEqual([])
  })

  it('lets one sheet total build on another directly', () => {
    const aggs = [newStep('Total GR', 'sum(GR@100%)'), newStep('Half', 'Total GR / 2')]
    expect(aggregateProblems(rows, aggs)).toEqual([])
  })

  it('refuses a bare column at sheet level', () => {
    const bad = aggregateProblems(rows, [newStep('Total', 'GR@100% * 2')])
    expect(bad.some(t => /"GR@100%" is a column/.test(t))).toBe(true)
  })

  it('refuses a column that reads a sheet total — that is circular', () => {
    const cols = [...rows, newStep('Share', 'GR@100% / Total GR')]
    const bad = aggregateProblems(cols, [newStep('Total GR', 'sum(GR@100%)')])
    expect(bad.some(t => /uses the sheet total "Total GR"/.test(t))).toBe(true)
  })

  it('still applies the ordinary ordering rules to the totals', () => {
    const aggs = [newStep('Half', 'Total GR / 2'), newStep('Total GR', 'sum(GR@100%)')]
    expect(aggregateProblems(rows, aggs).some(t => /before it is worked out/.test(t))).toBe(true)
  })

  it('a node with columns and no totals is fine — totals are optional', () => {
    expect(aggregateProblems(rows, [])).toEqual([])
  })

  it('surfaces a sheet-level mistake on the node itself', () => {
    const n = at('formula', 'f', {
      steps: writeSteps(rows),
      aggregates: writeSteps([newStep('Total', 'GR@100% * 2')]),
    })
    const p = problems(flow([at('ratecard', 'r'), n, at('report', 'o', ok.report)], [['r', 'f'], ['f', 'o']]))
    expect(p.some(x => x.severity === 'error' && /is a column/.test(x.text))).toBe(true)
    expect(p.find(x => /is a column/.test(x.text))?.nodeId).toBe('f')
  })

  it('the full staffing configuration validates', () => {
    const n = at('formula', 'f', {
      steps: writeSteps(rows),
      aggregates: writeSteps([
        newStep('Total GR@100%', 'sum(GR@100%)'),
        newStep('Provision fees', '(1 - contract["% Routing"]) * sum(GR@100%)'),
      ]),
    })
    const f = flow(
      [at('ratecard', 'r'), at('contract', 'c'), n, at('report', 'o', ok.report)],
      [['r', 'f'], ['c', 'f'], ['f', 'o']],
    )
    expect(problems(f)).toEqual([])
  })
})

// ── working on a copy ───────────────────────────────────────────────────────

describe('write-back', () => {
  it('defaults to a copy, not to amending the uploaded file', () => {
    const n = newNode('formula', 0, 0)
    expect(n.config.writeback).toBe('Save a copy with the new columns')
  })

  it('offers amending in place, but never as the first choice', () => {
    const f = SPEC.formula.fields.find(x => x.key === 'writeback')!
    expect(f.options).toContain('Amend the rate card in place')
    expect(f.options?.[0]).toMatch(/copy/i)
  })

  it('is not required — a flow that only reports is still valid', () => {
    expect(SPEC.formula.required).not.toContain('writeback')
    expect(SPEC.formula.required).not.toContain('copy_name')
  })
})
