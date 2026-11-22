import { useEffect, useState, useCallback, useRef } from 'react'
import { Link } from 'react-router-dom'
import {
  Cpu, RefreshCw, FileText, Mail, XCircle, AlertTriangle, Clock, Network,
  GitCompare, ShieldCheck, Radar, Brain, Banknote, ScrollText, Percent, Landmark, HandCoins,
  ClipboardCheck, ArrowUpRight, MessageCircle,
} from 'lucide-react'
import { useAuth } from '../auth/AuthContext'
import { useEntitlements } from '../auth/EntitlementsContext'
import type { ServiceKey } from '../auth/services'
import FactGraphModal from '../components/factgraph/FactGraphModal'
import InvoiceProcessing from '../components/InvoiceProcessing'
import WhatsAppAgentPanel from '../components/agenthub/WhatsAppAgentPanel'
import { Switch, Button, Badge, useToast } from '../ui'
import { PATHS, reviewPath, settingsPath } from '../routes/paths'
import {
  fetchAgentStatus, toggleAgent, triggerAgentScan, fetchAgentEvents, fetchAgentPocs, setContactAgent,
  fetchAgentDrafts, fetchAgentDraft, fetchAgentDraftFile,
  type AgentStatus, type AgentEvent, type AgentPoc, type AgentDraft,
} from '../api/agent'
import { fetchWaStatus, updateWaSettings, errorText, type WaStatus } from '../api/whatsapp'
import './agenthub.css'

interface Props {
  onReviewDraft?: (item: { file: File; data: Record<string, unknown> }, draftId: string, origin?: string) => void
}

const ACTION_META: Record<string, { label: string; color: string; icon: React.ElementType }> = {
  draft_created:   { label: 'Draft created',      color: 'var(--cat-4)', icon: FileText },
  skipped_not_bill:{ label: 'Skipped — not a bill', color: 'var(--ink-500)', icon: XCircle },
  skipped_no_pdf:  { label: 'Skipped — no PDF',    color: 'var(--ink-500)', icon: XCircle },
  // A mail with no PDF is still read for terms by the communication agent.
  terms_found:     { label: 'Terms read → Review Hub', color: 'var(--cat-4)', icon: FileText },
  reading_terms:   { label: 'Reading for terms…',  color: 'var(--info-600)', icon: Clock },
  skipped_no_poc:  { label: 'Skipped — not a watched POC', color: 'var(--ink-500)', icon: XCircle },
  skipped_duplicate:{ label: 'Skipped — duplicate', color: 'var(--warn-600)', icon: XCircle },
  processing:      { label: 'Processing…',         color: 'var(--info-600)', icon: Clock },
  ocr_failed:      { label: 'OCR failed',          color: 'var(--danger-600)', icon: AlertTriangle },
}

// Agent fleet and licensed destinations.
type Shortcut = { label: string; to: string; requires: ServiceKey[]; adminOnly?: boolean }
const SERVICES: { name: string; desc: string; planned?: boolean; icon: React.ElementType; shortcuts?: Shortcut[] }[] = [
  { name: 'Verification', desc: 'Vendor identity and bank checks.', icon: ShieldCheck, shortcuts: [
    { label: 'Identity findings', to: `${reviewPath()}?types=vendor_identity`, requires: ['review_hub'] },
  ] },
  { name: 'Recon', desc: 'Invoice lines matched to purchase and receipt evidence.', icon: GitCompare, shortcuts: [
    { label: 'Recon findings', to: `${reviewPath()}?types=reconciliation`, requires: ['review_hub'] },
    { label: 'Browse vendors', to: PATHS.vendors, requires: ['recon', 'vendors'] },
  ] },
  { name: 'Analytics', desc: 'Approval turnaround and invoice rework.', icon: Radar, shortcuts: [
    { label: 'Approval analytics', to: `${PATHS.reports}?tab=approval`, requires: ['reports'] },
  ] },
  { name: 'CFO Orchestrator', desc: 'Runs invoice controls and surfaces exceptions.', icon: Brain, shortcuts: [
    { label: 'Open orchestrator', to: PATHS['cfo-orchestrator'], requires: ['agent_hub'] },
  ] },
  { name: 'Payable', desc: 'Approval routing and payment status.', icon: Banknote, shortcuts: [
    { label: 'Payment findings', to: `${reviewPath()}?types=approval,payment`, requires: ['review_hub'] },
    { label: 'Open payments', to: PATHS.payments, requires: ['disbursement'] },
  ] },
  { name: 'Contract', desc: 'Extracted terms and invoice variances.', icon: ScrollText, shortcuts: [
    { label: 'Contract findings', to: `${reviewPath()}?type=contract_bill_variance`, requires: ['review_hub'] },
  ] },
  { name: 'TDS', desc: 'Withholding on eligible bills.', icon: Percent, shortcuts: [
    { label: 'Tax findings', to: `${reviewPath()}?types=tax`, requires: ['review_hub', 'tds'] },
    { label: 'TDS settings', to: settingsPath('tds'), requires: ['settings', 'tds'], adminOnly: true },
  ] },
  { name: 'GST', desc: 'Vendor GST registration checks.', icon: Landmark, shortcuts: [
    { label: 'GSTIN findings', to: `${reviewPath()}?type=vendor_gstin_verification_failed`, requires: ['review_hub'] },
  ] },
  { name: 'Receivable', desc: 'Receipts matched to open invoices.', icon: HandCoins, shortcuts: [
    { label: 'Cash application', to: PATHS['ar-cash'], requires: ['receivables'] },
  ] },
]

function timeAgo(iso: string): string {
  const then = new Date(iso).getTime()
  if (Number.isNaN(then)) return iso
  const s = Math.floor((Date.now() - then) / 1000)
  if (s < 60) return `${s}s ago`
  if (s < 3600) return `${Math.floor(s / 60)}m ago`
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`
  return new Date(iso).toLocaleDateString()
}

function focusPanel(id: string) {
  const panel = document.getElementById(id)
  panel?.focus({ preventScroll: true })
  panel?.scrollIntoView({ block: 'start' })
}

export default function AgentHubPage({ onReviewDraft }: Props) {
  const { user, activeBrand } = useAuth()
  const toast = useToast()
  const { has } = useEntitlements()
  const companyId = user?.company_id

  const [status, setStatus]   = useState<AgentStatus | null>(null)
  const [events, setEvents]   = useState<AgentEvent[]>([])
  const [pocs, setPocs]       = useState<AgentPoc[]>([])
  const [drafts, setDrafts]   = useState<AgentDraft[]>([])
  const [loading, setLoading] = useState(true)
  const [scanning, setScanning] = useState(false)
  const [opening, setOpening] = useState<string | null>(null)
  const [savingToggle, setSavingToggle] = useState(false)
  const [showGraph, setShowGraph] = useState(false)

  const [waStatus, setWaStatus] = useState<WaStatus | null>(null)
  const [waSaving, setWaSaving] = useState(false)
  const waVersion = useRef(0)
  const loadWaStatus = useCallback(async () => {
    const version = ++waVersion.current
    try {
      const result = await fetchWaStatus(activeBrand?.id)
      if (version === waVersion.current) setWaStatus(result)
    } catch (err) {
      if (version === waVersion.current) setWaStatus(null)
      throw err
    }
  }, [activeBrand?.id])
  const wa = waStatus?.connection
  const toggleWaIntake = async (enabled: boolean) => {
    if (user?.role !== 'admin' || !wa || waSaving) return
    setWaSaving(true)
    try {
      const { connection } = await updateWaSettings({ inbound_enabled: enabled })
      ++waVersion.current
      setWaStatus(current => current && { ...current, connection })
      toast.success(enabled ? 'WhatsApp intake enabled' : 'WhatsApp intake paused')
    } catch (err) {
      toast.error('Could not update WhatsApp intake', errorText(err, 'Try again.'))
    } finally {
      setWaSaving(false)
    }
  }

  const refresh = useCallback(async () => {
    if (!companyId) return
    try {
      const [s, e, p, d] = await Promise.all([
        fetchAgentStatus(companyId),
        fetchAgentEvents(companyId, 50),
        fetchAgentPocs(companyId),
        fetchAgentDrafts(companyId),
      ])
      setStatus(s); setEvents(e); setPocs(p); setDrafts(d)
    } catch { /* silent */ } finally { setLoading(false) }
  }, [companyId])

  // Manual "Scan now" also runs a live mailbox scan, then reloads the results.
  const manualRefresh = useCallback(async () => {
    if (!companyId || scanning) return
    setScanning(true)
    try { await triggerAgentScan(companyId) }
    catch { /* still refresh below to reflect whatever changed */ }
    finally { await refresh(); setScanning(false) }
  }, [companyId, scanning, refresh])

  useEffect(() => { refresh() }, [refresh])
  // Light auto-refresh so the log stays current while the page is open.
  useEffect(() => {
    // Pause polling while the tab is hidden — no point scanning on behalf of a
    // window nobody is looking at.
    const t = setInterval(() => {
      if (document.visibilityState === 'visible') refresh()
    }, 30000)
    return () => clearInterval(t)
  }, [refresh])

  const handleToggleAgent = async () => {
    if (!companyId || !status) return
    setSavingToggle(true)
    const next = !status.enabled
    setStatus({ ...status, enabled: next })
    try {
      await toggleAgent(companyId, next)
      toast.success(next ? 'Mailbox scanning enabled' : 'Mailbox scanning paused')
    } catch {
      // The toggle used to flip back with no explanation, leaving the user
      // believing a mailbox-reading agent was off when it was still running.
      setStatus({ ...status, enabled: !next })
      toast.error(
        next ? 'Could not enable mailbox scanning' : 'Could not pause mailbox scanning',
        'The mailbox setting stayed the same. Try again.',
      )
    } finally { setSavingToggle(false) }
  }

  const handleTogglePoc = async (poc: AgentPoc) => {
    if (!companyId) return
    const next = !poc.agent_enabled
    setPocs(prev => prev.map(p => p.id === poc.id ? { ...p, agent_enabled: next } : p))
    try { await setContactAgent(poc.supplier_id, poc.id, companyId, next) }
    catch {
      setPocs(prev => prev.map(p => p.id === poc.id ? { ...p, agent_enabled: !next } : p))
      toast.error(`Could not ${next ? 'start' : 'stop'} watching ${poc.name}`, 'Nothing changed. Try again.')
    }
  }

  const openDraft = async (draftId: string, sourceFile: string) => {
    if (!companyId || !onReviewDraft) return
    setOpening(draftId)
    try {
      const [detail, file] = await Promise.all([
        fetchAgentDraft(draftId, companyId),
        fetchAgentDraftFile(draftId, companyId, sourceFile),
      ])
      onReviewDraft({ file, data: detail.payload }, draftId, 'agent-hub')
    } catch { /* silent */ } finally { setOpening(null) }
  }

  const watched = pocs.filter(p => p.agent_enabled)
  const mailboxEnabled = status?.enabled === true
  const plannedCount = SERVICES.filter(agent => agent.planned).length
  const waLive = Boolean(wa?.inbound_enabled && wa.state === 'ACTIVE' && waStatus?.worker_enabled)
  const liveCount = SERVICES.length - plannedCount + 2 + Number(waLive)

  const telemetry = [
    { key: 'Watched contacts', val: status?.watched_pocs ?? 0 },
    { key: 'Pending drafts', val: status?.pending_drafts ?? 0 },
    { key: 'Events logged', val: status?.events_total ?? 0 },
    { key: 'Scan interval', val: status ? `${Math.round(status.poll_interval / 60)}m` : '—' },
    { key: 'Last scan', val: status?.last_scan_at ? timeAgo(status.last_scan_at) : 'never' },
  ]

  return (
    <div className="ah">
      {/* ── Command deck ─────────────────────────────────────────────────── */}
      <div className="ah-deck" data-scanning={scanning}>
        <div className="ah-deck__row">
          <div className="ah-deck__id">
            <div className="ah-deck__mark"><Cpu size={22} /></div>
            <div style={{ minWidth: 0 }}>
              <h1 className="ah-deck__title">Agent Hub</h1>
              <div className="ah-deck__meta">
                <span className="ah-dot ah-dot--deck ah-dot--on" aria-hidden="true" />
                <span>{liveCount} live modules</span>
              </div>
            </div>
          </div>
          <div className="ah-deck__actions">
            {has('fact_graph') && <button
              className="ah-deck__btn"
              onClick={() => setShowGraph(true)}
              title="Shared memory: every vendor, bill and contact, plus the facts agents extract"
            >
              <Network size={14} aria-hidden="true" /> Fact Graph
            </button>}
            <button
              className="ah-deck__btn ah-deck__btn--accent"
              onClick={manualRefresh}
              disabled={scanning || savingToggle || !mailboxEnabled}
              title="Scan the watched mailboxes now and reload"
            >
              <RefreshCw size={14} className={scanning || loading ? 'ah-spin' : ''} aria-hidden="true" />
              {scanning ? 'Scanning…' : 'Scan mailbox'}
            </button>
          </div>
        </div>
      </div>

      <div className="ah-console">
        <section className="ah-roster" aria-labelledby="ah-fleet-title">
          <div className="ah-roster__head">
            <h2 id="ah-fleet-title">Agent fleet</h2>
            <span>{liveCount} live · {plannedCount} planned</span>
          </div>
          <ul className="ah-fleet">
                <li className="ah-agent">
                    <div className="ah-roster__identity">
                      <span className="ah-agent__icon"><Mail size={16} aria-hidden="true" /></span>
                      <div><strong>Communication</strong><small>Mailbox → extraction → draft or claim</small></div>
                    </div>
                    <span className="ah-roster__status"><span className="ah-dot ah-dot--on" aria-hidden="true" />Live</span>
                    <div className="ah-agent__actions">
                      <button type="button" className="ah-shortcut" onClick={() => focusPanel('ah-mailbox-activity')}>Mailbox evidence</button>
                      {drafts.length > 0 && <button type="button" className="ah-shortcut" onClick={() => focusPanel('ah-drafts')}>View drafts</button>}
                    </div>
                    <div className="ah-agent__switch">
                      <span>Mailbox scanning</span>
                      <Switch checked={mailboxEnabled} onChange={handleToggleAgent}
                        disabled={savingToggle || scanning || !status} label="Mailbox scanning" />
                    </div>
                </li>
                <li className="ah-agent">
                    <div className="ah-roster__identity">
                      <span className="ah-agent__icon"><ClipboardCheck size={16} aria-hidden="true" /></span>
                      <div><strong>Compliance</strong><small>Vendor compliance, master data, and contracts</small></div>
                    </div>
                  <span className="ah-roster__status"><span className="ah-dot ah-dot--on" aria-hidden="true" />Live</span>
                  {has('review_hub') && <Link className="ah-shortcut" to={reviewPath()}>View findings <ArrowUpRight size={12} aria-hidden="true" /></Link>}
                </li>
                {has('whatsapp_agent') && <li className="ah-agent">
                  <div className="ah-roster__identity">
                    <span className="ah-agent__icon"><MessageCircle size={16} aria-hidden="true" /></span>
                    <div><strong>WhatsApp Agent</strong><small>Vendor invoices and messages via Twilio</small></div>
                  </div>
                  {wa && <span className="ah-roster__status">
                    <span className={waLive ? 'ah-dot ah-dot--on' : 'ah-dot'} aria-hidden="true" />
                    {waLive ? 'Live' : !wa.inbound_enabled ? 'Paused' : wa.state === 'AWAITING_TEST' ? 'Testing' : 'Check setup'}
                  </span>}
                  <div className="ah-agent__actions">
                    <button type="button" className="ah-shortcut" onClick={() => focusPanel('ah-whatsapp')}>
                      WhatsApp activity
                    </button>
                    {user?.role === 'admin' && <Link className="ah-shortcut" to="/integrations#whatsapp">
                      {waStatus && !wa ? 'Connection setup' : 'Manage connection'}
                    </Link>}
                  </div>
                  <div className="ah-agent__switch">
                    <span>WhatsApp intake</span>
                    <Switch checked={!!wa?.inbound_enabled} onChange={toggleWaIntake}
                      disabled={!wa || waSaving || user?.role !== 'admin'} label="WhatsApp intake" />
                  </div>
                </li>}
                {SERVICES.map(agent => {
                  const Icon = agent.icon
                  const shortcuts = agent.shortcuts?.filter(shortcut =>
                    (shortcut.to !== PATHS['cfo-orchestrator'] || user?.role === 'admin' || user?.role === 'finance_controller') &&
                    shortcut.requires.every(has) && (!shortcut.adminOnly || user?.role === 'admin'),
                  )
                  return (
                    <li key={agent.name} className={agent.planned ? 'ah-agent ah-agent--planned' : 'ah-agent'}>
                        <div className="ah-roster__identity">
                          <span className="ah-agent__icon"><Icon size={16} aria-hidden="true" /></span>
                          <div><strong>{agent.name}</strong><small>{agent.desc}</small></div>
                        </div>
                      <span className="ah-roster__status"><span className={agent.planned ? 'ah-dot' : 'ah-dot ah-dot--on'} aria-hidden="true" />{agent.planned ? 'Planned' : 'Live'}</span>
                        <div className="ah-agent__actions">
                          {shortcuts?.map(shortcut => (
                            <Link className="ah-shortcut" key={shortcut.to} to={shortcut.to}>{shortcut.label} <ArrowUpRight size={12} aria-hidden="true" /></Link>
                          ))}
                        </div>
                    </li>
                  )
                })}
          </ul>
        </section>

        <aside className="ah-console__tools" aria-label="Agent tools">
          {user && ['admin', 'finance_controller'].includes(user.role) && (
            <InvoiceProcessing key={`${companyId}:${activeBrand?.id ?? ''}`} brandId={activeBrand?.id} />
          )}
          <section className="ah-mailbox" aria-labelledby="ah-mailbox-title">
            <div className="ah-roster__head">
              <h2 id="ah-mailbox-title">Mailbox watcher</h2>
              <span>{status ? mailboxEnabled ? 'Enabled' : 'Paused' : 'Status unavailable'}</span>
            </div>
            <dl className="ah-tele">
              {telemetry.map(metric => (
                <div key={metric.key}>
                  <dt>{metric.key}</dt><dd>{metric.val}</dd>
                </div>
              ))}
            </dl>
          </section>
        </aside>
      </div>

      <div className="ah-panels">
        {/* Activity stream */}
        <div className="ah-panel" id="ah-mailbox-activity" tabIndex={-1} role="region" aria-label="Mailbox activity">
          <div className="ah-panel__head">
            <div className="ah-panel__title">Activity</div>
            <span className="ah-panel__count">{events.length} events</span>
          </div>
          <div className="ah-panel__body ah-panel__body--tall">
            {events.length === 0 && <div className="ah-empty">No activity yet.</div>}
            {events.map(ev => {
              const meta = ACTION_META[ev.action] ?? { label: ev.action, color: 'var(--ink-500)', icon: Clock }
              const Icon = meta.icon
              const draft = ev.action === 'draft_created' && ev.draft_id
                ? drafts.find(x => x.id === ev.draft_id)
                : undefined
              const body = (
                <>
                  <Icon size={15} color={meta.color} className="ah-ev__icon" aria-hidden="true" />
                  <div style={{ minWidth: 0 }}>
                    <div className="ah-ev__head">
                      <span className="ah-ev__action" style={{ color: meta.color }}>{meta.label}</span>
                      {ev.supplier_name && <span className="ah-ev__who"> · {ev.supplier_name}</span>}
                    </div>
                    <div className="ah-ev__sub" title={`${ev.subject ?? ''}${ev.detail ? ` — ${ev.detail}` : ''}`}>
                      {ev.subject || ev.from_email || '—'}{ev.detail ? ` — ${ev.detail}` : ''}
                    </div>
                  </div>
                  <div className="ah-ev__time">{timeAgo(ev.created_at)}</div>
                </>
              )
              // A row that opens a draft is a real button — it used to be a
              // <div onClick>, unreachable by keyboard.
              return draft
                ? <button key={ev.id} className="ah-ev" onClick={() => openDraft(draft.id, draft.source_file)}>{body}</button>
                : <div key={ev.id} className="ah-ev">{body}</div>
            })}
          </div>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--sp-4)', minWidth: 0 }}>
          {/* Watched contacts */}
          <div className="ah-panel">
            <div className="ah-panel__head">
              <div className="ah-panel__title">Watched contacts</div>
              <span className="ah-panel__count">{watched.length}/{pocs.length}</span>
            </div>
            <div className="ah-panel__body ah-panel__body--tall">
              {pocs.length === 0 && (
                <div className="ah-empty">No vendor contacts with an email. Add points of contact on Vendors first.</div>
              )}
              {pocs.length > 0 && (
                <table className="ah-contact-table" aria-label="Vendor contacts">
                  <thead><tr><th scope="col">Contact</th><th scope="col">Vendor</th><th scope="col">Watch</th></tr></thead>
                  <tbody>
                    {pocs.map(p => (
                      <tr key={p.id}>
                        <th scope="row"><span className="ah-poc__name">{p.name}</span><span className="ah-poc__mail">{p.email}</span></th>
                        <td>{p.supplier_name || '—'}</td>
                        <td>
                          <Switch checked={p.agent_enabled} onChange={() => handleTogglePoc(p)}
                            label={`Watch ${p.name}${p.email ? ` (${p.email})` : ''}`} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </div>

          {/* Drafts waiting */}
          {drafts.length > 0 && (
            <div className="ah-panel" id="ah-drafts" tabIndex={-1} role="region" aria-label="Drafts waiting">
              <div className="ah-panel__head">
                <div className="ah-panel__title"><FileText size={13} aria-hidden="true" /> Drafts waiting</div>
                <span className="ah-panel__count">{drafts.length}</span>
              </div>
              <div className="ah-panel__body">
                {drafts.map(d => (
                  <div key={d.id} className="ah-draft">
                    <div style={{ minWidth: 0, flex: 1 }}>
                      <div className="ah-draft__name">
                        {d.vendor_name ?? 'Unknown vendor'}
                        {d.invoice_number && <span className="ah-poc__org"> · {d.invoice_number}</span>}
                        {d.source_channel === 'whatsapp' && (
                          <span style={{ marginLeft: 6 }}><Badge tone="success" icon={<MessageCircle size={11} />}>WhatsApp</Badge></span>
                        )}
                      </div>
                      <div className="ah-draft__sub" title={d.subject ?? ''}>{d.subject ?? d.from_email ?? '—'}</div>
                    </div>
                    {d.total_amount != null && (
                      <div className="ah-draft__amt">
                        {d.currency} {Number(d.total_amount).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                      </div>
                    )}
                    <Button size="sm" variant="primary" onClick={() => openDraft(d.id, d.source_file)} loading={opening === d.id}>
                      Review
                    </Button>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>

      {has('whatsapp_agent') && <section className="ah-panel" id="ah-whatsapp" tabIndex={-1} aria-label="WhatsApp Agent" style={{ marginTop: 'var(--sp-6, 24px)' }}>
        <div className="ah-panel__head">
          <div className="ah-panel__title"><MessageCircle size={13} aria-hidden="true" /> WhatsApp Agent · vendor invoices on WhatsApp</div>
        </div>
        <div className="ah-panel__body">
          <WhatsAppAgentPanel onOpenDraft={openDraft} status={waStatus} loadStatus={loadWaStatus} />
        </div>
      </section>}

      {showGraph && <FactGraphModal companyId={companyId} onClose={() => setShowGraph(false)} />}
    </div>
  )
}
