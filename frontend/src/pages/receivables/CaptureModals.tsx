import { useState } from 'react'
import { useDropzone } from 'react-dropzone'
import { FileUp } from 'lucide-react'
import { Button, Input, Modal, Select, Textarea, useToast } from '../../ui'
import {
  addRemittance, apiError, importStatement, recordPayment, type PaymentRow, type Remittance,
} from '../../api/receivables'
import { money } from './format'

/** Bank statement (CSV / XLSX) → credits, deduped, queued for the agent. */
export function ImportStatementModal({ open, onClose, onDone, onView }: {
  open: boolean; onClose: () => void; onDone: () => void; onView: (statementId: string) => void
}) {
  const toast = useToast()
  const [file, setFile] = useState<File | null>(null)
  const [account, setAccount] = useState('')
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState<Awaited<ReturnType<typeof importStatement>> | null>(null)
  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    multiple: false,
    accept: { 'application/pdf': ['.pdf'], 'text/csv': ['.csv'], 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': ['.xlsx'] },
    onDrop: f => { setFile(f[0] ?? null); setResult(null) },
  })
  const close = () => { setFile(null); setResult(null); onClose() }
  const run = async () => {
    if (!file) return
    setBusy(true)
    try {
      const r = await importStatement(file, account || undefined)
      setResult(r)
      onDone()
      toast.success('Statement imported', `${r.imported} new receipt${r.imported === 1 ? '' : 's'} — the agent is matching them`)
    } catch (e) {
      toast.error('Import failed', apiError(e))
    } finally {
      setBusy(false)
    }
  }
  return (
    <Modal open={open} onClose={close} title="Import bank statement" size="md"
      description="Credits are read from the statement; the agent matches them to open invoices in the background."
      footer={result
        ? <><Button variant="secondary" onClick={() => { const id = result.statement_id; close(); onView(id) }}>View statement</Button>
            <Button onClick={close}>Done</Button></>
        : <><Button variant="ghost" onClick={close}>Cancel</Button>
            <Button onClick={run} loading={busy} disabled={!file}>Import</Button></>}>
      {result ? (
        <div className="ar-result">
          <Stat k="Credits read" v={result.credits} />
          <Stat k="New receipts" v={result.imported} />
          <Stat k="Already imported" v={result.duplicates} />
          <Stat k="Excluded (not customer payments)" v={result.set_aside} />
          {result.possible_bounces > 0 && <Stat k="Possible bounces" v={result.possible_bounces} />}
        </div>
      ) : (
        <div className="ar-form ar-form--1">
          <div {...getRootProps()} className={`ar-drop${isDragActive ? ' ar-drop--over' : ''}`}>
            <input {...getInputProps()} />
            <FileUp size={20} aria-hidden="true" />
            <div>{file ? <strong>{file.name}</strong> : 'Drop the statement here, or click to choose (PDF, CSV or XLSX)'}</div>
            <div className="ar-muted">Any bank's export. A PDF is read page by page; a spreadsheet's header row is found automatically. The file is kept and can be opened again.</div>
          </div>
          <Input label="Bank account (optional)" placeholder="e.g. HDFC current a/c ··1234" value={account}
            onChange={e => setAccount(e.target.value)} />
        </div>
      )}
    </Modal>
  )
}

function Stat({ k, v }: { k: string; v: number }) {
  return (
    <div className="ar-kpi">
      <span className="ar-kpi__label">{k}</span>
      <span className="ar-kpi__value">{v}</span>
    </div>
  )
}

/** Remittance advice — pasted email text, or a PDF / photo. */
export function RemittanceModal({ open, onClose, onDone }: { open: boolean; onClose: () => void; onDone: (paymentId: string | null) => void }) {
  const toast = useToast()
  const [mode, setMode] = useState<'text' | 'file'>('text')
  const [text, setText] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [busy, setBusy] = useState(false)
  const [parsed, setParsed] = useState<{ r: Remittance; paymentId: string | null } | null>(null)
  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    multiple: false,
    accept: { 'application/pdf': ['.pdf'], 'image/jpeg': ['.jpg', '.jpeg'], 'image/png': ['.png'], 'image/webp': ['.webp'] },
    onDrop: f => setFile(f[0] ?? null),
  })
  const close = () => { setText(''); setFile(null); setParsed(null); onClose() }
  const run = async () => {
    setBusy(true)
    try {
      const r = await addRemittance(mode === 'text' ? { text } : { file: file! })
      setParsed({ r: r.parsed, paymentId: r.payment_id })
      onDone(r.payment_id)
    } catch (e) {
      toast.error('Could not read the remittance', apiError(e))
    } finally {
      setBusy(false)
    }
  }
  const ready = mode === 'text' ? text.trim().length > 10 : !!file
  return (
    <Modal open={open} onClose={close} title="Add remittance advice" size="lg" closeOnBackdrop={false}
      description="Which invoices the customer says the payment covers. It is linked to the payment by UTR or by amount and date — or kept until the payment arrives."
      footer={parsed
        ? <Button onClick={close}>Done</Button>
        : <><Button variant="ghost" onClick={close}>Cancel</Button>
            <Button onClick={run} loading={busy} disabled={!ready}>Read remittance</Button></>}>
      {parsed ? (
        <div className="ar-wb">
          <div className="ar-facts">
            <Fact k="Payer" v={parsed.r.payer_name} />
            <Fact k="Reference / UTR" v={parsed.r.payment_reference} />
            <Fact k="Total" v={parsed.r.total_amount != null ? money(parsed.r.total_amount) : null} />
            <Fact k="Linked payment" v={parsed.paymentId ? 'Found — the agent is matching it now' : 'Not linked yet — the agent is checking payments of this amount, and links it as soon as its payment arrives'} />
          </div>
          <div className="ar-alloc-wrap">
            <table className="ar-alloc">
              <thead><tr><th>Invoice</th><th className="num">Paid</th><th className="num">Held back</th><th>Reason</th></tr></thead>
              <tbody>
                {parsed.r.lines.length === 0 && <tr><td colSpan={4} className="ar-muted">No invoices named in the advice.</td></tr>}
                {parsed.r.lines.map((l, i) => (
                  <tr key={i}>
                    <td>{l.invoice_number}</td>
                    <td className="num ar-money">{money(l.amount_paid)}</td>
                    <td className="num ar-money">{l.deduction_amount ? money(l.deduction_amount) : '—'}</td>
                    <td>{l.deduction_reason || '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ) : (
        <div className="ar-form ar-form--1">
          <div className="ar-tabs" role="tablist">
            <button role="tab" aria-selected={mode === 'text'} className={`ar-tab${mode === 'text' ? ' ar-tab--on' : ''}`} onClick={() => setMode('text')}>Paste email text</button>
            <button role="tab" aria-selected={mode === 'file'} className={`ar-tab${mode === 'file' ? ' ar-tab--on' : ''}`} onClick={() => setMode('file')}>Upload PDF / photo</button>
          </div>
          {mode === 'text' ? (
            <Textarea label="Remittance text" rows={9} value={text} onChange={e => setText(e.target.value)}
              placeholder={'e.g. "We have released ₹1,16,000 via NEFT (UTR HDFCN5202611…) against Inv 1045 after TDS 2%."'} />
          ) : (
            <div {...getRootProps()} className={`ar-drop${isDragActive ? ' ar-drop--over' : ''}`}>
              <input {...getInputProps()} />
              <FileUp size={20} aria-hidden="true" />
              <div>{file ? <strong>{file.name}</strong> : 'Drop the payment advice here, or click to choose'}</div>
            </div>
          )}
        </div>
      )}
    </Modal>
  )
}

function Fact({ k, v }: { k: string; v: string | null | undefined }) {
  return (
    <div className="ar-fact">
      <span className="ar-fact__k">{k}</span>
      <span className="ar-fact__v">{v || '—'}</span>
    </div>
  )
}

const METHODS = ['NEFT', 'RTGS', 'IMPS', 'UPI', 'CHQ', 'CASH', 'OTHER'].map(m => ({ value: m, label: m === 'CHQ' ? 'Cheque' : m }))

/** A receipt not in a statement yet — a cheque, cash, a transfer seen in net banking. */
export function RecordPaymentModal({ open, onClose, onDone }: { open: boolean; onClose: () => void; onDone: (id: string) => void }) {
  const toast = useToast()
  const today = new Date().toISOString().slice(0, 10)
  const [f, setF] = useState({ received_on: today, amount: '', method: 'NEFT', utr: '', payer_name: '', narration: '' })
  const [dups, setDups] = useState<PaymentRow[] | null>(null)
  const [busy, setBusy] = useState(false)
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF(s => ({ ...s, [k]: e.target.value }))
  const close = () => { setDups(null); setF({ received_on: today, amount: '', method: 'NEFT', utr: '', payer_name: '', narration: '' }); onClose() }
  const save = async (force = false) => {
    setBusy(true)
    try {
      const r = await recordPayment({ ...f, amount: f.amount.replace(/,/g, ''), utr: f.utr || undefined, force })
      if (r.duplicate_warning) { setDups(r.duplicate_warning); return }
      toast.success('Payment recorded', 'The agent has matched it — open it to review')
      onDone(r.payment_id!)
      close()
    } catch (e) {
      toast.error('Could not record the payment', apiError(e))
    } finally {
      setBusy(false)
    }
  }
  const valid = Number(f.amount.replace(/,/g, '')) > 0 && !!f.received_on
  return (
    <Modal open={open} onClose={close} title="Record a payment" size="md"
      footer={dups
        ? <><Button variant="ghost" onClick={() => setDups(null)}>Back</Button>
            <Button variant="secondary" onClick={() => save(true)} loading={busy}>Record anyway</Button></>
        : <><Button variant="ghost" onClick={close}>Cancel</Button>
            <Button onClick={() => save(false)} loading={busy} disabled={!valid}>Record</Button></>}>
      {dups ? (
        <div className="ar-flags">
          <div className="ar-flag">This looks like a payment that is already recorded:</div>
          {dups.map(d => (
            <div key={d.id} className="ar-muted">
              {d.received_on} · {money(d.amount)} · {d.payer_name || 'payer unknown'} · {d.utr || 'no UTR'} · {d.status.replace('_', ' ')}
            </div>
          ))}
        </div>
      ) : (
        <div className="ar-form">
          <Input label="Received on" type="date" required value={f.received_on} onChange={set('received_on')} />
          <Input label="Amount (₹)" required inputMode="decimal" value={f.amount} onChange={set('amount')} />
          <Select label="Method" options={METHODS} value={f.method} onChange={set('method')} />
          <Input label="UTR / cheque no." value={f.utr} onChange={set('utr')} />
          <div className="ar-form__full"><Input label="Payer name" value={f.payer_name} onChange={set('payer_name')} /></div>
          <div className="ar-form__full"><Input label="Note / narration" hint="Invoice numbers mentioned here are used for matching"
            value={f.narration} onChange={set('narration')} /></div>
        </div>
      )}
    </Modal>
  )
}
