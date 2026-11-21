import { useEffect, useRef, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { AlertCircle, Database, FileSpreadsheet, Minimize2, RefreshCw, X } from 'lucide-react'
import type { BillDetail } from '../api/invoices'
import { fetchBillDetail } from '../api/invoices'
import { fetchAuthedBlob } from '../api/authedFiles'
import { fetchVendorDocumentData } from '../api/vendorCard'
import { useFlyPanel } from '../pages/useFlyPanel'
import '../pages/billPdfFullscreen.css'
import './parsedData.css'

/**
 * What a document was read into, in the full-screen document viewer's shell
 * (pages/BillPdfFullscreen.tsx): the same fly-out, blur and toolbar, with the
 * values shown as a table — a tab per sheet, numbered rows.
 *
 *  - ParsedDataModal: a bill's stored fields and line items, opened from the PDF.
 *  - SheetViewer: a spreadsheet — what the database holds (Parsed info, the
 *    default) or the file itself, every sheet cell for cell (Raw file).
 */

export type Cell = string | number | boolean | null
export interface ParsedSheet {
  name: string
  columns: string[]
  /** `n` is the row's own number: the sheet row for a spreadsheet, the line number for a bill. */
  rows: { n: number | string; cells: Cell[] }[]
  /** Said under the tabs, e.g. "Header on row 3". */
  note?: string
  /** Column indexes to right-align: numbers that arrive as display text (raw file). */
  numericCols?: Set<number>
  /** The Excel letter for each column, when the names came from a header row.
   *  Kept so a value can still be traced to its cell (Rate in column D, row 7). */
  columnHints?: string[]
}
export interface ParsedView {
  sheets: ParsedSheet[]
  /** Shown instead of the table when nothing has been stored, e.g. still reading. */
  empty?: string
}

const cellText = (v: Cell) =>
  v == null ? '' : typeof v === 'number' ? v.toLocaleString('en-IN', { maximumFractionDigits: 2 }) : String(v)

/** What had focus when a viewer opened: it flies out of, and back into, that. */
function useOrigin() {
  return useRef<HTMLElement | null>(
    typeof document !== 'undefined' && document.activeElement instanceof HTMLElement && document.activeElement !== document.body
      ? document.activeElement : null,
  )
}

/** The viewer shell: backdrop, flying panel, toolbar. Escape closes this layer only. */
function Shell({ label, onClose, left, right, children, nested }: {
  label: string; onClose: () => void; left?: ReactNode; right?: ReactNode; children: ReactNode
  /** Opened over another full-screen viewer: drawn above it, and that one leaves Escape to this. */
  nested?: boolean
}) {
  const origin = useOrigin()
  const { panelRef, backdropRef, close } = useFlyPanel(origin as React.RefObject<HTMLElement>, onClose)
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return
      e.stopImmediatePropagation()
      e.preventDefault()
      close()
    }
    window.addEventListener('keydown', onKey, true)
    return () => window.removeEventListener('keydown', onKey, true)
  }, [close])
  return createPortal(
    <div className="bpf" role="dialog" aria-modal="true" aria-label={label}
         {...(nested ? { 'data-parsed-layer': '' } : {})} style={nested ? { zIndex: 10001 } : undefined}>
      <div className="bpf__backdrop" ref={backdropRef} onClick={close} />
      <div className="bpf__panel pdv__panel" ref={panelRef}>
        <div className="bpf__bar">
          <div className="bpf__group">
            <button className="bpf__ctrl" onClick={close} title="Exit full screen" aria-label="Exit full screen"><Minimize2 size={15} /></button>
            {left && <><div className="bpf__sep" />{left}</>}
          </div>
          <div className="bpf__group">
            {right}
            {right && <div className="bpf__sep" />}
            <button className="bpf__ctrl" onClick={close} aria-label="Close"><X size={16} /></button>
          </div>
        </div>
        {children}
      </div>
    </div>,
    document.body,
  )
}

/** Loads a view and shows it: loading, error with Retry, empty, or the sheets. */
function useView(load: () => Promise<ParsedView>, key: string, enabled = true) {
  const [view, setView] = useState<ParsedView | null>(null)
  const [err, setErr] = useState(false)
  const [tries, setTries] = useState(0)
  // Loaded once per key: switching views and back doesn't fetch again; Retry does.
  const done = useRef<string | null>(null)
  useEffect(() => {
    const k = `${key}#${tries}`
    if (!enabled || done.current === k) return
    done.current = k
    let live = true
    setView(null); setErr(false)
    load().then(v => { if (live) setView(v) }).catch(() => { if (live) { setErr(true); done.current = null } })
    return () => { live = false; if (done.current === k && !view) done.current = null }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, tries, enabled])
  return { view, err, retry: () => setTries(n => n + 1) }
}

function ViewBody({ view, err, retry, loadingText }: { view: ParsedView | null; err: boolean; retry: () => void; loadingText: string }) {
  const [active, setActive] = useState(0)
  useEffect(() => { setActive(0) }, [view])
  if (err) return (
    <div role="alert" className="pdv__center">
      <AlertCircle size={26} color="#b42318" />
      <span>Couldn't load this.</span>
      <button type="button" className="bpf__ctrl bpf__ctrl--text pdv__retry" onClick={retry}><RefreshCw size={13} />Retry</button>
    </div>
  )
  if (!view) return <div className="pdv__center"><RefreshCw size={14} className="pdv__spin" /> {loadingText}</div>
  const sheet = view.sheets[active]
  if (!sheet) return <div className="pdv__center">{view.empty || 'Nothing to show.'}</div>
  return (
    <div className="pdv__view">
      {view.sheets.length > 1 && (
        <div className="pdv__tabs" role="tablist">
          {view.sheets.map((s, i) => (
            <button key={i} role="tab" aria-selected={i === active} className={`pdv__tab${i === active ? ' is-on' : ''}`} onClick={() => setActive(i)}>
              {s.name}<span className="pdv__tab-n">{s.rows.length.toLocaleString('en-IN')}</span>
            </button>
          ))}
        </div>
      )}
      {sheet.note && <div className="pdv__note">{sheet.note}</div>}
      <div className="pdv__scroll">
        <table className="pdv__table">
          <thead>
            <tr>
              <th className="pdv__rn">#</th>
              {sheet.columns.map((c, i) => (
                <th key={i}>
                  {c}
                  {sheet.columnHints?.[i] && <span className="pdv__colhint">{sheet.columnHints[i]}</span>}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {sheet.rows.map((r, ri) => (
              <tr key={ri}>
                <td className="pdv__rn">{r.n}</td>
                {sheet.columns.map((_, ci) => {
                  const v = r.cells[ci] ?? null
                  const right = typeof v === 'number' || sheet.numericCols?.has(ci)
                  return <td key={ci} title={v == null ? undefined : String(v)} className={right ? 'tnum is-num' : undefined}>{cellText(v)}</td>
                })}
              </tr>
            ))}
            {sheet.rows.length === 0 && <tr><td colSpan={sheet.columns.length + 1} className="pdv__none">No rows in this sheet</td></tr>}
          </tbody>
        </table>
      </div>
    </div>
  )
}

/** A bill's stored values, opened over its PDF from the viewer's Parsed info button. */
export function ParsedDataModal({ title, load, onClose }: {
  title: string
  load: () => Promise<ParsedView>
  onClose: () => void
}) {
  const v = useView(load, title)
  return (
    <Shell nested label={`Parsed info, ${title}`} onClose={onClose}
           left={<span className="pdv__title"><Database size={15} />{title}<span className="pdv__badge">Parsed info</span></span>}>
      <ViewBody {...v} loadingText="Loading…" />
    </Shell>
  )
}

/**
 * A spreadsheet from a vendor's documents, full screen. Opens on what the
 * database holds; Raw file shows the file itself, every sheet.
 */
export function SheetViewer({ name, url, supplierId, docId, parsed, onClose }: {
  name: string
  /** The file, fetched with the login token. */
  url: string
  supplierId: string
  docId: string
  /** False when the file was never read into the database (an old .xls): opens on Raw file. */
  parsed: boolean
  onClose: () => void
}) {
  const [mode, setMode] = useState<'parsed' | 'raw'>(parsed ? 'parsed' : 'raw')
  const parsedV = useView(() => loadVendorDocParsed(supplierId, docId), `p:${docId}`, mode === 'parsed')
  const rawV = useView(() => loadRawSpreadsheet(url, name), `r:${url}`, mode === 'raw')
  return (
    <Shell label={`${name}, full screen`} onClose={onClose}
      left={
        <>
          <span className="pdv__title"><FileSpreadsheet size={15} />{name}</span>
          <div className="pdv__seg" role="group" aria-label="View">
            <button className={mode === 'parsed' ? 'is-on' : ''} aria-pressed={mode === 'parsed'} disabled={!parsed}
                    title={parsed ? 'Values as stored in the database' : "This file wasn't read into the database"}
                    onClick={() => setMode('parsed')}><Database size={13} />Parsed info</button>
            <button className={mode === 'raw' ? 'is-on' : ''} aria-pressed={mode === 'raw'}
                    title="The file itself, every sheet" onClick={() => setMode('raw')}><FileSpreadsheet size={13} />Raw file</button>
          </div>
        </>
      }>
      {mode === 'parsed'
        ? <ViewBody {...parsedV} loadingText="Loading parsed info…" />
        : <ViewBody {...rawV} loadingText="Opening the file…" />}
    </Shell>
  )
}

// ── Loaders ──────────────────────────────────────────────────────────────────

/** A vendor document's spreadsheet rows, as stored (vendor_doc_rows). */
export async function loadVendorDocParsed(supplierId: string, docId: string): Promise<ParsedView> {
  const d = await fetchVendorDocumentData(supplierId, docId)
  if (d.data_status === 'PENDING') return { sheets: [], empty: 'Still reading this file — try again in a moment.' }
  if (d.data_status === 'FAILED') return { sheets: [], empty: d.data_error || "This file couldn't be read." }
  if (!d.sheets.length) return { sheets: [], empty: 'Nothing has been read from this file.' }
  return {
    sheets: d.sheets.map(s => {
      const cols = s.columns.map(c => c.name)
      const notes = [s.header_row ? `Header on row ${s.header_row}` : null,
        s.truncated ? 'cut short: too many rows to store' : null,
        s.row_count > s.loaded ? `showing first ${s.loaded.toLocaleString('en-IN')} of ${s.row_count.toLocaleString('en-IN')} rows` : null]
      return {
        name: s.sheet_name,
        columns: cols,
        note: notes.filter(Boolean).join(' · ') || undefined,
        rows: d.rows.filter(r => r.sheet_index === s.sheet_index)
          .map(r => ({ n: r.row_number, cells: cols.map(c => (r.data[c] ?? null) as Cell) })),
      }
    }),
  }
}

const RAW_MAX_ROWS = 5000

/** How many rows to look at before giving up on finding a header. */
const HEADER_SCAN = 10

/**
 * Index of the header row, or -1 if these rows do not look like a table.
 *
 * Same rule as the backend's `_pick_header` (app/core/vendor_doc_tables.py) on
 * purpose: Parsed info and Raw file naming their columns differently for the
 * same file is the sort of discrepancy that gets reported as a data bug.
 * A title row above the table ("Vendor resource list Sep'26") has one or two
 * cells, so it is skipped in favour of the first wide, mostly-text row.
 */
export function pickHeaderRow(rows: Cell[][]): number {
  const filled = rows.map(r => r.filter(c => c != null && c !== ''))
  const widest = Math.max(0, ...filled.map(f => f.length))
  if (!widest) return -1
  for (let i = 0; i < filled.length; i++) {
    const f = filled[i]
    const text = f.filter(c => typeof c === 'string' && !/^-?[\d,.]+$/.test(c.trim())).length
    // At least two cells (unless the sheet really is one column wide): a
    // single-cell row is a title, and on a narrow table "half the widest"
    // is one cell, which let those titles through as headings.
    const need = Math.max(widest > 1 ? 2 : 1, widest * 0.6)
    if (f.length >= need && text >= f.length * 0.6) return i
  }
  return -1
}

/** Clean, unique column names; a blank header keeps its Excel letter. */
export function headerNames(row: Cell[], letters: string[]): string[] {
  const seen = new Map<string, number>()
  return letters.map((letter, i) => {
    const raw = row[i]
    let n = raw == null || raw === '' ? '' : String(raw).replace(/\s+/g, ' ').trim()
    n = n.slice(0, 120) || letter
    const hit = seen.get(n)
    if (hit) { seen.set(n, hit + 1); return `${n} (${hit + 1})` }
    seen.set(n, 1)
    return n
  })
}


/**
 * The file itself: every sheet, cell for cell, as Excel shows it — column
 * letters across the top, the sheet's own row numbers down the side, leading
 * blank rows and columns kept, values in their display format.
 */
export async function loadRawSpreadsheet(url: string, name: string): Promise<ParsedView> {
  const [XLSX, blob] = await Promise.all([import('xlsx'), fetchAuthedBlob(url)])
  const buf = await blob.arrayBuffer()
  const wb = /\.csv$/i.test(name)
    ? XLSX.read(new TextDecoder().decode(buf), { type: 'string', cellDates: true })
    : XLSX.read(buf, { type: 'array', cellDates: true })
  return {
    sheets: wb.SheetNames.map((sheetName): ParsedSheet => {
      const ws = wb.Sheets[sheetName]
      const ref = ws?.['!ref']
      if (!ref) return { name: sheetName, columns: [], rows: [] }
      const range = XLSX.utils.decode_range(ref)
      // From A1, so the grid lines up with Excel's own row and column labels.
      const lastRow = Math.min(range.e.r, RAW_MAX_ROWS - 1)
      const ncols = range.e.c + 1
      const letters = Array.from({ length: ncols }, (_, c) => XLSX.utils.encode_col(c))
      const numericCols = new Set<number>()
      const numCount = new Array(ncols).fill(0), textCount = new Array(ncols).fill(0)
      const rows: ParsedSheet['rows'] = []
      for (let r = 0; r <= lastRow; r++) {
        const cells: Cell[] = []
        for (let c = 0; c < ncols; c++) {
          const cell = ws[XLSX.utils.encode_cell({ r, c })]
          if (!cell || cell.v == null || cell.v === '') { cells.push(null); continue }
          if (cell.t === 'n') numCount[c]++; else textCount[c]++
          cells.push(cell.w ?? (cell.v instanceof Date ? cell.v.toISOString().slice(0, 10) : String(cell.v)))
        }
        rows.push({ n: r + 1, cells })
      }
      numCount.forEach((n, c) => { if (n > textCount[c]) numericCols.add(c) })

      // Name the columns after the sheet's own header row rather than A, B, C.
      // The letters stay on the header cell, so a value is still traceable to
      // the cell it came from; a sheet with no header row keeps the letters as
      // its names, which is the only honest thing to call those columns.
      const h = pickHeaderRow(rows.slice(0, HEADER_SCAN).map(r => r.cells))
      const columns = h >= 0 ? headerNames(rows[h].cells, letters) : letters
      const body = h >= 0 ? rows.slice(h + 1) : rows

      const hidden = wb.Workbook?.Sheets?.find(s => s.name === sheetName)?.Hidden
      const notes = [hidden ? 'Hidden sheet' : null,
        h > 0 ? `Header on row ${rows[h].n}` : null,
        range.e.r + 1 > RAW_MAX_ROWS ? `showing first ${RAW_MAX_ROWS.toLocaleString('en-IN')} of ${(range.e.r + 1).toLocaleString('en-IN')} rows` : null]
      return {
        name: sheetName, columns, rows: body, numericCols,
        columnHints: h >= 0 ? letters : undefined,
        note: notes.filter(Boolean).join(' · ') || undefined,
      }
    }),
  }
}

/** A bill as stored: its fields, and its line items. */
export async function loadBillParsed(invoiceId: string): Promise<ParsedView> {
  return billParsedView(await fetchBillDetail(invoiceId))
}

export function billParsedView(b: BillDetail): ParsedView {
  const g = b.tax_breakdown
  const bank = b.vendor?.bank
  const fields: [string, Cell][] = [
    ['Bill number', b.bill_number],
    ['Bill date', b.invoice_date],
    ['Due date', b.due_date],
    ['Service month', b.service_month],
    ['Vendor', b.vendor?.name ?? null],
    ['Vendor GSTIN', b.vendor?.gstn ?? null],
    ['Vendor email', b.vendor?.email ?? null],
    ['Billed to', b.buyer?.name ?? null],
    ['Buyer GSTIN', b.buyer?.gstn ?? null],
    ['Place of supply', g?.place_of_supply ?? null],
    ['Currency', b.currency_code],
    ['Subtotal', b.subtotal],
    ['Discount', b.discount_amount],
    ['Taxable amount', g?.taxable_amount ?? null],
    ['CGST', g?.cgst ?? null],
    ['SGST', g?.sgst ?? null],
    ['IGST', g?.igst ?? null],
    ['Cess', g?.cess ?? null],
    ['Tax total', b.tax_amount],
    ['Bill total', b.total_amount],
    ['TDS section', b.tds_section_code],
    ['TDS rate %', b.tds_rate],
    ['TDS amount', b.tds_amount],
    ['Net payable', b.net_payable],
    ['Amount paid', b.amount_paid],
    ['Outstanding', b.outstanding_amount],
    ['Payment terms (days)', b.payment_terms_days],
    ['Bank', bank?.bank_name ?? null],
    ['Account number', bank?.account_number ?? null],
    ['IFSC', bank?.ifsc ?? null],
    ['Category', b.category],
    ['Cost centre', b.cost_center_name],
    ['Status', b.status_label || b.status],
  ]
  const lineCols = ['Description', 'HSN/SAC', 'Qty', 'Unit', 'Unit price', 'Discount', 'GST %', 'Tax', 'Amount', 'Ledger']
  return {
    sheets: [
      {
        name: 'Bill',
        columns: ['Field', 'Value'],
        rows: fields.filter(([, v]) => v != null && v !== '').map(([k, v], i) => ({ n: i + 1, cells: [k, v] })),
      },
      {
        name: 'Line items',
        columns: lineCols,
        rows: (b.line_items ?? []).map(l => ({
          n: l.line_number,
          cells: [l.product_name, l.hsn_code, l.quantity, l.unit, l.unit_price, l.discount_amount,
            l.tax_rate_percent, l.tax_amount, l.line_total, l.ledger_name],
        })),
      },
    ],
  }
}
