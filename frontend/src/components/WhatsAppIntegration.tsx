import { useCallback, useEffect, useState } from 'react'
import { ChevronDown, Copy, MessageCircle } from 'lucide-react'
import { connectWa, disconnectWa, errorText, fetchWaStatus, updateWaSettings, type WaStatus } from '../api/whatsapp'
import { Badge, Button, ConfirmDialog, Switch, useToast } from '../ui'
import './WhatsAppIntegration.css'

const stateLabels = { ACTIVE: 'Active', AWAITING_TEST: 'Awaiting test message', NEEDS_ATTENTION: 'Needs attention', PAUSED: 'Paused', DISCONNECTED: 'Disconnected' }

export default function WhatsAppIntegration({ brandId }: { brandId?: string }) {
  const [status, setStatus] = useState<WaStatus | null>(null)
  const [expanded, setExpanded] = useState(() => window.location.hash === '#whatsapp')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [confirm, setConfirm] = useState(false)
  const toast = useToast()
  const load = useCallback(async () => {
    try { setStatus(await fetchWaStatus(brandId)); setError('') }
    catch (err) { setError(errorText(err, 'Could not load the WhatsApp connection.')) }
  }, [brandId])
  useEffect(() => { void load() }, [load])
  useEffect(() => {
    if (window.location.hash === '#whatsapp') document.getElementById('whatsapp')?.scrollIntoView?.()
  }, [])
  const conn = status?.connection
  useEffect(() => {
    if (conn?.state !== 'AWAITING_TEST' || busy) return
    const timer = window.setInterval(load, 15000)
    return () => window.clearInterval(timer)
  }, [conn?.state, load, busy])
  async function save(action: () => Promise<unknown>) {
    setBusy(true)
    try { await action(); await load() }
    catch (err) { setError(errorText(err, 'Could not update the WhatsApp connection.')) }
    finally { setBusy(false) }
  }
  return <section id="whatsapp" className="wa-integration" aria-labelledby="wa-title">
    <header><h2 id="wa-title"><button className="wa-expand" type="button" aria-expanded={expanded}
      aria-controls="wa-details" onClick={() => setExpanded(value => !value)}>
      <MessageCircle size={20} />WhatsApp (Twilio)<ChevronDown size={16} /></button></h2>
      {status && <Badge tone={conn?.state === 'ACTIVE' ? 'success' : 'neutral'}>{conn ? stateLabels[conn.state] : 'Not connected'}</Badge>}
    </header>
    <div id="wa-details" className="wa-details" hidden={!expanded}>
    {error && <div role="alert">{error} <Button size="sm" onClick={load}>Retry</Button></div>}
    {!status && !error && <p>Loading connection…</p>}
    {status && !conn && <>
      <p>Connect a WhatsApp sender to receive vendor invoices.</p>
      {status.server_credentials_available && <Button disabled={busy} onClick={() => save(() => connectWa({ use_server_credentials: true }))}>Use configured sender {status.server_sender}</Button>}
      <form onSubmit={event => {
        event.preventDefault()
        const form = event.currentTarget
        const fields = new FormData(form)
        void save(async () => {
          await connectWa({ use_server_credentials: false, account_sid: String(fields.get('sid')).trim(),
            auth_token: String(fields.get('token')).trim(), sender: String(fields.get('sender')).trim() })
          form.reset()
        })
      }}>
        <label>Account SID<input name="sid" required autoComplete="off" /></label>
        <label>Auth token<input name="token" required type="password" autoComplete="new-password" /></label>
        <label>WhatsApp sender<input name="sender" required type="tel" placeholder="+14155550123" /></label>
        <Button type="submit" disabled={busy}>Connect Twilio</Button>
      </form>
    </>}
    {conn && <>
      <p><strong>Sender</strong> {conn.sender}　 <strong>Account</strong> {conn.account_sid} <strong>Last processed</strong> {conn.last_processed_at ? new Date(conn.last_processed_at).toLocaleString() : 'Never'}</p>
      {conn.signature_failures > 0 && <p>Rejected requests: {conn.signature_failures}</p>}
      {conn.state === 'AWAITING_TEST' && <p>Set the inbound webhook in Twilio, then send a test message from a joined phone to verify the connection.</p>}
      {!status?.worker_enabled && <p>The processing worker is disabled. Incoming messages are recorded.</p>}
      {([['Inbound webhook (POST)', conn.webhook_url], ['Status callback (POST)', conn.status_callback_url]] as const).map(([label, url]) =>
        <div key={label}><strong>{label}</strong><div className="wa-url"><code>{url}</code>
          <Button size="sm" aria-label={'Copy ' + label} iconLeft={<Copy size={14} />} onClick={async () => {
            try { await navigator.clipboard.writeText(url); toast.success('Copied') } catch { toast.error('Copy failed') }
          }}>Copy</Button></div></div>)}
      <footer><span className="wa-intake"><Switch checked={conn.inbound_enabled} label="Process incoming invoices" disabled={busy}
        onChange={enabled => save(() => updateWaSettings({ inbound_enabled: enabled }))} /> Process incoming invoices</span>
        <Switch checked={conn.outbound_enabled} label="Allow replies to vendors" showLabel disabled={busy}
        onChange={enabled => save(() => updateWaSettings({ outbound_enabled: enabled }))} />
        <Button size="sm" variant="danger" disabled={busy} onClick={() => setConfirm(true)}>Disconnect</Button></footer>
    </>}
    </div>
    <ConfirmDialog open={confirm} onCancel={() => setConfirm(false)} onConfirm={() => { setConfirm(false); void save(disconnectWa) }}
      title="Disconnect WhatsApp?" description="Incoming messages will be rejected until you reconnect. Drafts, history and contact watches are kept." confirmLabel="Disconnect" tone="danger" />
  </section>
}
