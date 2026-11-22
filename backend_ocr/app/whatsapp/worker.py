"""WhatsApp intake worker — drains whatsapp_media_jobs with leases.

  * claim: UPDATE … WHERE id IN (SELECT … FOR UPDATE SKIP LOCKED); an expired
    CLAIMED lease is reclaimable, so a crashed worker loses nothing (edge case F1)
  * finish: fenced by lease_token — a slow worker whose lease was taken over
    updates 0 rows and its work is discarded (edge case F3)
  * draft insert and job finish commit in ONE transaction
  * retries: exponential backoff with jitter, DEAD after WA_MAX_ATTEMPTS

Runs in a daemon thread with its own event loop (same pattern as the email
poller). On by default; set WA_WORKER_ENABLED=false on instances that should
not process jobs. Several instances are safe together (SKIP LOCKED + leases).
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import random
import threading
import time
import traceback
from datetime import timedelta
from pathlib import Path

from psycopg2.extras import RealDictCursor

from ..config import get_conn, put_conn
from . import repo
from .intake import Provenance, RetryableIntakeError, classify, decide_and_draft, pdf_text, store_contract
from .twilio import MediaError, fetch_media, is_pdf, mask_phone

log = logging.getLogger("whatsapp.worker")

ENABLED = os.getenv("WA_WORKER_ENABLED", "true").strip().lower() in ("1", "true", "yes", "on")
CONCURRENCY = int(os.getenv("WA_WORKER_CONCURRENCY", "2"))
LEASE_SECONDS = int(os.getenv("WA_LEASE_SECONDS", "600"))
MAX_ATTEMPTS = int(os.getenv("WA_MAX_ATTEMPTS", "5"))
OCR_MAX_ATTEMPTS = 3
IDLE_POLL_S = float(os.getenv("WA_WORKER_POLL_S", "15"))

_wake = threading.Event()
_started = False


def wake() -> None:
    _wake.set()


def backoff(attempts: int) -> timedelta:
    base = min(30 * (2 ** max(attempts - 1, 0)), 1800)
    return timedelta(seconds=base * random.uniform(0.8, 1.2))


# ── Queue primitives ──────────────────────────────────────────────────────────

def claim(cur, conn, limit: int, tenant_id: str | None = None) -> list[dict]:
    scope = "AND tenant_id = %(tenant)s" if tenant_id else ""
    cur.execute(f"""
        UPDATE whatsapp_media_jobs j
        SET state='CLAIMED', lease_token=gen_random_uuid(),
            lease_expires_at = now() + make_interval(secs => %(lease)s),
            attempts = attempts + 1
        WHERE j.id IN (
            SELECT id FROM whatsapp_media_jobs
            WHERE ((state IN ('PENDING','RETRY_WAIT') AND next_attempt_at <= now())
                   OR (state='CLAIMED' AND lease_expires_at < now()))
              {scope}
            ORDER BY created_at
            LIMIT %(limit)s
            FOR UPDATE SKIP LOCKED)
        RETURNING j.*
    """, {"lease": LEASE_SECONDS, "limit": limit, "tenant": tenant_id})
    rows = cur.fetchall()
    conn.commit()
    return rows


def _finish(cur, job: dict, state: str, *, decision=None, failure_code=None, detail=None,
            draft_id=None, sha=None, source_file=None, next_in: timedelta | None = None) -> bool:
    cur.execute("""
        UPDATE whatsapp_media_jobs
        SET state=%s, decision=COALESCE(%s, decision), failure_code=%s, detail=%s,
            draft_id=COALESCE(%s, draft_id), content_sha256=COALESCE(%s, content_sha256),
            source_file=COALESCE(%s, source_file),
            next_attempt_at = CASE WHEN %s::interval IS NULL THEN next_attempt_at ELSE now() + %s::interval END,
            finished_at = CASE WHEN %s IN ('DONE','DEAD','QUARANTINED') THEN now() ELSE NULL END,
            lease_token = NULL, lease_expires_at = NULL
        WHERE id=%s AND lease_token=%s
    """, (state, decision, failure_code, (detail or "")[:500] or None, draft_id, sha, source_file,
          next_in, next_in, state, job["id"], job["lease_token"]))
    return cur.rowcount == 1


def _roll_up_message(cur, message_id) -> None:
    """Message outcome follows its jobs once none is still in flight."""
    cur.execute("""
        UPDATE whatsapp_messages m SET outcome='PROCESSED', updated_at=now()
        WHERE m.id=%s AND m.outcome IN ('QUEUED','PAUSED')
          AND NOT EXISTS (SELECT 1 FROM whatsapp_media_jobs j WHERE j.message_id=m.id
                          AND j.state IN ('PENDING','HELD','CLAIMED','RETRY_WAIT'))
    """, (message_id,))


# ── One job ───────────────────────────────────────────────────────────────────

async def process(job: dict) -> str:
    conn = get_conn()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        result = await _process(conn, cur, job)
        _roll_up_message(cur, job["message_id"])
        conn.commit()
        return result
    except Exception:
        log.exception("whatsapp job %s crashed", job["id"])
        try:
            conn.rollback()
            cur = conn.cursor(cursor_factory=RealDictCursor)
            dead = job["attempts"] >= MAX_ATTEMPTS
            _finish(cur, job, "DEAD" if dead else "RETRY_WAIT", failure_code="INTERNAL_ERROR",
                    detail=traceback.format_exc(limit=1)[-300:], next_in=None if dead else backoff(job["attempts"]))
            conn.commit()
        except Exception:
            traceback.print_exc()
        return "error"
    finally:
        put_conn(conn)


def _retry_or_dead(cur, job, code, detail, max_attempts=MAX_ATTEMPTS) -> str:
    if job["attempts"] >= max_attempts:
        _finish(cur, job, "DEAD", failure_code=code, detail=detail)
        return "dead"
    _finish(cur, job, "RETRY_WAIT", failure_code=code, detail=detail, next_in=backoff(job["attempts"]))
    return "retry"


async def _process(conn, cur, job: dict) -> str:
    tenant_id = str(job["tenant_id"])
    cur.execute("SELECT * FROM whatsapp_messages WHERE id=%s", (job["message_id"],))
    msg = cur.fetchone()
    c = repo.get_connection_by_id(cur, msg["connection_id"]) if msg else None

    # ── Guard: re-check scope before touching media (LLD §6.2) ────────────────
    if not msg or not c or c["state"] == "DISCONNECTED":
        _finish(cur, job, "DONE", decision="SKIPPED", failure_code="CONNECTION_GONE", detail="Connection disconnected")
        return "skipped"
    if not c["inbound_enabled"]:
        cur.execute("UPDATE whatsapp_media_jobs SET state='HELD', lease_token=NULL, lease_expires_at=NULL,"
                    " attempts=GREATEST(attempts-1,0) WHERE id=%s AND lease_token=%s",
                    (job["id"], job["lease_token"]))
        return "held"
    if not repo.licensed(tenant_id):
        _finish(cur, job, "DONE", decision="SKIPPED", failure_code="LICENSE_INACTIVE",
                detail="WhatsApp Agent not enabled for this workspace")
        return "skipped"
    cur.execute("""SELECT w.*, c.name AS contact_name FROM whatsapp_contact_watches w
                   JOIN supplier_contacts c ON c.id=w.contact_id
                   WHERE w.id=%s AND w.watch_enabled""", (msg["watch_id"],))
    watch = cur.fetchone()
    if not watch:
        _finish(cur, job, "DONE", decision="SKIPPED", failure_code="UNWATCHED",
                detail="Contact is no longer watched — media not downloaded")
        return "skipped"
    conn.commit()

    prov = Provenance(
        tenant_id=tenant_id, channel="whatsapp",
        source_ref=f"{msg['message_sid']}:{job['media_index']}",
        idempotency_key=f"whatsapp:{c['id']}:{msg['message_sid']}:{job['media_index']}",
        supplier_id=str(watch["supplier_id"]), contact_id=str(watch["contact_id"]),
        sender_masked=mask_phone(msg["from_e164"]),
        conversation_key=f"wa:{c['id']}:{msg['from_e164']}",
        caption=(msg["body"] or "").strip(),
    )

    # Already drafted by an earlier attempt whose finish was lost?
    cur.execute("SELECT id::text FROM agent_draft_bills WHERE tenant_id=%s AND idempotency_key=%s",
                (tenant_id, prov.idempotency_key))
    prior = cur.fetchone()
    if prior:
        _finish(cur, job, "DONE", decision="DRAFTED", draft_id=prior["id"], detail="Draft already created")
        return "done"

    # ── Fetch media ───────────────────────────────────────────────────────────
    token = repo.auth_token_for(c)
    try:
        media = await asyncio.to_thread(fetch_media, job["media_url"], c["account_sid"], token or "")
    except MediaError as e:
        if e.retryable:
            return _retry_or_dead(cur, job, e.code, str(e))
        _finish(cur, job, "DEAD", failure_code=e.code, detail=str(e))
        return "dead"
    if not is_pdf(media.data):
        _finish(cur, job, "DEAD", failure_code="MEDIA_NOT_PDF", detail="File is not a real PDF")
        return "dead"

    sha = hashlib.sha256(media.data).hexdigest()
    from ..core import object_store
    from ..core.storage import UPLOADS_DIR
    source_file = f"wa_{sha[:16]}_{job['media_index']}.pdf"
    path = Path(UPLOADS_DIR) / source_file
    path.write_bytes(media.data)
    if object_store.enabled():
        try:
            object_store.save(object_store.key("agent-drafts", tenant_id, source_file), media.data,
                              "application/pdf", local_backup=False)
        except Exception:
            traceback.print_exc()

    # ── Readability + classification ──────────────────────────────────────────
    try:
        text, encrypted = await asyncio.to_thread(pdf_text, str(path))
    except ValueError as e:
        _finish(cur, job, "DONE", decision="UNREADABLE", failure_code="PDF_CORRUPT", detail=str(e)[:200],
                sha=sha, source_file=source_file)
        return "done"
    if encrypted:
        _finish(cur, job, "DONE", decision="UNREADABLE", failure_code="PDF_ENCRYPTED",
                detail="PDF is password-protected — ask the vendor for an unlocked copy", sha=sha,
                source_file=source_file)
        return "done"

    if not job.get("force_bill"):
        try:
            kind, conf, reason = await asyncio.to_thread(classify, prov.caption, text)
        except RetryableIntakeError as e:
            return _retry_or_dead(cur, job, e.code, str(e))
        if kind == "contract":
            doc_id = store_contract(cur, tenant_id, prov.supplier_id, f"whatsapp_{source_file}", media.data)
            _finish(cur, job, "DONE", decision="CONTRACT", detail=f"Saved to vendor documents ({doc_id}) — {reason}",
                    sha=sha, source_file=source_file)
            return "done"
        if kind == "other":
            _finish(cur, job, "DONE", decision="NOT_A_BILL", detail=reason, sha=sha, source_file=source_file)
            return "done"
        if kind == "low":
            _finish(cur, job, "DONE", decision="LOW_CONFIDENCE",
                    detail=f"Not sure this is a bill ({conf:.2f}) — {reason}. Use 'Draft anyway' if it is.",
                    sha=sha, source_file=source_file)
            return "done"

    # ── OCR ───────────────────────────────────────────────────────────────────
    from ..integrations.ocr import process_pdf_async
    try:
        ocr = await process_pdf_async(str(path))
        ocr["_source_file"] = source_file
    except Exception as e:
        if job["attempts"] < OCR_MAX_ATTEMPTS:
            return _retry_or_dead(cur, job, "OCR_FAILED", str(e)[:200])
        _finish(cur, job, "DONE", decision="UNREADABLE", failure_code="OCR_FAILED", detail=str(e)[:200],
                sha=sha, source_file=source_file)
        return "done"

    # ── Dedupe + draft + finish: one transaction ──────────────────────────────
    res = decide_and_draft(cur, prov, source_file, sha, ocr)
    ok = _finish(cur, job, "DONE", decision=res.decision, draft_id=res.draft_id or res.related_draft_id,
                 detail=res.reason, sha=sha, source_file=source_file)
    if not ok:
        conn.rollback()        # lease lost: another worker owns this job now
        return "lease_lost"
    cur.execute("UPDATE whatsapp_connections SET last_processed_at=now() WHERE id=%s", (c["id"],))
    log.info("whatsapp job %s tenant=%s decision=%s draft=%s", job["id"], tenant_id, res.decision, res.draft_id)
    return res.decision.lower()


# ── Drain + loop ──────────────────────────────────────────────────────────────

async def drain(tenant_id: str | None = None, limit: int = 20) -> int:
    """Process up to `limit` ready jobs (optionally for one tenant). Used by the
    loop and by the Agent Hub Refresh button."""
    done = 0
    while done < limit:
        conn = get_conn()
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            jobs = claim(cur, conn, min(CONCURRENCY, limit - done), tenant_id)
        finally:
            put_conn(conn)
        if not jobs:
            break
        await asyncio.gather(*(process(j) for j in jobs))
        done += len(jobs)
    return done


async def _loop() -> None:
    await asyncio.sleep(10)
    log.info("[whatsapp] worker started (concurrency=%s, lease=%ss)", CONCURRENCY, LEASE_SECONDS)
    last_reconcile = 0.0
    while True:
        try:
            n = await drain(limit=50)
            if time.monotonic() - last_reconcile > 60:
                last_reconcile = time.monotonic()
                from .outbox import reconcile_unknown
                await asyncio.to_thread(reconcile_unknown)
        except Exception:
            traceback.print_exc()
            n = 0
        if n == 0:
            await asyncio.to_thread(_wake.wait, IDLE_POLL_S)
            _wake.clear()


def start_worker() -> None:
    global _started
    if _started or not ENABLED:
        if not ENABLED:
            log.info("[whatsapp] worker disabled (WA_WORKER_ENABLED=false)")
        return
    _started = True

    def _runner():
        try:
            asyncio.run(_loop())
        except Exception:
            traceback.print_exc()

    threading.Thread(target=_runner, name="whatsapp-intake-worker", daemon=True).start()
