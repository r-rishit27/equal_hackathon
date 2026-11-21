"""End-to-end ingest on the real Anjile sample PDFs, uploaded out of order
(report → PO → invoice), against a throwaway Postgres with a FakeLLM.

Needs RECON_TEST_DB_URL and the sample folder "AHU by Anjile/" at the repo root
(client data — kept out of git). The FakeLLM answers only what a model would be
asked here: the scanned field-sheet pages' class and the invoice text (built
from the golden fixture).
"""
from __future__ import annotations

import json
import os
import uuid
from decimal import Decimal as D
from pathlib import Path

import pytest

asyncpg = pytest.importorskip("asyncpg")

from backend_ocr.app.recon.llm import FakeLLM
from backend_ocr.app.recon.pipeline import ReconPipeline
from backend_ocr.app.recon.repo import ReconRepository
from backend_ocr.app.recon.schema import DDL

from .vocab_db import apply_vocab

from .golden import GOLDEN
from .test_repo_db import STUBS

ROOT = Path(__file__).resolve().parents[2]
ANJILE = ROOT / "AHU by Anjile"
DB_URL = os.getenv("RECON_TEST_DB_URL")
pytestmark = pytest.mark.skipif(not DB_URL or not ANJILE.exists(), reason="needs RECON_TEST_DB_URL and sample PDFs")

TENANT, SUPPLIER = str(uuid.uuid4()), str(uuid.uuid4())
EXTRA = """
DROP TABLE IF EXISTS dim_suppliers, supplier_gstins CASCADE;
CREATE TABLE dim_suppliers (supplier_id UUID PRIMARY KEY, tenant_id UUID, name TEXT, gstn TEXT, brand_id UUID, legal_name TEXT);
CREATE TABLE supplier_gstins (supplier_id UUID, tenant_id UUID, gstin TEXT);
ALTER TABLE vendor_documents ADD COLUMN IF NOT EXISTS claims_status VARCHAR(20);
"""


def _fake_llm() -> FakeLLM:
    g = json.loads((GOLDEN / "anjile.json").read_text())["invoice"]
    header = {"invoice_no": g["invoice_no"], "invoice_date": "24-Oct-26", "vendor": {**g["vendor"]},
              "buyer_gstin": g["buyer_gstin"], "place_of_supply": g["place_of_supply"], "po_ref": g["po_ref"],
              "header_lines": [{"sno": r[0], "description": r[1], "amount": r[5]} for r in g["header_lines"]],
              "taxable": g["taxable"], "igst": g["tax"]["igst"], "tax_rate": "18", "round_off": g["round_off"],
              "total": g["total"], "corrections": []}
    annex = {"invoice_no": "AMP/26-27/000", "po_ref": g["po_ref"], "printed_subtotal": g["printed_subtotal"],
             "lines": [{"sno": r[0], "description": r[1], "unit": r[2], "qty": str(r[3]), "rate": r[4], "amount": r[5],
                        "after_subtotal": False} for r in g["annexure_lines"]]}
    return FakeLLM({
        "classify_page": {"doc_class": "PV_FIELD_SHEET", "confidence": 0.9},
        "field_sheet": {"rows": []},
        "field_sheet_check": {"rows": []},
        "invoice_header": header,
        "invoice_annexure": annex,
    })


@pytest.fixture
async def pool():
    p = await asyncpg.create_pool(DB_URL, min_size=1, max_size=4)
    async with p.acquire() as c:
        await c.execute(STUBS)
        await c.execute(EXTRA)
        for stmt in DDL:
            await c.execute(stmt)
        apply_vocab(DB_URL)                      # vocabulary codes, generated columns, FKs
        await c.execute("INSERT INTO dim_suppliers VALUES ($1::uuid, $2::uuid, 'Anjle Mep Projects Pvt Ltd', "
                        "'07AAQCA8977K1ZP', NULL)", SUPPLIER, TENANT)
    yield p
    await p.close()


async def _upload(pool, path: Path) -> dict:
    async with pool.acquire() as c:
        r = await c.fetchrow(
            "INSERT INTO vendor_documents (supplier_id, tenant_id, file_name, file_path, doc_type, recon_status) "
            "VALUES ($1::uuid, $2::uuid, $3, $4, 'recon', 'PENDING') RETURNING id, tenant_id, supplier_id, file_name, file_path",
            SUPPLIER, TENANT, path.name, str(path))
    return dict(r)


async def _bytes(_tenant, path):
    return Path(path).read_bytes()


async def test_anjile_out_of_order_end_to_end(pool):
    repo = ReconRepository(pool)
    llm = _fake_llm()
    pipe = ReconPipeline(repo, llm=llm, load_bytes=_bytes)
    async with pool.acquire() as c:              # the bill already exists (ingested by the normal bill upload)
        sb = await c.fetchval("INSERT INTO stg_bills (tenant_id, bill_number, taxable_amount, gstin_seller, igst_amount, "
                              "igst_rate) VALUES ($1::uuid, 'AMP/26-27/070', 634890.50, '07AAQCA8977K1ZP', 114280.29, 18) "
                              "RETURNING stg_bill_id", TENANT)
        bill_id = str(await c.fetchval(
            "INSERT INTO fact_invoices (tenant_id, supplier_id, invoice_number, invoice_date, total_amount, stg_bill_id) "
            "VALUES ($1::uuid, $2::uuid, 'AMP/26-27/070', '2026-10-24', 749171.00, $3) RETURNING invoice_id",
            TENANT, SUPPLIER, sb))

    # 1. the auditor's report first — nothing to link to yet
    report = await _upload(pool, ANJILE / "Outlet mall HP Thane (8255) PV Report.pdf")
    out = await pipe.ingest(report)
    segs = await repo.segments_for_doc(str(report["id"]))
    by_title = {s["section_title"]: s for s in segs if s["kind"] == "PV_SECTION"}
    assert by_title["Annexure-4: AHU"]["status"] == "UNLINKED"
    assert {by_title[t]["status"] for t in ("Annexure-1: Civil & Electric Work", "Annexure-2: Lighting Work",
                                             "Annexure-3: Signage Work")} == {"FOREIGN"}
    assert out.status == "NEEDS_LINK"

    # 2. the PO — the AHU section now finds it and opens a case waiting for its invoice
    po_doc = await _upload(pool, ANJILE / "Show purchase order.pdf")
    out = await pipe.ingest(po_doc)
    cases = await repo.cases_for_supplier(TENANT, SUPPLIER)
    assert len(cases) == 1 and cases[0]["bill_id"] is None and cases[0]["po_id"] is not None

    # 3. the invoice — binds to the existing bill and adopts the waiting case
    inv_doc = await _upload(pool, ANJILE / "Final Tax Invoice of HP @Bhumi World Mumbai as per Audit Main bill.pdf")
    out = await pipe.ingest(inv_doc)
    cases = await repo.cases_for_supplier(TENANT, SUPPLIER)
    assert len(cases) == 1
    case = cases[0]
    assert str(case["bill_id"]) == bill_id
    s = case["summary_json"]
    assert D(s["expected_total"]) == D("636740.50")
    assert D(s["billed_total"]) == D("634890.50")
    assert D(s["under_billed"]) == D("1850.00")
    assert D(s["money_at_risk"]) == 0
    assert case["status"] == "NEEDS_REVIEW"
    roles = sorted(x["role"] for x in case["docs"])
    assert roles == ["evidence", "invoice", "po"]
    lines, header = await repo.results(str(case["id"]))
    hooter = next(l for l in lines if l["description"].startswith("Supply and Installation MCP Hooter"))
    assert "UNDER_BILLED" in hooter["statuses"]
    assert not [l for l in lines if l["kind"] == "not_in_po"]
    # Only the scanned field sheets and the invoice text reached the model.
    purposes = {p for p, _, _ in llm.calls}
    assert purposes <= {"classify_page", "field_sheet", "field_sheet_check", "invoice_header", "invoice_annexure"}


async def test_waiting_po_reads_the_vendors_existing_bill(pool):
    """A PO uploaded when the invoice is already in the app as a bill: recon reads
    that bill's own file (bills don't store a PO number) instead of waiting forever."""
    repo = ReconRepository(pool)
    pipe = ReconPipeline(repo, llm=_fake_llm(), load_bytes=_bytes)
    async with pool.acquire() as c:
        await c.execute("ALTER TABLE vendor_documents ADD COLUMN IF NOT EXISTS claims_status VARCHAR(20)")
        bill_id = str(await c.fetchval(
            "INSERT INTO fact_invoices (tenant_id, supplier_id, invoice_number, invoice_date, total_amount, upload_id) "
            "VALUES ($1::uuid, $2::uuid, 'AMP/26-27/070', '2026-10-24', 749171.00, gen_random_uuid()) RETURNING invoice_id",
            TENANT, SUPPLIER))
        await c.execute("INSERT INTO fact_invoices (tenant_id, supplier_id, invoice_number, invoice_date, upload_id) "
                        "VALUES ($1::uuid, $2::uuid, 'OLD/1', '2025-01-01', gen_random_uuid())", TENANT, SUPPLIER)
    po_doc = await _upload(pool, ANJILE / "Show purchase order.pdf")
    await pipe.ingest(po_doc)
    seg = (await repo.segments_for_doc(str(po_doc["id"])))[0]
    assert seg["status"] == "WAITING"
    async with pool.acquire() as c:
        rows = await c.fetch("SELECT file_path, recon_status, doc_label FROM vendor_documents WHERE file_path LIKE 'bill-upload:%'")
    assert len(rows) == 1                                   # only the bill dated after the PO
    assert rows[0]["recon_status"] == "PENDING" and rows[0]["doc_label"] == "Invoice (from bill)"
    await pipe.ingest(po_doc)                                # re-reading the PO doesn't queue the bill twice
    async with pool.acquire() as c:
        assert await c.fetchval("SELECT count(*) FROM vendor_documents WHERE file_path LIKE 'bill-upload:%'") == 1
