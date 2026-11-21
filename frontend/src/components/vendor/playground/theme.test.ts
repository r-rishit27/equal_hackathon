/**
 * The light/dark surface.
 *
 * These are structural rather than cosmetic, because the way this broke the
 * first time was not a wrong colour: the `.pg` rule was split into light and
 * dark halves and `display: grid` went with the dark half, which nothing
 * matched. The palette stretched the full width and the canvas disappeared.
 * A theme must only ever change colour.
 */
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

const css = readFileSync(join(__dirname, 'playground.css'), 'utf8')

/** The body of a rule, given its selector. */
function block(selector: string): string {
  const at = css.indexOf(selector + ' {')
  if (at < 0) return ''
  return css.slice(at, css.indexOf('\n}', at))
}

const LAYOUT = ['display:', 'grid-template-columns:', 'height:', 'min-height:', 'gap:', 'overflow:']

describe('playground theme', () => {
  it('keeps the layout in the base rule', () => {
    const base = block('.pg')
    expect(base).toContain('display: grid')
    expect(base).toContain('grid-template-columns')
  })

  it('never puts layout inside a themed block', () => {
    const light = block(".pg[data-theme='light']")
    expect(light).not.toBe('')
    for (const prop of LAYOUT) {
      expect(light, `${prop} must not be themed`).not.toContain(prop)
    }
  })

  it('the themed block only sets custom properties', () => {
    const light = block(".pg[data-theme='light']")
    const decls = light
      .split('\n')
      .map(l => l.trim())
      .filter(l => l.includes(':') && !l.startsWith('/*') && !l.startsWith('*'))
    expect(decls.length).toBeGreaterThan(5)
    for (const d of decls) {
      expect(d, `"${d}" should be a --token`).toMatch(/^--pg-/)
    }
  })

  it('both surfaces define the same token set, so neither falls back silently', () => {
    const names = (sel: string) =>
      new Set((block(sel).match(/--pg-[\w-]+(?=:)/g) ?? []))
    const base = names('.pg')
    const light = names(".pg[data-theme='light']")
    expect([...base].filter(t => !light.has(t))).toEqual([])
  })

  it('defaults to dark: the base rule carries the dark surface', () => {
    expect(block('.pg')).toContain('--pg-bg: #0b1220')
  })

  it('has no leftover dark-only override from the broken attempt', () => {
    expect(css).not.toContain("data-theme='dark'")
  })
})
