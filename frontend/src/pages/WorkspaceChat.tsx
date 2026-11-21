import { createContext, useContext, type ReactNode, useEffect, useRef, useState, type FormEvent } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { ArrowUp, ChevronRight, FileText, Maximize2, Paperclip, RotateCcw, X } from 'lucide-react'
import { useAuth } from '../auth/AuthContext'
import { useEntitlements } from '../auth/EntitlementsContext'
import { readImpersonation } from '../admin/impersonation'
import './workspace-chat.css'

interface Source { id: string; title: string; path: string | null; domain: string; values: Record<string, unknown> }
interface Turn { moreBills?: boolean; contextId?: string; question: string; message?: string; sources?: Source[]; file?: string; error?: boolean }
const prompts = ['Give me a workspace overview', 'Which bills need attention?', 'Explain reconciliation differences', 'Show supplier relationships for pending bills.', 'Which pending bills are overdue?', 'Show bills and decision history I can access.']
const languages = ['Auto','English','Hindi','Spanish','French','Tamil','Telugu','Marathi','Bengali']
const endpoint = (import.meta.env.VITE_API_URL ?? '') + '/api/finance-desk/assistant/chat'

function useConversation() {
  const [turns,setTurns] = useState<Turn[]>([])
  const [text,setText] = useState('')
  const [lang,setLang] = useState('Auto')
  const [file,setFile] = useState<File | null>(null)
  const [busy,setBusy] = useState(false)
  const [notice,setNotice] = useState('')
  const controller = useRef<AbortController | null>(null)
  useEffect(() => () => controller.current?.abort(), [])
  function reset() {
    controller.current?.abort()
    setBusy(false); setTurns([]); setText(''); setFile(null); setNotice('')
  }
  async function send(value: string, options: { bill_id?: string; more_bills?: boolean; context_id?: string } = {}) {
    const question=value.trim()
    if ((!question && !file) || busy) return
    const wording=question || 'Review this document and check its calculations.'
    const data=new FormData()
    data.set('payload', JSON.stringify({question:wording,language:lang,context_id:turns[turns.length-1]?.contextId,previous_questions:turns.slice(-4).map(t=>t.question),...options}))
    if (file) data.set('document',file)
    const abort=new AbortController()
    controller.current=abort
    setBusy(true); setText(''); setNotice('')
    setTurns(t=>[...t,{question:wording,file:file?.name}])
    try {
      const res=await fetch(endpoint,{method:'POST',body:data,signal:abort.signal})
      const body=await res.json()
      if (abort.signal.aborted) return
      if (!res.ok) {
        if (res.status===403 || res.status===401) {
          setTurns([]); setFile(null); setNotice('Your workspace access has changed. Sign in again or contact your administrator.')
          return
        }
        throw new Error(typeof body.detail === 'string' ? body.detail : 'Could not complete the request.')
      }
      if (!abort.signal.aborted) setTurns(t=>[...t.slice(0,-1),{question:wording,file:file?.name,message:body.message,sources:body.sources,contextId:body.context_id,moreBills:body.more_bills}])
    } catch(e) {
      if (!abort.signal.aborted) setTurns(t=>[...t.slice(0,-1),{question:wording,error:true,message:e instanceof Error?e.message:'Connection failed.'}])
    } finally { if (!abort.signal.aborted) setBusy(false) }
  }
  return {turns,text,setText,lang,setLang,file,setFile,busy,notice,setNotice,reset,send}
}

const Conversation = createContext<ReturnType<typeof useConversation> | null>(null)

export function ConversationProvider({children}: {children: ReactNode}) {
  const state = useConversation()
  return <Conversation.Provider value={state}>{children}</Conversation.Provider>
}

export function WorkspaceChat() {
  const state = useContext(Conversation)
  if (!state) throw new Error('WorkspaceChat needs a conversation provider')
  return <ChatView {...state} />
}

function Reply({ turn }: { turn: Turn }) {
  const lines = (turn.message || '').split(/\n+/).filter(Boolean)
  return <div className="wc-prose" role={turn.error ? 'alert' : undefined}>{lines.map((line, index) =>
    <p key={index}>{line.split(/(\[[SD]\d+\]|\*\*[^*]+\*\*)/g).map((part, j) => {
      const source = turn.sources?.find(s => '[' + s.id + ']' === part)
      if (source?.path) return <Link className="wc-ref" key={j} to={source.path} aria-label={'Open ' + source.title}>{source.id}</Link>
      if (part.startsWith('**') && part.endsWith('**')) return <strong key={j}>{part.slice(2,-2)}</strong>
      return part
    })}</p>)}</div>
}

function ChatView({ turns,text,setText,lang,setLang,file,setFile,busy,notice,setNotice,reset,send }: ReturnType<typeof useConversation>) {
  const input = useRef<HTMLInputElement>(null)
  const scroll = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const feed = scroll.current
    if (!feed) return
    const latest = feed.querySelector<HTMLElement>('.wc-turn:last-of-type .wc-answer')
    feed.scrollTop = latest && !busy
      ? feed.scrollTop + latest.getBoundingClientRect().top - feed.getBoundingClientRect().top - 8
      : feed.scrollHeight
  }, [turns,busy])
  function submit(e:FormEvent) { e.preventDefault(); void send(text) }
  return <div className="workspace-chat">
    <div className="wc-toolbar"><label>Reply language <select value={lang} onChange={e=>setLang(e.target.value)}>
      {languages.map(l=><option key={l} value={l}>{l==='Auto'?'Match my language':l}</option>)}</select></label>
      <button type="button" onClick={reset} aria-label="New conversation"><RotateCcw size={15} /> New chat</button></div>
    <div ref={scroll} className="wc-feed" role="log" aria-label="Conversation">
      {!turns.length && <div className="wc-welcome"><img src="/favicon.svg" alt="" /><h2>How can I help?</h2>
        <p>Explore your finance workspace or attach a document to review.</p>
        <div className="wc-prompts">{prompts.map(p=><button key={p} onClick={()=>void send(p)}>{p}<ChevronRight size={15}/></button>)}</div></div>}
      {turns.map((turn,i)=><div className="wc-turn" key={i}><div className="wc-question">{turn.question}{turn.file && <small><Paperclip size={12}/>{turn.file}</small>}</div>
        {turn.message && <div className="wc-answer"><div className="wc-author"><img src="/favicon.svg" alt="" width={20} height={20}/><strong>Reckon Copilot</strong></div><Reply turn={turn} />
          {!!turn.sources?.length && <details><summary>Sources ({turn.sources.length})</summary>{turn.sources.map(s=><div className="wc-source" key={s.id}>
            {s.path ? <Link to={s.path}>[{s.id}] {s.title}</Link> : <strong>[{s.id}] {s.title}</strong>}
            <dl>{Object.entries(s.values).filter(([k,v])=>v!=null && typeof v!=='object' && k!=='more_bills').map(([k,v])=><div key={k}><dt>{k.replace(/_/g,' ')}</dt><dd>{typeof v==='boolean' ? (v?'Yes':'No') : String(v)}</dd></div>)}</dl>
            {Array.isArray(s.values.decision_history) && !!s.values.decision_history.length && <ol>{s.values.decision_history.map((event: {action:string;role?:string;at?:string}, n:number) =>
              <li key={n}>{[event.action,event.role,event.at && new Date(event.at).toLocaleString()].filter(Boolean).join(' / ')}</li>)}</ol>}
            {s.path?.startsWith('/bills/') && <button disabled={busy} type="button" onClick={()=>void send('Show the decision history for ' + s.title, {bill_id:s.path!.split('/').pop()})}>Review bill history</button>}
            {s.domain === 'document' && Array.isArray(s.values.invoice_checks) && s.values.invoice_checks.map((c: {invoice:string;status:string;difference?:string;currency?:string;path?:string}) =>
              <p key={c.invoice}>{c.path ? <Link to={c.path}>{c.invoice}</Link> : c.invoice} / {c.status} {c.difference && c.difference + ' ' + c.currency}</p>)}
            {s.domain === 'document' && Array.isArray(s.values.examples) && s.values.examples.map((r: {row:number;expected:string;difference:string}) =>
              <p key={r.row}>Row {r.row}: expected {r.expected}, difference {r.difference}</p>)}
          </div>)}</details>}{turn.moreBills && <button disabled={busy} onClick={()=>void send('Show the next bills',{more_bills:true,context_id:turn.contextId})}>More bills <ChevronRight size={14}/></button>}</div>}</div>)}
      {busy && <p className="wc-thinking" role="status">Checking your sources…</p>}
    </div>
    {notice && <p role="alert">{notice}</p>}
    <form onSubmit={submit} className="wc-composer">
      {file && <div className="wc-file"><FileText size={15}/>{file.name}<button type="button" aria-label="Remove attachment" onClick={()=>setFile(null)}><X size={14}/></button></div>}
      <textarea aria-label="Message Reckon Copilot" value={text} onChange={e=>setText(e.target.value)} maxLength={2000}
        placeholder="Ask Reckon Copilot…" rows={2} onKeyDown={e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.nativeEvent.isComposing){e.preventDefault();void send(text)}}}/>
      <div><input hidden aria-label="Attach a finance document" ref={input} type="file" accept=".pdf,.csv,.txt" onChange={e=>{
        const f=e.target.files?.[0]; e.target.value=''
        if(f && f.size<=2097152) {setFile(f); setNotice('')} else if(f) setNotice('Choose a file up to 2 MB.')
      }}/><button type="button" disabled={busy} onClick={()=>input.current?.click()}><Paperclip size={16}/> Attach file</button>
      <button className="wc-send" disabled={busy||(!text.trim()&&!file)} aria-label="Send message"><ArrowUp size={18}/></button></div>
    </form><small className="wc-help">PDF, CSV or TXT · 2 MB max. For line checks, use CSV columns quantity, unit_price and line_total.</small>
  </div>
}

export function CopilotLauncher() {
  const [open,setOpen]=useState(false)
  const {user}=useAuth()
  const {has}=useEntitlements()
  const {pathname}=useLocation()
  useEffect(()=>{setOpen(false)},[pathname,user?.company_id,user?.username,user?.role])
  useEffect(()=>{
    if(!open)return
    const onKey=(e:KeyboardEvent)=>{if(e.key==='Escape')setOpen(false)}
    window.addEventListener('keydown',onKey);return ()=>window.removeEventListener('keydown',onKey)
  },[open])
  if(!user||readImpersonation()||user.role==='member'||!has('fact_graph')||pathname==='/finance-desk/copilot')return null
  return <aside className="wc-launcher">{open && <section className="wc-panel" aria-label="Reckon Copilot chat">
    <header><img src="/favicon.svg" alt=""/><strong>Reckon Copilot</strong><Link to="/finance-desk/copilot" aria-label="Open full chat"><Maximize2 size={16}/></Link>
      <button onClick={()=>setOpen(false)} aria-label="Close chat"><X size={18}/></button></header>
    <WorkspaceChat key={[user.company_id,user.username,user.role].join('/')} /></section>}
    <button className="wc-launch" aria-expanded={open} aria-label="Toggle Reckon Copilot" onClick={()=>setOpen(!open)}><img src="/favicon.svg" alt=""/> Copilot</button>
  </aside>
}
