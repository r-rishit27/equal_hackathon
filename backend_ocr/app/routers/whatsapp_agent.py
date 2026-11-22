"""WhatsApp Agent — Agent Hub + vendor conversation APIs (tenant-scoped).

Contracts: docs/whatsapp-agent/03-lld.md §7. Every query is filtered by the
tenant from the JWT (require_tenant); client-sent ids are only ever used
together with that tenant.
"""
from __future__ import annotations

import asyncio
import os
import time
import traceback
import uuid

from fastapi import APIRouter, HTTPException, Query, Request
from psycopg2 import errors as pg_errors
from psycopg2.extras import RealDictCursor
from pydantic import BaseModel, Field

from ..config import get_conn, put_conn
from ..security.auth import current_username, require_role, require_tenant
from ..whatsapp import repo
from ..whatsapp.outbox import PolicyError, WINDOW, send_reply
from ..whatsapp.twilio import SendError, check_account, mask_phone, normalize_e164

router = APIRouter(tags=["WhatsApp Agent"])

_REFRESH_EVERY_S = 30
_last_refresh: dict[str, float] = {}


def _db():
    conn = get_conn()
    return conn, conn.cursor(cursor_factory=RealDictCursor)


def _brand_filter(brand_id: str | None, alias: str = "s") -> tuple[str, list]:
    """Vendor-scoped rows follow the vendor's brand; brand-less rows show under every brand."""
    if not brand_id:
        return "", []
    try:
        uuid.UUID(brand_id)
    except ValueError:
        raise HTTPException(400, "brand_id must be a UUID")
    return f" AND ({alias}.brand_id IS NULL OR {alias}.brand_id = %s::uuid)", [brand_id]


def _conn_public(c: dict | None, request: Request) -> dict | None:
    if not c:
        return None
    urls = repo.webhook_urls(c["connection_key"], request)
    return {
        "id": str(c["id"]),
        "state": c["state"],
        "account_sid": c["account_sid"][:6] + "…" + c["account_sid"][-4:],
        "sender": c["sender_e164"],
        "uses_server_credentials": c["secret_ref"] == "env",
        "inbound_enabled": c["inbound_enabled"],
        "outbound_enabled": c["outbound_enabled"],
        "signature_failures": c["signature_failures"],
        "last_inbound_at": c["last_inbound_at"].isoformat() if c["last_inbound_at"] else None,
        "last_processed_at": c["last_processed_at"].isoformat() if c["last_processed_at"] else None,
        "webhook_url": urls["inbound"],
        "status_callback_url": urls["status"],
    }


# ── Status ────────────────────────────────────────────────────────────────────

@router.get("/api/agent/whatsapp/status")
def whatsapp_status(request: Request, brand_id: str | None = Query(default=None)):
    tenant = require_tenant()
    conn, cur = _db()
    try:
        c = repo.get_connection_for_tenant(cur, tenant)
        bf, bp = _brand_filter(brand_id)
        cur.execute(f"""
            SELECT count(*) AS n FROM whatsapp_contact_watches w
            LEFT JOIN dim_suppliers s ON s.supplier_id = w.supplier_id
            WHERE w.tenant_id=%s AND w.watch_enabled {bf}
        """, [tenant, *bp])
        watched = cur.fetchone()["n"]
        cur.execute("""
            SELECT
              count(*) FILTER (WHERE state IN ('PENDING','RETRY_WAIT','CLAIMED')) AS queued,
              count(*) FILTER (WHERE state = 'RETRY_WAIT') AS retrying,
              count(*) FILTER (WHERE state = 'HELD') AS held,
              count(*) FILTER (WHERE state = 'DEAD') AS dead,
              min(created_at) FILTER (WHERE state IN ('PENDING','RETRY_WAIT','HELD')) AS oldest
            FROM whatsapp_media_jobs WHERE tenant_id=%s
        """, (tenant,))
        q = cur.fetchone()
        cur.execute(f"""
            SELECT count(*) AS n FROM agent_draft_bills d
            LEFT JOIN dim_suppliers s ON s.supplier_id = d.supplier_id
            WHERE d.tenant_id=%s AND d.status='pending' AND d.source_channel='whatsapp' {bf}
        """, [tenant, *bp])
        drafts = cur.fetchone()["n"]
        cur.execute("""SELECT count(*) AS n FROM whatsapp_messages
                       WHERE tenant_id=%s AND direction='inbound' AND received_at > now() - interval '24 hours'""",
                    (tenant,))
        inbound_24h = cur.fetchone()["n"]
        put_conn(conn)
        from ..whatsapp.worker import ENABLED as worker_enabled
        return {
            "agent": "whatsapp_agent",
            "connection": _conn_public(c, request),
            "server_credentials_available": bool(os.getenv("TWILIO_ACCOUNT_SID") and os.getenv("TWILIO_AUTH_TOKEN")),
            "server_sender": os.getenv("TWILIO_WHATSAPP_FROM") or None,
            "worker_enabled": worker_enabled,
            "watched_contacts": watched,
            "pending_drafts": drafts,
            "inbound_24h": inbound_24h,
            "queue": {
                "queued": q["queued"], "retrying": q["retrying"], "held": q["held"], "dead": q["dead"],
                "oldest_at": q["oldest"].isoformat() if q["oldest"] else None,
            },
        }
    except HTTPException:
        put_conn(conn)
        raise
    except pg_errors.UndefinedTable:
        put_conn(conn, close=True)
        raise HTTPException(503, "WhatsApp Agent tables are missing — run `python3 scripts/run_api_migrations.py` "
                                 "on this environment's database")
    except Exception:
        put_conn(conn, close=True)
        traceback.print_exc()
        raise HTTPException(500, "Failed to load WhatsApp status")


# ── Connection ────────────────────────────────────────────────────────────────

class ConnectionBody(BaseModel):
    use_server_credentials: bool = True
    account_sid: str | None = None
    auth_token: str | None = None
    sender: str | None = None


@router.put("/api/agent/whatsapp/connection")
def put_connection(body: ConnectionBody, request: Request):
    tenant = require_tenant()
    require_role("admin")
    if body.use_server_credentials:
        sid, token = os.getenv("TWILIO_ACCOUNT_SID"), os.getenv("TWILIO_AUTH_TOKEN")
        sender = normalize_e164(os.getenv("TWILIO_WHATSAPP_FROM"))
        secret_ref = "env"
        if not (sid and token and sender):
            raise HTTPException(400, "Server Twilio credentials are not configured (TWILIO_ACCOUNT_SID, "
                                     "TWILIO_AUTH_TOKEN, TWILIO_WHATSAPP_FROM)")
    else:
        sid, token, sender = (body.account_sid or "").strip(), (body.auth_token or "").strip(), normalize_e164(body.sender)
        if not (sid.startswith("AC") and len(sid) == 34):
            raise HTTPException(400, "Account SID must start with AC and be 34 characters")
        if not token or not sender:
            raise HTTPException(400, "Auth token and sender number are required")
        secret_ref = repo.seal_secret(token)
    try:
        acct = check_account(sid, token)
    except SendError as e:
        raise HTTPException(400, str(e))
    except Exception:
        raise HTTPException(502, "Could not reach Twilio to verify the credentials")
    if acct.get("status") != "active":
        raise HTTPException(400, f"Twilio account is {acct.get('status')}")

    conn, cur = _db()
    try:
        existing = repo.get_connection_for_tenant(cur, tenant)
        if existing:
            cur.execute("""
                UPDATE whatsapp_connections
                SET account_sid=%s, sender_e164=%s, secret_ref=%s, signature_failures=0,
                    state = CASE WHEN account_sid=%s AND sender_e164=%s AND state='ACTIVE' THEN 'ACTIVE'
                                 ELSE 'AWAITING_TEST' END,
                    updated_at=now()
                WHERE id=%s RETURNING *
            """, (sid, sender, secret_ref, sid, sender, existing["id"]))
        else:
            cur.execute("""
                INSERT INTO whatsapp_connections (tenant_id, connection_key, account_sid, sender_e164, secret_ref,
                                                  created_by)
                VALUES (%s,%s,%s,%s,%s,%s) RETURNING *
            """, (tenant, repo.new_connection_key(), sid, sender, secret_ref, current_username()))
        row = cur.fetchone()
        conn.commit()
        put_conn(conn)
        return {"connection": _conn_public(row, request), "twilio_account": acct}
    except pg_errors.UniqueViolation:
        conn.rollback()
        put_conn(conn)
        raise HTTPException(409, "This Twilio account + sender is already connected to another workspace. "
                                 "Disconnect it there first.")
    except Exception:
        put_conn(conn, close=True)
        traceback.print_exc()
        raise HTTPException(500, "Failed to save the connection")


@router.delete("/api/agent/whatsapp/connection")
def delete_connection():
    tenant = require_tenant()
    require_role("admin")
    conn, cur = _db()
    try:
        cur.execute("""UPDATE whatsapp_connections SET state='DISCONNECTED', secret_ref='revoked', updated_at=now()
                       WHERE tenant_id=%s AND state <> 'DISCONNECTED'""", (tenant,))
        conn.commit()
        put_conn(conn)
        return {"disconnected": True}
    except Exception:
        put_conn(conn, close=True)
        traceback.print_exc()
        raise HTTPException(500, "Failed to disconnect")


class SettingsBody(BaseModel):
    inbound_enabled: bool | None = None
    outbound_enabled: bool | None = None
    backlog_action: str | None = Field(default=None, pattern="^(drain|discard)$")


@router.patch("/api/agent/whatsapp/settings")
def patch_settings(body: SettingsBody, request: Request):
    tenant = require_tenant()
    require_role("admin")
    conn, cur = _db()
    try:
        c = repo.get_connection_for_tenant(cur, tenant)
        if not c:
            put_conn(conn)
            raise HTTPException(404, "WhatsApp is not connected")
        cur.execute("""
            UPDATE whatsapp_connections
            SET inbound_enabled=COALESCE(%s, inbound_enabled), outbound_enabled=COALESCE(%s, outbound_enabled),
                updated_at=now()
            WHERE id=%s RETURNING *
        """, (body.inbound_enabled, body.outbound_enabled, c["id"]))
        c = cur.fetchone()
        released = 0
        if c["inbound_enabled"] and body.backlog_action == "drain":
            cur.execute("UPDATE whatsapp_media_jobs SET state='PENDING', next_attempt_at=now() "
                        "WHERE tenant_id=%s AND state='HELD'", (tenant,))
            released = cur.rowcount
        elif body.backlog_action == "discard":
            cur.execute("""UPDATE whatsapp_media_jobs SET state='DONE', decision='DISCARDED', finished_at=now(),
                           detail='Discarded by admin while inbound was paused'
                           WHERE tenant_id=%s AND state='HELD'""", (tenant,))
            released = cur.rowcount
        conn.commit()
        put_conn(conn)
        if released and body.backlog_action == "drain":
            from ..whatsapp.worker import wake
            wake()
        return {"connection": _conn_public(c, request), "backlog_changed": released}
    except HTTPException:
        raise
    except Exception:
        put_conn(conn, close=True)
        traceback.print_exc()
        raise HTTPException(500, "Failed to update settings")


# ── Activity ──────────────────────────────────────────────────────────────────

@router.get("/api/agent/whatsapp/events")
def whatsapp_events(brand_id: str | None = Query(default=None), outcome: str | None = Query(default=None),
                    supplier_id: str | None = Query(default=None), limit: int = Query(default=50)):
    tenant = require_tenant()
    bf, bp = _brand_filter(brand_id)
    where, params = ["m.tenant_id=%s", "m.direction='inbound'"], [tenant]
    if outcome:
        where.append("m.outcome=%s"); params.append(outcome.upper())
    if supplier_id:
        where.append("m.supplier_id=%s::uuid"); params.append(supplier_id)
    conn, cur = _db()
    try:
        cur.execute(f"""
            SELECT m.id::text, m.received_at, m.from_e164, m.body, m.num_media, m.outcome, m.outcome_reason,
                   m.supplier_id::text, s.name AS supplier_name, sc.name AS contact_name,
                   COALESCE(json_agg(json_build_object(
                       'id', j.id, 'index', j.media_index, 'state', j.state, 'decision', j.decision,
                       'failure_code', j.failure_code, 'detail', j.detail, 'draft_id', j.draft_id,
                       'attempts', j.attempts) ORDER BY j.media_index) FILTER (WHERE j.id IS NOT NULL), '[]') AS jobs
            FROM whatsapp_messages m
            LEFT JOIN whatsapp_media_jobs j ON j.message_id = m.id
            LEFT JOIN dim_suppliers s ON s.supplier_id = m.supplier_id
            LEFT JOIN supplier_contacts sc ON sc.id = m.contact_id
            WHERE {' AND '.join(where)} {bf}
            GROUP BY m.id, s.name, sc.name
            ORDER BY m.received_at DESC
            LIMIT %s
        """, [*params, *bp, min(max(limit, 1), 200)])
        rows = []
        for r in cur.fetchall():
            rows.append({
                "id": r["id"], "received_at": r["received_at"].isoformat(),
                "sender": mask_phone(r["from_e164"]), "supplier_id": r["supplier_id"],
                "supplier_name": r["supplier_name"], "contact_name": r["contact_name"],
                "text": (r["body"] or "")[:200], "num_media": r["num_media"],
                "outcome": r["outcome"], "reason": r["outcome_reason"], "jobs": r["jobs"],
            })
        put_conn(conn)
        return rows
    except Exception:
        put_conn(conn, close=True)
        traceback.print_exc()
        raise HTTPException(500, "Failed to load WhatsApp activity")


@router.post("/api/agent/whatsapp/refresh")
async def whatsapp_refresh():
    tenant = require_tenant()
    now = time.monotonic()
    if now - _last_refresh.get(tenant, 0) < _REFRESH_EVERY_S:
        return {"drained": 0, "throttled": True}
    _last_refresh[tenant] = now
    from ..whatsapp.worker import drain
    n = await asyncio.to_thread(lambda: asyncio.run(drain(tenant, 20)))
    return {"drained": n, "throttled": False}


def _job_action(job_id: str, sql: str, allowed: tuple[str, ...]):
    tenant = require_tenant()
    conn, cur = _db()
    try:
        cur.execute("SELECT state, decision FROM whatsapp_media_jobs WHERE id=%s AND tenant_id=%s", (job_id, tenant))
        j = cur.fetchone()
        if not j:
            put_conn(conn)
            raise HTTPException(404, "Job not found")
        if j["state"] not in allowed and (j["decision"] or "") not in allowed:
            put_conn(conn)
            raise HTTPException(409, f"Job is {j['state']} ({j['decision'] or '—'}) and can't be changed")
        cur.execute(sql, (job_id, tenant))
        conn.commit()
        put_conn(conn)
        from ..whatsapp.worker import wake
        wake()
        return {"queued": True}
    except HTTPException:
        raise
    except Exception:
        put_conn(conn, close=True)
        traceback.print_exc()
        raise HTTPException(500, "Failed to update job")


@router.post("/api/agent/whatsapp/jobs/{job_id}/retry")
def retry_job(job_id: str):
    return _job_action(job_id, """
        UPDATE whatsapp_media_jobs SET state='PENDING', attempts=0, failure_code=NULL, detail=NULL,
               next_attempt_at=now(), finished_at=NULL
        WHERE id=%s AND tenant_id=%s""", ("DEAD", "UNREADABLE"))


@router.post("/api/agent/whatsapp/jobs/{job_id}/draft-anyway")
def draft_anyway(job_id: str):
    return _job_action(job_id, """
        UPDATE whatsapp_media_jobs SET state='PENDING', attempts=0, force_bill=true, failure_code=NULL,
               detail=NULL, decision=NULL, next_attempt_at=now(), finished_at=NULL
        WHERE id=%s AND tenant_id=%s""", ("LOW_CONFIDENCE", "NOT_A_BILL"))


# ── Contacts + watch ──────────────────────────────────────────────────────────

@router.get("/api/agent/whatsapp/contacts")
def whatsapp_contacts(brand_id: str | None = Query(default=None)):
    tenant = require_tenant()
    bf, bp = _brand_filter(brand_id)
    conn, cur = _db()
    try:
        cur.execute(f"""
            SELECT c.id::text, c.supplier_id::text, c.name, c.role, c.phone, s.name AS supplier_name,
                   w.phone_e164, COALESCE(w.watch_enabled, false) AS watch_enabled, w.consent, w.last_inbound_at
            FROM supplier_contacts c
            LEFT JOIN dim_suppliers s ON s.supplier_id = c.supplier_id
            LEFT JOIN whatsapp_contact_watches w ON w.contact_id = c.id AND w.tenant_id = c.tenant_id
            WHERE c.tenant_id=%s AND (COALESCE(c.phone,'') <> '' OR w.id IS NOT NULL) {bf}
            ORDER BY COALESCE(w.watch_enabled, false) DESC, s.name ASC NULLS LAST, c.name ASC
        """, [tenant, *bp])
        out = []
        for r in cur.fetchall():
            last = r["last_inbound_at"]
            out.append({
                "id": r["id"], "supplier_id": r["supplier_id"], "name": r["name"], "role": r["role"],
                "supplier_name": r["supplier_name"],
                "phone": r["phone_e164"] or normalize_e164(r["phone"]) or r["phone"],
                "watch_enabled": r["watch_enabled"], "consent": r["consent"] or "UNKNOWN",
                "last_inbound_at": last.isoformat() if last else None,
                "window_open": bool(last and (time.time() - last.timestamp()) < WINDOW.total_seconds()),
            })
        put_conn(conn)
        return out
    except Exception:
        put_conn(conn, close=True)
        traceback.print_exc()
        raise HTTPException(500, "Failed to load contacts")


class WatchBody(BaseModel):
    enabled: bool
    phone: str | None = None


@router.patch("/api/vendors/{supplier_id}/contacts/{contact_id}/whatsapp-watch")
def set_whatsapp_watch(supplier_id: str, contact_id: str, body: WatchBody):
    tenant = require_tenant()
    conn, cur = _db()
    try:
        cur.execute("SELECT phone FROM supplier_contacts WHERE id=%s AND supplier_id=%s AND tenant_id=%s",
                    (contact_id, supplier_id, tenant))
        contact = cur.fetchone()
        if not contact:
            put_conn(conn)
            raise HTTPException(404, "Contact not found")
        phone = normalize_e164(body.phone or contact["phone"])
        if body.enabled and not phone:
            put_conn(conn)
            raise HTTPException(422, "A valid WhatsApp number is required, e.g. +919876543210")
        if body.enabled:
            cur.execute("""
                SELECT w.contact_id::text, c.name, s.name AS supplier_name
                FROM whatsapp_contact_watches w
                JOIN supplier_contacts c ON c.id = w.contact_id
                LEFT JOIN dim_suppliers s ON s.supplier_id = w.supplier_id
                WHERE w.tenant_id=%s AND w.phone_e164=%s AND w.watch_enabled AND w.contact_id <> %s
            """, (tenant, phone, contact_id))
            clash = cur.fetchone()
            if clash:
                put_conn(conn)
                raise HTTPException(409, f"{phone} is already watched for {clash['name']}"
                                         f"{' at ' + clash['supplier_name'] if clash['supplier_name'] else ''}. "
                                         "Turn that watch off first.")
            if not contact["phone"]:
                cur.execute("UPDATE supplier_contacts SET phone=%s WHERE id=%s AND tenant_id=%s",
                            (phone, contact_id, tenant))
        cur.execute("""
            INSERT INTO whatsapp_contact_watches (tenant_id, supplier_id, contact_id, phone_e164, watch_enabled)
            VALUES (%s,%s,%s,%s,%s)
            ON CONFLICT (tenant_id, contact_id) DO UPDATE
              SET watch_enabled=EXCLUDED.watch_enabled,
                  phone_e164=CASE WHEN EXCLUDED.watch_enabled THEN EXCLUDED.phone_e164
                                  ELSE whatsapp_contact_watches.phone_e164 END,
                  supplier_id=EXCLUDED.supplier_id, updated_at=now()
            RETURNING watch_enabled, phone_e164
        """, (tenant, supplier_id, contact_id, phone or "", body.enabled))
        row = cur.fetchone()
        conn.commit()
        put_conn(conn)
        return {"watch_enabled": row["watch_enabled"], "phone": row["phone_e164"]}
    except HTTPException:
        raise
    except pg_errors.UniqueViolation:
        conn.rollback()
        put_conn(conn)
        raise HTTPException(409, "That number is already watched for another contact")
    except Exception:
        put_conn(conn, close=True)
        traceback.print_exc()
        raise HTTPException(500, "Failed to update WhatsApp watch")


# ── Vendor conversations + replies ────────────────────────────────────────────

@router.get("/api/vendors/{supplier_id}/whatsapp/conversations")
def vendor_conversations(supplier_id: str, contact_id: str | None = Query(default=None)):
    tenant = require_tenant()
    conn, cur = _db()
    try:
        params = [tenant, supplier_id]
        extra = ""
        if contact_id:
            extra = " AND m.contact_id=%s::uuid"
            params.append(contact_id)
        cur.execute(f"""
            SELECT m.id::text, m.direction, m.body, m.num_media, m.outcome, m.outcome_reason,
                   m.provider_status, m.error_code, m.sent_by, m.received_at, m.contact_id::text,
                   COALESCE(json_agg(json_build_object('id', j.id, 'decision', j.decision, 'state', j.state,
                            'draft_id', j.draft_id, 'detail', j.detail)) FILTER (WHERE j.id IS NOT NULL), '[]') AS jobs
            FROM whatsapp_messages m
            LEFT JOIN whatsapp_media_jobs j ON j.message_id = m.id
            WHERE m.tenant_id=%s AND m.supplier_id=%s::uuid {extra}
            GROUP BY m.id
            ORDER BY m.received_at DESC
            LIMIT 200
        """, params)
        msgs = [{
            "id": r["id"], "direction": r["direction"], "body": r["body"], "num_media": r["num_media"],
            "outcome": r["outcome"], "reason": r["outcome_reason"], "status": r["provider_status"],
            "error": r["error_code"], "sent_by": r["sent_by"], "at": r["received_at"].isoformat(),
            "contact_id": r["contact_id"], "jobs": r["jobs"],
        } for r in cur.fetchall()]
        msgs.reverse()
        put_conn(conn)
        return {"messages": msgs}
    except Exception:
        put_conn(conn, close=True)
        traceback.print_exc()
        raise HTTPException(500, "Failed to load WhatsApp conversation")


class ReplyBody(BaseModel):
    contact_id: str
    body: str
    op_key: str | None = None


@router.post("/api/vendors/{supplier_id}/whatsapp/reply")
async def vendor_reply(supplier_id: str, body: ReplyBody, request: Request):
    tenant = require_tenant()
    user = current_username()
    op_key = body.op_key or str(uuid.uuid4())
    conn, cur = _db()
    try:
        c = repo.get_connection_for_tenant(cur, tenant)
    finally:
        put_conn(conn)
    status_cb = repo.webhook_urls(c["connection_key"], request)["status"] if c else None
    try:
        return await asyncio.to_thread(send_reply, tenant, supplier_id, body.contact_id, body.body, op_key,
                                       user, status_cb)
    except PolicyError as e:
        raise HTTPException(422, {"code": e.code, "message": e.message})
    except Exception:
        traceback.print_exc()
        raise HTTPException(500, "Failed to send the WhatsApp message")
