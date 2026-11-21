import { useEffect, useRef, useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { GitBranch, MessageSquare, Send } from 'lucide-react'
import { useAuth } from '../auth/AuthContext'
import { billPath } from '../routes/paths'
import { WorkspaceChat } from './WorkspaceChat'
import { useEntitlements } from '../auth/EntitlementsContext'
import './copilot.css'

const questions = [
  'Which bills are in my approval queue?',
  'Which pending bills are overdue?',
  'Show supplier relationships for pending bills.',
  'Show bills and decision history I can access.',
]
interface Evidence {
  id: string; citation: string; invoice_number: string | null; stage: string; record_state?: string; step_role: string | null
  supplier: string | null; graph_link: boolean; latest_action: string | null; action_at: string | null
  decision_history?: { action: string; role: string | null; at: string | null }[]
  due_date: string | null
}
interface Answer { intent?: string; answer: string; evidence: Evidence[]; partial: boolean }

export function ApprovalAssistant() {
  const [question, setQuestion] = useState('')
  const [offset, setOffset] = useState(0)
  const [asked, setAsked] = useState('')
  const [answer, setAnswer] = useState<Answer | null>(null)
  const [attached, setAttached] = useState<Evidence | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const pending = useRef<AbortController | null>(null)
  useEffect(() => () => pending.current?.abort(), [])

  async function ask(text: string, bill = attached, pageOffset = 0) {
    if (!text.trim()) return
    pending.current?.abort()
    const request = new AbortController()
    pending.current = request
    setOffset(pageOffset); setBusy(true); setAsked(text); setAnswer(null); setError('')
    try {
      const res = await fetch((import.meta.env.VITE_API_URL ?? '') + '/api/finance-desk/assistant/query', {
        method: 'POST', signal: request.signal, headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: text.trim(), bill_id: bill?.id, offset: pageOffset || undefined }),
      })
      if (!res.ok) throw new Error(res.status === 403 ? 'Your account does not have approval Copilot access.' : 'Unable to retrieve approval evidence. Please retry.')
      const data: Answer = await res.json()
      if (!request.signal.aborted) setAnswer(data)
    } catch (e) {
      if (!request.signal.aborted) { setAttached(null); setError(e instanceof Error ? e.message : 'Request failed.') }
    } finally { if (!request.signal.aborted) setBusy(false) }
  }
  function submit(event: FormEvent) { event.preventDefault(); void ask(question) }
  return <div><header><MessageSquare size={23} /><h2>Approval evidence</h2></header>
    <p>Explore pending bills, supplier relationships and recent approval activity within your approval scope.</p>
    <form onSubmit={submit}><label htmlFor="copilot-question">Ask about approvals</label>
      {attached && <p>Selected bill: {attached.invoice_number || attached.id} <button type="button" disabled={busy} onClick={() => { setAttached(null); setAnswer(null) }}>Clear</button></p>}
      <textarea id="copilot-question" maxLength={2000} value={question} onChange={e => setQuestion(e.target.value)} rows={3} />
      <button type="submit" disabled={busy || !question.trim()}><Send size={15} /> Ask Copilot</button>
    </form>
    <div className="copilot-prompts">{questions.map(q => <button key={q} disabled={busy} onClick={() => { setQuestion(q); void ask(q) }}>{q}</button>)}</div>
    {busy && <p role="status">Checking the approval chain and related records…</p>}
    {error && <p role="alert">{error}</p>}
    {answer && <section aria-live="polite"><h2>{asked}</h2><p>{answer.answer}</p>
      {answer.evidence.map(r => <article key={r.id}><div><Link to={billPath(r.id)}>[{r.citation}] {r.invoice_number || r.id}</Link>
        <button onClick={() => { setAttached(r); const next = answer.intent === 'records' ? questions[3] : questions[2]; setQuestion(next); void ask(next, r) }}>Focus on bill</button></div>
        <p><GitBranch size={15} /> {r.supplier || 'Supplier unavailable'} · {r.graph_link ? 'Graph-linked bill' : 'Invoice record'} · {r.stage}{r.record_state && r.record_state !== 'active' && ' / ' + r.record_state}</p>
        <p>Assigned role: {r.step_role?.replace(/_/g, ' ') || 'No current assignment'} · Due: {r.due_date || 'Unrecorded'}</p>
        {r.latest_action && <p>Latest action: {r.latest_action}{r.action_at && ' · ' + new Date(r.action_at).toLocaleString()}</p>}
        {!!r.decision_history?.length && <details><summary>Decision history ({r.decision_history.length})</summary>
          <ol>{r.decision_history.map((event, index) => <li key={index}>{event.action} / {event.role || 'Role unrecorded'} / {event.at ? new Date(event.at).toLocaleString() : 'Date unrecorded'}</li>)}</ol>
        </details>}
      </article>)}
      {(offset > 0 || answer.partial) && <div className="copilot-prompts">
        {offset > 0 && <button onClick={() => void ask(asked, attached, Math.max(0, offset - 12))}>Previous bills</button>}
        {answer.partial && <button onClick={() => void ask(asked, attached, offset + answer.evidence.length)}>More bills</button>}
      </div>}
    </section>}
  </div>
}

export default function CopilotPage() {
  const { user } = useAuth()
  const { has } = useEntitlements()
  const [view,setView] = useState('chat')
  const approvalAccess = has('bills') && has('approvals')
  return <main className="reckon-copilot"><header><img src="/favicon.svg" height={32} width={32} alt="" /><h1>Reckon Copilot</h1></header>
    {approvalAccess && <nav className="wc-tabs"><button aria-pressed={view==='chat'} onClick={()=>setView('chat')}>Workspace chat</button>
      <button aria-pressed={view==='approval'} onClick={()=>setView('approval')}>Approval evidence</button></nav>}
    {view==='approval' && approvalAccess ? <ApprovalAssistant key={[user?.company_id,user?.username,user?.role].join('/')} /> : <WorkspaceChat key={[user?.company_id,user?.username,user?.role].join('/')} />}
  </main>
}
