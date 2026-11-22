"""Signed inbound webhook → message + media jobs, in one transaction.

Persist first, acknowledge second (LLD §6.1). The webhook never downloads media
or calls a model; it only verifies, triages and queues, so the acknowledgement
stays fast and a crash after commit loses nothing.
"""
from __future__ import annotations

import logging

from psycopg2.extras import RealDictCursor

from ..config import get_conn, put_conn
from . import repo
from .twilio import mask_phone, normalize_e164, verify_signature

log = logging.getLogger("whatsapp.ingress")

EMPTY_TWIML = '<?xml version="1.0" encoding="UTF-8"?><Response></Response>'

_PDF_TYPES = {"application/pdf", "application/x-pdf"}
_STOP_WORDS = {"stop", "unsubscribe", "stopall", "cancel", "end", "quit"}
_START_WORDS = {"start", "unstop", "yes"}


class IngressResult:
    def __init__(self, status: int, body: str = EMPTY_TWIML, outcome: str | None = None):
        self.status = status
        self.body = body
        self.outcome = outcome


def handle_inbound(connection_key: str, url: str, form: list[tuple[str, str]], signature: str | None) -> IngressResult:
    params = dict(form)  # single-valued view; verification uses the full multi list
    conn = get_conn()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        c = repo.get_connection_by_key(cur, connection_key)
        if not c:
            put_conn(conn)
            return IngressResult(404, "")

        token = repo.auth_token_for(c)
        to_e164 = normalize_e164(params.get("To"))
        if (not verify_signature(token or "", url, form, signature)
                or params.get("AccountSid") != c["account_sid"]
                or to_e164 != c["sender_e164"]):
            cur.execute("UPDATE whatsapp_connections SET signature_failures = signature_failures + 1,"
                        " updated_at=now() WHERE id=%s", (c["id"],))
            conn.commit()
            put_conn(conn)
            log.warning("whatsapp webhook rejected: bad signature/account/sender connection=%s", c["id"])
            return IngressResult(403, "")

        tenant_id = str(c["tenant_id"])
        sid = params.get("MessageSid") or params.get("SmsMessageSid")
        from_e164 = normalize_e164(params.get("From"))
        body = (params.get("Body") or "")[:4000]
        try:
            num_media = int(params.get("NumMedia") or 0)
        except ValueError:
            num_media = 0

        cur.execute("""
            INSERT INTO whatsapp_messages
                (tenant_id, connection_id, direction, message_sid, from_e164, to_e164, body, num_media)
            VALUES (%s,%s,'inbound',%s,%s,%s,%s,%s)
            ON CONFLICT (connection_id, message_sid) WHERE message_sid IS NOT NULL DO NOTHING
            RETURNING id::text
        """, (tenant_id, c["id"], sid, from_e164, to_e164, body, num_media))
        row = cur.fetchone()
        if not row:                       # Twilio retry of a message we already have
            conn.rollback()
            put_conn(conn)
            return IngressResult(200, outcome="REPLAY")
        msg_id = row["id"]

        # First signed message proves the webhook URL + token are right.
        cur.execute("""
            UPDATE whatsapp_connections
            SET last_inbound_at=now(), updated_at=now(),
                state = CASE WHEN state IN ('AWAITING_TEST','NEEDS_ATTENTION') THEN 'ACTIVE' ELSE state END
            WHERE id=%s
        """, (c["id"],))

        outcome, reason, watch, jobs = _triage(cur, c, tenant_id, from_e164, body, num_media, params)

        cur.execute("""
            UPDATE whatsapp_messages
            SET outcome=%s, outcome_reason=%s, watch_id=%s, supplier_id=%s, contact_id=%s, updated_at=now()
            WHERE id=%s
        """, (outcome, reason, watch["id"] if watch else None, watch["supplier_id"] if watch else None,
              watch["contact_id"] if watch else None, msg_id))

        held = not c["inbound_enabled"]
        for idx, url_, ctype in jobs:
            cur.execute("""
                INSERT INTO whatsapp_media_jobs (tenant_id, message_id, media_index, media_url, content_type, state)
                VALUES (%s,%s,%s,%s,%s,%s)
                ON CONFLICT (message_id, media_index) DO NOTHING
            """, (tenant_id, msg_id, idx, url_, ctype, "HELD" if held else "PENDING"))

        if watch:
            # A vendor messaging us opts in to replies; STOP opts out and sticks
            # until they send START.
            word = body.strip().lower()
            consent = watch["consent"]
            if word in _STOP_WORDS:
                consent = "OPTED_OUT"
            elif consent != "OPTED_OUT" or word in _START_WORDS:
                consent = "OPTED_IN"
            cur.execute("""
                UPDATE whatsapp_contact_watches
                SET last_inbound_at=now(), updated_at=now(),
                    consent_at = CASE WHEN consent=%s THEN consent_at ELSE now() END,
                    consent=%s
                WHERE id=%s
            """, (consent, consent, watch["id"]))

        comm_msg_id = None
        if watch and c["inbound_enabled"] and _carries_terms(body, num_media):
            comm_msg_id = _hand_to_communication_agent(cur, tenant_id, watch, sid, from_e164, body)
            if comm_msg_id and outcome == "TEXT_ONLY":
                cur.execute("UPDATE whatsapp_messages SET outcome_reason=%s WHERE id=%s",
                            ("Sent to the Communication Agent — any terms it finds go to Review Hub", msg_id))

        conn.commit()
        put_conn(conn)
        if comm_msg_id:
            try:
                from ..domain import fact_graph
                fact_graph.enqueue(fact_graph.enrich_email, tenant_id, comm_msg_id)
            except Exception:
                log.exception("whatsapp: fact graph enqueue failed for %s", comm_msg_id)
        log.info("whatsapp inbound tenant=%s from=%s outcome=%s media=%s jobs=%s",
                 tenant_id, mask_phone(from_e164), outcome, num_media, len(jobs))
        if jobs and not held:
            from .worker import wake
            wake()
        return IngressResult(200, outcome=outcome)
    except Exception:
        log.exception("whatsapp inbound failed; returning 500 so Twilio retries")
        try:
            conn.rollback()
        except Exception:
            pass
        put_conn(conn, close=True)
        return IngressResult(500, "")


def _carries_terms(body: str, num_media: int) -> bool:
    """Whether a message's text is worth reading for terms. Skips opt-in/out
    keywords, one-word pings and a caption that is just the attachment's name."""
    text = (body or "").strip()
    if len(text) < 8 or text.lower() in _STOP_WORDS | _START_WORDS:
        return False
    if num_media and " " not in text and "." in text[-6:]:
        return False  # "26GJKMWSI15224.pdf"
    return True


def _hand_to_communication_agent(cur, tenant_id, watch, sid, from_e164, body) -> str | None:
    """Queue a watched vendor's WhatsApp text for the same claim extraction the
    email agent's messages get (comm_extraction_worker reads poc_email_messages;
    its insert trigger wakes the worker). Terms it finds — a fee, a payment
    condition, bank details — become Review Hub findings exactly as from email.
    Best-effort: a failure here never costs the message itself."""
    try:
        cur.execute("SAVEPOINT wa_comm")
        cur.execute("""
            INSERT INTO poc_email_messages
                (tenant_id, supplier_id, contact_id, direction, gmail_msg_id, thread_id,
                 from_email, subject, body, sent_at)
            VALUES (%s,%s,%s,'inbound',%s,%s,%s,%s,%s,now())
            ON CONFLICT (tenant_id, gmail_msg_id, direction) WHERE gmail_msg_id IS NOT NULL DO NOTHING
            RETURNING message_id::text
        """, (tenant_id, watch["supplier_id"], watch["contact_id"], f"wa:{sid}", f"wa:{from_e164}",
              f"whatsapp:{from_e164}", "WhatsApp message", body))
        row = cur.fetchone()
        if row:
            cur.execute("SELECT pg_notify('ch_comm_extract', %s)", (row["message_id"],))
        cur.execute("RELEASE SAVEPOINT wa_comm")
        return row["message_id"] if row else None
    except Exception:
        cur.execute("ROLLBACK TO SAVEPOINT wa_comm")
        log.exception("whatsapp: could not queue text for the Communication Agent")
        return None


def _triage(cur, c, tenant_id, from_e164, body, num_media, params):
    """Decide the message outcome and which attachments become jobs."""
    if not repo.licensed(tenant_id):
        return "LICENSE_INACTIVE", "WhatsApp Agent is not enabled for this workspace", None, []
    if not from_e164:
        return "UNWATCHED", "Sender number could not be read", None, []

    watches = repo.active_watches_for_phone(cur, tenant_id, from_e164)
    suppliers = {w["supplier_id"] for w in watches}
    if not watches:
        # Unwatched: keep minimal metadata, never fetch media (PRD FR-7).
        return "UNWATCHED", "Sender is not a watched vendor contact", None, []
    if len(suppliers) > 1:
        return "AMBIGUOUS_CONTACT", "Number is watched for more than one vendor", None, []
    watch = watches[0]

    if num_media == 0:
        return "TEXT_ONLY", "No attachment — message kept on the vendor timeline", watch, []

    jobs, unsupported = [], []
    for i in range(min(num_media, 10)):
        url = params.get(f"MediaUrl{i}")
        ctype = (params.get(f"MediaContentType{i}") or "").lower()
        if not url:
            continue
        if ctype in _PDF_TYPES:
            jobs.append((i, url, ctype))
        else:
            unsupported.append(ctype or "unknown")
    if not jobs:
        return ("UNSUPPORTED_MEDIA",
                f"Only PDF invoices are processed (got {', '.join(sorted(set(unsupported)))}) — ask the vendor to send a PDF",
                watch, [])
    if not c["inbound_enabled"]:
        return "PAUSED", "Inbound paused by admin — held until resume", watch, jobs
    reason = f"{len(jobs)} PDF queued" + (f", {len(unsupported)} unsupported skipped" if unsupported else "")
    return "QUEUED", reason, watch, jobs
