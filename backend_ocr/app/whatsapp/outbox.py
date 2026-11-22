"""Outbound replies: policy, idempotent send, status projection, reconciliation.

A send whose HTTP result is lost may still have gone out, so it is marked
UNKNOWN and reconciled from Twilio's message list — never blindly retried
(edge case H3).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from psycopg2.extras import RealDictCursor

from ..config import get_conn, put_conn
from . import repo
from .twilio import SendError, list_recent, mask_phone, map_status, next_status, send_message

log = logging.getLogger("whatsapp.outbox")

WINDOW = timedelta(hours=24)


class PolicyError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def evaluate_policy(c: dict | None, watch: dict | None, now: datetime) -> None:
    if not c:
        raise PolicyError("NOT_CONNECTED", "WhatsApp is not connected for this workspace")
    if not c["outbound_enabled"]:
        raise PolicyError("OUTBOUND_PAUSED", "Outbound messages are paused by an admin")
    if not watch:
        raise PolicyError("NOT_WATCHED", "This contact is not set up for WhatsApp")
    if watch["consent"] == "OPTED_OUT":
        raise PolicyError("OPTED_OUT", "The vendor opted out (sent STOP). They must send START first")
    last = watch.get("last_inbound_at")
    if not last or now - last > WINDOW:
        raise PolicyError("WINDOW_CLOSED",
                          "Outside WhatsApp's 24-hour reply window — the vendor must message first "
                          "(approved templates are needed to start a conversation)")


def send_reply(tenant_id: str, supplier_id: str, contact_id: str, body: str, op_key: str,
               sent_by: str | None, status_callback_base: str | None) -> dict:
    body = (body or "").strip()
    if not body:
        raise PolicyError("EMPTY", "Message is empty")
    if len(body) > 1600:
        raise PolicyError("TOO_LONG", "Message is longer than 1600 characters")

    conn = get_conn()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        # Idempotent on op_key: a double click returns the first attempt.
        cur.execute("SELECT * FROM whatsapp_messages WHERE tenant_id=%s AND op_key=%s", (tenant_id, op_key))
        existing = cur.fetchone()
        if existing:
            put_conn(conn)
            return _public(existing)

        c = repo.get_connection_for_tenant(cur, tenant_id)
        cur.execute("""SELECT * FROM whatsapp_contact_watches
                       WHERE tenant_id=%s AND supplier_id=%s AND contact_id=%s AND watch_enabled""",
                    (tenant_id, supplier_id, contact_id))
        watch = cur.fetchone()
        evaluate_policy(c, watch, datetime.now(timezone.utc))

        cur.execute("""
            INSERT INTO whatsapp_messages
                (tenant_id, connection_id, direction, op_key, from_e164, to_e164, watch_id, supplier_id,
                 contact_id, body, outcome, provider_status, sent_by)
            VALUES (%s,%s,'outbound',%s,%s,%s,%s,%s,%s,%s,'SENDING','QUEUED',%s)
            ON CONFLICT (tenant_id, op_key) WHERE op_key IS NOT NULL DO NOTHING
            RETURNING *
        """, (tenant_id, c["id"], op_key, c["sender_e164"], watch["phone_e164"], watch["id"], supplier_id,
              contact_id, body, sent_by))
        row = cur.fetchone()
        conn.commit()
        if not row:
            cur.execute("SELECT * FROM whatsapp_messages WHERE tenant_id=%s AND op_key=%s", (tenant_id, op_key))
            r = cur.fetchone()
            put_conn(conn)
            return _public(r)

        cb = f"{status_callback_base}" if status_callback_base else None
        try:
            data = send_message(c["account_sid"], repo.auth_token_for(c) or "", c["sender_e164"],
                                watch["phone_e164"], body, cb)
            status, sid, err = map_status(data.get("status")) or "QUEUED", data.get("sid"), None
            outcome = "SENT"
        except SendError as e:
            sid = None
            status = "UNKNOWN" if e.unknown else "FAILED"
            err = f"{e.code}: {e}"[:300]
            outcome = "UNKNOWN" if e.unknown else "FAILED"
            log.warning("whatsapp send to %s %s: %s", mask_phone(watch["phone_e164"]), status, err)
        cur.execute("""
            UPDATE whatsapp_messages SET message_sid=%s, provider_status=%s, error_code=%s, outcome=%s,
                   updated_at=now()
            WHERE id=%s RETURNING *
        """, (sid, status, err, outcome, row["id"]))
        row = cur.fetchone()
        conn.commit()
        put_conn(conn)
        return _public(row)
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        put_conn(conn)
        raise


def apply_status_callback(connection_key: str, params: dict) -> bool:
    sid = params.get("MessageSid") or params.get("SmsSid")
    status = map_status(params.get("MessageStatus") or params.get("SmsStatus"))
    if not sid:
        return False
    conn = get_conn()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        c = repo.get_connection_by_key(cur, connection_key)
        if not c:
            put_conn(conn)
            return False
        cur.execute("SELECT id, provider_status FROM whatsapp_messages WHERE connection_id=%s AND message_sid=%s"
                    " FOR UPDATE", (c["id"], sid))
        m = cur.fetchone()
        cur.execute("""
            INSERT INTO whatsapp_status_events (tenant_id, message_id, provider_sid, status, error_code)
            VALUES (%s,%s,%s,%s,%s) ON CONFLICT (provider_sid, status) DO NOTHING
        """, (c["tenant_id"], m["id"] if m else None, sid, status, params.get("ErrorCode")))
        if m:
            nxt = next_status(m["provider_status"], status)
            err = params.get("ErrorCode")
            cur.execute("""UPDATE whatsapp_messages SET provider_status=%s,
                           error_code=COALESCE(%s, error_code), updated_at=now() WHERE id=%s""",
                        (nxt, f"{err}: {params.get('ErrorMessage') or 'delivery failed'}" if err else None, m["id"]))
        conn.commit()
        put_conn(conn)
        return True
    except Exception:
        conn.rollback()
        put_conn(conn, close=True)
        raise


def reconcile_unknown() -> int:
    """Resolve UNKNOWN sends older than 2 minutes from Twilio's message list."""
    conn = get_conn()
    fixed = 0
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("""
            SELECT m.*, c.account_sid, c.secret_ref FROM whatsapp_messages m
            JOIN whatsapp_connections c ON c.id = m.connection_id
            WHERE m.provider_status='UNKNOWN' AND m.direction='outbound'
              AND m.updated_at < now() - interval '2 minutes'
            LIMIT 20
        """)
        for m in cur.fetchall():
            try:
                recent = list_recent(m["account_sid"], repo.auth_token_for(m) or "", m["to_e164"], m["from_e164"])
            except Exception:
                continue
            match = next((r for r in recent if (r.get("body") or "").strip() == (m["body"] or "").strip()), None)
            age = datetime.now(timezone.utc) - m["received_at"]
            if match:
                cur.execute("""UPDATE whatsapp_messages SET message_sid=%s, provider_status=%s, outcome='SENT',
                               error_code=NULL, updated_at=now() WHERE id=%s AND message_sid IS NULL""",
                            (match["sid"], map_status(match.get("status")), m["id"]))
                fixed += 1
            elif age > timedelta(minutes=15):
                cur.execute("""UPDATE whatsapp_messages SET provider_status='FAILED', outcome='FAILED',
                               error_code='RECONCILE_NOT_FOUND: Twilio has no record — safe to resend',
                               updated_at=now() WHERE id=%s""", (m["id"],))
                fixed += 1
        conn.commit()
    finally:
        put_conn(conn)
    return fixed


def _public(r: dict | None) -> dict:
    if not r:
        return {}
    return {
        "id": str(r["id"]),
        "direction": r["direction"],
        "body": r["body"],
        "status": r.get("provider_status"),
        "error": r.get("error_code"),
        "sent_by": r.get("sent_by"),
        "at": r["received_at"].isoformat() if r.get("received_at") else None,
    }
