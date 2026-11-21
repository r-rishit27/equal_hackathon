"""CashAppWorker — the cash application agent's loop (02_LLD.md §7).

Drains ar_match_jobs: `UPDATE … WHERE id IN (… FOR UPDATE SKIP LOCKED)`, so any
number of workers can run side by side; today the scheduler runs exactly one
(advisory lock). Woken by NOTIFY on `ar_match` from every enqueue, with
BaseWorker's safety poll for anything a notification missed.

The job handler is idempotent: run_match re-reads the payment and skips one that
is no longer waiting, and apply() refuses a payment that is already applied, so a
job that runs twice (crash after apply, before DONE) cannot apply cash twice.

Off unless CASHAPP_WORKER_ENABLED=1 — local backends share the dev database, and
the first process to start owns the workers (see the review-workers incident).
"""
from __future__ import annotations

import logging
import os
import time

from ..review.base_worker import BaseWorker
from .repo import CashAppRepository, NOTIFY_CHANNEL
from .service import CashApplicationService, ServiceError
from .types import JobReason

logger = logging.getLogger(__name__)

STALE_MINUTES = 10
SWEEP_EVERY_S = 6 * 3600


class CashAppWorker(BaseWorker):
    name = "cash_app"
    notify_channel = NOTIFY_CHANNEL
    skip_backfill = False

    def __init__(self) -> None:
        self._svc: CashApplicationService | None = None
        self._started = False
        self._last_sweep = 0.0

    async def _service(self) -> CashApplicationService:
        if self._svc is None:
            from db import get_pool
            self._svc = CashApplicationService(CashAppRepository(await get_pool()))
        return self._svc

    async def process_batch(self) -> int:
        svc = await self._service()
        repo = svc.repo
        # At start-up any RUNNING job belongs to a process that died — re-queue now.
        n = await repo.reset_stale_jobs(0 if not self._started else STALE_MINUTES)
        if n:
            logger.warning("[cash_app] re-queued %d job(s) left RUNNING", n)
        self._started = True
        if time.monotonic() - self._last_sweep > SWEEP_EVERY_S:
            self._last_sweep = time.monotonic()
            swept = await repo.sweep()
            if swept:
                logger.info("[cash_app] sweep queued %d unmatched payment(s)", swept)

        jobs = await repo.claim_jobs(self.batch_size)
        for job in jobs:
            try:
                await svc.run_match(job["tenant_id"], job["payment_id"],
                                    allow_auto=job["reason"] != JobReason.UNAPPLIED)
                await repo.finish_job(job["id"])
            except ServiceError as e:
                # A business refusal (e.g. the payment was applied by a person meanwhile) is an answer.
                logger.info("[cash_app] job %s: %s", job["id"], e.message)
                await repo.finish_job(job["id"])
            except Exception as e:  # noqa: BLE001 — one bad payment must not stop the queue
                logger.exception("[cash_app] job %s failed", job["id"])
                await repo.fail_job(job["id"], job["attempts"], f"{type(e).__name__}: {e}")
        return len(jobs)


def start_enabled() -> bool:
    return os.getenv("CASHAPP_WORKER_ENABLED", "0").strip().lower() in ("1", "true", "yes", "on")
