import { useCallback, useEffect, useRef, useState } from 'react'
import { AlertTriangle, BarChart3, ChevronDown, FileSearch, FileText, Folder, FolderOpen, LayoutDashboard, Loader2, RotateCw, Trash2, Upload, X } from 'lucide-react'

import axios from 'axios'
import {
  deleteReconDocument, fetchReconCases, fetchReconDocuments, fetchReconFileView, ignoreSegment, linkSegment,
  rereadReconDocument, uploadReconDocuments,
  type LinkCandidate, type ReconCaseSummary, type ReconDocument, type ReconFileView, type ReconSegment,
} from '../../../api/recon'

import { useRecordCards } from '../../records/recordLinks'
import { ReconLink } from '../../records/RecordLink'
import ReconDocViewer from './ReconDocViewer'
import { CaseList } from './CaseList'
import { CaseStatusChip } from './CaseStatusChip'
import { ReconDashboard, matchesFilter } from './ReconDashboard'
import { ConfirmDialog } from '../../../ui'
import {
  FOLDER_HINT, FOLDER_LABEL, FOLDER_LEG, FOLDER_ORDER, KIND_LABEL, STAGE_LABEL, coverBadge, folderOf, inr,
  type ReconFolderKey,
} from './reconFormat'

/** Remembered per browser, so the screen opens the way it was left. */
const BOARD_KEY = 'recon.dashboard.open'
import './recon.css'

const ACCEPT = '.pdf,.png,.jpg,.jpeg,.webp,.heic,.tif,.tiff,.xlsx,.xlsm,.csv'
const MAX_MB = 25
const POLL_MS = 3000
const POLL_LIMIT_MS = 10 * 60 * 1000

/**
 * Vendor card → Documents → Recon (docs/bata-recon/04_LLD_FRONTEND.md §5).
 * Drop POs, invoices, site-audit reports, delivery proofs, memos or sheets; they
 * are read in the background, filed against the right invoice, and each invoice
 * becomes a case reconciled line by line against its PO and the report.
 */
export default function ReconFolder({ supplierId, brandId, notify, view: screen = 'documents', onView }: {
  supplierId: string
  brandId: string | null
  notify: (msg: string, type?: 'error' | 'info') => void
  /** 'board' is the dashboard screen, reached from its own entry in the
   *  vendor's sidebar; 'documents' is the folders of files. */
  view?: 'documents' | 'board'
  onView?: (v: 'documents' | 'board') => void
}) {
  // A case opens as its own card over the page (?open=recon:<id>), like a bill or vendor.
  const { openRecon } = useRecordCards()
  const onCase = (id: string) => openRecon(id)
  const [docs, setDocs] = useState<ReconDocument[] | null>(null)
  const [cases, setCases] = useState<ReconCaseSummary[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [uploading, setUploading] = useState(false)
  const [over, setOver] = useState(false)
  const input = useRef<HTMLInputElement>(null)
  const pollStart = useRef<number>(0)

  const load = useCallback(async () => {
    try {
      const [d, c] = await Promise.all([fetchReconDocuments(supplierId, brandId), fetchReconCases(supplierId)])
      setDocs(d)
      setCases(c)
      setError(null)
    } catch (e) {
      setError(axios.isAxiosError(e) ? (e.response?.data?.detail ?? 'Could not load recon documents') : 'Could not load recon documents')
    }
  }, [supplierId, brandId])

  useEffect(() => { setDocs(null); setCases(null); load() }, [load])

  const reading = (docs ?? []).filter(d => d.recon_status === 'PENDING' || d.recon_status === 'RUNNING')
  useEffect(() => {
    if (!reading.length) { pollStart.current = 0; return }
    if (!pollStart.current) pollStart.current = Date.now()
    if (Date.now() - pollStart.current > POLL_LIMIT_MS) return
    const t = window.setTimeout(load, POLL_MS)
    return () => window.clearTimeout(t)
  }, [docs, load, reading.length])

  async function send(files: File[]) {
    const ok = files.filter(f => f.size <= MAX_MB * 1024 * 1024)
    if (ok.length < files.length) notify(`${files.length - ok.length} file(s) are over ${MAX_MB} MB and were skipped`, 'error')
    if (!ok.length) return
    setUploading(true)
    try {
      const res = await uploadReconDocuments(supplierId, ok, { brandId })
      const dup = res.filter(r => r.duplicate_of)
      const bad = res.filter(r => r.error)
      bad.forEach(r => notify(`${r.file_name}: ${r.error}`, 'error'))
      if (dup.length) notify(`${dup.map(d => d.file_name).join(', ')} ${dup.length > 1 ? 'were' : 'was'} already uploaded`, 'info')
      const queued = res.filter(r => r.id).length
      if (queued) notify(`Reading ${queued} file${queued > 1 ? 's' : ''}. They’ll be matched to their invoice automatically.`, 'info')
      await load()
    } catch (e) {
      notify(axios.isAxiosError(e) ? (e.response?.data?.detail ?? 'Upload failed') : 'Upload failed', 'error')
    } finally {
      setUploading(false)
    }
  }

  async function act(fn: () => Promise<unknown>, done: string) {
    try { await fn(); notify(done, 'info'); await load() } catch (e) {
      notify(axios.isAxiosError(e) ? (e.response?.data?.detail ?? 'That didn’t work') : 'That didn’t work', 'error')
    }
  }

  // The file open in the viewer (index into `files`), and what it read as.
  const [viewing, setViewing] = useState<number | null>(null)
  const [deleting, setDeleting] = useState<ReconDocument | null>(null)
  const reread = (d: ReconDocument) => act(() => rereadReconDocument(d.id), `Reading ${d.file_name} again`)
  const remove = async (d: ReconDocument) => {
    setDeleting(null)
    if (viewing !== null) setViewing(null)
    await act(() => deleteReconDocument(d.id), `${d.file_name} deleted. Add it again any time.`)
  }
  const [view, setView] = useState<{ id: string; data: ReconFileView | null; error: string | null } | null>(null)
  // What the dashboard is currently asking to see. Null is everything.
  const [focus, setFocus] = useState<string | null>(null)
  // Open by default, and remembered — a finance manager opens this screen to
  // see where the money stands, not to click a toggle first.
  const onBoard = screen === 'board'
  const [board, setBoard] = useState<boolean>(() => {
    try { return localStorage.getItem(BOARD_KEY) !== '0' } catch { return true }
  })

  const files = (docs ?? []).filter(d => d.recon_status !== 'PENDING' && d.recon_status !== 'RUNNING')
  const openId = viewing !== null ? files[viewing]?.id ?? null : null
  useEffect(() => {
    if (!openId) { setView(null); return }
    let live = true
    setView({ id: openId, data: null, error: null })
    fetchReconFileView(openId)
      .then(data => { if (live) setView({ id: openId, data, error: null }) })
      .catch(e => { if (live) setView({ id: openId, data: null, error: axios.isAxiosError(e) ? (e.response?.data?.detail ?? 'Could not open this file') : 'Could not open this file' }) })
    return () => { live = false }
  }, [openId])

  const needs: { doc: ReconDocument; seg: ReconSegment }[] = []
  const failed = (docs ?? []).filter(d => d.recon_status === 'FAILED')
  for (const d of docs ?? []) {
    if (d.recon_status === 'PENDING' || d.recon_status === 'RUNNING') continue
    for (const s of d.segments) if (s.status === 'UNLINKED' || s.status === 'FOREIGN' || s.status === 'NEEDS_REVIEW' || s.needs_review_cells > 0) needs.push({ doc: d, seg: s })
  }
  const caseById = new Map((cases ?? []).map(c => [c.id, c]))
  const all = [...reading, ...files]
  // Filed by what each document was read as. A file still being read has no
  // segments yet, so it waits in "Not filed yet" until it does.
  // A dashboard that shows a problem and leaves you to find it below has only
  // told you to go looking, so picking a panel narrows the folders too: a
  // document is kept when any case it belongs to passes the filter.
  const keep = (d: ReconDocument) => {
    if (!focus) return true
    const ids = d.segments.map(s2 => s2.case_id).filter((x): x is string => !!x)
    const cs = ids.map(id => caseById.get(id)).filter((c): c is ReconCaseSummary => !!c)
    return cs.some(c => matchesFilter(c, focus))
  }
  const byFolder = new Map<ReconFolderKey, ReconDocument[]>()
  for (const d of all.filter(keep)) {
    const k = folderOf(d.segments)
    byFolder.set(k, [...(byFolder.get(k) ?? []), d])
  }

  return (
    <div className="rc">
      <div className="vc__folder-h">
        <div className="vc__grow">
          <div className="vc__folder-t">{onBoard ? 'Recon dashboard' : 'Recon'}</div>
          <div className="vc__folder-d">{onBoard
            ? 'Where every invoice on this vendor stands. Pick anything to see only those.'
            : 'Every PO, invoice and site audit you add is read, filed against its invoice and checked line by line.'}</div>
        </div>
        {onView && (
          <button className="vc__btn vc__btn--sm" onClick={() => onView(onBoard ? 'documents' : 'board')}>
            {onBoard ? <><FolderOpen size={14} />Documents</> : <><LayoutDashboard size={14} />Dashboard</>}
          </button>
        )}
        <button className="vc__btn vc__btn--primary vc__btn--sm" onClick={() => input.current?.click()} disabled={uploading}>
          {uploading ? <Loader2 size={14} className="rc__spin" /> : <Upload size={14} />}Add documents
        </button>
        <input ref={input} type="file" multiple accept={ACCEPT} hidden
          onChange={e => { const f = Array.from(e.target.files ?? []); e.target.value = ''; send(f) }} />
      </div>

      <div className={`rc__drop${over ? ' is-over' : ''}`} role="button" tabIndex={0}
        onClick={() => input.current?.click()}
        onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); input.current?.click() } }}
        onDragOver={e => { e.preventDefault(); setOver(true) }} onDragLeave={() => setOver(false)}
        onDrop={e => { e.preventDefault(); setOver(false); send(Array.from(e.dataTransfer.files)) }}>
        <FileSearch size={18} strokeWidth={1.8} />
        <span>{over ? 'Drop to read them' : 'Drop POs, invoices, audit reports, delivery proofs, memos or spreadsheets'}</span>
        <span className="vc__muted vc__xs">PDF, photo, XLSX or CSV · up to {MAX_MB} MB each · any order</span>
      </div>

      {error && <div className="vc__err vc__err--inline">{error} <button className="vc__lnk" onClick={load}>Try again</button></div>}

      {/* On the dashboard screen the board IS the screen. On the documents
          screen it stays a panel that can be folded away. */}
      {onBoard ? (
        <>
          <ReconDashboard cases={cases} active={focus} onPick={setFocus} />
          {/* The invoices the counts above are made of. Without this the
              reconciliation screen had no front door: it could only be
              reached by finding a document that belonged to it. */}
          {/* Withdrawn bills sort last: still reachable, never the first thing
              a reviewer reads. */}
          {cases && <CaseList filtered={!!focus}
            cases={cases.filter(c => matchesFilter(c, focus))
              .slice().sort((a, b) => Number(!!a.bill_deleted) - Number(!!b.bill_deleted))} />}
        </>
      ) : (cases?.length ?? 0) > 0 && (
        <>
          <div className="rc__dashbar">
            <button type="button" className={`rc__dashbtn${board ? ' on' : ''}`}
              aria-expanded={board} aria-controls="recon-dashboard"
              onClick={() => { setBoard(b => !b); try { localStorage.setItem(BOARD_KEY, board ? '0' : '1') } catch { /* private window */ } }}>
              <BarChart3 size={15} aria-hidden />
              <span className="vc__grow">Reconciliation dashboard</span>
              <span className="vc__muted vc__xs">{board ? 'Hide' : `${cases!.length} invoice${cases!.length === 1 ? '' : 's'}`}</span>
              <ChevronDown size={15} aria-hidden className={`rc__chev${board ? ' on' : ''}`} />
            </button>
          </div>
          <div id="recon-dashboard" hidden={!board}>
            {board && <ReconDashboard cases={cases} active={focus} onPick={setFocus} />}
          </div>
        </>
      )}



      {(needs.length > 0 || failed.length > 0) && (
        <section className="rc__sec" aria-label="Needs you">
          <div className="vc__subhead">Needs you ({needs.length + failed.length})</div>
          <div className="vc__box">
            {failed.map(d => (
              <div key={d.id} className="vc__docrow">
                <AlertTriangle size={14} className="vc__bad" />
                <div className="vc__grow vc__min0">
                  <div className="vc__strong vc__ellipsis">{d.file_name}</div>
                  <div className="vc__bad vc__xs">{readError(d.error)}</div>
                </div>
                {isStorageProblem(d.error)
                  ? <button className="vc__btn vc__btn--sm" onClick={() => input.current?.click()}>
                      <Upload size={14} />Upload again</button>
                  : <button className="vc__btn vc__btn--sm" onClick={() => reread(d)}><RotateCw size={14} />Read again</button>}
                <button className="vc__iconbtn vc__iconbtn--sm vc__iconbtn--danger" aria-label={`Delete ${d.file_name}`} title="Delete"
                  onClick={() => setDeleting(d)}><Trash2 size={14} /></button>
              </div>
            ))}
            {needs.map(({ doc, seg }) => (
              <NeedsRow key={seg.id} doc={doc} seg={seg}
                onLink={c => act(() => linkSegment(seg.id, c.case_id ? { case_id: c.case_id } : c.bill_id ? { bill_id: c.bill_id } : { po_id: c.po_id ?? undefined }), 'Linked')}
                onIgnore={reason => act(() => ignoreSegment(seg.id, reason), 'Set aside')}
                onOpen={() => { const i = files.findIndex(f => f.id === doc.id); if (i >= 0) setViewing(i) }} />
            ))}
          </div>
        </section>
      )}

      {!onBoard && <section className="rc__sec" aria-label="Documents">
        <div className="vc__subhead">
          Documents{docs ? ` (${all.filter(keep).length}${focus ? ` of ${all.length}` : ''})` : ''}
        </div>
        {docs === null ? <div className="vc__muted vc__xs rc__pad"><Loader2 size={14} className="rc__spin" /> Loading…</div>
          : all.length === 0 ? (
            <div className="vc__empty">
              <div className="vc__empty-t">Nothing added yet</div>
              <div className="vc__muted vc__xs">Add the PO, the invoice and the site audit report for an invoice, in any order. Each is checked against the others as soon as it’s read.</div>
            </div>
          ) : (
            /* One folder per kind of document. The classification already
               exists on every segment, so this files what is there rather
               than asking for anything to be read again — documents added
               long before these folders existed land in them straight away.
               A folder with nothing in it is not shown; empty shelves are
               not reassuring, they are just more to scroll past. */
            FOLDER_ORDER.filter(k => byFolder.get(k)?.length).map(key => (
            <details key={key} className="rc__folder" open={(byFolder.get(key) ?? []).length <= 12}>
              <summary className="rc__folder-h">
                <Folder size={14} className="vc__muted" />
                <span className="vc__strong">{FOLDER_LABEL[key]}</span>
                <span className="vc__c">{(byFolder.get(key) ?? []).length}</span>
                <span className="vc__muted vc__xs rc__folder-d">{FOLDER_HINT[key]}</span>
              </summary>
            <div className="rc__scroll">
              <table className="rc__table rc__files">
                <thead><tr><th>Document</th><th>Read as</th><th>Invoice</th>
                  <th title="How much of the invoice's value this document accounts for">Covers</th>
                  <th>Check</th><th><span className="vc__sr">Actions</span></th></tr></thead>
                <tbody>
                  {(byFolder.get(key) ?? []).map(d => {
                    const busy = d.recon_status === 'PENDING' || d.recon_status === 'RUNNING'
                    const fi = files.indexOf(d)
                    const open = () => { if (fi >= 0) setViewing(fi) }
                    const used = d.segments.filter(s => s.status !== 'IGNORED' && s.status !== 'FOREIGN')
                    const aside = d.segments.length - used.length
                    const caseIds = [...new Set(used.map(s => s.case_id).filter((x): x is string => !!x))]
                    const firstCase = caseIds.map(id => caseById.get(id)).find(Boolean)
                    return (
                      <tr key={d.id} className={busy ? undefined : 'rc__click'} onClick={busy ? undefined : open} tabIndex={busy ? undefined : 0}
                        onKeyDown={e => { if (!busy && e.key === 'Enter') open() }} aria-label={busy ? undefined : `Open ${d.file_name}`}>
                        <td className="rc__file-name">
                          <div className="rc__item"><FileText size={14} className="vc__muted" /><span className="vc__strong">{d.file_name}</span></div>
                          <div className="vc__muted vc__xs">{[d.uploaded_by, d.uploaded_at && new Date(d.uploaded_at).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })].filter(Boolean).join(' · ')}</div>
                        </td>
                        <td>
                          {busy ? <ReadingCell d={d} />
                            : d.recon_status === 'FAILED' ? <span className="vc__bad vc__xs">{readError(d.error)}</span>
                            : used.length === 0 && aside === 0 ? <span className="vc__muted vc__xs">Nothing to check found</span>
                            : <span className="rc__kinds">{kindsOf(used).map(k => <span key={k} className="vc__chip vc__chip--plain vc__chip--xs">{k}</span>)}
                                {aside > 0 && <span className="vc__muted vc__xs">+{aside} set aside</span>}</span>}
                        </td>
                        <td>
                          {caseIds.length > 0 ? (
                            <span className="rc__kinds">{caseIds.map(id => {
                              const c = caseById.get(id)
                              return (
                                <ReconLink key={id} caseId={id} className="rc__caselink" title="Open the reconciliation">
                                  <span className="vc__strong">{c?.invoice_no ?? (c?.po_number ? `PO ${c.po_number}` : 'Invoice')}</span>
                                  {c?.ref && <span className="rc__ref">{c.ref}</span>}
                                </ReconLink>
                              )
                            })}</span>
                          ) : busy ? null
                            : used.some(s => s.status === 'UNLINKED') ? <span className="rc__state--warn vc__xs">Not linked</span>
                            : used.some(s => s.status === 'WAITING') ? <span className="vc__muted vc__xs">Waiting for its invoice</span>
                            : <span className="vc__muted vc__xs">—</span>}
                        </td>
                        <td>
                          {(() => {
                            const leg = FOLDER_LEG[key]
                            const cov = leg && firstCase ? coverBadge(firstCase.leg_cover?.[leg]) : null
                            return cov ? (
                              <span className={`vc__chip vc__chip--${cov.tone} vc__chip--xs`}
                                title={`${cov.pct}% of what this invoice bills is accounted for by this document`}>
                                {cov.pct}%
                              </span>
                            ) : <span className="vc__muted vc__xs">—</span>
                          })()}
                        </td>
                        <td>
                          {firstCase ? (
                            <span className="rc__kinds">
                              <span className="rc__ways rc__ways--sm" title={waysTitle(firstCase)}>{waysOf(firstCase)}-way</span>
                              <CaseStatusChip status={firstCase.status} />
                              {Number(firstCase.money_at_risk) > 0 && <span className="vc__bad vc__xs rc__tnum">₹{inr(firstCase.money_at_risk)} at risk</span>}
                            </span>
                          ) : <span className="vc__muted vc__xs">—</span>}
                        </td>
                        <td className="rc__rowacts" onClick={e => e.stopPropagation()} onKeyDown={e => e.stopPropagation()}>
                          {!busy && !isStorageProblem(d.error) && (
                            <button className="vc__iconbtn vc__iconbtn--sm" aria-label={`Read ${d.file_name} again`} title="Read again"
                              onClick={() => reread(d)}><RotateCw size={14} /></button>
                          )}
                          {!busy && isStorageProblem(d.error) && (
                            <button className="vc__iconbtn vc__iconbtn--sm" aria-label={`Upload ${d.file_name} again`}
                              title="The stored file cannot be read — upload it again"
                              onClick={() => input.current?.click()}><Upload size={14} /></button>
                          )}
                          <button className="vc__iconbtn vc__iconbtn--sm vc__iconbtn--danger" aria-label={`Delete ${d.file_name}`} title="Delete"
                            disabled={busy} onClick={() => setDeleting(d)}><Trash2 size={14} /></button>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
            </details>
            ))
          )}
      </section>}

      <ConfirmDialog
        open={!!deleting}
        title="Delete this file from Recon?"
        description={deleting ? deleteSays(deleting, caseById) : ''}
        items={deleting ? [deleting.file_name] : undefined}
        confirmLabel="Delete"
        onCancel={() => setDeleting(null)}
        onConfirm={() => deleting ? remove(deleting) : undefined}
      />

      {viewing !== null && files[viewing] && (
        <ReconDocViewer
          title={files[viewing].file_name}
          subtitle={view?.data ? [view.data.parts.length > 1 ? `${view.data.parts.length} parts` : null, view.data.uploaded_by,
            view.data.uploaded_at && new Date(view.data.uploaded_at).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' })].filter(Boolean).join(' · ') : undefined}
          parts={view?.data?.parts ?? []} loading={!view?.data && !view?.error} error={view?.error}
          initialPart={firstUsedPart(view?.data?.parts ?? [])}
          onClose={() => setViewing(null)}
          onOpenCase={id => { setViewing(null); onCase(id) }}
          nav={{ index: viewing, count: files.length, onMove: setViewing }} />
      )}
    </div>
  )
}

/** A reading failure in words a finance user can act on; the technical text stays in the log. */
/** Is this a storage problem rather than a parsing problem?
 *
 *  The two look identical in a list and need opposite actions: a file we could
 *  not parse is worth reading again, a file whose bytes we never had is not.
 *  Offering "Read again" for the second wastes a person's time for ever. */
function isStorageProblem(e: string | null): boolean {
  return !!e && /stored on another machine|no file was stored|no longer on disk/i.test(e)
}

function readError(e: string | null): string {
  if (!e) return 'Couldn’t be read. Read it again, or delete it and upload a clearer copy.'
  if (/value too long|character varying|violates|syntax|constraint|psycopg|asyncpg/i.test(e))
    return 'Couldn’t be read (a reading problem on our side). Read it again.'
  return e
}

/** What deleting a file does, naming the invoices it's on. */
function deleteSays(d: ReconDocument, cases: Map<string, ReconCaseSummary>): string {
  const ids = [...new Set(d.segments.map(s => s.case_id).filter((x): x is string => !!x))]
  const names = ids.map(id => cases.get(id)).filter(Boolean).map(c => c!.invoice_no ?? c!.ref ?? 'an invoice')
  const on = names.length ? ` It is used on ${names.join(', ')}; ${names.length > 1 ? 'those are' : 'that is'} checked again without it.` : ''
  return `The file and everything read from it are removed.${on} You can upload it again afterwards.`
}

function ReadingCell({ d }: { d: ReconDocument }) {
  const p = d.progress ?? {}
  const pct = p.segments ? Math.round(((p.segment ?? 0) / p.segments) * 100) : null
  return (
    <div className="rc__reading">
      <span className="vc__xs"><Loader2 size={12} className="rc__spin" /> {d.recon_status === 'PENDING' ? 'Waiting to be read' : STAGE_LABEL[d.recon_stage ?? ''] ?? 'Reading'}
        {p.pages ? ` · ${p.pages} pages` : ''}</span>
      {pct !== null && <div className="rc__bar"><span style={{ width: `${pct}%` }} /></div>}
    </div>
  )
}

/** "Purchase order", "Site audit ×4" — what a file was read as, ignoring parts set aside. */
function kindsOf(segs: ReconSegment[]): string[] {
  const n = new Map<string, number>()
  for (const s of segs) {
    const k = KIND_LABEL[s.kind] ?? s.kind
    n.set(k, (n.get(k) ?? 0) + 1)
  }
  return [...n].map(([k, c]) => (c > 1 ? `${k} ×${c}` : k))
}

const waysOf = (c: ReconCaseSummary) => [c.docs.po, c.docs.invoice, c.docs.evidence > 0, c.docs.pod].filter(Boolean).length
const waysTitle = (c: ReconCaseSummary) =>
  `Checked across: ${[c.docs.po && 'PO', c.docs.invoice && 'invoice', c.docs.evidence > 0 && 'site audit', c.docs.pod && 'delivery proof'].filter(Boolean).join(', ')}`

/** Open on the first part that is actually used, not on another vendor's section. */
const firstUsedPart = (parts: { status?: string }[]) => Math.max(0, parts.findIndex(p => p.status !== 'IGNORED' && p.status !== 'FOREIGN'))

function NeedsRow({ doc, seg, onLink, onIgnore, onOpen }: {
  doc: ReconDocument; seg: ReconSegment
  onLink: (c: LinkCandidate) => void; onIgnore: (reason: string) => void; onOpen: () => void
}) {
  const what = `${KIND_LABEL[seg.kind] ?? seg.kind}${seg.section_title ? ` · ${seg.section_title}` : ''}`
  const pages = seg.pages.length > 1 ? `pages ${seg.pages[0]}–${seg.pages[seg.pages.length - 1]}` : `page ${seg.pages[0]}`
  return (
    <div className="vc__docrow rc__needs">
      <div className="vc__grow vc__min0">
        <div className="vc__strong vc__ellipsis">{doc.file_name}</div>
        <div className="vc__muted vc__xs">{what} · {pages}</div>
        {seg.status === 'FOREIGN' && (
          <div className="vc__xs rc__why">Belongs to another vendor{seg.vendor_name ? ` (${seg.vendor_name})` : ''}.</div>
        )}
        {seg.status === 'UNLINKED' && (
          <div className="rc__cands">
            <span className="vc__xs">{seg.candidates.length ? 'Which invoice is this for?' : 'No matching invoice or PO yet. It will link when they arrive.'}</span>
            {seg.candidates.map(c => (
              <button key={c.target_id} className="vc__btn vc__btn--sm" onClick={() => onLink(c)}
                title={Object.entries(c.signals).map(([k, v]) => `${k}: ${Math.round(Number(v) * 100)}%`).join(' · ')}>
                {c.label} · {Math.round(c.score * 100)}%
              </button>
            ))}
          </div>
        )}
        {seg.needs_review_cells > 0 && seg.status !== 'UNLINKED' && (
          <div className="vc__xs rc__why">{seg.needs_review_cells} handwritten number{seg.needs_review_cells > 1 ? 's' : ''} to check.</div>
        )}
      </div>
      <button className="vc__btn vc__btn--sm" onClick={onOpen}>Open</button>
      {(seg.status === 'FOREIGN' || seg.status === 'UNLINKED') && (
        <button className="vc__iconbtn vc__iconbtn--sm" aria-label="Set aside" title="Set aside"
          onClick={() => onIgnore(seg.status === 'FOREIGN' ? 'other vendor' : 'not needed')}><X size={14} /></button>
      )}
    </div>
  )
}

export function Flags({ counts }: { counts: Record<string, number> }) {
  const b = counts?.BLOCKER ?? 0, r = counts?.REVIEW ?? 0, i = counts?.INFO ?? 0
  return (
    <span className="rc__flags" aria-label={`${b} blockers, ${r} to review, ${i} info`}>
      {b > 0 && <span className="vc__chip vc__chip--bad vc__chip--xs">{b} blocker{b > 1 ? 's' : ''}</span>}
      {r > 0 && <span className="vc__chip vc__chip--warn vc__chip--xs">{r} to review</span>}
      {b === 0 && r === 0 && <span className="vc__chip vc__chip--ok vc__chip--xs">Clear</span>}
      {i > 0 && <span className="vc__muted vc__xs">+{i} info</span>}
    </span>
  )
}


// Kept exported here for the screens that already import it from this module.
export { CaseStatusChip }
