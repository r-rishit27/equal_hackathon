"""The adapter contract.

**scan() yields the complete current truth for its slice, not a delta.**

That is the single most important property in this package. It is what lets the
worker AUTO_RESOLVE anything a detector stopped asserting, which in turn is what
makes mirroring existing signal into rh_findings safe rather than a staleness
bug waiting to happen.

It also means a pass must stay **bounded**. The CDC triggers are FOR EACH
STATEMENT and staging_promotion / tds_processing / category_enrichment all write
fact_invoices constantly, so this worker is woken often. BaseWorker coalesces a
notify storm into one wakeup, but only because a pass is cheap and idempotent.
If an adapter ever does unbounded work per wakeup, that protection disappears.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

import asyncpg

from ..types import FindingDraft


class FindingAdapter(ABC):
    #: stable identifier, also the AUTO_RESOLVE sweep scope
    detector: str
    #: the closed family spine this adapter writes into
    family: str
    #: which licensed service the findings belong to, so a tenant without that
    #: licence is not shown them even though the hub itself is core
    source_service: str = "bills"

    @abstractmethod
    def scan(
        self, conn: asyncpg.Connection, tenant_id: str, limit: int
    ) -> AsyncIterator[FindingDraft]:
        """Yield the current full truth for this slice."""
        raise NotImplementedError
