import { useEffect, useRef, useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { GitBranch, MessageSquare, Send } from 'lucide-react'
import { useAuth } from '../auth/AuthContext'
import { billPath } from '../routes/paths'
import './copilot.css'

const questions = [
  'Which bills are in my approval queue?',
  'Which pending bills are overdue?',
  'Show supplier relationships for pending bills.',
]
interface Evidence {
  id: string; citation: string; invoice_number: string | null; stage: string; step_role: string
  supplier: string | null; graph_link: boolean; latest_action: string | null; action_at: string | null
  due_date: string | null
}
interface Answer { answer: string; evidence: Evidence[]; partial: boolean }

function ApprovalAssistant() {
  const [question, setQuestion] = useState('')
  const [asked, setAsked] = useState('')
  const [answer, setAnswer] = useState<Answer | null>(null)
  const [attached, setAttached] = useState<Evidence | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const pending = useRef<AbortController | null>(null)
  useEffect(() => () => pending.current?.abort(), [])

  async function ask(text: string, bill = attached) {
    if (!text.trim()) return
    pending.current?.abort()
    const request = new AbortController()
    pending.current = request
    setBusy(true); setAsked(text); setAnswer(null); setError('')
    try {
      const res = await fetch((import.meta.env.VITE_API_URL ?? '') + '/api/finance-desk/assistant/query', {
        method: 'POST', signal: request.signal, headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: text.trim(), bill_id: bill?.id }),
      })
      if (!res.ok) throw new Error(res.status === 403 ? 'Your account does not have approval Copilot access.' : 'Unable to retrieve approval evidence. Please retry.')
      const data: Answer = await res.json()
      if (!request.signal.aborted) setAnswer(data)
    } catch (e) {
      if (!request.signal.aborted) { setAttached(null); setError(e instanceof Error ? e.message : 'Request failed.') }
    } finally { if (!request.signal.aborted) setBusy(false) }
  }
  function submit(event: FormEvent) { event.preventDefault(); void ask(question) }
  return <main className="reckon-copilot"><header><MessageSquare size={23} /><h1>Reckon Copilot</h1></header>
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
        <button onClick={() => { setAttached(r); setQuestion(questions[2]); void ask(questions[2], r) }}>Focus on bill</button></div>
        <p><GitBranch size={15} /> {r.supplier || 'Supplier unavailable'} · {r.graph_link ? 'Graph-linked bill' : 'Invoice record'} · {r.stage}</p>
        <p>Assigned role: {r.step_role.replace(/_/g, ' ')} · Due: {r.due_date || 'Unrecorded'}</p>
        {r.latest_action && <p>Latest action: {r.latest_action}{r.action_at && ' · ' + new Date(r.action_at).toLocaleString()}</p>}
      </article>)}
    </section>}
  </main>
}

export default function CopilotPage() {
  const { user } = useAuth()
  return <ApprovalAssistant key={[user?.company_id, user?.username, user?.role].join('/')} />
}
