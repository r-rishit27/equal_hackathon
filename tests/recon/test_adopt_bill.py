"""`adopt_bill`, the method two production bugs came out of.

It had no test because it is raw SQL and the suite has no database. That was
the largest gap in docs/reconciliation/STRESS_TESTING.md, and it is closable without one: the part
that was wrong both times is the **decision** — which key to look under,
whether a deleted row counts, whether to revive it — not the SQL itself.

So the connection is faked. These tests say nothing about whether the queries
run; they say what the method decides, which is where the bugs were:

  - keyed on the upload, so two bills shared one document (fixed `a30ee64`)
  - a deleted row returned as if usable, so a waiting PO never read its bill
    (fixed `6819836`)
"""
from __future__ import annotations

import pytest

from backend_ocr.app.recon.repo import ReconRepository


class FakeConn:
    """Enough of an asyncpg connection to watch the decisions being made."""

    def __init__(self, rows: dict[str, dict | None]) -> None:
        self.rows = rows            # file_path -> row, or None for "absent"
        self.updated: list[str] = []
        self.inserted: list[str] = []

    async def fetchrow(self, sql: str, *args):
        if "UPDATE" in sql:
            return None
        path = args[1]
        row = self.rows.get(path)
        # The legacy lookup adds "AND deleted_at IS NULL", so a deleted row is
        # invisible to it however the caller asked.
        if row is not None and "deleted_at IS NULL" in sql and row["deleted_at"] is not None:
            return None
        return row

    async def execute(self, sql: str, *args):
        if sql.strip().startswith("UPDATE"):
            self.updated.append(str(args[0]))

    async def fetchval(self, sql: str, *args):
        if "INSERT INTO vendor_documents" in sql:
            self.inserted.append(args[4])       # file_path
            return "new-doc-id"
        return None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False


class FakePool:
    def __init__(self, conn: FakeConn) -> None:
        self._conn = conn

    def acquire(self):
        return self._conn


def repo_with(rows: dict[str, dict | None], bill: dict | None = None):
    r = ReconRepository.__new__(ReconRepository)
    conn = FakeConn(rows)
    r.pool = FakePool(conn)

    async def _bill(_tenant, _bill_id):
        return bill if bill is not None else {
            "upload_id": "UP1", "supplier_id": "SUP1", "brand_id": None,
            "invoice_number": "IS-120",
        }
    r.bill = _bill                                             # type: ignore[assignment]
    return r, conn


T, B = "tenant-1", "bill-1"


@pytest.mark.asyncio
async def test_a_new_bill_gets_a_document_keyed_to_the_bill():
    """Not to its upload. Re-uploading an invoice makes a second bill row
    against the SAME upload, and an upload-keyed document was shared by both:
    deleting one bill's copy took the other's invoice with it."""
    r, conn = repo_with({})
    out = await r.adopt_bill(T, B, "recon")
    assert out == "new-doc-id"
    assert conn.inserted == [f"bill:{B}"]


@pytest.mark.asyncio
async def test_an_existing_bill_keyed_document_is_reused():
    r, conn = repo_with({f"bill:{B}": {"id": "doc-1", "deleted_at": None}})
    assert await r.adopt_bill(T, B, "recon") == "doc-1"
    assert conn.inserted == [], "idempotent per bill"


@pytest.mark.asyncio
async def test_a_live_upload_keyed_document_from_before_the_change_still_serves():
    """Existing links must not break on deploy."""
    r, conn = repo_with({"bill-upload:UP1": {"id": "legacy-1", "deleted_at": None}})
    assert await r.adopt_bill(T, B, "recon") == "legacy-1"
    assert conn.inserted == []


@pytest.mark.asyncio
async def test_a_deleted_upload_keyed_document_is_not_inherited():
    """The collision in reverse: this bill must not inherit another bill's
    deletion. It gets a document of its own."""
    r, conn = repo_with({"bill-upload:UP1": {"id": "legacy-1", "deleted_at": "2026-11-19"}})
    out = await r.adopt_bill(T, B, "recon")
    assert out == "new-doc-id"
    assert conn.inserted == [f"bill:{B}"]


@pytest.mark.asyncio
async def test_a_deleted_document_is_not_offered_as_usable():
    """Returning its id was the bug: the caller logged "reading 1 bill" and
    read none, and the PO waited for an invoice that existed."""
    r, _ = repo_with({f"bill:{B}": {"id": "doc-1", "deleted_at": "2026-11-19"}})
    assert await r.adopt_bill(T, B, "recon") is None


@pytest.mark.asyncio
async def test_a_waiting_po_can_revive_it():
    """The one moment that justifies undoing a deletion: a PO actively waiting
    for its invoice is a fresh request, not the loop resurrecting it."""
    r, conn = repo_with({f"bill:{B}": {"id": "doc-1", "deleted_at": "2026-11-19"}})
    assert await r.adopt_bill(T, B, "recon", revive=True) == "doc-1"
    assert conn.updated == ["doc-1"], "cleared the deletion and re-queued"


@pytest.mark.asyncio
async def test_revive_does_not_disturb_a_live_document():
    r, conn = repo_with({f"bill:{B}": {"id": "doc-1", "deleted_at": None}})
    assert await r.adopt_bill(T, B, "recon", revive=True) == "doc-1"
    assert conn.updated == [], "nothing to undo"


@pytest.mark.asyncio
async def test_a_bill_with_no_file_cannot_be_adopted():
    """There is nothing to read. Better None than a document pointing nowhere."""
    r, conn = repo_with({}, bill={"upload_id": None, "supplier_id": "SUP1"})
    assert await r.adopt_bill(T, B, "recon") is None
    assert conn.inserted == []


@pytest.mark.asyncio
async def test_a_missing_bill_cannot_be_adopted():
    r, _ = repo_with({}, bill={})
    assert await r.adopt_bill(T, B, "recon") is None
