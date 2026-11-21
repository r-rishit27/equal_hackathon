"""CommExtractionWorker — turns an inbound vendor email or an uploaded
contract PDF into typed claims.

Per email message: resolve vendor -> extract_claims_from_email -> restore PII
-> comm_extractions row -> flip comm_thread_state -> agent_runs audit.

Per contract document (§5.1.4 of the HLD, Phase 3): resolve vendor -> read the
PDF's TEXT LAYER (never vision — see the note below) -> extract_claims_from_contract
-> restore PII -> comm_extractions row (source_type='contract') -> agent_runs
audit -> mark the `vendor_documents` row processed so it is never re-extracted.

**One worker, two claim surfaces, not two workers.** `poc_email_messages` and
`vendor_documents` differ in shape (one is a mailbox row, the other a stored
file), but the claiming pattern (`UPDATE ... SET claims_status='RUNNING'
WHERE claims_status='PENDING' ... FOR UPDATE SKIP LOCKED RETURNING ...`), the
concurrency budget, the `agent_runs` audit wrapping, and the destination table
(`comm_extractions`) are all identical. Forcing a second near-duplicate
BaseWorker subclass through that same shape for the sake of "one table per
worker" would be the awkward choice, not this one — see this module's own
class docstring for the two `process_batch` queries side by side.

**skip_backfill = True.** Without it, BaseWorker Phase 1 would drain every
historical inbound email (and every historical vendor document) through a
model on first boot — years of history, most of it long since irrelevant.
That is the exact cost bomb `ReviewAgentWorker` already guards against with
the same flag (see that module's docstring), and it is one attribute away at
all times, which is why it is called out here rather than left implicit.

**The extraction runs here, never in the API process.** Same reasoning as
ReviewAgentWorker: the FastAPI process is sync psycopg2 on a shared pool, and
holding a connection open for seconds while an LLM call is in flight would
stall it. `poc_email_messages` rows are written by the existing mailbox poller
and the outbound send endpoint; `vendor_documents` rows are written by the
mailbox poller's new contract branch (`agent.py`) or the existing manual
upload endpoint (`vendor_documents.py`) — this worker only ever reads and
updates both tables.

**Text layer, never vision, for a contract.** This codebase has a standing
rule (`OCR_TO_USE`, see utils/ocr_engine.py's module docstring) that
identifiers and numbers must come from a PDF's embedded text layer, because
vision measurably misreads GSTINs and other digits. A contract's rate and
payment-term clauses deserve the same exactness a bill's line items get, so
this worker calls `utils.ocr_engine._pdf_to_text` directly — the same
function `process_pdf_async`'s text path uses internally — and never runs the
full bill-OCR structuring pipeline (which is a different, invoice-shaped
schema) or a vision re-read. A PDF with no usable text layer (a scanned
contract) is the one exception: its pages are transcribed verbatim with vision
(app/docread: gpt-5.4 vision, Sarvam if OpenAI fails) and its terms read from that text.
That is safe only because nothing a contract says is ever written on its own
(master_data_conflict.py: every claim waits for an admin), and the document is
marked as read from a scan (`claims_error = SCAN_NOTE` on a DONE row) so the
claims panel tells the reviewer to check each digit against the page.

Pool discipline: shares db.py's asyncpg pool (max_size=10) with a dozen other
workers, hence the concurrency semaphore — identical shape to
ReviewAgentWorker.MAX_CONCURRENCY.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os

from db import get_pool
from .base_worker import BaseWorker
from ..docread.checks import gstin_valid

from .comm_extract import PROMPT_VERSION, extract_claims_from_contract, extract_claims_from_email

logger = logging.getLogger(__name__)

# Small on purpose — same rationale as agent_worker.py: every concurrent run
# holds a pool connection while it waits on the network, out of only ten
# shared with a dozen other workers.
MAX_CONCURRENCY = 2

MODEL = "gpt-4o-mini"
# Contracts read with the full model: on a 14-page agreement gpt-4o-mini
# returned no terms at all, where gpt-4o found the fee, payment condition,
# invoicing deadline, term and notice period (about $0.03 a contract). Email
# volume stays on the mini model.
# Contracts, IOs and vendor POs are read by their own prompts (comm_extract.CONTRACT_SYSTEMS).
CONTRACT_MODEL = os.getenv("COMM_CONTRACT_MODEL", "gpt-5.4-mini")

# A contract can run to hundreds of pages; this bounds one extraction call.
# 60k characters (~15k tokens, about $0.002 on gpt-4o-mini) holds a typical
# 15-20 page agreement whole; 20k used to stop around page 9, before the
# annexures where rates and bank details live. Beyond it, fit_contract_text
# keeps the opening and closing pages and drops the middle.
MAX_CONTRACT_CHARS = 60000

def fit_contract_text(pages: list[str], limit: int = MAX_CONTRACT_CHARS) -> str:
    """Pages joined, within `limit`. A long contract keeps its opening (parties,
    term, payment clauses) and its closing pages (annexures and schedules, where
    rate cards and bank details usually sit) and drops the middle, rather than
    cutting the end off."""
    body = "\n\n".join(pages)
    if len(body) <= limit:
        return body
    marker = "\n\n[... middle pages omitted ...]\n\n"
    head_budget = int((limit - len(marker)) * 0.55)
    tail_budget = limit - len(marker) - head_budget
    head, tail = [], []
    used = 0
    for p in pages:  # whole pages from the front
        if used + len(p) + 2 > head_budget:
            break
        head.append(p); used += len(p) + 2
    used = 0
    for p in reversed(pages[len(head):]):  # whole pages from the back
        if used + len(p) + 2 > tail_budget:
            break
        tail.insert(0, p); used += len(p) + 2
    if not head and not tail:
        return body[:limit]
    return "\n\n".join(head) + marker + "\n\n".join(tail)


# Stored in vendor_documents.claims_error on a DONE contract whose text came
# from a vision transcription of a scan rather than a text layer.
SCAN_NOTE = "read from a scan"

# Defense-in-depth, not just a prompt fix: a vendor_bank claim auto-applies
# (master_data_conflict.py — bank is always multi-valid, never a conflict a
# human reviews first), so a misread here writes a wrong account straight
# into supplier_bank_accounts. Caught once already: a document's "PHONE NO."
# field extracted as an account number, since it was also just a string of
# digits sitting near other vendor-details rows. The prompt now says not to
# do this; this is the check that holds even if a model slips anyway.
_ACCOUNT_CONTEXT_WORDS = ("account", "a/c", "ifsc", "bank")


def _looks_like_real_account_claim(evidence_quote: str) -> bool:
    q = (evidence_quote or "").lower()
    return any(w in q for w in _ACCOUNT_CONTEXT_WORDS)


# Domains where our own staff and a vendor's staff can legitimately share an
# address, so "same domain as us" proves nothing.
_FREEMAIL_DOMAINS = frozenset({
    "gmail.com", "googlemail.com", "yahoo.com", "yahoo.in", "yahoo.co.in",
    "hotmail.com", "outlook.com", "live.com", "rediffmail.com", "icloud.com",
    "protonmail.com", "proton.me", "aol.com",
})


def _email_domain(value: str) -> str:
    # No "@" means no domain. rpartition would hand back the whole string
    # here, which is not a domain and must not be compared against ours.
    _, at, domain = (value or "").strip().lower().rpartition("@")
    return domain if at else ""


def _drop_pan_contradicting_gstin(claims: list[dict]) -> tuple[list[dict], str | None]:
    """Refuse a PAN that the extracted GSTIN says cannot be this vendor's.

    A PAN is characters 3-12 of a GSTIN — core/vendor_identity._effective_pan
    already treats the embedded one as authoritative, because it is
    checksum-validated while a free-standing PAN field is not. So a vendor_pan
    that disagrees with the vendor_gstin read off the same document is not this
    vendor's PAN at all.

    In practice it is the buyer's: an insertion order prints a PAN on the
    purchaser's side and often leaves the vendor's own PAN row blank, and a
    model filling that gap reaches across the table. Caught exactly that way —
    the vendor's GSTIN read correctly, paired with a PAN that turned out to be
    the middle ten characters of the *buyer's* GSTIN.

    Nothing is synthesised to replace it: approving the GSTIN already writes the
    PAN, since add_supplier_gstin derives it the same way.

    Returns the surviving claims and the PAN that was dropped, if any.
    """
    gstin_claim = next((c for c in claims if c.get("scope") == "vendor_gstin"), None)
    if not gstin_claim:
        return claims, None
    gstin = str(gstin_claim.get("new_value") or "").strip().upper()
    if len(gstin) != 15:
        return claims, None
    embedded = gstin[2:12]

    kept, dropped = [], None
    for c in claims:
        if c.get("scope") == "vendor_pan":
            stated = str(c.get("new_value") or "").strip().upper()
            if stated and stated != embedded:
                dropped = stated
                continue
        kept.append(c)
    return kept, dropped


async def _own_staff_domains(conn, tenant_id: str) -> set[str]:
    """Email domains belonging to US, the buyer.

    A contract sets the buyer and the vendor side by side in identical shapes,
    and a model that reads the wrong column files our own colleague as the
    vendor's point of contact — which the Communication Agent would then go on
    to email as if they were the vendor. The prompt is explicit about this now,
    but a prompt is a request, not a guarantee, so the buyer's own domains are
    also refused outright here. Free-mail domains are excluded: a vendor on
    gmail.com is ordinary and proves nothing either way.
    """
    rows = await conn.fetch(
        "SELECT DISTINCT lower(split_part(email, '@', 2)) AS domain "
        "  FROM users "
        " WHERE company_id::text = $1 AND email IS NOT NULL AND email <> ''",
        tenant_id,
    )
    return {
        r["domain"] for r in rows
        if r["domain"] and r["domain"] not in _FREEMAIL_DOMAINS
    }


async def _known_terms(conn, tenant_id: str, supplier_id: str) -> dict[str, str]:
    """The commercial terms the vendor's latest contract states, {field: "5 %…"},
    so an email's change is extracted under the same field name."""
    try:
        row = await conn.fetchrow(
            """SELECT claims FROM comm_extractions
                WHERE tenant_id = $1::uuid AND supplier_id = $2::uuid AND source_type = 'contract'
                ORDER BY created_at DESC LIMIT 1""",
            tenant_id, supplier_id,
        )
    except Exception:
        logger.warning("[comm_extraction] could not read the vendor's contract terms", exc_info=True)
        return {}
    claims = row["claims"] if row else None
    if isinstance(claims, str):
        claims = json.loads(claims)
    out: dict[str, str] = {}
    for c in claims or []:
        if (isinstance(c, dict) and c.get("scope") == "commercial_term" and c.get("field")
                and str(c.get("status", "")).upper() != "DISCARDED"):
            out[str(c["field"])] = f"{c.get('new_value') or c.get('value') or ''} {c.get('unit') or ''}".strip()
    return out


async def _propose_term_changes(conn, tenant_id: str, supplier_id: str, message_id: str,
                                subject: str, claims: list[dict]) -> None:
    """Record an email's commercial-term changes on the vendor's playground flow.

    The same open question a newer contract creates (domain/playground/
    checks.py), so Review Hub offers the same either/or and the next run
    calculates with whatever is chosen.
    """
    changes = [c for c in claims if c.get("scope") == "commercial_term"]
    if not changes:
        return
    from ..domain.playground.checks import propose_change

    async with conn.transaction():
        row = await conn.fetchrow(
            "SELECT flow_id, terms FROM vendor_flows "
            " WHERE tenant_id = $1::uuid AND supplier_id = $2::uuid FOR UPDATE",
            tenant_id, supplier_id,
        )
        if not row:
            return
        terms = row["terms"] or {}
        if isinstance(terms, str):
            terms = json.loads(terms)
        msg = await conn.fetchrow(
            """SELECT COALESCE(m.sent_at, m.created_at) AS at, c.name
                 FROM poc_email_messages m
                 LEFT JOIN supplier_contacts c ON c.id = m.contact_id
                WHERE m.message_id = $1::uuid""",
            message_id,
        )
        who = (msg["name"] or "").split()[0] if msg and msg["name"] else ""
        when = msg["at"].strftime("%d %b").lstrip("0") if msg and msg["at"] else ""
        # "Email from Subhash, 19 Nov" — the subject is in the quote's company.
        label = "Email" + (f" from {who}" if who else "") + (f", {when}" if when else "")
        changed = False
        for c in changes:
            changed |= propose_change(terms, str(c["field"]), c.get("new_value"), c.get("unit"),
                                      {"id": message_id, "label": label,
                                       "quote": c.get("evidence_quote")})
        if changed:
            await conn.execute("UPDATE vendor_flows SET terms = $2::jsonb WHERE flow_id = $1",
                               row["flow_id"], json.dumps(terms))


async def _wake_review_adapters(conn) -> None:
    """Tell ReviewAdapterWorker a new extraction is waiting for it.

    `comm_extractions` has no CDC trigger in `pipelines/cdc.py` (that list
    installs `ch_review_adapters` triggers for fact_invoices, dim_suppliers,
    ai_anomalies, ... — never for this table), so until some *unrelated* write
    happened to wake the adapter worker, a contract's claims sat at PENDING and
    the conflicts they imply were in nobody's Review Hub. In practice that meant
    up to `idle_poll_interval_s` (300s, config.PIPELINE_CFG['review_adapters'])
    between "the Communication Agent read this contract" and "the finding exists"
    — long enough that a user who opens the hub right after the agent logs
    `contract_detected` sees nothing and reasonably concludes it was dropped.

    Notified from here rather than by adding the table to `pipelines/cdc.py`
    because that bootstrap only runs in the separate pipelines process, while
    this worker runs inside the API process (review/scheduler.py) — and because
    an INSERT OR UPDATE trigger would also fire on master_data_conflict.py's own
    write-back of `claims`, waking the worker for a pass it just finished.
    Same explicit-notify pattern routers/vendor_documents.py already uses after
    a claim is approved or discarded.

    Never raises: a missed wakeup costs latency (the safety-poll still catches
    it), a raised one would fail an extraction that has already been stored.
    """
    try:
        await conn.execute("SELECT pg_notify('ch_review_adapters', '')")
    except Exception:
        logger.warning("[comm_extraction] could not wake the review adapters — "
                       "its claims will surface on the next safety-poll instead",
                       exc_info=True)


class CommExtractionWorker(BaseWorker):
    name = "comm_extraction"
    notify_channel = "ch_comm_extract"
    skip_backfill = True   # load-bearing — see the module docstring

    def __init__(self) -> None:
        self._sem = asyncio.Semaphore(MAX_CONCURRENCY)

    async def process_batch(self) -> int:
        pool = await get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                UPDATE poc_email_messages
                   SET claims_status = 'RUNNING'
                 WHERE message_id IN (
                     SELECT message_id FROM poc_email_messages
                      WHERE direction = 'inbound'
                        AND claims_status = 'PENDING'
                        AND body IS NOT NULL AND body <> ''
                      ORDER BY created_at
                      FOR UPDATE SKIP LOCKED
                      LIMIT $1
                 )
                RETURNING message_id, tenant_id, supplier_id, contact_id,
                          thread_id, subject, body
                """,
                self.batch_size,
            )

        total = 0
        if rows:
            await asyncio.gather(*(self._run_one(dict(r)) for r in rows))
            total += len(rows)

        # Contract PDFs (uploaded via agent.py's new branch, or by hand through
        # vendor_documents.py) awaiting claim extraction. Only .pdf files: this
        # worker reads a text layer, so an Excel/CSV vendor_documents row would
        # have nothing for it to extract and is left at its default status.
        async with pool.acquire() as conn:
            doc_rows = await conn.fetch(
                """
                UPDATE vendor_documents
                   SET claims_status = 'RUNNING'
                 WHERE id IN (
                     SELECT id FROM vendor_documents
                      WHERE claims_status = 'PENDING'
                        AND deleted_at IS NULL
                        AND file_name ILIKE '%.pdf'
                      ORDER BY uploaded_at
                      FOR UPDATE SKIP LOCKED
                      LIMIT $1
                 )
                RETURNING id, tenant_id, supplier_id, file_name, file_path
                """,
                self.batch_size,
            )
        if doc_rows:
            await asyncio.gather(*(self._run_one_contract(dict(r)) for r in doc_rows))
            total += len(doc_rows)

        return total

    async def _mark(self, conn, message_id, status: str, error: str | None = None) -> None:
        await conn.execute(
            "UPDATE poc_email_messages SET claims_status = $2, claims_error = $3 "
            " WHERE message_id = $1",
            message_id, status, error,
        )

    async def _mark_document(self, conn, doc_id, status: str, error: str | None = None) -> None:
        await conn.execute(
            "UPDATE vendor_documents SET claims_status = $2, claims_error = $3 "
            " WHERE id = $1",
            doc_id, status, error,
        )

    async def _run_one(self, row: dict) -> None:
        async with self._sem:
            pool = await get_pool()
            async with pool.acquire() as conn:
                message_id = row["message_id"]
                tenant_id = str(row["tenant_id"])
                supplier_id = str(row["supplier_id"]) if row["supplier_id"] else None
                contact_id = str(row["contact_id"]) if row["contact_id"] else None
                thread_id = row["thread_id"]
                subject = row["subject"] or ""
                body = row["body"] or ""

                try:
                    if not supplier_id:
                        await self._mark(conn, message_id, "SKIPPED",
                                          "no vendor linked to this email")
                        return

                    vendor = await conn.fetchrow(
                        "SELECT name FROM dim_suppliers "
                        " WHERE supplier_id = $1::uuid AND tenant_id = $2::uuid",
                        supplier_id, tenant_id,
                    )
                    if vendor is None:
                        await self._mark(conn, message_id, "SKIPPED", "vendor not found")
                        return
                    vendor_name = vendor["name"]

                    await self._extract_and_publish(
                        conn, message_id=message_id, tenant_id=tenant_id,
                        supplier_id=supplier_id, contact_id=contact_id,
                        thread_id=thread_id, subject=subject, body=body,
                        vendor_name=vendor_name,
                    )
                except Exception:
                    logger.exception("[comm_extraction] message %s failed", message_id)
                    await self._mark(conn, message_id, "FAILED", "unexpected worker error")

    async def _extract_and_publish(
        self, conn, *, message_id, tenant_id: str, supplier_id: str,
        contact_id: str | None, thread_id: str | None, subject: str, body: str,
        vendor_name: str,
    ) -> None:
        run_id = await conn.fetchval(
            """
            INSERT INTO agent_runs
                (tenant_id, agent_name, trigger_type, trigger_ref, subject_type,
                 subject_id, model, prompt_version)
            VALUES ($1::uuid, 'communication', 'event', $2, 'vendor', $3::uuid, $4, $5)
            RETURNING run_id
            """,
            tenant_id, str(message_id), supplier_id, MODEL, PROMPT_VERSION,
        )

        # Lazy import to avoid a module-load-time cycle between this package
        # and backend_ocr.app.ai — mirrors comm_extract.py's own import.
        from ..ai.llm import LLMRefused

        try:
            result, red = await extract_claims_from_email(
                tenant_id, vendor_name, subject, body, model=MODEL,
                known_terms=await _known_terms(conn, tenant_id, supplier_id),
            )
        except LLMRefused as exc:
            await conn.execute(
                "UPDATE agent_runs SET status = 'REFUSED', error = $2, finished_at = now() "
                " WHERE run_id = $1",
                run_id, str(exc)[:500],
            )
            await self._mark(conn, message_id, "FAILED", str(exc)[:500])
            return
        except Exception as exc:
            await conn.execute(
                "UPDATE agent_runs SET status = 'FAILED', error = $2, finished_at = now() "
                " WHERE run_id = $1",
                run_id, str(exc)[:500],
            )
            await self._mark(conn, message_id, "FAILED", str(exc)[:500])
            return

        raw_claims = result.content.get("claims") if isinstance(result.content, dict) else None
        claims: list[dict] = []
        for c in (raw_claims or []):
            if not isinstance(c, dict):
                continue
            claim = dict(c)
            # `field` and `new_value` are the two things master_data_conflict.py
            # actually routes on — a claim missing either is unusable downstream
            # regardless of what CLAIM_SCHEMA required at the wire level (kept
            # deliberately lenient there, see that module's docstring, so one
            # malformed claim doesn't cost the whole batch). Drop it here instead
            # of storing something nothing can act on.
            if not claim.get("field") or not str(claim.get("new_value") or "").strip():
                continue
            if (claim.get("scope") == "vendor_bank" and claim.get("field") == "account_number"
                    and not _looks_like_real_account_claim(claim.get("evidence_quote"))):
                continue
            # PII never leaves this function: tokens go back to real values only
            # now, on the way into storage a human (or the conflict adapter) will
            # read — never inside the prompt or the model's response.
            claim["new_value"] = red.restore(str(claim.get("new_value") or ""))
            claim["evidence_quote"] = red.restore(str(claim.get("evidence_quote") or ""))
            claim["confidence"] = float(claim["confidence"]) if isinstance(claim.get("confidence"), (int, float)) else 0.5
            claim["status"] = "PENDING"
            claims.append(claim)

        try:
            # Inserted even when claims is empty — an extraction that ran and
            # found nothing must be distinguishable from one that never ran, or
            # a controller cannot tell "checked, clean" from "not checked yet".
            await conn.execute(
                """
                INSERT INTO comm_extractions
                    (tenant_id, source_type, source_id, supplier_id, contact_id,
                     thread_id, model, prompt_version, agent_run_id, claims)
                VALUES ($1::uuid, 'email', $2::uuid, $3::uuid, $4::uuid, $5, $6, $7,
                        $8::uuid, $9::jsonb)
                """,
                tenant_id, str(message_id), supplier_id, contact_id, thread_id,
                MODEL, PROMPT_VERSION, str(run_id), json.dumps(claims),
            )
            await self._mark(conn, message_id, "DONE", None)

            if thread_id:
                # purpose is deliberately left at its default/current value —
                # classifying bill_followup vs contract_request vs general is
                # out of scope for Phase 0+1 (§5.1.4, deferred to Phase 3).
                await conn.execute(
                    """
                    INSERT INTO comm_thread_state
                        (tenant_id, thread_id, supplier_id, contact_id,
                         last_direction, last_message_at, status)
                    VALUES ($1::uuid, $2, $3::uuid, $4::uuid, 'inbound', now(),
                            'awaiting_internal')
                    ON CONFLICT (tenant_id, thread_id) DO UPDATE SET
                        supplier_id     = COALESCE(EXCLUDED.supplier_id, comm_thread_state.supplier_id),
                        contact_id      = COALESCE(EXCLUDED.contact_id, comm_thread_state.contact_id),
                        last_direction  = 'inbound',
                        last_message_at = now(),
                        status          = 'awaiting_internal',
                        updated_at      = now()
                    """,
                    tenant_id, thread_id, supplier_id, contact_id,
                )
        except Exception as exc:
            await conn.execute(
                "UPDATE agent_runs SET status = 'FAILED', error = $2, finished_at = now() "
                " WHERE run_id = $1",
                run_id, str(exc)[:500],
            )
            await self._mark(conn, message_id, "FAILED", str(exc)[:500])
            return

        if claims:
            # A term change ("routing fee is now 10%") is put to the vendor's
            # playground flow as an open question; playground_checks raises it.
            try:
                await _propose_term_changes(conn, tenant_id, supplier_id, str(message_id),
                                            subject, claims)
            except Exception:
                logger.exception("[comm_extraction] could not put a term change to the flow")
            # The claims are stored; master_data_conflict.py is what turns the
            # ones that disagree with the vendor master into Review Hub
            # findings, and nothing else in this transaction's tables wakes it.
            await _wake_review_adapters(conn)

        await conn.execute(
            """
            UPDATE agent_runs
               SET status = 'SUCCEEDED', finished_at = now(),
                   input_tokens = $2, output_tokens = $3, cost_usd = $4,
                   latency_ms = $5, outcome = $6::jsonb
             WHERE run_id = $1
            """,
            run_id, result.input_tokens, result.output_tokens, result.cost_usd,
            result.latency_ms, json.dumps({"claims_found": len(claims)}),
        )

    # ── Contract documents (§5.1.4) ───────────────────────────────────────────

    async def _read_document(self, file_path: str, file_name: str = ""):
        """Every page of the stored document, through the shared reader (app/docread): the text layer
        where a page has one, gpt-5.4 vision for scanned pages, Sarvam if OpenAI fails. Returns a
        DocRead; `from_scan` is True when any page came from an image."""
        from pathlib import Path

        import pymupdf

        from ..core import object_store
        from ..docread import read_document

        suffix = Path(file_name or file_path).suffix.lower() or ".pdf"
        # A handful of contracts landed here with a "no such file" error for a path that existed moments
        # later (a brief write-visibility delay on the volume). A short, bounded retry turns that rare miss
        # into a normal success; a genuinely absent file still fails after three tries.
        last_exc: Exception | None = None
        for attempt in range(3):
            if attempt:
                await asyncio.sleep(0.5 * attempt)
            try:
                with object_store.local_path(file_path, suffix=suffix) as path:
                    return await read_document(str(path), file_name or str(path))
            except (pymupdf.FileNotFoundError, FileNotFoundError) as exc:
                last_exc = exc
        raise last_exc

    async def _run_one_contract(self, row: dict) -> None:
        async with self._sem:
            pool = await get_pool()
            async with pool.acquire() as conn:
                doc_id = row["id"]
                tenant_id = str(row["tenant_id"])
                supplier_id = str(row["supplier_id"]) if row["supplier_id"] else None
                file_name = row["file_name"] or ""
                file_path = row["file_path"]

                try:
                    if not supplier_id:
                        await self._mark_document(conn, doc_id, "SKIPPED",
                                                   "no vendor linked to this document")
                        return
                    if not file_path:
                        await self._mark_document(conn, doc_id, "SKIPPED", "no file on disk")
                        return

                    vendor = await conn.fetchrow(
                        "SELECT name FROM dim_suppliers "
                        " WHERE supplier_id = $1::uuid AND tenant_id = $2::uuid",
                        supplier_id, tenant_id,
                    )
                    if vendor is None:
                        await self._mark_document(conn, doc_id, "SKIPPED", "vendor not found")
                        return
                    vendor_name = vendor["name"]

                    try:
                        read = await self._read_document(file_path, file_name)
                    except Exception as exc:
                        # Encrypted/malformed/missing file — a read failure, worth a
                        # FAILED (retriable by an operator) rather than a silent SKIPPED.
                        logger.exception("[comm_extraction] could not read %s", file_path)
                        await self._mark_document(conn, doc_id, "FAILED", str(exc)[:500])
                        return

                    text = fit_contract_text(read.page_texts)
                    failed = [p for p in read.pages if p.source == "failed"]
                    if not text.strip():
                        if failed:
                            await self._mark_document(conn, doc_id, "FAILED",
                                                      f"Couldn't read this scanned document: {(failed[0].error or '')[:400]}")
                        else:
                            await self._mark_document(conn, doc_id, "SKIPPED", "no readable text on the scan")
                        return
                    if failed:
                        logger.warning("[comm_extraction] %s: %d page(s) unreadable, read the rest",
                                       file_path, len(failed))
                    from_scan = read.from_scan
                    logger.info("[comm_extraction] %s read: %s, $%.4f", file_path, dict(read.sources), read.cost_usd)

                    await self._extract_and_publish_contract(
                        conn, doc_id=doc_id, tenant_id=tenant_id, supplier_id=supplier_id,
                        file_name=file_name, text=text, vendor_name=vendor_name, from_scan=from_scan,
                    )
                except Exception:
                    logger.exception("[comm_extraction] contract document %s failed", doc_id)
                    await self._mark_document(conn, doc_id, "FAILED", "unexpected worker error")

    async def _extract_and_publish_contract(
        self, conn, *, doc_id, tenant_id: str, supplier_id: str,
        file_name: str, text: str, vendor_name: str, from_scan: bool = False,
    ) -> None:
        run_id = await conn.fetchval(
            """
            INSERT INTO agent_runs
                (tenant_id, agent_name, trigger_type, trigger_ref, subject_type,
                 subject_id, model, prompt_version)
            VALUES ($1::uuid, 'communication', 'event', $2, 'vendor', $3::uuid, $4, $5)
            RETURNING run_id
            """,
            tenant_id, str(doc_id), supplier_id, CONTRACT_MODEL, PROMPT_VERSION,
        )

        from ..ai.llm import LLMRefused

        try:
            result, red = await extract_claims_from_contract(
                tenant_id, vendor_name, file_name, text, model=CONTRACT_MODEL,
            )
        except LLMRefused as exc:
            await conn.execute(
                "UPDATE agent_runs SET status = 'REFUSED', error = $2, finished_at = now() "
                " WHERE run_id = $1",
                run_id, str(exc)[:500],
            )
            await self._mark_document(conn, doc_id, "FAILED", str(exc)[:500])
            return
        except Exception as exc:
            await conn.execute(
                "UPDATE agent_runs SET status = 'FAILED', error = $2, finished_at = now() "
                " WHERE run_id = $1",
                run_id, str(exc)[:500],
            )
            await self._mark_document(conn, doc_id, "FAILED", str(exc)[:500])
            return

        raw_claims = result.content.get("claims") if isinstance(result.content, dict) else None
        own_domains = await _own_staff_domains(conn, tenant_id)
        buyer_side_contact = False
        claims: list[dict] = []
        for c in (raw_claims or []):
            if not isinstance(c, dict):
                continue
            claim = dict(c)
            # Same drop rule as the email path (see its comment): a claim with
            # no field or no value is nothing contract_bill_variance.py or
            # master_data_conflict.py could route, whatever the wire schema let
            # through. A contract's "other details" table (payout, campaign
            # name, billable event...) is exactly what tends to produce these —
            # real content, just not a claim this schema models.
            if not claim.get("field") or not str(claim.get("new_value") or "").strip():
                continue
            if (claim.get("scope") == "vendor_bank" and claim.get("field") == "account_number"
                    and not _looks_like_real_account_claim(claim.get("evidence_quote"))):
                continue
            claim["new_value"] = red.restore(str(claim.get("new_value") or ""))
            claim["evidence_quote"] = red.restore(str(claim.get("evidence_quote") or ""))
            # A real GSTIN always passes its mod-36 check character; one that fails was misread
            # (no parser in docs/RECON_PARSER_EVAL.md read every GSTIN exactly) and must not reach the
            # vendor record.
            if claim.get("scope") == "vendor_gstin" and not gstin_valid(claim["new_value"]):
                logger.warning("[comm-extract] contract %s: dropped GSTIN %r — its check character is wrong",
                               doc_id, claim["new_value"])
                continue
            if claim.get("summary"):
                claim["summary"] = red.restore(str(claim["summary"]))
            # Read the buyer's column instead of the vendor's — the one
            # mistake here that ends with us emailing ourselves as the vendor.
            # Checked after restore because the address is a redaction token
            # until then.
            if (claim.get("scope") == "vendor_contact" and claim.get("field") == "email"
                    and _email_domain(claim["new_value"]) in own_domains):
                logger.warning(
                    "[comm-extract] contract %s: dropped a vendor_contact on our own "
                    "domain (%s) — that is the buyer's POC, not the vendor's",
                    doc_id, _email_domain(claim["new_value"]),
                )
                buyer_side_contact = True
                continue
            target_ref = claim.get("target_ref")
            if target_ref:
                claim["target_ref"] = red.restore(str(target_ref))
            claim["confidence"] = float(claim["confidence"]) if isinstance(claim.get("confidence"), (int, float)) else 0.5
            claim["status"] = "PENDING"
            claims.append(claim)

        if buyer_side_contact:
            # Its name/phone siblings described the same wrong person, and
            # without the email anchor the adapter could not act on them anyway.
            claims = [c for c in claims if c.get("scope") != "vendor_contact"]

        claims, dropped_pan = _drop_pan_contradicting_gstin(claims)
        if dropped_pan:
            logger.warning(
                "[comm-extract] contract %s: dropped PAN %s — it is not the PAN inside "
                "the GSTIN we read, so it belongs to the other party on the document",
                doc_id, dropped_pan,
            )

        try:
            # No thread_id, no contact_id — a stored document has neither; a
            # contract's claims are matched to the vendor record and to bills
            # (contract_bill_variance.py), not to a mailbox thread.
            await conn.execute(
                """
                INSERT INTO comm_extractions
                    (tenant_id, source_type, source_id, supplier_id,
                     model, prompt_version, agent_run_id, claims)
                VALUES ($1::uuid, 'contract', $2::uuid, $3::uuid, $4, $5, $6::uuid, $7::jsonb)
                """,
                tenant_id, str(doc_id), supplier_id, CONTRACT_MODEL, PROMPT_VERSION,
                str(run_id), json.dumps(claims),
            )
            await self._mark_document(conn, doc_id, "DONE", SCAN_NOTE if from_scan else None)
        except Exception as exc:
            await conn.execute(
                "UPDATE agent_runs SET status = 'FAILED', error = $2, finished_at = now() "
                " WHERE run_id = $1",
                run_id, str(exc)[:500],
            )
            await self._mark_document(conn, doc_id, "FAILED", str(exc)[:500])
            return

        if claims:
            # A term change ("routing fee is now 10%") is put to the vendor's
            # playground flow as an open question; playground_checks raises it.
            try:
                await _propose_term_changes(conn, tenant_id, supplier_id, str(message_id),
                                            subject, claims)
            except Exception:
                logger.exception("[comm_extraction] could not put a term change to the flow")
            # The claims are stored; master_data_conflict.py is what turns the
            # ones that disagree with the vendor master into Review Hub
            # findings, and nothing else in this transaction's tables wakes it.
            await _wake_review_adapters(conn)

        await conn.execute(
            """
            UPDATE agent_runs
               SET status = 'SUCCEEDED', finished_at = now(),
                   input_tokens = $2, output_tokens = $3, cost_usd = $4,
                   latency_ms = $5, outcome = $6::jsonb
             WHERE run_id = $1
            """,
            run_id, result.input_tokens, result.output_tokens, result.cost_usd,
            result.latency_ms, json.dumps({"claims_found": len(claims)}),
        )
