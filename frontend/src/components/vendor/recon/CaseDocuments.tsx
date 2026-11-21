import { useEffect, useState } from 'react'
import { AlertTriangle, FileText, Loader2 } from 'lucide-react'
import axios from 'axios'
import { fetchCaseDocuments, type CaseDocument } from '../../../api/recon'
import ReconDocViewer from './ReconDocViewer'
import { ROLE_LABEL, SOURCE_LABEL, fmtValue, lookCount, pageSpan } from './reconFormat'

/** The fields worth seeing on the card, before the document is opened. */
const KEY_FIELDS = ['PO number', 'Invoice number', 'PO date', 'Invoice date', 'Store', 'Auditor', 'Verified on', 'PO total',
  'Invoice total', 'Taxable value', 'Rows', 'Lines', 'Extra items found on site', 'Handwritten values to check']

/**
 * Step 1 of an invoice's reconciliation: a card per document with its key
 * values. A card opens the shared viewer — the document beside what was read
 * from it and how each line compares with the invoice's other documents —
 * with the invoice's documents as tabs.
 */
export default function CaseDocuments({ caseId, title, onReconcile }: { caseId: string; title: string; onReconcile: () => void }) {
  const [docs, setDocs] = useState<CaseDocument[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [open, setOpen] = useState<number | null>(null)

  useEffect(() => {
    let live = true
    setDocs(null)
    fetchCaseDocuments(caseId)
      .then(d => { if (live) { setDocs(d); setError(null) } })
      .catch(e => { if (live) setError(axios.isAxiosError(e) ? (e.response?.data?.detail ?? 'Could not load the documents') : 'Could not load the documents') })
    return () => { live = false }
  }, [caseId])

  if (error) return <div className="vc__err vc__err--inline">{error}</div>
  if (!docs) return <div className="vc__muted vc__xs rc__pad"><Loader2 size={14} className="rc__spin" /> Loading the documents…</div>
  if (docs.length === 0) return <div className="vc__muted vc__xs rc__pad">No documents on this invoice yet.</div>

  const missing = (['po', 'invoice', 'evidence'] as const).filter(r => !docs.some(x => x.role === r))

  return (
    <section className="rc__sec" aria-label="Documents read">
      <div className="vc__subhead">Documents</div>
      {missing.length > 0 && (
        <div className="vc__muted vc__xs">Not on this invoice yet: {missing.map(r => ROLE_LABEL[r].toLowerCase()).join(', ')}. Upload it in Recon and it will be linked.</div>
      )}
      <div className="rc__doccards">
        {docs.map((d, i) => {
          const n = lookCount(d)
          const keys = KEY_FIELDS.map(k => d.fields.find(f => f.label === k)).filter(Boolean).slice(0, 6)
          return (
            <button key={d.id} className="rc__doccard" onClick={() => setOpen(i)} aria-label={`Open ${ROLE_LABEL[d.role]} ${d.title}`}>
              <div className="rc__doccard-h">
                <span className="vc__chip vc__chip--plain vc__chip--xs">{ROLE_LABEL[d.role]}</span>
                {n > 0 && <span className="vc__chip vc__chip--warn vc__chip--xs"><AlertTriangle size={11} /> {n} to check</span>}
              </div>
              <div className="vc__strong vc__ellipsis">{d.title}</div>
              <div className="vc__muted vc__xs vc__ellipsis">{d.file_name ?? SOURCE_LABEL[d.source]}{d.pages.length ? ` · ${pageSpan(d.pages)}` : ''}</div>
              <dl className="rc__doccard-f">
                {keys.map(f => <div key={f!.label}><dt className="vc__muted vc__xs">{f!.label}</dt><dd className="rc__tnum">{fmtValue(f!.value, f!.fmt)}</dd></div>)}
              </dl>
              <span className="rc__doccard-open vc__xs"><FileText size={13} /> Open with the original</span>
            </button>
          )
        })}
      </div>
      <div className="rc__doc-next">
        <span className="vc__muted vc__xs">The reconciliation uses exactly these values.</span>
        <button className="vc__btn vc__btn--primary vc__btn--sm" onClick={onReconcile}>See reconciliation</button>
      </div>
      {open !== null && (
        <ReconDocViewer title={title} subtitle={`${docs.length} document${docs.length > 1 ? 's' : ''} on this invoice`}
          parts={docs} initialPart={open} onClose={() => setOpen(null)} />
      )}
    </section>
  )
}
