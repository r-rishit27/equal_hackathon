import { useCallback, useEffect, useRef, useState } from 'react'
import {
  MessageCircle, RefreshCw, FileText, XCircle, AlertTriangle, Clock, Copy, Send, RotateCcw, Link2, PauseCircle,
} from 'lucide-react'
import { useAuth } from '../../auth/AuthContext'
import { Badge, Button, ConfirmDialog, Modal, Switch, useToast, type BadgeTone } from '../../ui'
import {
  fetchWaStatus, fetchWaEvents, fetchWaContacts, connectWa, disconnectWa, updateWaSettings, refreshWa,
  retryWaJob, draftWaJobAnyway, setWaWatch, fetchWaConversation, sendWaReply, errorText,
  type WaStatus, type WaEvent, type WaContact, type WaMessage, type WaJob,
} from '../../api/whatsapp'

interface Props {
  /** Opens a draft in ReviewPage (same handler the email drafts use). */
  onOpenDraft: (draftId: string, sourceFile: string) => void
  /** Bumps when the parent wants a reload (e.g. after a draft was submitted). */
  reloadKey?: number
}

const STATE_META: Record<string, { label: string; tone: BadgeTone }> = {
  ACTIVE: { label: 'Active', tone: 'success' },
  AWAITING_TEST: { label: 'Awaiting test message', tone: 'warn' },
  PAUSED: { label: 'Paused', tone: 'neutral' },
  NEEDS_ATTENTION: { label: 'Needs attention', tone: 'danger' },
}

const OUTCOME_META: Record<string, { label: string; color: string; icon: React.ElementType }> = {
  QUEUED: { label: 'Queued', color: 'var(--info-600)', icon: Clock },
  PROCESSED: { label: 'Processed', color: 'var(--cat-4)', icon: FileText },
  TEXT_ONLY: { label: 'Text only', color: 'var(--ink-500)', icon: MessageCircle },
  UNWATCHED: { label: 'Skipped — not a watched contact', color: 'var(--ink-500)', icon: XCircle },
  UNSUPPORTED_MEDIA: { label: 'Skipped — not a PDF', color: 'var(--warn-600)', icon: XCircle },
  AMBIGUOUS_CONTACT: { label: 'Quarantined — ambiguous number', color: 'var(--danger-600)', icon: AlertTriangle },
  PAUSED: { label: 'Held — inbound paused', color: 'var(--warn-600)', icon: PauseCircle },
  LICENSE_INACTIVE: { label: 'Blocked — not licensed', color: 'var(--danger-600)', icon: XCircle },
}

const DECISION_META: Record<string, { label: string; tone: BadgeTone }> = {
  DRAFTED: { label: 'Draft created', tone: 'success' },
  CORRECTION: { label: 'Correction draft', tone: 'warn' },
  DUPLICATE: { label: 'Duplicate', tone: 'neutral' },
  NOT_A_BILL: { label: 'Not a bill', tone: 'neutral' },
  CONTRACT: { label: 'Saved as contract', tone: 'info' },
  LOW_CONFIDENCE: { label: 'Needs review', tone: 'warn' },
  UNREADABLE: { label: 'Unreadable', tone: 'danger' },
  SKIPPED: { label: 'Skipped', tone: 'neutral' },
  DISCARDED: { label: 'Discarded', tone: 'neutral' },
}

function timeAgo(iso: string | null): string {
  if (!iso) return 'never'
  const s = Math.floor((Date.now() - new Date(iso).getTime()) / 1000)
  if (s < 60) return `${Math.max(s, 0)}s ago`
  if (s < 3600) return `${Math.floor(s / 60)}m ago`
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`
  return new Date(iso).toLocaleDateString()
}

function jobBadge(j: WaJob) {
  if (j.state === 'DEAD') return { label: `Failed · ${j.failure_code ?? 'error'}`, tone: 'danger' as BadgeTone }
  if (j.state === 'RETRY_WAIT') return { label: `Retrying (${j.attempts})`, tone: 'warn' as BadgeTone }
  if (j.state === 'HELD') return { label: 'Held', tone: 'neutral' as BadgeTone }
  if (j.state === 'PENDING' || j.state === 'CLAIMED') return { label: 'Processing…', tone: 'info' as BadgeTone }
  return DECISION_META[j.decision ?? ''] ?? { label: j.decision ?? j.state, tone: 'neutral' as BadgeTone }
}

function newOpKey(): string {
  try { return crypto.randomUUID() } catch { return `${Date.now()}-${Math.random().toString(36).slice(2)}` }
}

export default function WhatsAppAgentPanel({ onOpenDraft, reloadKey }: Props) {
  const { user, activeBrand } = useAuth()
  const toast = useToast()
  const brandId = activeBrand?.id ?? null
  const isAdmin = user?.role === 'admin'

  const [status, setStatus] = useState<WaStatus | null>(null)
  const [events, setEvents] = useState<WaEvent[]>([])
  const [contacts, setContacts] = useState<WaContact[]>([])
  const [loadError, setLoadError] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [chat, setChat] = useState<WaContact | null>(null)
  const [confirmDisconnect, setConfirmDisconnect] = useState(false)
  const loadSeq = useRef(0)

  const load = useCallback(async () => {
    const seq = ++loadSeq.current
    try {
      const [s, e, c] = await Promise.all([fetchWaStatus(brandId), fetchWaEvents(brandId, 50), fetchWaContacts(brandId)])
      if (seq !== loadSeq.current) return // a newer load (e.g. brand switch) superseded this one
      setStatus(s); setEvents(e); setContacts(c); setLoadError(null)
    } catch (err) {
      if (seq !== loadSeq.current) return
      const code = (err as { response?: { status?: number } })?.response?.status
      setLoadError(code === 403 ? 'WhatsApp Agent is not enabled for this workspace.' : errorText(err, 'Could not load WhatsApp Agent.'))
    }
  }, [brandId])

  // Brand switch: clear stale rows first so one brand's data never shows under another.
  useEffect(() => { setEvents([]); setContacts([]); load() }, [load, reloadKey])
  useEffect(() => {
    const t = setInterval(() => { if (document.visibilityState === 'visible') load() }, 15000)
    return () => clearInterval(t)
  }, [load])

  const run = async (key: string, fn: () => Promise<unknown>, ok?: string, failTitle = 'Something went wrong') => {
    setBusy(key)
    try { await fn(); if (ok) toast.success(ok); await load() }
    catch (err) { toast.error(failTitle, errorText(err, 'Nothing changed. Try again.')) }
    finally { setBusy(null) }
  }

  const conn = status?.connection ?? null
  const stateMeta = conn ? (!conn.inbound_enabled ? STATE_META.PAUSED : STATE_META[conn.state]) : null

  const copy = (text: string) => {
    navigator.clipboard?.writeText(text).then(() => toast.success('Copied'), () => toast.error('Copy failed', text))
  }

  const toggleWatch = async (c: WaContact) => {
    const next = !c.watch_enabled
    setContacts(prev => prev.map(x => x.id === c.id ? { ...x, watch_enabled: next } : x))
    try { await setWaWatch(c.supplier_id, c.id, next, c.phone) ; load() }
    catch (err) {
      setContacts(prev => prev.map(x => x.id === c.id ? { ...x, watch_enabled: !next } : x))
      toast.error(`Could not ${next ? 'watch' : 'stop watching'} ${c.name}`, errorText(err, 'Nothing changed. Try again.'))
    }
  }

  if (loadError && !status) {
    return (
      <div className="ah-panel" style={{ padding: 'var(--sp-4)' }}>
        <div className="ah-empty">{loadError}</div>
      </div>
    )
  }

  const telemetry = [
    { key: 'Watched numbers', val: status?.watched_contacts ?? 0 },
    { key: 'Pending drafts', val: status?.pending_drafts ?? 0 },
    { key: 'Messages (24h)', val: status?.inbound_24h ?? 0 },
    { key: 'In queue', val: (status?.queue.queued ?? 0) + (status?.queue.held ?? 0) },
    { key: 'Failed jobs', val: status?.queue.dead ?? 0 },
    { key: 'Last message', val: timeAgo(conn?.last_inbound_at ?? null) },
  ]

  return (
    <>
      {/* ── Connection ─────────────────────────────────────────────────────── */}
      <div className="ah-panel" style={{ marginBottom: 'var(--sp-4)' }}>
        <div className="ah-panel__head">
          <div className="ah-panel__title"><MessageCircle size={13} aria-hidden="true" /> WhatsApp connection</div>
          {stateMeta && <Badge tone={stateMeta.tone}>{stateMeta.label}</Badge>}
        </div>
        <div className="ah-panel__body" style={{ padding: 'var(--sp-4)', display: 'grid', gap: 'var(--sp-3)' }}>
          {!conn && (
            <>
              <div style={{ fontSize: 13, color: 'var(--ink-600)' }}>
                Connect a Twilio WhatsApp sender. Vendors you watch below can then send PDF invoices on WhatsApp,
                and each one becomes a draft bill for review.
              </div>
              {isAdmin ? (
                <div>
                  <Button
                    variant="primary"
                    iconLeft={<Link2 size={14} />}
                    loading={busy === 'connect'}
                    disabled={!status?.server_credentials_available}
                    onClick={() => run('connect', () => connectWa({ use_server_credentials: true }),
                      'WhatsApp connected — send a test message to finish setup', 'Could not connect WhatsApp')}
                  >
                    Connect Twilio{status?.server_sender ? ` (${status.server_sender})` : ''}
                  </Button>
                  {!status?.server_credentials_available && (
                    <div style={{ fontSize: 12, color: 'var(--danger-600)', marginTop: 6 }}>
                      The server has no Twilio credentials. Set TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN and
                      TWILIO_WHATSAPP_FROM on the backend.
                    </div>
                  )}
                </div>
              ) : (
                <div style={{ fontSize: 12, color: 'var(--ink-500)' }}>Ask an admin to connect WhatsApp.</div>
              )}
            </>
          )}

          {conn && (
            <>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 'var(--sp-4)', fontSize: 13 }}>
                <span><b>Sender</b> {conn.sender}</span>
                <span><b>Account</b> {conn.account_sid}</span>
                <span><b>Last processed</b> {timeAgo(conn.last_processed_at)}</span>
                {conn.signature_failures > 0 && (
                  <span style={{ color: 'var(--danger-600)' }}><b>Rejected requests</b> {conn.signature_failures}</span>
                )}
              </div>

              <div style={{ display: 'grid', gap: 6 }}>
                <div style={{ fontSize: 12, color: 'var(--ink-500)' }}>
                  Twilio Console → Messaging → Try it out → WhatsApp sandbox settings → <b>When a message comes in</b> (POST):
                </div>
                <div style={{ display: 'flex', gap: 6, alignItems: 'center', minWidth: 0 }}>
                  <code style={{ flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontSize: 12, padding: '6px 8px', background: 'var(--ink-50, #f6f7f9)', borderRadius: 6 }}>
                    {conn.webhook_url}
                  </code>
                  <Button size="sm" variant="secondary" iconLeft={<Copy size={13} />} onClick={() => copy(conn.webhook_url)}>Copy</Button>
                </div>
                <div style={{ fontSize: 12, color: 'var(--ink-500)' }}><b>Status callback URL</b> (POST):</div>
                <div style={{ display: 'flex', gap: 6, alignItems: 'center', minWidth: 0 }}>
                  <code style={{ flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontSize: 12, padding: '6px 8px', background: 'var(--ink-50, #f6f7f9)', borderRadius: 6 }}>
                    {conn.status_callback_url}
                  </code>
                  <Button size="sm" variant="secondary" iconLeft={<Copy size={13} />} onClick={() => copy(conn.status_callback_url)}>Copy</Button>
                </div>
              </div>

              {conn.state === 'AWAITING_TEST' && (
                <div style={{ fontSize: 12, background: 'var(--warn-50, #fffbeb)', color: 'var(--warn-700, #92400e)', padding: 10, borderRadius: 8 }}>
                  <b>Finish setup:</b> paste the URL above into the Twilio sandbox settings, then from a phone that has
                  joined the sandbox send any message to {conn.sender}. This card turns <b>Active</b> once a signed message arrives.
                </div>
              )}

              {!status?.worker_enabled && (
                <div style={{ fontSize: 12, color: 'var(--danger-600)' }}>
                  The processing worker is disabled on this server (WA_WORKER_ENABLED=false). Messages are recorded but not processed.
                </div>
              )}

              {(status?.queue.held ?? 0) > 0 && conn.inbound_enabled && isAdmin && (
                <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap', fontSize: 12 }}>
                  <span>{status?.queue.held} attachment(s) arrived while paused (oldest {timeAgo(status?.queue.oldest_at ?? null)}).</span>
                  <Button size="sm" variant="primary" loading={busy === 'drain'}
                    onClick={() => run('drain', () => updateWaSettings({ backlog_action: 'drain' }), 'Backlog queued for processing')}>
                    Process them
                  </Button>
                  <Button size="sm" variant="ghost" loading={busy === 'discard'}
                    onClick={() => run('discard', () => updateWaSettings({ backlog_action: 'discard' }), 'Backlog discarded')}>
                    Discard
                  </Button>
                </div>
              )}

              {isAdmin && (
                <div style={{ display: 'flex', gap: 'var(--sp-4)', alignItems: 'center', flexWrap: 'wrap' }}>
                  <Switch
                    checked={conn.inbound_enabled}
                    showLabel
                    label="Process incoming invoices"
                    disabled={busy === 'inbound'}
                    onChange={v => run('inbound', () => updateWaSettings({ inbound_enabled: v }),
                      v ? 'Inbound resumed' : 'Inbound paused — new messages are held')}
                  />
                  <Switch
                    checked={conn.outbound_enabled}
                    showLabel
                    label="Allow replies to vendors"
                    disabled={busy === 'outbound'}
                    onChange={v => run('outbound', () => updateWaSettings({ outbound_enabled: v }),
                      v ? 'Replies enabled' : 'Replies paused')}
                  />
                  <span style={{ flex: 1 }} />
                  <Button size="sm" variant="danger" loading={busy === 'disconnect'}
                    onClick={() => setConfirmDisconnect(true)}>
                    Disconnect
                  </Button>
                </div>
              )}
            </>
          )}
        </div>
      </div>

      {/* ── Telemetry ──────────────────────────────────────────────────────── */}
      <div className="ah-tele">
        {telemetry.map(t => (
          <div key={t.key} className="ah-tele__cell">
            <div className="ah-tele__val">{t.val}</div>
            <div className="ah-tele__key">{t.key}</div>
          </div>
        ))}
      </div>

      <div className="ah-panels">
        {/* ── Activity ─────────────────────────────────────────────────────── */}
        <div className="ah-panel">
          <div className="ah-panel__head">
            <div className="ah-panel__title">WhatsApp activity</div>
            <Button size="sm" variant="ghost" loading={busy === 'refresh'}
              iconLeft={<RefreshCw size={13} />}
              onClick={() => run('refresh', async () => {
                const r = await refreshWa()
                if (r.throttled) toast.warn('Just refreshed', 'Try again in a few seconds.')
              })}>
              Refresh
            </Button>
          </div>
          <div className="ah-panel__body ah-panel__body--tall">
            {events.length === 0 && <div className="ah-empty">No WhatsApp messages yet.</div>}
            {events.map(ev => {
              const meta = OUTCOME_META[ev.outcome] ?? { label: ev.outcome, color: 'var(--ink-500)', icon: Clock }
              const Icon = meta.icon
              return (
                <div key={ev.id} className="ah-ev" style={{ alignItems: 'flex-start' }}>
                  <Icon size={15} color={meta.color} className="ah-ev__icon" aria-hidden="true" />
                  <div style={{ minWidth: 0, flex: 1 }}>
                    <div className="ah-ev__head">
                      <span className="ah-ev__action" style={{ color: meta.color }}>{meta.label}</span>
                      <span className="ah-ev__who"> · {ev.supplier_name ?? ev.sender ?? 'Unknown'}{ev.contact_name ? ` (${ev.contact_name})` : ''}</span>
                    </div>
                    {(ev.text || ev.reason) && (
                      <div className="ah-ev__sub" title={`${ev.text}${ev.reason ? ` — ${ev.reason}` : ''}`}>
                        {ev.text ? `“${ev.text}”` : ''}{ev.text && ev.reason ? ' — ' : ''}{ev.jobs.length === 0 ? ev.reason : ''}
                      </div>
                    )}
                    {ev.jobs.map(j => {
                      const b = jobBadge(j)
                      return (
                        <div key={j.id} style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 4, flexWrap: 'wrap' }}>
                          <Badge tone={b.tone}>PDF {j.index + 1}: {b.label}</Badge>
                          {j.detail && (
                            <span style={{ fontSize: 11, color: 'var(--ink-500)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: 320 }} title={j.detail}>
                              {j.detail}
                            </span>
                          )}
                          {j.draft_id && (j.decision === 'DRAFTED' || j.decision === 'CORRECTION') && (
                            <Button size="sm" variant="primary" onClick={() => onOpenDraft(j.draft_id!, `whatsapp-${j.draft_id}.pdf`)}>Review</Button>
                          )}
                          {(j.state === 'DEAD' || j.decision === 'UNREADABLE') && (
                            <Button size="sm" variant="secondary" iconLeft={<RotateCcw size={12} />} loading={busy === `retry-${j.id}`}
                              onClick={() => run(`retry-${j.id}`, () => retryWaJob(j.id), 'Queued for retry')}>Retry</Button>
                          )}
                          {(j.decision === 'LOW_CONFIDENCE' || j.decision === 'NOT_A_BILL') && (
                            <Button size="sm" variant="secondary" loading={busy === `force-${j.id}`}
                              onClick={() => run(`force-${j.id}`, () => draftWaJobAnyway(j.id), 'Drafting it as a bill')}>Draft anyway</Button>
                          )}
                        </div>
                      )
                    })}
                  </div>
                  <div className="ah-ev__time">{timeAgo(ev.received_at)}</div>
                </div>
              )
            })}
          </div>
        </div>

        {/* ── Contacts ─────────────────────────────────────────────────────── */}
        <div className="ah-panel">
          <div className="ah-panel__head">
            <div className="ah-panel__title">WhatsApp contacts</div>
            <span className="ah-panel__count">{contacts.filter(c => c.watch_enabled).length}/{contacts.length}</span>
          </div>
          <div className="ah-panel__body ah-panel__body--tall">
            {contacts.length === 0 && (
              <div className="ah-empty">No vendor contacts with a phone number. Add one on the vendor's contacts first.</div>
            )}
            {contacts.map(c => (
              <div key={c.id} className="ah-poc">
                <div style={{ minWidth: 0, flex: 1 }}>
                  <div className="ah-poc__name">
                    {c.name}{c.supplier_name && <span className="ah-poc__org"> · {c.supplier_name}</span>}
                  </div>
                  <div className="ah-poc__mail">
                    {c.phone ?? '—'}
                    {c.consent === 'OPTED_OUT' && <span style={{ color: 'var(--danger-600)' }}> · opted out</span>}
                    {c.watch_enabled && c.window_open && <span style={{ color: 'var(--cat-4)' }}> · reply window open</span>}
                  </div>
                </div>
                {c.watch_enabled && (
                  <Button size="sm" variant="ghost" iconLeft={<MessageCircle size={13} />} onClick={() => setChat(c)}>Chat</Button>
                )}
                <Switch checked={c.watch_enabled} onChange={() => toggleWatch(c)} label={`Watch ${c.name} on WhatsApp`} />
              </div>
            ))}
          </div>
        </div>
      </div>

      <ConfirmDialog
        open={confirmDisconnect}
        onCancel={() => setConfirmDisconnect(false)}
        onConfirm={async () => {
          setConfirmDisconnect(false)
          await run('disconnect', disconnectWa, 'WhatsApp disconnected', 'Could not disconnect')
        }}
        title="Disconnect WhatsApp?"
        description="Incoming WhatsApp messages will be rejected until you connect again. Drafts, history and contact watches are kept."
        confirmLabel="Disconnect"
        tone="danger"
      />

      {chat && (
        <ConversationModal
          contact={chat}
          outboundEnabled={!!conn?.outbound_enabled}
          onClose={() => { setChat(null); load() }}
          onOpenDraft={onOpenDraft}
        />
      )}
    </>
  )
}

function ConversationModal({ contact, outboundEnabled, onClose, onOpenDraft }: {
  contact: WaContact
  outboundEnabled: boolean
  onClose: () => void
  onOpenDraft: (draftId: string, sourceFile: string) => void
}) {
  const toast = useToast()
  const [messages, setMessages] = useState<WaMessage[] | null>(null)
  const [text, setText] = useState('')
  const [sending, setSending] = useState(false)
  const opKey = useRef(newOpKey())
  const endRef = useRef<HTMLDivElement>(null)

  const load = useCallback(async () => {
    try { setMessages(await fetchWaConversation(contact.supplier_id, contact.id)) }
    catch (err) { toast.error('Could not load conversation', errorText(err, '')); setMessages([]) }
  }, [contact.supplier_id, contact.id, toast])

  useEffect(() => { load() }, [load])
  useEffect(() => {
    const t = setInterval(load, 10000)
    return () => clearInterval(t)
  }, [load])
  useEffect(() => { endRef.current?.scrollIntoView({ block: 'end' }) }, [messages])

  const blocked = !outboundEnabled ? 'Replies are paused by an admin.'
    : contact.consent === 'OPTED_OUT' ? 'This vendor opted out (sent STOP).'
    : !contact.window_open ? 'Outside WhatsApp\'s 24-hour reply window — the vendor has to message first.'
    : null

  const send = async () => {
    if (!text.trim() || sending) return
    setSending(true)
    try {
      const r = await sendWaReply(contact.supplier_id, contact.id, text.trim(), opKey.current)
      if (r.status === 'FAILED') toast.error('WhatsApp did not accept the message', r.error ?? '')
      else if (r.status === 'UNKNOWN') toast.warn('Send result unknown', 'We are checking with Twilio — do not resend yet.')
      setText('')
      opKey.current = newOpKey()
      await load()
    } catch (err) {
      toast.error('Not sent', errorText(err, 'Try again.'))
    } finally { setSending(false) }
  }

  return (
    <Modal open onClose={onClose} size="lg" title={`WhatsApp · ${contact.name}`}
      description={`${contact.supplier_name ?? ''} · ${contact.phone ?? ''}`}
      footer={
        <div style={{ display: 'flex', gap: 8, width: '100%', alignItems: 'flex-end' }}>
          <textarea
            value={text}
            onChange={e => setText(e.target.value)}
            placeholder={blocked ?? 'Type a reply…'}
            disabled={!!blocked || sending}
            rows={2}
            maxLength={1600}
            style={{ flex: 1, resize: 'vertical', fontSize: 13, padding: 8, borderRadius: 8, border: '1px solid var(--ink-200, #e5e7eb)' }}
            onKeyDown={e => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) send() }}
          />
          <Button variant="primary" iconLeft={<Send size={14} />} loading={sending} disabled={!!blocked || !text.trim()} onClick={send}>
            Send
          </Button>
        </div>
      }
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8, maxHeight: 420, overflowY: 'auto', padding: 4 }}>
        {messages === null && <div className="ah-empty">Loading…</div>}
        {messages?.length === 0 && <div className="ah-empty">No messages yet.</div>}
        {messages?.map(m => {
          const out = m.direction === 'outbound'
          return (
            <div key={m.id} style={{ alignSelf: out ? 'flex-end' : 'flex-start', maxWidth: '78%' }}>
              <div style={{
                background: out ? 'var(--brand-50, #eef2ff)' : 'var(--ink-50, #f6f7f9)', borderRadius: 10, padding: '8px 10px',
                fontSize: 13, whiteSpace: 'pre-wrap', wordBreak: 'break-word',
              }}>
                {m.body || (m.num_media ? '' : '—')}
                {m.num_media > 0 && (
                  <div style={{ fontSize: 12, color: 'var(--ink-500)', marginTop: m.body ? 4 : 0 }}>📎 {m.num_media} attachment(s)</div>
                )}
                {m.jobs.filter(j => j.draft_id && (j.decision === 'DRAFTED' || j.decision === 'CORRECTION')).map(j => (
                  <button key={j.id} className="u-btn u-btn--ghost u-btn--sm" style={{ marginTop: 4 }}
                    onClick={() => { onClose(); onOpenDraft(j.draft_id!, `whatsapp-${j.draft_id}.pdf`) }}>
                    Review draft
                  </button>
                ))}
              </div>
              <div style={{ fontSize: 11, color: 'var(--ink-500)', textAlign: out ? 'right' : 'left', marginTop: 2 }}>
                {new Date(m.at).toLocaleString()}
                {out && m.status && ` · ${m.status.toLowerCase()}`}
                {out && m.sent_by && ` · ${m.sent_by}`}
                {m.error && <span style={{ color: 'var(--danger-600)' }}> · {m.error}</span>}
              </div>
            </div>
          )
        })}
        <div ref={endRef} />
      </div>
    </Modal>
  )
}
