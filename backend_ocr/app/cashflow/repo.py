"""All SQL for the cf_* tables. Every statement is tenant-scoped and parameterised."""

from __future__ import annotations

from collections import OrderedDict
from threading import Lock

from psycopg2.extras import Json, execute_values

from .types import CashEvent, Exclusion, OpeningBalance, PaymentWindow, Snapshot, ViewDates, jsonable

# ── Snapshots ───────────────────────────────────────────────────────────────
_CACHE: "OrderedDict[tuple, Snapshot]" = OrderedDict()
_CACHE_LOCK = Lock()
_CACHE_SIZE = 64


def latest_ref(cur, tenant):
    cur.execute("""SELECT id::text, revision, content_hash FROM cf_snapshots
                   WHERE tenant_id = %s ORDER BY revision DESC LIMIT 1""", (tenant,))
    return cur.fetchone()


def insert_snapshot(cur, snap: Snapshot, reason: str, actor: str) -> tuple[str, int, bool]:
    """Persist `snap` as a new revision unless its content equals the latest one.

    Returns (snapshot_id, revision, changed). Caller owns the transaction.
    """
    tenant = snap.tenant_id
    cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"cf:{tenant}",))
    latest = latest_ref(cur, tenant)
    if latest and latest["content_hash"] == snap.content_hash:
        return latest["id"], latest["revision"], False
    revision = (latest["revision"] if latest else 0) + 1
    cur.execute("""
        INSERT INTO cf_snapshots (tenant_id, revision, as_of, start_date, horizon_days, reserve_paise,
                                  od_headroom_paise, coverage, content_hash, reason, built_by)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id::text""",
                (tenant, revision, snap.as_of, snap.start, snap.horizon_days, snap.reserve_paise,
                 snap.od_headroom_paise, Json(snap.coverage), snap.content_hash, reason, actor))
    sid = cur.fetchone()["id"]
    execute_values(cur, """INSERT INTO cf_snapshot_balances (tenant_id, snapshot_id, bank_account_id, account_name,
                               account_mask, balance_paise, as_of, source, freshness) VALUES %s""",
                   [(tenant, sid, b.bank_account_id, b.account_name, b.account_mask, b.balance_paise, b.as_of,
                     b.source, b.freshness) for b in snap.balances])
    if snap.events:
        execute_values(cur, """INSERT INTO cf_snapshot_events (tenant_id, snapshot_id, event_key, source_type, source_id,
                                   label, counterparty, counterparty_id, document_number, direction, amount_paise, category,
                                   confidence, date_expected, date_downside, date_no_collections, date_basis, nominal_date,
                                   window_earliest, window_latest, fixed, link_path) VALUES %s""",
                       [(tenant, sid, e.event_key, e.source_type, e.source_id, e.label, e.counterparty, e.counterparty_id,
                         e.document_number, e.direction, e.amount_paise, e.category, e.confidence, e.dates.expected,
                         e.dates.downside, e.dates.no_collections,
                         Json(dict(e.date_basis, **({"_agreed_with": e.window.agreed_with,
                                                       "_evidence": e.window.evidence} if e.window else {}))),
                         e.nominal_date, e.window.earliest if e.window else None, e.window.latest if e.window else None,
                         e.fixed, e.link_path) for e in snap.events], page_size=1000)
    if snap.exclusions:
        execute_values(cur, """INSERT INTO cf_snapshot_exclusions (tenant_id, snapshot_id, source_type, source_id, reason,
                                   label, amount_paise, detail, views, link_path) VALUES %s""",
                       [(tenant, sid, x.source_type, x.source_id, x.reason, x.label, x.amount_paise, x.detail,
                         list(x.views), x.link_path) for x in snap.exclusions])
    return sid, revision, True


def load_snapshot(cur, tenant, snapshot_id) -> Snapshot | None:
    key = (str(tenant), str(snapshot_id))
    with _CACHE_LOCK:
        if key in _CACHE:
            _CACHE.move_to_end(key)
            return _CACHE[key]
    cur.execute("""SELECT id::text, revision, as_of, start_date, horizon_days, reserve_paise, od_headroom_paise,
                          coverage, content_hash FROM cf_snapshots WHERE tenant_id = %s AND id = %s""",
                (tenant, str(snapshot_id)))
    s = cur.fetchone()
    if not s:
        return None
    cur.execute("""SELECT bank_account_id::text, account_name, account_mask, balance_paise, as_of, source, freshness
                   FROM cf_snapshot_balances WHERE tenant_id = %s AND snapshot_id = %s ORDER BY account_name""",
                (tenant, s["id"]))
    balances = tuple(OpeningBalance(**r) for r in cur.fetchall())
    cur.execute("SELECT * FROM cf_snapshot_events WHERE tenant_id = %s AND snapshot_id = %s ORDER BY event_key",
                (tenant, s["id"]))
    events = []
    for r in cur.fetchall():
        basis = dict(r["date_basis"])
        agreed, evidence = basis.pop("_agreed_with", None), basis.pop("_evidence", None)
        window = PaymentWindow(r["window_earliest"], r["window_latest"], agreed, evidence) if r["window_latest"] else None
        events.append(CashEvent(
            event_key=r["event_key"], source_type=r["source_type"], source_id=r["source_id"], label=r["label"],
            direction=r["direction"], amount_paise=int(r["amount_paise"]), category=r["category"],
            confidence=r["confidence"], dates=ViewDates(r["date_expected"], r["date_downside"], r["date_no_collections"]),
            date_basis=basis, nominal_date=r["nominal_date"], counterparty=r["counterparty"],
            counterparty_id=r["counterparty_id"], document_number=r["document_number"], window=window,
            fixed=r["fixed"], link_path=r["link_path"]))
    cur.execute("""SELECT source_type, source_id, label, amount_paise, reason, detail, views, link_path
                   FROM cf_snapshot_exclusions WHERE tenant_id = %s AND snapshot_id = %s
                   ORDER BY source_type, source_id, reason""", (tenant, s["id"]))
    exclusions = tuple(Exclusion(r["source_type"], r["source_id"], r["label"], int(r["amount_paise"]), r["reason"],
                                 r["detail"], tuple(r["views"]), r["link_path"]) for r in cur.fetchall())
    snap = Snapshot(tenant_id=str(tenant), as_of=s["as_of"], start=s["start_date"], horizon_days=s["horizon_days"],
                    reserve_paise=int(s["reserve_paise"]), od_headroom_paise=int(s["od_headroom_paise"]),
                    balances=balances, events=tuple(events), exclusions=exclusions, coverage=s["coverage"],
                    content_hash=s["content_hash"], snapshot_id=s["id"], revision=s["revision"])
    with _CACHE_LOCK:
        _CACHE[key] = snap
        while len(_CACHE) > _CACHE_SIZE:
            _CACHE.popitem(last=False)
    return snap


# ── Settings and inputs ─────────────────────────────────────────────────────
SETTINGS_FIELDS = ("reserve_paise", "horizon_days", "timezone", "default_view", "include_pending_approval_ap",
                   "overdue_fallback_days", "downside_exclude_overdue_after_days", "min_customer_history",
                   "allow_self_approval", "publish_daily")


def get_settings_row(cur, tenant):
    cur.execute("SELECT * FROM cf_settings WHERE tenant_id = %s", (tenant,))
    return cur.fetchone()


def upsert_settings(cur, tenant, actor, values: dict):
    cols = [k for k in SETTINGS_FIELDS if k in values]
    cur.execute(f"""
        INSERT INTO cf_settings (tenant_id, {", ".join(cols)}, updated_by, updated_at)
        VALUES (%s, {", ".join(["%s"] * len(cols))}, %s, now())
        ON CONFLICT (tenant_id) DO UPDATE SET {", ".join(f"{c} = EXCLUDED.{c}" for c in cols)},
            updated_by = EXCLUDED.updated_by, updated_at = now()""",
                [tenant, *[values[c] for c in cols], actor])


def audit(cur, tenant, entity, entity_id, action, actor, before=None, after=None, request_id=None):
    cur.execute("""INSERT INTO cf_audit_log (tenant_id, entity, entity_id, action, actor, before, after, request_id)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                (tenant, entity, str(entity_id), action, actor,
                 Json(jsonable(before)) if before is not None else None,
                 Json(jsonable(after)) if after is not None else None, request_id))


# ── Plans ───────────────────────────────────────────────────────────────────
PLAN_COLS = """id::text, scenario_id::text, version, state, snapshot_id::text, revision, view, overrides, overrides_hash,
               metrics, baseline_metrics, note, submitted_by, submitted_at, superseded_by::text, created_by, created_at,
               updated_at"""


def get_plan(cur, tenant, plan_id, for_update=False):
    cur.execute(f"SELECT {PLAN_COLS} FROM cf_plans WHERE tenant_id = %s AND id = %s" + (" FOR UPDATE" if for_update else ""),
                (tenant, str(plan_id)))
    return cur.fetchone()


def list_plans(cur, tenant, state=None):
    sql = f"SELECT {PLAN_COLS} FROM cf_plans WHERE tenant_id = %s"
    params = [tenant]
    if state:
        sql += " AND state = %s"
        params.append(state)
    cur.execute(sql + " ORDER BY updated_at DESC LIMIT 100", params)
    return cur.fetchall()


def decisions_for(cur, tenant, plan_id):
    cur.execute("""SELECT id::text, plan_version, decision, note, decided_by, validated_on_revision, decided_at
                   FROM cf_plan_decisions WHERE tenant_id = %s AND plan_id = %s ORDER BY decided_at""",
                (tenant, str(plan_id)))
    return cur.fetchall()


def history_for(cur, tenant, entity, entity_id):
    cur.execute("""SELECT action, actor, created_at, after FROM cf_audit_log
                   WHERE tenant_id = %s AND entity = %s AND entity_id = %s ORDER BY created_at""",
                (tenant, entity, str(entity_id)))
    return cur.fetchall()


def decision_by_key(cur, tenant, key):
    cur.execute("""SELECT payload_hash, response FROM cf_plan_decisions WHERE tenant_id = %s AND idempotency_key = %s""",
                (tenant, key))
    return cur.fetchone()

