import { describe, expect, it, vi } from 'vitest'
import * as XLSX from 'xlsx'

vi.mock('../api/authedFiles', () => ({ fetchAuthedBlob: vi.fn() }))
import { fetchAuthedBlob } from '../api/authedFiles'
import { loadRawSpreadsheet, pickHeaderRow, headerNames } from './ParsedDataModal'

// jsdom's Blob has no arrayBuffer(); the browser's does.
const fileOf = (buf: ArrayBuffer) => ({ arrayBuffer: async () => buf }) as unknown as Blob

function workbook(): ArrayBuffer {
  const wb = XLSX.utils.book_new()
  // A title row and a blank row above the table, and a blank first column — as real exports have.
  XLSX.utils.book_append_sheet(wb, XLSX.utils.aoa_to_sheet([
    [null, "Vendor resource list Sep'26"],
    [],
    [null, 'Vendor', 'Rate'],
    [null, 'Acestack LLP', 528441.56],
    [null, 'Aforv', 2814988.14],
  ]), 'Sheet3')
  XLSX.utils.book_append_sheet(wb, XLSX.utils.aoa_to_sheet([['Only'], ['one']]), 'Sheet1')
  return XLSX.write(wb, { type: 'array', bookType: 'xlsx' })
}

describe('loadRawSpreadsheet', () => {
  it("names the columns after the sheet's own header row, past the title rows", async () => {
    const buf = workbook()
    vi.mocked(fetchAuthedBlob).mockResolvedValue(fileOf(buf))
    const view = await loadRawSpreadsheet('/x', 'list.xlsx')
    expect(view.sheets.map(s => s.name)).toEqual(['Sheet3', 'Sheet1'])
    const s = view.sheets[0]
    // Row 3 holds the headings; the blank first column keeps its letter.
    expect(s.columns).toEqual(['A', 'Vendor', 'Rate'])
    expect(s.note).toContain('Header on row 3')
    // The letters stay available so a value is still traceable to its cell.
    expect(s.columnHints).toEqual(['A', 'B', 'C'])
  })

  it('drops the header and everything above it, keeping the sheet numbering', async () => {
    vi.mocked(fetchAuthedBlob).mockResolvedValue(fileOf(workbook()))
    const s = (await loadRawSpreadsheet('/x', 'list.xlsx')).sheets[0]
    expect(s.rows.map(r => r.n)).toEqual([4, 5])
    expect(s.rows[0].cells[1]).toBe('Acestack LLP')
    expect(s.rows[0].cells[2]).toContain('528441.56')
    expect(s.numericCols?.has(2)).toBe(true)
  })

  it('falls back to letters when a sheet has no header row', async () => {
    const csv = new TextEncoder().encode('1,2' + String.fromCharCode(10) + '3,4' + String.fromCharCode(10))
    vi.mocked(fetchAuthedBlob).mockResolvedValue(fileOf(csv.buffer as ArrayBuffer))
    const s = (await loadRawSpreadsheet('/x', 'x.csv')).sheets[0]
    expect(s.columns).toEqual(['A', 'B'])
    expect(s.columnHints).toBeUndefined()
    expect(s.rows).toHaveLength(2)
  })

  it('reads a csv, taking its first line as the column names', async () => {
    const csv = new TextEncoder().encode('Vendor,Rate' + String.fromCharCode(10) + '1,2' + String.fromCharCode(10))
    vi.mocked(fetchAuthedBlob).mockResolvedValue(fileOf(csv.buffer as ArrayBuffer))
    const view = await loadRawSpreadsheet('/x', 'x.csv')
    expect(view.sheets[0].columns).toEqual(['Vendor', 'Rate'])
    expect(view.sheets[0].rows[0].cells).toEqual(['1', '2'])
  })
})

// ── naming a raw sheet's columns ────────────────────────────────────────────
// The raw view used to label columns A, B, C like Excel, which left the real
// headings sitting in row 1 as if they were data. These pin the rule that
// replaced it — and that it stays in step with the backend's own header pick,
// since Parsed info and Raw file disagreeing about a file reads as a data bug.

describe('pickHeaderRow', () => {
  it('takes the first row when it is the headings', () => {
    expect(pickHeaderRow([
      ['Consultant Name', 'ClientName', 'Working Location'],
      ['Narenderreddy', 'TCS', 'Hyderabad'],
    ])).toBe(0)
  })

  it('skips a title row above the table', () => {
    expect(pickHeaderRow([
      ["Vendor resource list Sep'26", null, null],
      ['Consultant Name', 'ClientName', 'Working Location'],
      ['Narenderreddy', 'TCS', 'Hyderabad'],
    ])).toBe(1)
  })

  it('skips several narrow preamble rows', () => {
    expect(pickHeaderRow([
      ['Report', null, null],
      ['Generated 11-Nov-26', null, null],
      ['Consultant Name', 'ClientName', 'Working Location'],
    ])).toBe(2)
  })

  it('does not take a row of numbers as headings', () => {
    expect(pickHeaderRow([
      ['1', '2', '3'],
      ['Consultant Name', 'ClientName', 'Working Location'],
    ])).toBe(1)
  })

  it('reports none for an empty sheet', () => {
    expect(pickHeaderRow([])).toBe(-1)
    expect(pickHeaderRow([[null, null], ['', '']])).toBe(-1)
  })

  it('reports none when nothing looks like headings', () => {
    expect(pickHeaderRow([['1', '2'], ['3', '4']])).toBe(-1)
  })
})

describe('headerNames', () => {
  const letters = ['A', 'B', 'C', 'D']

  it('uses the header cells', () => {
    expect(headerNames(['Consultant Name', 'ClientName'], ['A', 'B']))
      .toEqual(['Consultant Name', 'ClientName'])
  })

  it('keeps the Excel letter for a blank heading', () => {
    expect(headerNames(['Name', null, '', 'Rate'], letters))
      .toEqual(['Name', 'B', 'C', 'Rate'])
  })

  it('collapses the stray whitespace Excel leaves in a merged heading', () => {
    expect(headerNames(['  Staffing   Start Date '], ['A'])).toEqual(['Staffing Start Date'])
  })

  it('makes a repeated heading unique rather than losing a column', () => {
    expect(headerNames(['Rate', 'Rate', 'Rate'], ['A', 'B', 'C']))
      .toEqual(['Rate', 'Rate (2)', 'Rate (3)'])
  })

  it('renders a numeric heading as text', () => {
    expect(headerNames([2026, 2027], ['A', 'B'])).toEqual(['2026', '2027'])
  })

  it('never returns an empty name', () => {
    expect(headerNames([null, undefined as never, ''], ['A', 'B', 'C'])).toEqual(['A', 'B', 'C'])
  })
})
