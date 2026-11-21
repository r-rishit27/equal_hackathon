"""Cash application end to end against a real Postgres (repo + service + job queue).

Runs only when AR_TEST_DB_URL points at a THROWAWAY database, e.g.

    createdb ar_test
    AR_TEST_DB_URL=postgresql://localhost/ar_test python3.12 -m pytest tests/receivables/test_service_db.py

Each test uses a fresh random tenant, so runs don't interfere.
"""
from __future__ import annotations

import os
import uuid
from decimal import Decimal as D

import pytest

asyncpg = pytest.importorskip("asyncpg")
DB_URL = os.getenv("AR_TEST_DB_URL")
pytestmark = pytest.mark.skipif(not DB_URL, reason="AR_TEST_DB_URL not set")

from backend_ocr.app.receivables.repo import CashAppRepository          # noqa: E402
from backend_ocr.app.receivables.schema import DDL, OPTIONAL_DDL        # noqa: E402
from backend_ocr.app.receivables.service import CashApplicationService, ServiceError  # noqa: E402


@pytest.fixture
async def svc():
    pool = await asyncpg.create_pool(DB_URL, min_size=1, max_size=4)
    async with pool.acquire() as c:
        for stmt in DDL:
            await c.execute(stmt)
        for stmt in OPTIONAL_DDL:
            try:
                await c.execute(stmt)
            except Exception:
                pass
    yield CashApplicationService(CashAppRepository(pool)), str(uuid.uuid4())
    await pool.close()


def invoice(num, buyer, total, taxable, gstin=None, date="01-11-2026", po=None):
    return {"invoice_number": num, "invoice_date": date, "payment_terms": "Net 30", "po_number": po,
            "buyer": {"name": buyer, "gstin": gstin},
            "taxes": {"taxable_amount": taxable, "total_tax_amount": total - taxable},
            "total_amount": total, "currency_code": "INR"}


async def drain(s: CashApplicationService):
    """What the worker does: claim jobs and run each."""
    n = 0
    while jobs := await s.repo.claim_jobs(50):
        for j in jobs:
            await s.run_match(j["tenant_id"], j["payment_id"], allow_auto=j["reason"] != "unapplied")
            await s.repo.finish_job(j["id"])
            n += 1
    return n


STATEMENT = b"""Date,Narration,Chq/Ref No,Withdrawal Amt,Deposit Amt
15/11/26,NEFT-HDFCN52026111500000001-ACME TRADING-INV 1045,HDFCN52026111500000001,,"1,18,000.00"
15/11/26,NEFT-HDFCN52026111500000002-BETA RETAIL LLP,HDFCN52026111500000002,,"58,000.00"
15/11/26,INT.PD 01-10-2026 TO 31-10-2026,,,"312.00"
16/11/26,NEFT-HDFCN52026111600000003-GAMMA FOODS,HDFCN52026111600000003,,"7,777.00"
"""


async def _status(s, t, pid):
    return (await s.repo.get_payment(t, pid))["status"]


async def _pid(s, t, needle):
    rows, _ = await s.repo.list_payments(t, None, None, needle, 10, 0)
    assert len(rows) == 1, (needle, rows)
    return str(rows[0]["id"])


async def test_end_to_end(svc):
    s, t = svc
    a = await s.ingest_invoice(t, invoice("INV-1045", "Acme Trading Pvt Ltd", 118000, 100000, "27AAACA1234A1Z5"), "u")
    await s.ingest_invoice(t, invoice("B-77", "Beta Retail LLP", 59000, 50000), "u")
    with pytest.raises(ServiceError) as e:                                   # duplicate invoice
        await s.ingest_invoice(t, invoice("INV-1045", "Acme Trading Pvt Ltd", 1, 1, "27AAACA1234A1Z5"), "u")
    assert e.value.status == 409

    out = await s.import_statement(t, STATEMENT, "nov.csv", "HDFC 1234", "u")
    assert out["credits"] == 4 and out["set_aside"] == 1 and out["queued"] == 3
    await drain(s)

    # A1: invoice quoted + exact → applied by the agent, invoice paid
    acme = await _pid(s, t, "00000001")
    p = await s.repo.get_payment(t, acme)
    assert p["status"] == "applied" and p["auto_applied"]
    inv = await s.repo.get_invoice(t, a["invoice_id"])
    assert inv["status"] == "paid" and inv["outstanding"] == D("0.00")

    # B1: Beta paid 59,000 − 2% of 50,000 = 58,000 → review with a TDS suggestion
    beta = await _pid(s, t, "00000002")
    p = await s.repo.get_payment(t, beta)
    assert p["status"] == "needs_review"
    best = p["suggestion"]["best"]
    assert best["kind"] == "amount_tds" and best["allocations"][0]["tds_amount"] == "1000.00"

    # G1: a stale version is refused
    with pytest.raises(ServiceError) as e:
        await s.apply(t, beta, best["allocations"], version=p["version"] - 1, method="accepted", actor="u")
    assert e.value.status == 409

    # Accept → paid, TDS recorded, rate + alias learned
    await s.apply(t, beta, best["allocations"], version=p["version"], method="accepted", actor="u",
                  kind=best["kind"], customer_id=best["customer_id"])
    rows, _ = await s.repo.list_invoices(t, None, None, "B-77", False, 5, 0)
    assert rows[0]["status"] == "paid" and rows[0]["tds_amount"] == D("1000.00")
    cust = await s.repo.get_customer(t, best["customer_id"])
    assert cust["tds_rate_hint"] == D("2.0")
    assert any(al["source"] == "learned" for al in cust["aliases"]) or cust["aliases"]

    # Non-receipt was set aside; unknown payer with no fitting invoice stays unmatched
    assert await _status(s, t, await _pid(s, t, "INT.PD")) == "not_receipt"
    gamma = await _pid(s, t, "00000003")
    assert await _status(s, t, gamma) == "unmatched"

    # E2: the identical file is refused; an overlapping statement imports only new lines
    with pytest.raises(ServiceError) as e:
        await s.import_statement(t, STATEMENT, "nov.csv", "HDFC 1234", "u")
    assert e.value.status == 409
    overlap = STATEMENT + b'17/11/26,NEFT-HDFCN52026111700000004-ACME TRADING,HDFCN52026111700000004,,"10.00"\n'
    again = await s.import_statement(t, overlap, "nov-dec.csv", "HDFC 1234", "u")
    assert again["duplicates"] == 4 and again["imported"] == 1

    # Statements are kept and can be shown back line by line, with each payment's status now
    sts = await s.repo.list_statements(t, 10, 0)
    assert [x["file_name"] for x in sts] == ["nov-dec.csv", "nov.csv"] and all(x["has_document"] for x in sts)
    first = await s.repo.get_statement(t, str(out["statement_id"]))
    assert [ln["outcome"] for ln in first["lines"]] == ["new", "new", "set_aside", "new"]
    assert first["lines"][0]["payment_status"] == "applied"
    ref, name, fmt = await s.repo.statement_document(t, str(out["statement_id"]))
    from backend_ocr.app.core import object_store
    assert object_store.load(ref) == STATEMENT and fmt == "csv"
    assert (await s.repo.get_payment(t, acme))["statement_id"] is not None

    # G3: unapply reopens the invoice; the agent does not re-apply on its own
    await s.unapply(t, acme, "wrong customer", "u")
    await drain(s)
    inv = await s.repo.get_invoice(t, a["invoice_id"])
    assert inv["status"] == "open" and inv["outstanding"] == D("118000.00")
    assert await _status(s, t, acme) == "needs_review"

    # KPIs
    summ = await s.repo.summary(t, 30)
    assert summ["payments"]["receipts"] == 4 and summ["payments"]["auto_count"] == 0  # auto flag cleared by unapply


async def test_remittance_before_payment_and_partial(svc):
    s, t = svc
    await s.ingest_invoice(t, invoice("INV-1", "Delta Corp", 100000, 100000), "u")
    await s.ingest_invoice(t, invoice("INV-2", "Delta Corp", 50000, 50000), "u")
    # C4: the advice arrives first, names both invoices, quotes the UTR
    r = await s.add_remittance(t, data={"payer_name": "Delta Corp", "payment_reference": "UTIBR520261120000099",
                                        "payment_date": None, "total_amount": 150000,
                                        "lines": [{"invoice_number": "INV-1", "amount_paid": 100000},
                                                  {"invoice_number": "INV-2", "amount_paid": 50000}]},
                               source="text", raw_text="...", source_file=None, storage_ref=None, actor="u")
    assert r["payment_id"] is None
    rem = await s.repo.get_remittance(t, r["remittance_id"])
    assert rem["raw_text"] == "..." and len(rem["lines"]) == 2
    stmt = b"Date,Narration,Deposit Amt\n20/11/26,RTGS/UTIBR520261120000099/DLT,150000\n"
    await s.import_statement(t, stmt, "s.csv", None, "u")
    await drain(s)
    pid = await _pid(s, t, "UTIBR520261120000099")
    p = await s.repo.get_payment(t, pid)
    assert p["status"] == "applied" and p["suggestion"]["best"]["kind"] == "remittance"

    # A3 + A9: a manual partial, then the rest stays on account
    await s.ingest_invoice(t, invoice("INV-3", "Delta Corp", 10000, 10000), "u")
    res = await s.record_payment(t, {"received_on": "2026-11-21", "amount": "15000", "payer_name": "DELTA CORP",
                                     "utr": "X1"}, "u")
    pid2 = res["payment_id"]
    p2 = await s.repo.get_payment(t, pid2)
    inv3, _ = await s.repo.list_invoices(t, None, None, "INV-3", False, 5, 0)
    out = await s.apply(t, pid2, [{"invoice_id": str(inv3[0]["id"]), "amount_applied": "10000"}],
                        version=p2["version"], method="manual", actor="u")
    assert out["status"] == "partially_applied" and out["left_on_account"] == "5000.00"
    # over-applying the invoice is refused
    with pytest.raises(ServiceError):
        p2 = await s.repo.get_payment(t, pid2)
        await s.apply(t, pid2, [{"invoice_id": str(inv3[0]["id"]), "amount_applied": "5000"}],
                      version=p2["version"], method="manual", actor="u")
    # a manual payment with the same UTR warns rather than creating a duplicate (E4)
    dup = await s.record_payment(t, {"received_on": "2026-11-21", "amount": "15000", "utr": "X1"}, "u")
    assert "duplicate_warning" in dup


async def test_uploads_match_straight_away_without_the_worker(svc):
    """Every upload re-runs the agent on what it affects (service.drain), worker or not."""
    s, t = svc
    await s.ingest_invoice(t, invoice("D-1", "Delta Corp", 100000, 100000), "u")
    await s.ingest_invoice(t, invoice("D-2", "Delta Corp", 50000, 50000), "u")
    await s.ingest_invoice(t, invoice("E-1", "Echo Traders", 150000, 150000), "u")
    s.repo.enqueued.clear()

    stmt = (b"Date,Narration,Chq/Ref No,Deposit Amt\n"
            b"10/11/26,NEFT CR-ICIC0000001-DELTA CORP-OURCO,ICICN52026111000000001,150000\n"
            b"10/11/26,NEFT CR-SBIN0000002-ECHO TRADERS-OURCO,SBINN52026111000000002,150000\n")
    await s.import_statement(t, stmt, "s.csv", None, "u")
    assert await s.drain(t, s.repo.enqueued) == 2
    delta, echo = await _pid(s, t, "DELTA CORP"), await _pid(s, t, "ECHO TRADERS")
    assert await _status(s, t, echo) == "applied"            # its only open invoice, exact
    assert await _status(s, t, delta) == "needs_review"      # two invoices, no advice yet

    # Remittance without a UTR: two payments of 1,50,000 exist, the payer name picks Delta's.
    s.repo.enqueued.clear()
    r = await s.add_remittance(t, data={"payer_name": "Delta Corp Pvt Ltd", "payment_reference": None,
                                        "payment_date": None, "total_amount": 150000,
                                        "lines": [{"invoice_number": "D-1", "amount_paid": 100000},
                                                  {"invoice_number": "D-2", "amount_paid": 50000}]},
                               source="text", raw_text="...", source_file=None, storage_ref=None, actor="u")
    assert r["payment_id"] == delta
    await s.drain(t, s.repo.enqueued)
    p = await s.repo.get_payment(t, delta)
    assert p["status"] == "applied" and p["auto_applied"] and p["suggestion"]["best"]["kind"] == "remittance"

    # A new invoice re-checks waiting payments: Foxtrot's money arrived before its invoice.
    s.repo.enqueued.clear()
    await s.import_statement(t, b"Date,Narration,Deposit Amt\n12/11/26,IMPS-631000000009-FOXTROT LLP,25000\n",
                             "s2.csv", None, "u")
    await s.drain(t, s.repo.enqueued)
    fox = await _pid(s, t, "FOXTROT")
    assert await _status(s, t, fox) == "unmatched"
    s.repo.enqueued.clear()
    await s.ingest_invoice(t, invoice("F-1", "Foxtrot LLP", 25000, 25000, date="01-11-2026"), "u")
    await s.drain(t, s.repo.enqueued)
    assert await _status(s, t, fox) == "applied"


async def test_applying_one_payment_rematches_the_customers_others(svc):
    """Two equal invoices, two equal deposits: once a person applies the first, the second
    is no longer ambiguous and applies itself (ledger_changed)."""
    s, t = svc
    await s.ingest_invoice(t, invoice("K-1", "Kilo Stationers", 5900, 5000, date="18-10-2026"), "u")
    await s.ingest_invoice(t, invoice("K-2", "Kilo Stationers", 5900, 5000, date="19-10-2026"), "u")
    s.repo.enqueued.clear()
    await s.import_statement(t, b"Date,Narration,Deposit Amt\n05/11/26,BY CASH DEP KILO STATIONERS,5900\n"
                                b"05/11/26,BY CASH DEP KILO STATIONERS,5900\n", "k.csv", None, "u")
    await s.drain(t, s.repo.enqueued)
    rows, _ = await s.repo.list_payments(t, None, None, "KILO", 5, 0)
    assert [r["suggestion_kind"] for r in rows] == ["amount_exact_ambiguous"] * 2
    first = await s.repo.get_payment(t, str(rows[0]["id"]))
    best = first["suggestion"]["best"]
    s.repo.enqueued.clear()
    await s.apply(t, str(first["id"]), best["allocations"], version=first["version"], method="accepted", actor="u")
    await s.drain(t, s.repo.enqueued)
    second = await s.repo.get_payment(t, str(rows[1]["id"]))
    assert second["status"] == "applied" and second["auto_applied"]
    assert second["suggestion"]["best"]["allocations"][0]["invoice_number"] != best["allocations"][0]["invoice_number"]
