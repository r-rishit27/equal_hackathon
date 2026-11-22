/** Plan status, plan list, review and decision (S-07, S-08, S-09, S-11). */
import { useEffect, useState } from 'react'
import { Badge, Button, Modal, type BadgeTone } from '../../ui'
import { api, ApiError } from './api'
import { rupees, shortDay, stamp } from './format'
import type { Me, Plan, PlanState } from './types'

const STATE_TONE: Record<PlanState, BadgeTone> = {
  draft: 'neutral',
  submitted: 'info',
  approved: 'success',
  returned: 'warn',
  withdrawn: 'neutral',
  superseded: 'neutral',
}

function lowest(p: Plan) {
  return `${rupees(p.baseline_metrics.minimum_closing_paise)} → ${rupees(p.metrics.minimum_closing_paise)}`
}

export default function PlansPanel({ me, reloadKey, onDecided }: { me: Me; reloadKey: number; onDecided: (m: string) => void }) {
  const [plans, setPlans] = useState<Plan[] | null>(null)
  const [error, setError] = useState('')
  const [open, setOpen] = useState<string | null>(null)
  const [showAll, setShowAll] = useState(false)

  useEffect(() => {
    let live = true
    api
      .plans()
      .then(p => live && setPlans(p))
      .catch((e: unknown) => live && setError(e instanceof ApiError ? e.message : 'Couldn’t load plans.'))
    return () => {
      live = false
    }
  }, [reloadKey])

  const waiting = plans?.filter(p => p.state === 'submitted') ?? []
  const approved = plans?.find(p => p.state === 'approved')
  const returned = plans?.filter(p => p.state === 'returned') ?? []

  return (
    <section className="cf-card cf-plans" aria-labelledby="cf-plans-title">
      <div className="cf-card__head">
        <h2 id="cf-plans-title">Plan</h2>
        {plans && plans.length > 0 && (
          <Button size="sm" variant="ghost" onClick={() => setShowAll(s => !s)}>
            {showAll ? 'Hide history' : `Plans & history (${plans.length})`}
          </Button>
        )}
      </div>
      {error && <p role="alert">{error}</p>}
      {plans && !waiting.length && (
        <p className="cf-muted">
          No plan awaiting decision. Last approved: {approved ? `${approved.scenario_name ?? 'plan'} (${shortDay(approved.updated_at)})` : '—'}
        </p>
      )}
      {[...waiting, ...(showAll ? (plans ?? []).filter(p => p.state !== 'submitted') : returned.slice(0, 1))].map(p => (
        <button key={p.id} type="button" className="cf-plan-row" onClick={() => setOpen(p.id)}>
          <Badge tone={STATE_TONE[p.state]}>{p.state.toUpperCase()}</Badge>
          <span className="cf-plan-row__name">
            {p.scenario_name ?? 'Plan'} · v{p.version}
          </span>
          <span className="cf-plan-row__meta">
            Lowest {lowest(p)} · by {p.submitted_by ?? p.created_by}
          </span>
        </button>
      ))}
      {open && (
        <PlanReview
          planId={open}
          me={me}
          onClose={() => setOpen(null)}
          onDecided={m => {
            setOpen(null)
            onDecided(m)
          }}
        />
      )}
    </section>
  )
}

function PlanReview({ planId, me, onClose, onDecided }: { planId: string; me: Me; onClose: () => void; onDecided: (m: string) => void }) {
  const [plan, setPlan] = useState<Plan | null>(null)
  const [error, setError] = useState('')
  const [decision, setDecision] = useState<'approve' | 'return' | null>(null)

  useEffect(() => {
    let live = true
    api
      .plan(planId)
      .then(p => live && setPlan(p))
      .catch((e: unknown) => live && setError(e instanceof ApiError ? e.message : 'Couldn’t load the plan.'))
    return () => {
      live = false
    }
  }, [planId])

  const canDecide = plan?.state === 'submitted' && me.can.approve
  const self = plan?.submitted_by === me.actor

  return (
    <Modal open onClose={onClose} title={plan ? `${plan.scenario_name ?? 'Cash plan'} · v${plan.version}` : 'Cash plan'} size="lg"
      footer={
        canDecide ? (
          <>
            <Button variant="secondary" onClick={() => setDecision('return')}>
              Return with note
            </Button>
            <Button onClick={() => setDecision('approve')} disabled={self} title={self ? 'You submitted this plan, so someone else needs to approve it.' : undefined}>
              Approve plan
            </Button>
          </>
        ) : (
          <Button variant="ghost" onClick={onClose}>
            Close
          </Button>
        )
      }>
      {error && <p role="alert">{error}</p>}
      {!plan && !error && <p role="status">Loading…</p>}
      {plan && (
        <div className="cf-review">
          <p>
            <Badge tone={STATE_TONE[plan.state]}>{plan.state.toUpperCase()}</Badge>{' '}
            Submitted by {plan.submitted_by ?? '—'}
            {plan.submitted_at ? ` · ${stamp(plan.submitted_at)}` : ''} · snapshot revision {plan.revision} ·{' '}
            {plan.view === 'expected' ? 'Expected' : plan.view === 'downside' ? 'Downside' : 'No new collections'} view
          </p>
          <dl className="cf-compare">
            <div>
              <dt>Lowest balance</dt>
              <dd>{lowest(plan)}</dd>
            </div>
            <div>
              <dt>Reserve breach</dt>
              <dd>
                {plan.baseline_metrics.first_reserve_breach_date ? shortDay(plan.baseline_metrics.first_reserve_breach_date) : 'none'} →{' '}
                {plan.metrics.first_reserve_breach_date ? shortDay(plan.metrics.first_reserve_breach_date) : 'none'}
              </dd>
            </div>
            <div>
              <dt>Closing</dt>
              <dd>
                {rupees(plan.baseline_metrics.closing_paise)} → {rupees(plan.metrics.closing_paise)}
              </dd>
            </div>
          </dl>
          <h3>Changes</h3>
          <ul className="cf-review__changes">
            {(plan.changes ?? []).map(c => (
              <li key={c.index}>
                <Badge tone={c.kind === 'decision' ? 'brand' : 'warn'}>{c.kind === 'decision' ? 'DECISION' : 'ASSUMPTION'}</Badge>{' '}
                <strong>{c.label ?? c.op}</strong>
                {c.amount_paise != null && ` · ${rupees(c.amount_paise)}`}
                {c.to_date && ` · ${c.from_date ? `${shortDay(c.from_date)} → ` : ''}${shortDay(c.to_date)}`}
                {c.window_latest && (
                  <span>
                    {' '}
                    · Agreed to {shortDay(c.window_latest)}
                    {c.evidence ? ` (${c.evidence})` : ''}
                  </span>
                )}
                {c.reason ? ` · ${c.reason}` : ''}
              </li>
            ))}
          </ul>
          {plan.note && (
            <p>
              <strong>Note:</strong> “{plan.note}”
            </p>
          )}
          {!!plan.decisions?.length && (
            <>
              <h3>Decisions</h3>
              <ul>
                {plan.decisions.map(d => (
                  <li key={d.id}>
                    {d.decision === 'approve' ? 'Approved' : 'Returned'} by {d.decided_by} · {stamp(d.decided_at)}
                    {d.note ? ` · “${d.note}”` : ''} · validated on revision {d.validated_on_revision}
                  </li>
                ))}
              </ul>
            </>
          )}
          <p className="cf-notice">
            Approving records these payment dates for future forecasts. Payments still go through Payment Hub with its usual
            approvals and OTP.
          </p>
        </div>
      )}
      {decision && plan && (
        <DecisionDialog plan={plan} decision={decision} onClose={() => setDecision(null)} onDone={onDecided} />
      )}
    </Modal>
  )
}

export function DecisionDialog({
  plan,
  decision,
  onClose,
  onDone,
}: {
  plan: Plan
  decision: 'approve' | 'return'
  onClose: () => void
  onDone: (m: string) => void
}) {
  // One key per dialog: a retried click replays the same decision instead of making a second.
  const [key] = useState(() => (globalThis.crypto?.randomUUID ? globalThis.crypto.randomUUID() : `cf-${Date.now()}-${Math.random()}`))
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<ApiError | null>(null)

  const submit = async () => {
    if (decision === 'return' && !note.trim()) {
      setError(new ApiError(422, 'VALIDATION_ERROR', 'Say what needs to change when returning a plan.'))
      return
    }
    setBusy(true)
    setError(null)
    try {
      await api.decide(plan.id, decision, plan.version, note.trim(), key)
      onDone(decision === 'approve' ? 'Plan approved. Its payment dates apply from the next refresh.' : 'Plan returned to the accountant.')
    } catch (e) {
      setError(e instanceof ApiError ? e : new ApiError(0, 'ERROR', 'Couldn’t record the decision.'))
    } finally {
      setBusy(false)
    }
  }

  const stale = error?.code === 'PLAN_STALE'
  const submitted = (error?.details?.submitted ?? null) as Record<string, number | string | null> | null
  const now = (error?.details?.now ?? null) as Record<string, number | string | null> | null

  return (
    <Modal open onClose={onClose} title={stale ? 'Things changed since this plan was submitted' : decision === 'approve' ? 'Approve plan' : 'Return plan'}
      closeOnBackdrop={false}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          {stale ? (
            <Button variant="secondary" loading={busy} onClick={async () => {
              setBusy(true)
              try {
                await api.decide(plan.id, 'return', plan.version, 'Inputs changed since submission; please re-check and resubmit.', crypto.randomUUID())
                onDone('Plan returned to the accountant.')
              } catch (e) {
                setError(e instanceof ApiError ? e : null)
              } finally {
                setBusy(false)
              }
            }}>
              Return to accountant
            </Button>
          ) : (
            <Button variant={decision === 'approve' ? 'primary' : 'secondary'} loading={busy} onClick={submit}>
              {decision === 'approve' ? 'Approve' : 'Return'}
            </Button>
          )}
        </>
      }>
      {stale ? (
        <div>
          <p>The forecast moved from revision {String(error?.details?.revision_submitted)} to {String(error?.details?.revision_now)}.</p>
          {submitted && now && (
            <ul>
              <li>
                Lowest balance: submitted {rupees(Number(submitted.minimum_closing_paise))}, now {rupees(Number(now.minimum_closing_paise))}
              </li>
              <li>
                Closing: submitted {rupees(Number(submitted.closing_paise))}, now {rupees(Number(now.closing_paise))}
              </li>
            </ul>
          )}
          {Array.isArray(error?.details?.refusals) &&
            (error!.details.refusals as { message: string }[]).map((r, i) => <p key={i}>• {r.message}</p>)}
        </div>
      ) : (
        <>
          <label className="cf-field">
            {decision === 'return' ? 'What needs to change (required)' : 'Note (optional)'}
            <textarea rows={3} value={note} maxLength={2000} onChange={e => setNote(e.target.value)} />
          </label>
          {error && <p role="alert" className="cf-error">{error.message}</p>}
        </>
      )}
    </Modal>
  )
}
