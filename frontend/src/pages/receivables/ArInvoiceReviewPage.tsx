import { useCallback, useEffect, useMemo, useState } from 'react'
import { Document, Page, pdfjs } from 'react-pdf'
import { ArrowLeft, ChevronLeft, ChevronRight } from 'lucide-react'
import { Button, Input, PdfLoading, useToast } from '../../ui'
import { apiError, ingestArInvoice } from '../../api/receivables'
import type { InvoicePayload } from '../../api/invoices'
import type { QueueItem } from '../../App'
import './receivables.css'

pdfjs.GlobalWorkerOptions.workerSrc = new URL('pdfjs-dist/build/pdf.worker.min.mjs', import.meta.url).toString()

interface Fields {
  customer: string
  gstin: string
  invoice_number: string
  invoice_date: string
  due_date: string
  po_number: string
  payment_terms: string
  taxable: string
  tax: string
  total: string
  currency: string
}

const str = (v: unknown) => (v === null || v === undefined ? '' : String(v))

function fieldsFrom(d: InvoicePayload): Fields {
  const buyer = (d.buyer ?? {}) as Record<string, unknown>
  const taxes = (d.taxes ?? {}) as Record<string, unknown>
  return {
    customer: str(buyer.name),
    gstin: str(buyer.gstin),
    invoice_number: str(d.invoice_number),
    invoice_date: str(d.invoice_date),
    due_date: str(d.due_date),
    po_number: str(d.po_number),
    payment_terms: str(d.payment_terms),
    taxable: str(taxes.taxable_amount ?? d.subtotal),
    tax: str(taxes.total_tax_amount),
    total: str(d.total_amount),
    currency: str(d.currency_code) || 'INR',
  }
}

function payloadFrom(d: InvoicePayload, f: Fields): InvoicePayload {
  const num = (s: string) => (s.trim() === '' ? null : Number(s.replace(/,/g, '')))
  return {
    ...d,
    buyer: { ...((d.buyer ?? {}) as object), name: f.customer.trim(), gstin: f.gstin.trim().toUpperCase() },
    invoice_number: f.invoice_number.trim(),
    invoice_date: f.invoice_date.trim(),
    due_date: f.due_date.trim(),
    po_number: f.po_number.trim(),
    payment_terms: f.payment_terms.trim(),
    taxes: { ...((d.taxes ?? {}) as object), taxable_amount: num(f.taxable), total_tax_amount: num(f.tax) },
    total_amount: num(f.total),
    currency_code: f.currency.trim().toUpperCase() || 'INR',
  }
}

/**
 * Review step for sales invoices — the receivable counterpart of the bill review.
 * Lighter on purpose: a sales invoice has no approval chain, TDS section or
 * ledger mapping to settle; what matters for collection is who owes it, how
 * much, by when, and the PO the customer will quote when paying.
 */
export default function ArInvoiceReviewPage({ queue, index, onNav, onSaved, onBack }: {
  queue: QueueItem[]
  index: number
  onNav: (i: number) => void
  onSaved: (index: number) => void
  onBack: () => void
}) {
  const toast = useToast()
  const item = queue[index]
  const [f, setF] = useState<Fields>(() => fieldsFrom(item.data))
  const [busy, setBusy] = useState(false)
  const [pages, setPages] = useState(0)
  const [width, setWidth] = useState(560)
  useEffect(() => { setF(fieldsFrom(item.data)); setPages(0) }, [item])

  const url = useMemo(() => URL.createObjectURL(item.file), [item.file])
  useEffect(() => () => URL.revokeObjectURL(url), [url])
  const isImage = item.file.type.startsWith('image/')
  const paneRef = useCallback((el: HTMLDivElement | null) => {
    if (el) setWidth(Math.max(280, el.clientWidth - 24))
  }, [])

  const set = (k: keyof Fields) => (e: { target: { value: string } }) => setF(s => ({ ...s, [k]: e.target.value }))
  const missing = !f.customer.trim() || !f.invoice_number.trim() || !f.total.trim()
  // Taxable + tax should make the total; say so rather than block (round-offs exist).
  const sumOff = f.taxable && f.tax && f.total
    && Math.abs(Number(f.taxable.replace(/,/g, '')) + Number(f.tax.replace(/,/g, '')) - Number(f.total.replace(/,/g, ''))) > 1

  const save = async () => {
    setBusy(true)
    try {
      const r = await ingestArInvoice(payloadFrom(item.data, f))
      toast.success(`Invoice ${f.invoice_number} saved`, r.customer_created ? `New customer: ${f.customer}` : undefined)
      onSaved(index)
    } catch (e) {
      toast.error('Not saved', apiError(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="ar-review">
      <div className="ar-review__pdf" ref={paneRef}>
        {isImage ? <img src={url} alt={item.file.name} /> : (
          <Document file={url} loading={<PdfLoading />} onLoadSuccess={d => setPages(d.numPages)}>
            {Array.from({ length: pages }, (_, i) => <Page key={i} pageNumber={i + 1} width={width} />)}
          </Document>
        )}
      </div>
      <div className="ar-review__form">
        <div className="ar-review__nav">
          <Button variant="ghost" size="sm" iconLeft={<ArrowLeft size={14} />} onClick={onBack}>Back to upload</Button>
          {queue.length > 1 && (
            <span className="ar-actions">
              <Button variant="ghost" size="sm" disabled={index === 0} onClick={() => onNav(index - 1)} aria-label="Previous invoice"><ChevronLeft size={14} /></Button>
              <span className="ar-muted">{index + 1} of {queue.length}</span>
              <Button variant="ghost" size="sm" disabled={index === queue.length - 1} onClick={() => onNav(index + 1)} aria-label="Next invoice"><ChevronRight size={14} /></Button>
            </span>
          )}
        </div>
        <div>
          <h1 className="u-pagehead__title">Review sales invoice</h1>
          <p className="ar-muted">{item.file.name} · read as an invoice <strong>you issued</strong>: the Bill-To party is the customer.</p>
        </div>
        <div className="ar-form">
          <div className="ar-form__full"><Input label="Customer (Bill To)" required value={f.customer} onChange={set('customer')} /></div>
          <Input label="Customer GSTIN" value={f.gstin} onChange={set('gstin')} />
          <Input label="Customer PO" hint="Quoted by the customer when paying" value={f.po_number} onChange={set('po_number')} />
          <Input label="Invoice number" required value={f.invoice_number} onChange={set('invoice_number')} />
          <Input label="Invoice date" placeholder="DD-MM-YYYY" value={f.invoice_date} onChange={set('invoice_date')} />
          <Input label="Payment terms" value={f.payment_terms} onChange={set('payment_terms')} />
          <Input label="Due date" placeholder="DD-MM-YYYY" hint={f.due_date ? undefined : 'Worked out from the terms if blank'} value={f.due_date} onChange={set('due_date')} />
          <Input label="Taxable value" inputMode="decimal" hint="TDS is deducted on this" value={f.taxable} onChange={set('taxable')} />
          <Input label="Tax (GST)" inputMode="decimal" value={f.tax} onChange={set('tax')} />
          <Input label="Total" required inputMode="decimal" value={f.total} onChange={set('total')}
            error={sumOff ? 'Taxable value + tax doesn’t make this total — check the figures' : null} />
          <Input label="Currency" value={f.currency} onChange={set('currency')} />
        </div>
        <div className="ar-actions">
          <Button onClick={save} loading={busy} disabled={missing}>Save invoice</Button>
        </div>
      </div>
    </div>
  )
}
