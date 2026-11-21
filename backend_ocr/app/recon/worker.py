"""ReconWorker — reads recon uploads in the background (03_LLD_BACKEND.md §5).

Same claim pattern as CommExtractionWorker: UPDATE … WHERE recon_status =
'PENDING' … FOR UPDATE SKIP LOCKED. Two kinds of wake-up arrive on the
`recon_docs` channel: a new upload (payload empty or {"kind":"doc"}) and a new or
changed bill for a supplier that has recon documents ({"kind":"bill", ...}),
which re-tries that supplier's unlinked documents (05_USER_FLOWS.md F8).
"""
from __future__ import annotations

import asyncio
import json
import logging

from ..review.base_worker import BaseWorker
from . import config as C
from .memory import MemoryPressure, available_mb
from .llm import ReconLLM
from .pipeline import ReconPipeline
from .repo import ReconRepository

logger = logging.getLogger(__name__)


_READ_TIMEOUT_S = max(120, 20 * C.MAX_PAGES)     # one file, start to finish


class ReconWorker(BaseWorker):
    name = "recon"
    notify_channel = "recon_docs"

    def __init__(self) -> None:
        self._repo: ReconRepository | None = None
        self._stale_checked = False

    async def _get_repo(self) -> ReconRepository:
        if self._repo is None:
            from db import get_pool
            self._repo = ReconRepository(await get_pool())
        return self._repo

    async def process_batch(self) -> int:
        repo = await self._get_repo()
        # Workers run in exactly one process (the scheduler's advisory lock), so at startup any file
        # still RUNNING belongs to a process that died — re-queue it now, not after a timeout
        # (2026-11-13: a restart within seconds left one stranded for two hours). After that, sweep on
        # every poll for anything running past the read timeout.
        n = await repo.reset_stale(0 if not self._stale_checked else _READ_TIMEOUT_S // 60 + 5)
        if n:
            logger.warning("[recon] re-queued %d document(s) left RUNNING by a stopped process", n)
        self._stale_checked = True
        # Don't start a read the box can't afford; the files stay queued for the next poll.
        free = available_mb()
        if free is not None and free < C.MIN_FREE_MB:
            logger.warning("[recon] %d MB free (< %d): leaving files queued", free, C.MIN_FREE_MB)
            return 0
        rows = await repo.claim_pending(limit=1)
        for row in rows:
            await self._run_one(repo, row)
        await self._relink_from_bills(repo)
        return len(rows)

    async def _run_one(self, repo: ReconRepository, row: dict) -> None:
        tenant, doc_id = str(row["tenant_id"]), str(row["id"])
        llm = ReconLLM()
        pipe = ReconPipeline(repo, llm=llm, adjudicate=_adjudicator(llm))
        try:
            out = await asyncio.wait_for(pipe.ingest(row), timeout=_READ_TIMEOUT_S)
            await repo.set_doc(doc_id, status=out.status, stage="done",
                               error="; ".join(out.warnings) if out.warnings else None)
            await repo.log_event(tenant, "extracted", {"status": out.status, "cases": sorted(out.touched_cases),
                                                       "warnings": out.warnings, "usd": round(llm.cost_usd, 4),
                                                       "llm_calls": llm.calls}, doc_id=doc_id)
        except MemoryPressure as exc:
            # Not a failure of the file: put it back in the queue and let the box breathe.
            logger.warning("[recon] doc %s deferred: %s", doc_id, exc)
            await repo.set_doc(doc_id, status="PENDING", stage="reading",
                               error="Waiting for the server to have room; it will be read shortly.")
            await repo.log_event(tenant, "deferred", {"reason": str(exc)}, doc_id=doc_id)
        except Exception as exc:
            logger.exception("[recon] doc %s failed", doc_id)
            await repo.set_doc(doc_id, status="FAILED", stage="done", error=_user_message(exc))
            await repo.log_event(tenant, "failed", {"error": str(exc)[:500]}, doc_id=doc_id)

    async def _relink_from_bills(self, repo: ReconRepository) -> None:
        """Pending 'a bill arrived' notices are stored as recon_events(kind='bill_arrived', processed=false)."""
        async with repo.pool.acquire() as c:
            rows = await c.fetch(
                """UPDATE recon_events SET kind = 'bill_arrived_done'
                    WHERE id IN (SELECT id FROM recon_events WHERE kind = 'bill_arrived'
                                  ORDER BY at LIMIT 20 FOR UPDATE SKIP LOCKED)
                RETURNING tenant_id, payload""")
        seen = set()
        for r in rows:
            p = json.loads(r["payload"]) if isinstance(r["payload"], str) else (r["payload"] or {})
            key = (str(r["tenant_id"]), p.get("supplier_id"))
            if not key[1] or key in seen:
                continue
            seen.add(key)
            try:
                await ReconPipeline(repo).relink_supplier(*key)
            except Exception:
                logger.exception("[recon] relink failed for supplier %s", key[1])


def _adjudicator(llm: ReconLLM):
    """Synchronous adjudicator hook for LineMatcher. The matcher is pure and
    synchronous; LLM adjudication is therefore pre-computed by the pipeline in a
    later version — for now the deterministic matcher (with unique-rate rescue)
    runs alone and leftover lines are left for a human."""
    return None


def _user_message(exc: Exception) -> str:
    msg = str(exc)
    if isinstance(exc, asyncio.TimeoutError):
        return "Reading took too long — try splitting the file"
    if "OPENAI_API_KEY" in msg:
        return "Scanned pages can't be read: the reading service isn't configured"
    return msg[:300] or type(exc).__name__


def start_enabled() -> bool:
    return C.WORKER_ENABLED
