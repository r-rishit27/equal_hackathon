"""Cash Flow Forecast API — /api/finance-desk/cash-forecast (docs/cashflow-forecast/04_LLD.md §7).

Every route resolves the tenant from the verified token and checks a role
capability. Nothing here moves money: the only business mutation is a cash
plan decision, and it records payment *dates* for future forecasts.
"""

from __future__ import annotations

import csv
import io
import time
from collections import defaultdict, deque
from datetime import date, datetime
from threading import Lock
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..cashflow import scenario as sc
from ..cashflow import service as svc
from ..cashflow.repo import audit, upsert_settings
from ..cashflow.types import jsonable
from ..security.auth import current_role, current_username, is_impersonating, require_role, require_tenant

router = APIRouter(prefix="/api/finance-desk/cash-forecast", tags=["Cash Flow Forecast"])

CAPS = {
    "view": ("admin", "finance_controller", "accountant", "auditor"),
    "edit": ("admin", "finance_controller", "accountant"),
    "approve": ("admin", "finance_controller"),
    "settings": ("admin", "finance_controller"),
}
View = Literal["expected", "downside", "no_collections"]


def _require(cap: str) -> tuple[str, str]:
    tenant = require_tenant()
    require_role(*CAPS[cap])
    if cap != "view" and is_impersonating():
        raise HTTPException(403, "Read-only session")
    return tenant, current_username() or "unknown"


def _err(e: svc.CFError) -> JSONResponse:
    return JSONResponse(status_code=e.status, content={"code": e.code, "message": e.message, "details": jsonable(e.details)})


def _call(fn, *a, **kw):
    try:
        return fn(*a, **kw)
    except svc.CFError as e:
        return _err(e)


_REFRESHES: dict[str, deque] = defaultdict(deque)
_REFRESH_LOCK = Lock()


def _rate_limit(tenant: str, per_minute: int = 30):
    now = time.monotonic()
    with _REFRESH_LOCK:
        q = _REFRESHES[tenant]
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) >= per_minute:
            raise svc.CFError(429, "RATE_LIMITED", f"Refreshed too often. Try again in {int(60 - (now - q[0])) + 1} seconds.")
        q.append(now)


# ── Models ──────────────────────────────────────────────────────────────────
class _In(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class SettingsUpdate(_In):
    reserve_paise: int | None = Field(default=None, ge=0, le=10**14)
    horizon_days: int | None = Field(default=None, ge=7, le=91)
    default_view: View | None = None
    include_pending_approval_ap: bool | None = None
    overdue_fallback_days: int | None = Field(default=None, ge=1, le=30)
    downside_exclude_overdue_after_days: int | None = Field(default=None, ge=15, le=365)
    min_customer_history: int | None = Field(default=None, ge=1, le=20)
    allow_self_approval: bool | None = None
    publish_daily: bool | None = None


class AccountUpdate(_In):
    include_in_forecast: bool | None = None
    od_limit_paise: int | None = Field(default=None, ge=0, le=10**14)


class BalanceCreate(_In):
    bank_account_id: UUID
    balance_paise: int = Field(ge=-10**14, le=10**14)
    as_of: datetime

    @field_validator("as_of")
    @classmethod
    def _aware(cls, v):
        if v.tzinfo is None:
            raise ValueError("as_of needs a timezone offset")
        return v


Category = Literal["customer", "supplier", "payroll", "statutory", "rent", "debt", "utilities", "operations",
                   "insurance", "capex", "refund", "financing", "other"]


class RecurringIn(_In):
    name: str = Field(min_length=1, max_length=120)
    category: Category
    direction: Literal["in", "out"] = "out"
    amount_paise: int | None = Field(default=None, gt=0, le=10**14)
    frequency: Literal["weekly", "monthly", "quarterly"]
    anchor: str = Field(pattern=r"^([0-9]|[12][0-9]|3[01]|last_banking_day)$")
    quarter_months: list[int] | None = None
    business_day_rule: Literal["next_banking_day", "previous_banking_day"] = "next_banking_day"
    confidence: Literal["committed", "estimated"] = "committed"
    statutory: bool = False
    start_date: date
    end_date: date | None = None


class RecurringPatch(RecurringIn):
    expected_version: int


class AdjustmentIn(_In):
    name: str = Field(min_length=1, max_length=120)
    category: Category
    direction: Literal["in", "out"]
    amount_paise: int = Field(gt=0, le=10**14)
    on_date: date
    confidence: Literal["committed", "estimated"]
    note: str | None = Field(default=None, max_length=1000)


class WindowIn(_In):
    invoice_id: UUID
    latest_date: date
    agreed_with: str = Field(min_length=1, max_length=200)
    evidence: str = Field(min_length=1, max_length=1000)


class PromiseIn(_In):
    invoice_id: UUID
    promised_date: date
    promised_amount_paise: int = Field(gt=0, le=10**14)
    source: Literal["call", "email", "meeting", "portal", "other"] = "call"
    note: str | None = Field(default=None, max_length=1000)


class PreviewIn(_In):
    snapshot_id: UUID
    revision: int = Field(ge=1)
    view: View
    overrides: list[sc.Override] = Field(default_factory=list, max_length=sc.MAX_OVERRIDES)


class DayIn(_In):
    snapshot_id: UUID
    view: View
    overrides: list[sc.Override] = Field(default_factory=list, max_length=sc.MAX_OVERRIDES)


class ScenarioIn(_In):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=1000)
    snapshot_id: UUID
    view: View
    overrides: list[sc.Override] = Field(default_factory=list, max_length=sc.MAX_OVERRIDES)


class ScenarioPatch(ScenarioIn):
    expected_version: int


class PlanIn(_In):
    scenario_id: UUID
    note: str | None = Field(default=None, max_length=2000)
    submit: bool = True


class VersionIn(_In):
    expected_version: int


class DecisionIn(_In):
    decision: Literal["approve", "return"]
    expected_version: int
    note: str | None = Field(default=None, max_length=2000)


# ── Settings, accounts, balances ────────────────────────────────────────────
STATUTORY_TEMPLATES = [
    ("Salaries (net pay)", "payroll", "monthly", "last_banking_day", None, "previous_banking_day", True),
    ("GST payment - GSTR-3B", "statutory", "monthly", "20", None, "previous_banking_day", True),
    ("TDS deposit (previous month)", "statutory", "monthly", "7", None, "previous_banking_day", True),
    ("PF and ESI contribution", "statutory", "monthly", "15", None, "previous_banking_day", True),
    ("Advance tax instalment", "statutory", "quarterly", "15", [6, 9, 12, 3], "previous_banking_day", True),
]


@router.get("/me")
def me():
    tenant, actor = _require("view")
    role = current_role()
    can = {cap: role in roles and (cap == "view" or not is_impersonating()) for cap, roles in CAPS.items()}
    return {"actor": actor, "role": role, "can": can}


@router.get("/settings")
def get_settings():
    tenant, _ = _require("view")
    s = svc.settings(tenant)
    return {k: getattr(s, k) for k in ("reserve_paise", "horizon_days", "timezone", "default_view",
                                       "include_pending_approval_ap", "overdue_fallback_days",
                                       "downside_exclude_overdue_after_days", "min_customer_history",
                                       "allow_self_approval", "publish_daily")} | {
        "holidays": [{"date": d.isoformat(), "name": n} for d, n in sorted(s.holidays.items())]}


@router.put("/settings")
def put_settings(body: SettingsUpdate):
    tenant, actor = _require("settings")
    values = body.model_dump(exclude_none=True)
    with svc.cursor() as (conn, cur):
        before = svc.repo.get_settings_row(cur, tenant)
        upsert_settings(cur, tenant, actor, values)
        audit(cur, tenant, "settings", tenant, "update", actor, before=dict(before) if before else None, after=values)
        conn.commit()
    return get_settings()


@router.get("/accounts")
def accounts():
    tenant, _ = _require("view")
    with svc.cursor() as (conn, cur):
        if svc.uses_fixture(tenant):
            from ..cashflow.sources import load_books_fixture, load_inputs
            data = load_books_fixture()
        else:
            from ..cashflow.sources import load_books_live, load_inputs
            data = load_books_live(cur, tenant)
        load_inputs(cur, tenant, data)
        conn.rollback()
    latest = {str(b["bank_account_id"]): b for b in data.balances}
    out = []
    for a in data.accounts:
        b = latest.get(str(a["bank_account_id"]))
        out.append({**{k: a[k] for k in ("bank_account_id", "account_name", "account_mask", "account_type", "od_limit_paise")},
                    "include_in_forecast": a["include"],
                    "balance_paise": b["balance_paise"] if b else None,
                    "as_of": b["as_of"].isoformat() if b else None, "source": b["source"] if b else None})
    return out


@router.patch("/accounts/{bank_account_id}")
def patch_account(bank_account_id: UUID, body: AccountUpdate):
    # Choosing accounts is part of first-run setup, which the accountant does (user flow UF-01).
    tenant, actor = _require("edit")
    current = {a["bank_account_id"]: a for a in accounts()}
    acct = current.get(str(bank_account_id))
    if acct is None:
        raise HTTPException(404, "Account not found")
    include = acct["include_in_forecast"] if body.include_in_forecast is None else body.include_in_forecast
    limit = acct["od_limit_paise"] if body.od_limit_paise is None else body.od_limit_paise
    with svc.cursor() as (conn, cur):
        cur.execute("""INSERT INTO cf_account_settings (tenant_id, bank_account_id, include_in_forecast, od_limit_paise)
                       VALUES (%s, %s, %s, %s) ON CONFLICT (tenant_id, bank_account_id)
                       DO UPDATE SET include_in_forecast = EXCLUDED.include_in_forecast, od_limit_paise = EXCLUDED.od_limit_paise""",
                    (tenant, str(bank_account_id), include, limit))
        audit(cur, tenant, "account", bank_account_id, "update", actor, after={"include": include, "od_limit_paise": limit})
        conn.commit()
    return {**acct, "include_in_forecast": include, "od_limit_paise": limit}


@router.post("/balances", status_code=201)
def add_balance(body: BalanceCreate):
    tenant, actor = _require("edit")
    if body.as_of.timestamp() > time.time() + 300:
        return _err(svc.CFError(422, "VALIDATION_ERROR", "The balance time can't be in the future."))
    if str(body.bank_account_id) not in {a["bank_account_id"] for a in accounts()}:
        raise HTTPException(404, "Account not found")
    with svc.cursor() as (conn, cur):
        cur.execute("""INSERT INTO cf_bank_balances (tenant_id, bank_account_id, balance_paise, as_of, source, created_by)
                       VALUES (%s, %s, %s, %s, 'manual', %s) RETURNING id::text""",
                    (tenant, str(body.bank_account_id), body.balance_paise, body.as_of, actor))
        bid = cur.fetchone()["id"]
        audit(cur, tenant, "balance", bid, "create", actor, after=body.model_dump(mode="json"))
        conn.commit()
    return {"id": bid}


# ── Generic input CRUD (recurring, adjustments, windows, promises) ──────────
REC_COLS = """id::text, name, category, direction, amount_paise, frequency, anchor, quarter_months, business_day_rule,
              confidence, statutory, start_date, end_date, active, version"""


def _rows(sql, params):
    with svc.cursor() as (conn, cur):
        cur.execute(sql, params)
        rows = cur.fetchall()
        conn.rollback()
    return [{k: (v.isoformat() if isinstance(v, (date, datetime)) else v) for k, v in r.items()} for r in rows]


@router.get("/recurring")
def list_recurring():
    tenant, _ = _require("view")
    return _rows(f"SELECT {REC_COLS} FROM cf_recurring_items WHERE tenant_id = %s AND active ORDER BY amount_paise DESC NULLS LAST, name",
                 (tenant,))


def _recurring_values(body: RecurringIn):
    if body.end_date and body.end_date < body.start_date:
        raise svc.CFError(422, "VALIDATION_ERROR", "End date must be on or after the start date.")
    if body.frequency == "weekly" and body.anchor not in [str(i) for i in range(7)]:
        raise svc.CFError(422, "VALIDATION_ERROR", "Weekly items need a weekday (0 = Monday … 6 = Sunday).")
    if body.frequency == "quarterly" and not body.quarter_months:
        raise svc.CFError(422, "VALIDATION_ERROR", "Quarterly items need their months.")
    fixed = body.category in ("payroll", "statutory")
    return (body.name, body.category, body.direction, body.amount_paise, body.frequency, body.anchor, body.quarter_months,
            body.business_day_rule, body.confidence, body.statutory or fixed, body.start_date, body.end_date)


@router.post("/recurring", status_code=201)
def create_recurring(body: RecurringIn):
    tenant, actor = _require("edit")
    try:
        values = _recurring_values(body)
    except svc.CFError as e:
        return _err(e)
    with svc.cursor() as (conn, cur):
        cur.execute(f"""INSERT INTO cf_recurring_items (tenant_id, name, category, direction, amount_paise, frequency, anchor,
                            quarter_months, business_day_rule, confidence, statutory, start_date, end_date, created_by)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING {REC_COLS}""",
                    (tenant, *values, actor))
        row = cur.fetchone()
        audit(cur, tenant, "recurring", row["id"], "create", actor, after=body.model_dump(mode="json"))
        conn.commit()
    return jsonable(dict(row))


@router.patch("/recurring/{item_id}")
def update_recurring(item_id: UUID, body: RecurringPatch):
    tenant, actor = _require("edit")
    try:
        values = _recurring_values(body)
    except svc.CFError as e:
        return _err(e)
    with svc.cursor() as (conn, cur):
        cur.execute(f"""UPDATE cf_recurring_items SET name=%s, category=%s, direction=%s, amount_paise=%s, frequency=%s,
                            anchor=%s, quarter_months=%s, business_day_rule=%s, confidence=%s, statutory=%s, start_date=%s,
                            end_date=%s, version = version + 1, updated_at = now()
                        WHERE tenant_id = %s AND id = %s AND active AND version = %s RETURNING {REC_COLS}""",
                    (*values, tenant, str(item_id), body.expected_version))
        row = cur.fetchone()
        if not row:
            conn.rollback()
            return _err(svc.CFError(409, "VERSION_CONFLICT", "This item changed or was removed. Reload and try again."))
        audit(cur, tenant, "recurring", item_id, "update", actor, after=body.model_dump(mode="json"))
        conn.commit()
    return jsonable(dict(row))


def _deactivate(table, entity, item_id):
    tenant, actor = _require("edit")
    with svc.cursor() as (conn, cur):
        cur.execute(f"UPDATE {table} SET active = false WHERE tenant_id = %s AND id = %s AND active RETURNING id",
                    (tenant, str(item_id)))
        if not cur.fetchone():
            conn.rollback()
            raise HTTPException(404, "Not found")
        audit(cur, tenant, entity, item_id, "delete", actor)
        conn.commit()
    return Response(status_code=204)


@router.delete("/recurring/{item_id}", status_code=204)
def delete_recurring(item_id: UUID):
    return _deactivate("cf_recurring_items", "recurring", item_id)


@router.post("/setup/seed-templates")
def seed_templates():
    tenant, actor = _require("edit")
    with svc.cursor() as (conn, cur):
        cur.execute("SELECT name FROM cf_recurring_items WHERE tenant_id = %s AND active", (tenant,))
        have = {r["name"] for r in cur.fetchall()}
        today = date.today().replace(day=1)
        for name, cat, freq, anchor, months, rule, stat in STATUTORY_TEMPLATES:
            if name not in have:
                cur.execute("""INSERT INTO cf_recurring_items (tenant_id, name, category, direction, frequency, anchor,
                                   quarter_months, business_day_rule, confidence, statutory, start_date, created_by)
                               VALUES (%s, %s, %s, 'out', %s, %s, %s, %s, 'committed', %s, %s, %s)""",
                            (tenant, name, cat, freq, anchor, months, rule, stat, today, actor))
        audit(cur, tenant, "recurring", tenant, "seed_templates", actor)
        conn.commit()
    return list_recurring()


ADJ_COLS = "id::text, name, category, direction, amount_paise, on_date, confidence, note, plan_id::text, active"


@router.get("/adjustments")
def list_adjustments():
    tenant, _ = _require("view")
    return _rows(f"SELECT {ADJ_COLS} FROM cf_adjustments WHERE tenant_id = %s AND active ORDER BY on_date", (tenant,))


@router.post("/adjustments", status_code=201)
def create_adjustment(body: AdjustmentIn):
    tenant, actor = _require("edit")
    with svc.cursor() as (conn, cur):
        cur.execute(f"""INSERT INTO cf_adjustments (tenant_id, name, category, direction, amount_paise, on_date, confidence,
                            note, created_by) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING {ADJ_COLS}""",
                    (tenant, body.name, body.category, body.direction, body.amount_paise, body.on_date, body.confidence,
                     body.note, actor))
        row = cur.fetchone()
        audit(cur, tenant, "adjustment", row["id"], "create", actor, after=body.model_dump(mode="json"))
        conn.commit()
    return jsonable(dict(row))


@router.delete("/adjustments/{item_id}", status_code=204)
def delete_adjustment(item_id: UUID):
    return _deactivate("cf_adjustments", "adjustment", item_id)


def _snapshot_event_for(tenant, source_type, source_id, direction):
    """The open event for a bill or invoice. An instalment bill's events are keyed by schedule, so match by link."""
    snap = svc.latest(tenant, "system")
    e = snap.event(f"{'bill' if source_type == 'bill' else 'ar'}:{source_id}")
    if e is None:
        path = f"/bills/{source_id}" if source_type == "bill" else f"/receivables/invoices/{source_id}"
        e = next((x for x in snap.events if x.link_path == path and x.direction == direction), None)
    return e


@router.get("/payment-windows")
def list_windows():
    tenant, _ = _require("view")
    return _rows("""SELECT id::text, invoice_id::text, earliest_date, latest_date, agreed_with, evidence, recorded_by, recorded_at
                    FROM cf_payment_windows WHERE tenant_id = %s AND active ORDER BY latest_date""", (tenant,))


@router.post("/payment-windows", status_code=201)
def create_window(body: WindowIn):
    tenant, actor = _require("edit")
    e = _snapshot_event_for(tenant, "bill", str(body.invoice_id), "out")
    if e is None:
        return _err(svc.CFError(404, "NOT_FOUND", "This bill isn't an open payable in the forecast."))
    earliest = e.nominal_date or e.dates.expected
    if body.latest_date < earliest:
        return _err(svc.CFError(422, "VALIDATION_ERROR", "The agreed date must be on or after the due date."))
    with svc.cursor() as (conn, cur):
        cur.execute("UPDATE cf_payment_windows SET active = false WHERE tenant_id = %s AND invoice_id = %s AND active",
                    (tenant, str(body.invoice_id)))
        cur.execute("""INSERT INTO cf_payment_windows (tenant_id, invoice_id, earliest_date, latest_date, agreed_with, evidence,
                           recorded_by) VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id::text""",
                    (tenant, str(body.invoice_id), earliest, body.latest_date, body.agreed_with, body.evidence, actor))
        wid = cur.fetchone()["id"]
        audit(cur, tenant, "payment_window", wid, "create", actor, after=body.model_dump(mode="json"))
        conn.commit()
    return {"id": wid, "earliest_date": earliest.isoformat(), "latest_date": body.latest_date.isoformat()}


@router.delete("/payment-windows/{item_id}", status_code=204)
def delete_window(item_id: UUID):
    return _deactivate("cf_payment_windows", "payment_window", item_id)


@router.get("/promises")
def list_promises():
    tenant, _ = _require("view")
    return _rows("""SELECT id::text, invoice_id::text, promised_date, promised_amount_paise, source, note, recorded_by, recorded_at
                    FROM cf_collection_promises WHERE tenant_id = %s AND active ORDER BY promised_date""", (tenant,))


@router.post("/promises", status_code=201)
def create_promise(body: PromiseIn):
    tenant, actor = _require("edit")
    if _snapshot_event_for(tenant, "ar_invoice", str(body.invoice_id), "in") is None:
        return _err(svc.CFError(404, "NOT_FOUND", "This invoice isn't an open receivable in the forecast."))
    with svc.cursor() as (conn, cur):
        cur.execute("UPDATE cf_collection_promises SET active = false WHERE tenant_id = %s AND invoice_id = %s AND active",
                    (tenant, str(body.invoice_id)))
        cur.execute("""INSERT INTO cf_collection_promises (tenant_id, invoice_id, promised_date, promised_amount_paise, source,
                           note, recorded_by) VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id::text""",
                    (tenant, str(body.invoice_id), body.promised_date, body.promised_amount_paise, body.source, body.note, actor))
        pid = cur.fetchone()["id"]
        audit(cur, tenant, "promise", pid, "create", actor, after=body.model_dump(mode="json"))
        conn.commit()
    return {"id": pid}


@router.delete("/promises/{item_id}", status_code=204)
def delete_promise(item_id: UUID):
    return _deactivate("cf_collection_promises", "promise", item_id)


# ── Snapshots and forecast ──────────────────────────────────────────────────
@router.get("/snapshots/latest")
def latest_snapshot():
    tenant, actor = _require("view")
    try:
        can_build = current_role() in CAPS["edit"] and not is_impersonating()
        snap = svc.latest(tenant, actor, build_if_missing=can_build)
        return svc.snapshot_ref(snap, svc.settings(tenant), tenant)
    except svc.CFError as e:
        return _err(e)


@router.post("/snapshots")
def refresh_snapshot():
    tenant, actor = _require("edit")
    try:
        _rate_limit(tenant)
        snap, changed = svc.build(tenant, actor, "manual")
        body = svc.snapshot_ref(snap, svc.settings(tenant), tenant, changed)
        return JSONResponse(status_code=201 if changed else 200, content=body)
    except svc.CFError as e:
        return _err(e)


@router.get("/forecast")
def get_forecast(snapshot_id: UUID, view: View = "expected"):
    tenant, _ = _require("view")
    return _call(svc.forecast, tenant, str(snapshot_id), view)


@router.post("/forecast/preview")
def post_preview(body: PreviewIn):
    tenant, _ = _require("view")
    return _call(svc.preview, tenant, str(body.snapshot_id), body.revision, body.view, body.overrides)


@router.post("/days/{day}")
def post_day(day: date, body: DayIn):
    tenant, _ = _require("view")
    return _call(svc.day_detail, tenant, str(body.snapshot_id), body.view, day, body.overrides)


@router.get("/events")
def get_events(snapshot_id: UUID, view: View = "expected"):
    tenant, _ = _require("view")
    return _call(svc.events_list, tenant, str(snapshot_id), view)


@router.get("/exclusions")
def get_exclusions(snapshot_id: UUID):
    tenant, _ = _require("view")
    return _call(svc.exclusions, tenant, str(snapshot_id))


# ── Scenarios ───────────────────────────────────────────────────────────────
@router.get("/scenarios")
def list_scenarios():
    tenant, actor = _require("view")
    return svc.list_scenarios(tenant, actor)


@router.get("/scenarios/{scenario_id}")
def get_scenario(scenario_id: UUID):
    tenant, _ = _require("view")
    return _call(svc.get_scenario, tenant, str(scenario_id))


@router.post("/scenarios", status_code=201)
def create_scenario(body: ScenarioIn):
    tenant, actor = _require("edit")
    return _call(svc.save_scenario, tenant, actor, {**body.model_dump(), "snapshot_id": str(body.snapshot_id),
                                                    "overrides": body.overrides})


@router.patch("/scenarios/{scenario_id}")
def update_scenario(scenario_id: UUID, body: ScenarioPatch):
    tenant, actor = _require("edit")
    return _call(svc.save_scenario, tenant, actor, {**body.model_dump(), "snapshot_id": str(body.snapshot_id),
                                                    "overrides": body.overrides}, str(scenario_id), body.expected_version)


@router.delete("/scenarios/{scenario_id}", status_code=204)
def delete_scenario(scenario_id: UUID):
    tenant, actor = _require("edit")
    out = _call(svc.archive_scenario, tenant, actor, str(scenario_id))
    return out if isinstance(out, JSONResponse) else Response(status_code=204)


# ── Plans ───────────────────────────────────────────────────────────────────
@router.get("/plans")
def list_plans(state: str | None = Query(default=None, pattern="^(draft|submitted|approved|returned|withdrawn|superseded)$")):
    tenant, _ = _require("view")
    return svc.list_plans(tenant, state)


@router.get("/plans/{plan_id}")
def get_plan(plan_id: UUID):
    tenant, _ = _require("view")
    return _call(svc.get_plan, tenant, str(plan_id))


@router.post("/plans", status_code=201)
def create_plan(body: PlanIn):
    tenant, actor = _require("edit")
    return _call(svc.create_plan, tenant, actor, str(body.scenario_id), body.note, body.submit)


@router.post("/plans/{plan_id}/submit")
def submit_plan(plan_id: UUID, body: VersionIn):
    tenant, actor = _require("edit")
    return _call(svc.transition, tenant, actor, str(plan_id), body.expected_version, "submitted")


@router.post("/plans/{plan_id}/withdraw")
def withdraw_plan(plan_id: UUID, body: VersionIn):
    tenant, actor = _require("edit")
    return _call(svc.transition, tenant, actor, str(plan_id), body.expected_version, "withdrawn")


@router.post("/plans/{plan_id}/decision")
def decide_plan(plan_id: UUID, body: DecisionIn,
                idempotency_key: str = Header(alias="Idempotency-Key", min_length=8, max_length=80)):
    tenant, actor = _require("approve")
    return _call(svc.decide, tenant, actor, str(plan_id), body.decision, body.expected_version, body.note, idempotency_key)


# ── Export ──────────────────────────────────────────────────────────────────
def _cell(v):
    s = "" if v is None else str(v)
    return "'" + s if s[:1] in ("=", "+", "-", "@") and not s.lstrip("-").replace(".", "").isdigit() else s


@router.get("/export.csv")
def export_csv(snapshot_id: UUID, view: View = "expected"):
    tenant, _ = _require("view")
    try:
        snap = svc.snapshot(tenant, str(snapshot_id))
        data = svc.forecast(tenant, str(snapshot_id), view)
    except svc.CFError as e:
        return _err(e)
    buf = io.StringIO()
    w = csv.writer(buf)
    rupees = lambda p: f"{p / 100:.2f}"
    w.writerow(["Cash flow forecast", f"revision {snap.revision}", f"view {view}", f"as of {snap.as_of.isoformat()}",
                f"reserve {rupees(snap.reserve_paise)}"])
    w.writerow([])
    w.writerow(["Date", "Banking day", "Opening", "Inflow", "Outflow", "Closing", "Below reserve"])
    for d in data["days"]:
        w.writerow([d["date"], "yes" if d["banking_day"] else "no", rupees(d["opening_paise"]), rupees(d["inflow_paise"]),
                    rupees(d["outflow_paise"]), rupees(d["closing_paise"]), "yes" if d["below_reserve"] else ""])
    w.writerow([])
    w.writerow(["Date", "Direction", "Amount", "Category", "Confidence", "Item", "Date basis"])
    for e in svc.events_list(tenant, str(snapshot_id), view):
        w.writerow([e["date"], e["direction"], rupees(e["amount_paise"]), e["category"], e["confidence"],
                    _cell(e["label"]), _cell(e["date_basis"])])
    w.writerow([])
    w.writerow(["Excluded", "Reason", "Amount", "Detail"])
    for x in snap.exclusions:
        w.writerow([_cell(x.label), x.reason, rupees(x.amount_paise), _cell(x.detail)])
    name = f"cash-forecast_{snap.start.isoformat()}_{view}_rev{snap.revision}.csv"
    return Response(buf.getvalue(), media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="{name}"'})
