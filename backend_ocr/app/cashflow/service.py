"""Use cases behind the cash forecast API: build, read, preview, scenarios, plans.

Routers stay thin; every function here takes the already-authenticated tenant
and actor. Errors are raised as `CFError` with a stable code
(docs/cashflow-forecast/04_LLD.md §10).
"""

from __future__ import annotations

import hashlib
import json
import logging
from contextlib import contextmanager
from datetime import date, datetime
from zoneinfo import ZoneInfo

from psycopg2 import errors as pg_errors
from psycopg2.extras import Json, RealDictCursor
from pydantic import TypeAdapter

from ..config import get_conn, put_conn
from . import engine, repo, scenario as sc
from .calendar import BusinessCalendar
from .rules import NoOpeningBalance, Settings, assemble
from .sources import fixture_today, load_books_fixture, load_books_live, load_inputs, uses_fixture
from .types import VIEWS, Snapshot, jsonable

log = logging.getLogger(__name__)
OVERRIDES = TypeAdapter(list[sc.Override])


class CFError(Exception):
    def __init__(self, status: int, code: str, message: str, details: dict | None = None):
        super().__init__(message)
        self.status, self.code, self.message, self.details = status, code, message, details or {}


@contextmanager
def cursor():
    conn = get_conn()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            yield conn, cur
    except Exception:
        conn.rollback()
        raise
    finally:
        put_conn(conn)


def _settings(cur, tenant) -> Settings:
    row = repo.get_settings_row(cur, tenant)
    cur.execute("SELECT holiday_date, name FROM cf_holidays WHERE tenant_id = %s", (tenant,))
    return Settings.from_row(dict(row) if row else None, {r["holiday_date"]: r["name"] for r in cur.fetchall()})


def today_for(tenant, settings: Settings) -> date:
    return fixture_today() if uses_fixture(tenant) else datetime.now(ZoneInfo(settings.timezone)).date()


def calendar_for(settings: Settings) -> BusinessCalendar:
    return BusinessCalendar(settings.holidays)


# ── Build ───────────────────────────────────────────────────────────────────
def build(tenant: str, actor: str, reason: str = "manual") -> tuple[Snapshot, bool]:
    with cursor() as (conn, cur):
        cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        if uses_fixture(tenant):
            data = load_books_fixture()
        else:
            settings_probe = _settings(cur, tenant)
            data = load_books_live(cur, tenant, settings_probe.timezone)
        settings = load_inputs(cur, tenant, data)
        conn.rollback()                                    # end the read-only snapshot
        try:
            snap = assemble(data, settings, today_for(tenant, settings), tenant)
        except NoOpeningBalance as exc:
            raise CFError(422, "NO_OPENING_BALANCE", "Add today's bank balance to see your forecast.") from exc
        sid, revision, changed = repo.insert_snapshot(cur, snap, reason, actor)
        if changed and settings.publish_daily and not uses_fixture(tenant):
            persisted = repo.load_snapshot(cur, tenant, sid)
            _publish(cur, persisted, calendar_for(settings))
        conn.commit()
        return repo.load_snapshot(cur, tenant, sid), changed


def _publish(cur, snap: Snapshot, cal):
    """Upsert the expected view into fact_cashflow_daily (Copilot, Reports). Never touches actuals."""
    result = engine.project(snap, "expected", calendar=cal)
    ar = sum(e.amount_paise for e in snap.events if e.source_type == "ar_invoice") / 100
    ap = sum(e.amount_paise for e in snap.events if e.source_type in ("bill", "schedule", "disbursement")) / 100
    try:
        cur.execute("SAVEPOINT cf_publish")
        for d in result.days:
            cur.execute("""
                INSERT INTO fact_cashflow_daily (cashflow_id, tenant_id, cashflow_date, currency_code, inflows_actual,
                    outflows_actual, inflows_forecast, outflows_forecast, opening_balance, closing_balance,
                    ar_outstanding, ap_outstanding, updated_at)
                VALUES (gen_random_uuid(), %s, %s, 'INR', 0, 0, %s, %s, %s, %s, %s, %s, now())
                ON CONFLICT (tenant_id, cashflow_date, currency_code) DO UPDATE SET
                    inflows_forecast = EXCLUDED.inflows_forecast, outflows_forecast = EXCLUDED.outflows_forecast,
                    opening_balance = EXCLUDED.opening_balance, closing_balance = EXCLUDED.closing_balance,
                    ar_outstanding = EXCLUDED.ar_outstanding, ap_outstanding = EXCLUDED.ap_outstanding,
                    updated_at = now()""",
                        (snap.tenant_id, d.date, d.inflow_paise / 100, d.outflow_paise / 100, d.opening_paise / 100,
                         d.closing_paise / 100, ar, ap))
        cur.execute("RELEASE SAVEPOINT cf_publish")
    except Exception as exc:                                # missing key or legacy duplicates: skip, don't fail
        cur.execute("ROLLBACK TO SAVEPOINT cf_publish")
        log.warning("cash forecast publish skipped for tenant %s: %s", snap.tenant_id, type(exc).__name__)


def latest(tenant: str, actor: str, build_if_missing: bool = True) -> Snapshot:
    with cursor() as (conn, cur):
        ref = repo.latest_ref(cur, tenant)
        if ref:
            snap = repo.load_snapshot(cur, tenant, ref["id"])
            conn.rollback()
            return snap
        conn.rollback()
    if not build_if_missing:
        raise CFError(404, "NO_SNAPSHOT", "No forecast has been built yet.")
    return build(tenant, actor, "manual")[0]


def snapshot(tenant: str, snapshot_id: str) -> Snapshot:
    with cursor() as (conn, cur):
        snap = repo.load_snapshot(cur, tenant, snapshot_id)
        conn.rollback()
    if snap is None:
        raise CFError(404, "NOT_FOUND", "Forecast not found.")
    return snap


def settings(tenant: str) -> Settings:
    with cursor() as (conn, cur):
        s = _settings(cur, tenant)
        conn.rollback()
        return s


def freshness_now(snap: Snapshot, s: Settings, tenant: str) -> dict:
    """Balance age is re-evaluated at read time; a snapshot doesn't get fresher by being re-read."""
    cal = calendar_for(s)
    today = today_for(tenant, s)
    tz = ZoneInfo(s.timezone)
    out = {}
    for b in snap.balances:
        age = cal.banking_days_between(b.as_of.astimezone(tz).date(), today)
        out[b.bank_account_id] = "fresh" if age <= 1 else "stale" if age <= 3 else "expired"
    return out


# ── Serialisers ─────────────────────────────────────────────────────────────
def snapshot_ref(snap: Snapshot, s: Settings, tenant: str, changed: bool | None = None) -> dict:
    fresh = freshness_now(snap, s, tenant)
    return {
        "snapshot_id": snap.snapshot_id, "revision": snap.revision, "as_of": snap.as_of.isoformat(),
        "start": snap.start.isoformat(), "end": snap.end.isoformat(), "horizon_days": snap.horizon_days,
        "reserve_paise": snap.reserve_paise, "od_headroom_paise": snap.od_headroom_paise,
        "content_hash": snap.content_hash, "changed": changed, "coverage": snap.coverage,
        "is_fixture": uses_fixture(tenant), "today": today_for(tenant, s).isoformat(),
        "balances": [dict(jsonable(b), freshness=fresh.get(b.bank_account_id, b.freshness)) for b in snap.balances],
    }


def result_json(result) -> dict:
    return {"view": result.view, "opening_paise": result.opening_paise, "reserve_paise": result.reserve_paise,
            "days": jsonable(result.days), "metrics": jsonable(result.metrics), "category_totals": result.category_totals}


def event_json(e, view, moved=False) -> dict:
    d = e.dates.get(view)
    return {"event_key": e.event_key, "source_type": e.source_type, "source_id": e.source_id, "label": e.label,
            "counterparty": e.counterparty, "counterparty_id": e.counterparty_id, "document_number": e.document_number,
            "direction": e.direction, "amount_paise": e.amount_paise, "category": e.category, "confidence": e.confidence,
            "date": d.isoformat() if d else None, "date_basis": e.date_basis.get(view, ""), "tds_note": e.date_basis.get("tds"),
            "nominal_date": e.nominal_date.isoformat() if e.nominal_date else None,
            "window": jsonable(e.window) if e.window else None, "fixed": e.fixed, "link_path": e.link_path,
            "moved_by_scenario": moved}


# ── Forecast and preview ────────────────────────────────────────────────────
def _check_view(view):
    if view not in VIEWS:
        raise CFError(422, "VALIDATION_ERROR", "Unknown view.", {"view": view})


def forecast(tenant: str, snapshot_id: str, view: str) -> dict:
    _check_view(view)
    snap, s = snapshot(tenant, snapshot_id), settings(tenant)
    return dict(result_json(engine.project(snap, view, calendar=calendar_for(s))), snapshot=snapshot_ref(snap, s, tenant))


def _scenario_events(snap, overrides, view, cal):
    refusals = sc.validate(snap, overrides, view, cal)
    if refusals:
        n = len(refusals)
        raise CFError(422, "OVERRIDE_REFUSED", f"{n} change{'s' if n > 1 else ''} can't be applied.", {"refusals": refusals})
    return sc.apply(snap, overrides, view, cal)


def preview(tenant: str, snapshot_id: str, revision: int, view: str, overrides) -> dict:
    _check_view(view)
    snap, s = snapshot(tenant, snapshot_id), settings(tenant)
    if snap.revision != revision:
        raise CFError(422, "SNAPSHOT_REVISION_MISMATCH", "The forecast changed. Reload and try again.")
    cal = calendar_for(s)
    base = engine.project(snap, view, calendar=cal)
    events, applied = _scenario_events(snap, overrides, view, cal)
    scen = engine.project(snap, view, events, cal)
    return {"baseline": result_json(base), "scenario": result_json(scen), "delta": jsonable(engine.delta(base, scen)),
            "applied": applied}


def day_detail(tenant: str, snapshot_id: str, view: str, day: date, overrides=()) -> dict:
    _check_view(view)
    snap, s = snapshot(tenant, snapshot_id), settings(tenant)
    cal = calendar_for(s)
    events, moved = list(snap.events), set()
    if overrides:
        events, applied = _scenario_events(snap, overrides, view, cal)
        moved = {k for a in applied for k in a["affected_event_keys"]}
    result = engine.project(snap, view, events, cal)
    row = next((r for r in result.days if r.date == day), None)
    if row is None:
        raise CFError(404, "NOT_FOUND", "That date is outside the forecast.")
    todays = [e for e in result.events if e.effective_date(view) == day]
    todays.sort(key=lambda e: -e.amount_paise)
    return {"day": jsonable(row),
            "inflows": [event_json(e, view, e.event_key in moved) for e in todays if e.direction == "in"],
            "outflows": [event_json(e, view, e.event_key in moved) for e in todays if e.direction == "out"]}


def events_list(tenant: str, snapshot_id: str, view: str) -> list[dict]:
    snap = snapshot(tenant, snapshot_id)
    return [event_json(e, view) for e in sorted(snap.events, key=lambda e: (e.dates.get(view) or date.max, -e.amount_paise))
            if e.in_view(view)]


def exclusions(tenant: str, snapshot_id: str) -> list[dict]:
    return [jsonable(x) for x in snapshot(tenant, snapshot_id).exclusions]


# ── Scenarios ───────────────────────────────────────────────────────────────
def _dump(overrides) -> list:
    return [o.model_dump(mode="json", exclude_none=True) for o in overrides]


def _rebase(latest_snap: Snapshot, overrides, view, cal) -> list[dict]:
    out = []
    for i, o in enumerate(overrides):
        refusals = sc.validate(latest_snap, [o], view, cal)
        if not refusals:
            out.append({"index": i, "status": "ok"})
        elif refusals[0]["code"] == "EVENT_NOT_FOUND":
            out.append({"index": i, "status": "target_gone", "message": refusals[0]["message"]})
        else:
            out.append({"index": i, "status": "now_invalid", "code": refusals[0]["code"], "message": refusals[0]["message"]})
    return out


def scenario_json(row, latest_snap=None, cal=None) -> dict:
    out = {k: (v.isoformat() if isinstance(v, (date, datetime)) else v) for k, v in row.items()}
    if latest_snap is not None and latest_snap.revision != row["revision"]:
        rebase = _rebase(latest_snap, OVERRIDES.validate_python(row["overrides"]), row["view"], cal)
        out["rebase"] = {"revision": latest_snap.revision, "snapshot_id": latest_snap.snapshot_id, "items": rebase}
        out["status"] = "needs_review" if any(r["status"] != "ok" for r in rebase) else "ok"
    return out


SCEN_COLS = """id::text, name, description, snapshot_id::text, revision, view, overrides, status, version, created_by,
               created_at, updated_at"""


def list_scenarios(tenant: str, actor: str) -> list[dict]:
    with cursor() as (conn, cur):
        cur.execute(f"SELECT {SCEN_COLS} FROM cf_scenarios WHERE tenant_id = %s AND NOT archived ORDER BY updated_at DESC",
                    (tenant,))
        rows = cur.fetchall()
        conn.rollback()
    return [scenario_json(r) for r in rows]


def get_scenario(tenant: str, scenario_id: str) -> dict:
    with cursor() as (conn, cur):
        cur.execute(f"SELECT {SCEN_COLS} FROM cf_scenarios WHERE tenant_id = %s AND id = %s AND NOT archived",
                    (tenant, scenario_id))
        row = cur.fetchone()
        ref = repo.latest_ref(cur, tenant)
        latest_snap = repo.load_snapshot(cur, tenant, ref["id"]) if ref else None
        s = _settings(cur, tenant)
        conn.rollback()
    if not row:
        raise CFError(404, "NOT_FOUND", "Scenario not found.")
    return scenario_json(row, latest_snap, calendar_for(s))


def save_scenario(tenant, actor, body, scenario_id=None, expected_version=None) -> dict:
    snap, s = snapshot(tenant, body["snapshot_id"]), settings(tenant)
    _scenario_events(snap, body["overrides"], body["view"], calendar_for(s))       # refuse invalid scenarios
    with cursor() as (conn, cur):
        if scenario_id is None:
            cur.execute(f"""INSERT INTO cf_scenarios (tenant_id, name, description, snapshot_id, revision, view, overrides,
                                created_by) VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING {SCEN_COLS}""",
                        (tenant, body["name"], body.get("description"), snap.snapshot_id, snap.revision, body["view"],
                         Json(_dump(body["overrides"])), actor))
            action = "create"
        else:
            cur.execute(f"""UPDATE cf_scenarios SET name = %s, description = %s, snapshot_id = %s, revision = %s, view = %s,
                                overrides = %s, status = 'ok', version = version + 1, updated_at = now()
                            WHERE tenant_id = %s AND id = %s AND NOT archived AND version = %s RETURNING {SCEN_COLS}""",
                        (body["name"], body.get("description"), snap.snapshot_id, snap.revision, body["view"],
                         Json(_dump(body["overrides"])), tenant, scenario_id, expected_version))
            action = "update"
        row = cur.fetchone()
        if not row:
            conn.rollback()
            raise CFError(409, "VERSION_CONFLICT", "Someone else changed this scenario. Reload it.")
        repo.audit(cur, tenant, "scenario", row["id"], action, actor, after={"name": row["name"], "overrides": row["overrides"]})
        conn.commit()
    return scenario_json(row)


def archive_scenario(tenant, actor, scenario_id):
    with cursor() as (conn, cur):
        cur.execute("UPDATE cf_scenarios SET archived = true, updated_at = now() WHERE tenant_id = %s AND id = %s RETURNING id",
                    (tenant, scenario_id))
        if not cur.fetchone():
            conn.rollback()
            raise CFError(404, "NOT_FOUND", "Scenario not found.")
        repo.audit(cur, tenant, "scenario", scenario_id, "archive", actor)
        conn.commit()


# ── Plans ───────────────────────────────────────────────────────────────────
def _canonical(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def _guard_inputs(snap: Snapshot, s: Settings, tenant: str):
    fresh = freshness_now(snap, s, tenant)
    if any(v == "expired" for v in fresh.values()):
        raise CFError(409, "BALANCE_EXPIRED", "Update bank balances first. They're over 3 banking days old.")
    if snap.coverage.get("state") == "partial":
        raise CFError(409, "COVERAGE_PARTIAL", "Some sources couldn't be read, so plans can't be submitted or approved.",
                      {"failed_sources": snap.coverage.get("failed_sources"),
                       "missing_balances": snap.coverage.get("missing_balances")})


def plan_json(row, extra=None) -> dict:
    out = {k: (v.isoformat() if isinstance(v, (date, datetime)) else v) for k, v in row.items()}
    out.update(extra or {})
    return out


def create_plan(tenant, actor, scenario_id, note, submit) -> dict:
    scen = get_scenario(tenant, scenario_id)
    if scen.get("rebase"):
        raise CFError(409, "PLAN_STALE", "The forecast changed since this scenario was saved. Open it again and re-save.",
                      {"rebase": scen["rebase"]})
    snap, s = snapshot(tenant, scen["snapshot_id"]), settings(tenant)
    if submit:
        _guard_inputs(snap, s, tenant)
        if not (note or "").strip():
            raise CFError(422, "VALIDATION_ERROR", "Add a note for the approver.")
    cal = calendar_for(s)
    overrides = OVERRIDES.validate_python(scen["overrides"])
    base = engine.project(snap, scen["view"], calendar=cal)
    events, _ = _scenario_events(snap, overrides, scen["view"], cal)
    result = engine.project(snap, scen["view"], events, cal)
    with cursor() as (conn, cur):
        cur.execute(f"""
            INSERT INTO cf_plans (tenant_id, scenario_id, version, state, snapshot_id, revision, view, overrides,
                                  overrides_hash, metrics, baseline_metrics, note, submitted_by, submitted_at, created_by)
            VALUES (%s, %s, 1, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING {repo.PLAN_COLS}""",
                    (tenant, scenario_id, "submitted" if submit else "draft", snap.snapshot_id, snap.revision, scen["view"],
                     Json(scen["overrides"]), _canonical(scen["overrides"]), Json(jsonable(result.metrics)),
                     Json(jsonable(base.metrics)), note, actor if submit else None,
                     datetime.now(ZoneInfo("UTC")) if submit else None, actor))
        row = cur.fetchone()
        repo.audit(cur, tenant, "plan", row["id"], "submit" if submit else "create", actor,
                   after={"version": 1, "metrics": row["metrics"], "note": note})
        conn.commit()
    return plan_json(row)


def get_plan(tenant, plan_id) -> dict:
    with cursor() as (conn, cur):
        row = repo.get_plan(cur, tenant, plan_id)
        if not row:
            conn.rollback()
            raise CFError(404, "NOT_FOUND", "Plan not found.")
        extra = {"decisions": [plan_json(d) for d in repo.decisions_for(cur, tenant, plan_id)],
                 "history": [plan_json(h) for h in repo.history_for(cur, tenant, "plan", plan_id)]}
        cur.execute("SELECT name FROM cf_scenarios WHERE tenant_id = %s AND id = %s", (tenant, row["scenario_id"]))
        sc_row = cur.fetchone()
        extra["scenario_name"] = sc_row["name"] if sc_row else None
        snap = repo.load_snapshot(cur, tenant, row["snapshot_id"])
        conn.rollback()
    extra["changes"] = _describe(snap, row["overrides"], row["view"]) if snap else []
    return plan_json(row, extra)


def _describe(snap: Snapshot, overrides, view) -> list[dict]:
    """What each change refers to, in the words an approver needs (label, amount, from → to, agreement)."""
    out = []
    for i, o in enumerate(OVERRIDES.validate_python(overrides)):
        item = {"index": i, "op": o.op, "kind": sc.kind(o, snap), "reason": o.reason}
        e = snap.event(getattr(o, "event_key", "")) if hasattr(o, "event_key") else None
        if e is not None:
            item.update(label=e.label, amount_paise=e.amount_paise, direction=e.direction, link_path=e.link_path,
                        from_date=(e.dates.get(view) or e.nominal_date).isoformat() if (e.dates.get(view) or e.nominal_date) else None)
            if e.window:
                item.update(window_latest=e.window.latest.isoformat(), agreed_with=e.window.agreed_with,
                            evidence=e.window.evidence)
        if isinstance(o, sc.ShiftEvent):
            item["to_date"] = o.to_date.isoformat()
        elif isinstance(o, sc.AddItem):
            item.update(label=o.label, amount_paise=o.amount_paise, direction=o.direction, to_date=o.on_date.isoformat())
        elif isinstance(o, sc.DelayCustomer):
            name = next((x.counterparty for x in snap.events if x.counterparty_id == o.customer_id), o.customer_id)
            item.update(label=f"{name}: all receipts {o.days} days later")
        elif isinstance(o, sc.HaircutCustomer):
            name = "every customer" if o.customer_id == "*" else next(
                (x.counterparty for x in snap.events if x.counterparty_id == o.customer_id), o.customer_id)
            item.update(label=f"Collect only {100 - o.percent}% from {name}")
        out.append(item)
    return out


def list_plans(tenant, state=None) -> list[dict]:
    with cursor() as (conn, cur):
        rows = repo.list_plans(cur, tenant, state)
        cur.execute("SELECT id::text, name FROM cf_scenarios WHERE tenant_id = %s", (tenant,))
        names = {r["id"]: r["name"] for r in cur.fetchall()}
        conn.rollback()
    return [plan_json(r, {"scenario_name": names.get(r["scenario_id"])}) for r in rows]


def transition(tenant, actor, plan_id, expected_version, to_state):
    """submit (draft/returned/withdrawn → submitted) or withdraw (submitted → withdrawn)."""
    with cursor() as (conn, cur):
        row = repo.get_plan(cur, tenant, plan_id, for_update=True)
        if not row:
            conn.rollback()
            raise CFError(404, "NOT_FOUND", "Plan not found.")
        if row["version"] != expected_version:
            conn.rollback()
            raise CFError(409, "PLAN_STATE", "This plan changed. Refresh to see the latest.")
        allowed = {"submitted": ("draft",), "withdrawn": ("submitted",)}[to_state]
        if row["state"] not in allowed:
            conn.rollback()
            raise CFError(409, "PLAN_STATE", f"A {row['state']} plan can't be {to_state}.")
        if to_state == "withdrawn" and row["submitted_by"] != actor:
            conn.rollback()
            raise CFError(403, "INSUFFICIENT_ROLE", "Only the person who submitted this plan can withdraw it.")
        cur.execute(f"""UPDATE cf_plans SET state = %s, submitted_by = COALESCE(%s, submitted_by),
                            submitted_at = CASE WHEN %s = 'submitted' THEN now() ELSE submitted_at END, updated_at = now()
                        WHERE tenant_id = %s AND id = %s RETURNING {repo.PLAN_COLS}""",
                    (to_state, actor if to_state == "submitted" else None, to_state, tenant, plan_id))
        out = cur.fetchone()
        repo.audit(cur, tenant, "plan", plan_id, to_state, actor)
        conn.commit()
    return plan_json(out)


def decide(tenant, actor, plan_id, decision, expected_version, note, idem_key) -> dict:
    payload = {"plan_id": str(plan_id), "decision": decision, "expected_version": expected_version, "note": note or ""}
    payload_hash = _canonical(payload)
    with cursor() as (conn, cur):
        prior = repo.decision_by_key(cur, tenant, idem_key)
        conn.rollback()
    if prior:
        if prior["payload_hash"] != payload_hash:
            raise CFError(409, "IDEMPOTENCY_CONFLICT", "This request key was already used for a different decision.")
        return prior["response"]
    if decision == "return" and not (note or "").strip():
        raise CFError(422, "VALIDATION_ERROR", "Say what needs to change when returning a plan.")

    plan = get_plan(tenant, plan_id)
    s = settings(tenant)
    current_rev = None
    if decision == "approve":
        if plan["state"] != "submitted":
            raise CFError(409, "PLAN_STATE", "This plan was already decided. Refresh to see the latest.")
        if plan["submitted_by"] == actor and not s.allow_self_approval:
            raise CFError(403, "SELF_APPROVAL", "You submitted this plan, so someone else needs to approve it.")
        current, _ = build(tenant, actor, "plan")
        _guard_inputs(current, s, tenant)
        current_rev = current.revision
        if current.revision != plan["revision"]:
            cal = calendar_for(s)
            overrides = OVERRIDES.validate_python(plan["overrides"])
            refusals = sc.validate(current, overrides, plan["view"], cal)
            metrics = None
            if not refusals:
                events, _ = sc.apply(current, overrides, plan["view"], cal)
                metrics = jsonable(engine.project(current, plan["view"], events, cal).metrics)
            keys = ("minimum_closing_paise", "minimum_date", "first_reserve_breach_date", "closing_paise")
            if refusals or any(metrics[k] != plan["metrics"][k] for k in keys):
                raise CFError(409, "PLAN_STALE", "Things changed since this plan was submitted.",
                              {"refusals": refusals, "submitted": {k: plan["metrics"][k] for k in keys},
                               "now": {k: metrics[k] for k in keys} if metrics else None,
                               "revision_submitted": plan["revision"], "revision_now": current.revision})

    with cursor() as (conn, cur):
        try:
            row = repo.get_plan(cur, tenant, plan_id, for_update=True)
            if row["state"] != "submitted" or row["version"] != expected_version:
                raise CFError(409, "PLAN_STATE", "This plan was already decided. Refresh to see the latest.")
            new_state = "approved" if decision == "approve" else "returned"
            if decision == "approve":
                cur.execute("""UPDATE cf_plans SET state = 'superseded', superseded_by = %s, updated_at = now()
                               WHERE tenant_id = %s AND state = 'approved' RETURNING id::text""", (plan_id, tenant))
                for old in cur.fetchall():
                    cur.execute("UPDATE cf_planned_dates SET active = false WHERE tenant_id = %s AND plan_id = %s",
                                (tenant, old["id"]))
                    cur.execute("UPDATE cf_adjustments SET active = false WHERE tenant_id = %s AND plan_id = %s",
                                (tenant, old["id"]))
                    repo.audit(cur, tenant, "plan", old["id"], "superseded", actor, after={"by": plan_id})
            cur.execute(f"""UPDATE cf_plans SET state = %s, updated_at = now() WHERE tenant_id = %s AND id = %s
                            RETURNING {repo.PLAN_COLS}""", (new_state, tenant, plan_id))
            updated = cur.fetchone()
            if decision == "approve":
                _adopt(cur, tenant, plan_id, row)
            response = {"plan": plan_json(updated), "decision": decision, "validated_on_revision": current_rev or row["revision"]}
            cur.execute("""INSERT INTO cf_plan_decisions (tenant_id, plan_id, plan_version, decision, note, decided_by,
                               idempotency_key, payload_hash, validated_on_revision, response)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                        (tenant, plan_id, row["version"], decision, note, actor, idem_key, payload_hash,
                         current_rev or row["revision"], Json(response)))
            repo.audit(cur, tenant, "plan", plan_id, new_state, actor, after={"note": note,
                                                                              "validated_on_revision": current_rev})
            conn.commit()
            return response
        except pg_errors.UniqueViolation:
            conn.rollback()
            prior = repo.decision_by_key(cur, tenant, idem_key)
            conn.rollback()
            if prior and prior["payload_hash"] == payload_hash:
                return prior["response"]
            raise CFError(409, "PLAN_STATE", "This plan was already decided. Refresh to see the latest.")
        except CFError:
            conn.rollback()
            raise


def _adopt(cur, tenant, plan_id, plan_row):
    """Carry approved *decisions* into future forecasts. Assumptions stay in the plan record."""
    snap = repo.load_snapshot(cur, tenant, plan_row["snapshot_id"])
    for o in OVERRIDES.validate_python(plan_row["overrides"]):
        if isinstance(o, sc.ShiftEvent):
            e = snap.event(o.event_key) if snap else None
            if e is None or e.direction != "out":
                continue
            source_id = f"{e.source_id}:{e.nominal_date.isoformat()}" if e.source_type == "recurring" else e.source_id
            cur.execute("""UPDATE cf_planned_dates SET active = false
                           WHERE tenant_id = %s AND source_type = %s AND source_id = %s AND active""",
                        (tenant, e.source_type, source_id))
            cur.execute("""INSERT INTO cf_planned_dates (tenant_id, source_type, source_id, planned_date, plan_id)
                           VALUES (%s, %s, %s, %s, %s)""", (tenant, e.source_type, source_id, o.to_date, plan_id))
        elif isinstance(o, sc.AddItem) and o.confidence == "committed":
            cur.execute("""INSERT INTO cf_adjustments (tenant_id, name, category, direction, amount_paise, on_date,
                               confidence, note, plan_id, created_by)
                           VALUES (%s, %s, %s, %s, %s, %s, 'committed', %s, %s, 'plan')""",
                        (tenant, o.label, o.category, o.direction, o.amount_paise, o.on_date, o.reason, plan_id))
