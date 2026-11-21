"""Recon schema + repository + recompute against a real Postgres.

Runs only when RECON_TEST_DB_URL points at a throwaway database, e.g.

    RECON_TEST_DB_URL=postgresql://postgres@127.0.0.1:55432/recon_test pytest tests/recon/test_repo_db.py

It creates minimal stand-ins for the app tables recon reads (vendor_documents,
fact_invoices, stg_bills, stg_bill_line_items), applies recon/schema.py twice
(idempotency), then pushes the golden sets through the DB path and checks the
result equals the in-memory one.
"""
from __future__ import annotations

import os
import uuid
from decimal import Decimal as D

import pytest

asyncpg = pytest.importorskip("asyncpg")

from backend_ocr.app.recon.assemble import reconcile
from backend_ocr.app.recon.pipeline import ReconPipeline
from backend_ocr.app.recon.repo import ReconRepository
from backend_ocr.app.recon.schema import DDL

from .vocab_db import apply_vocab
from backend_ocr.app.recon.types import CaseStatus, SegmentKind

from .golden import load

DB_URL = os.getenv("RECON_TEST_DB_URL")
pytestmark = pytest.mark.skipif(not DB_URL, reason="RECON_TEST_DB_URL not set")

STUBS = """
DROP TABLE IF EXISTS recon_events, vendor_item_aliases, recon_match_overrides, recon_header_checks,
  recon_line_results, recon_case_segments, recon_cases, recon_evidence_rows, recon_invoice_lines,
  purchase_order_lines, purchase_orders, recon_doc_segments, recon_doc_pages,
  vendor_documents, fact_invoices, stg_bills, stg_bill_line_items, tenant_service CASCADE;
-- Where a tenant's rule profile and GRN column mapping live. Added to the
-- stubs after the first full run of this suite failed on its absence: recon
-- started reading it when tenant rule profiles shipped, and nothing here
-- noticed because nothing ran these tests.
CREATE TABLE tenant_service (
  tenant_id UUID NOT NULL, service_key TEXT NOT NULL, enabled BOOLEAN NOT NULL DEFAULT true,
  limits JSONB NOT NULL DEFAULT '{}'::jsonb, config JSONB NOT NULL DEFAULT '{}'::jsonb,
  enabled_at TIMESTAMPTZ, disabled_at TIMESTAMPTZ, updated_by UUID, notes TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, service_key));
CREATE TABLE vendor_documents (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(), supplier_id UUID NOT NULL, tenant_id UUID NOT NULL,
  brand_id UUID, file_name VARCHAR(255) NOT NULL, file_path TEXT NOT NULL, file_size BIGINT,
  uploaded_by VARCHAR(100), uploaded_at TIMESTAMPTZ DEFAULT now(), doc_type VARCHAR(20) NOT NULL DEFAULT 'contract',
  doc_label VARCHAR(80), deleted_at TIMESTAMPTZ, deleted_by VARCHAR(100));
CREATE TABLE stg_bills (stg_bill_id UUID PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id UUID, bill_number TEXT,
  subtotal NUMERIC, taxable_amount NUMERIC, gstin_seller CHAR(15), cgst_amount NUMERIC, sgst_amount NUMERIC,
  igst_amount NUMERIC, cgst_rate NUMERIC, sgst_rate NUMERIC, igst_rate NUMERIC, place_of_supply TEXT);
CREATE TABLE fact_invoices (invoice_id UUID PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id UUID, supplier_id UUID,
  brand_id UUID, invoice_number TEXT, invoice_date DATE, total_amount NUMERIC, upload_id UUID, stg_bill_id UUID,
  archived_stg_bill_id UUID, soft_status TEXT DEFAULT 'active');
CREATE TABLE stg_bill_line_items (stg_bill_id UUID, tenant_id UUID, line_number INT, product_name TEXT, hsn_code TEXT,
  quantity NUMERIC, unit TEXT, unit_price NUMERIC, line_total NUMERIC, tax_rate_percent NUMERIC);
"""

TENANT = str(uuid.uuid4())
SUPPLIER = str(uuid.uuid4())


@pytest.fixture
async def pool():
    p = await asyncpg.create_pool(DB_URL, min_size=1, max_size=4)
    async with p.acquire() as c:
        await c.execute(STUBS)
        for _ in range(2):                       # idempotent
            for stmt in DDL:
                await c.execute(stmt)
        apply_vocab(DB_URL)                      # vocabulary codes, generated columns, FKs
    yield p
    await p.close()


async def _doc(pool, name="f.pdf") -> str:
    async with pool.acquire() as c:
        return str(await c.fetchval(
            "INSERT INTO vendor_documents (supplier_id, tenant_id, file_name, file_path, doc_type) "
            "VALUES ($1::uuid, $2::uuid, $3, 'x', 'recon') RETURNING id", SUPPLIER, TENANT, name))


async def _bill(pool, inv) -> str:
    async with pool.acquire() as c:
        sb = await c.fetchval(
            "INSERT INTO stg_bills (tenant_id, bill_number, taxable_amount, gstin_seller) VALUES ($1::uuid, $2, $3, $4) "
            "RETURNING stg_bill_id", TENANT, inv.invoice_no, inv.taxable, inv.vendor.gstin)
        return str(await c.fetchval(
            "INSERT INTO fact_invoices (tenant_id, supplier_id, invoice_number, invoice_date, total_amount, stg_bill_id) "
            "VALUES ($1::uuid, $2::uuid, $3, $4, $5, $6) RETURNING invoice_id",
            TENANT, SUPPLIER, inv.invoice_no, inv.invoice_date, inv.total, sb))


async def _load_case(pool, name: str, **cfg):
    """Golden set → rows, as the worker would have written them. Returns (repo, case_id, in-memory input)."""
    repo = ReconRepository(pool)
    inp = load(name, **cfg)
    doc = await _doc(pool, f"{name}.pdf")
    kinds = [SegmentKind.PURCHASE_ORDER, SegmentKind.TAX_INVOICE, *[SegmentKind.PV_SECTION] * len(inp.evidence),
             *[SegmentKind.POD] * len(inp.pods), *[SegmentKind.APPROVAL_MEMO] * len(inp.memos)]
    seg_ids = await repo.replace_segments(doc, TENANT, SUPPLIER, [{"kind": k.value, "pages": [i + 1]}
                                                                    for i, k in enumerate(kinds)])
    docs = [inp.po, inp.invoice, *inp.evidence, *inp.pods, *inp.memos]
    roles = ["po", "invoice", *["evidence"] * len(inp.evidence), *["pod"] * len(inp.pods), *["memo"] * len(inp.memos)]
    po_id = None
    for seg, kind, d in zip(seg_ids, kinds, docs):
        r = await repo.save_extraction(TENANT, SUPPLIER, seg, kind.value, d)
        po_id = po_id or r
    bill_id = await _bill(pool, inp.invoice)
    case_id = await repo.ensure_case(TENANT, SUPPLIER, bill_id=bill_id, invoice_no=inp.invoice.invoice_no,
                                     po_id=po_id, store_sn=inp.po.store_sn)
    for seg, role in zip(seg_ids, roles):
        await repo.attach(TENANT, case_id, seg, role, "auto", 0.99)
    return repo, case_id, inp


def _strip(res):
    s = res.summary
    return (s.expected_goods, s.expected_total, s.billed_total, s.money_at_risk, s.under_billed, s.counts,
            sorted((l.kind, l.severity.value, tuple(x.value for x in l.statuses)) for l in res.lines),
            sorted((h.code, h.passed) for h in res.header))


@pytest.mark.parametrize("name", ["bosch", "anjile", "innerspace_civil", "innerspace_red"])
async def test_db_recompute_equals_in_memory(pool, name):
    repo, case_id, inp = await _load_case(pool, name)
    db_res = await ReconPipeline(repo).recompute(TENANT, case_id)
    mem = reconcile(inp)
    assert _strip(db_res) == _strip(mem)
    lines, header = await repo.results(case_id)
    assert len(lines) == len(mem.lines) and header
    row = await repo.case_row(TENANT, case_id)
    assert row["status"] == CaseStatus.NEEDS_REVIEW.value
    assert await repo.case_row(str(uuid.uuid4()), case_id) is None          # other tenant sees nothing


async def test_po_upsert_and_reload(pool):
    repo, case_id, inp = await _load_case(pool, "anjile")
    pos = await repo.supplier_pos(TENANT, SUPPLIER)
    assert len(pos) == 1
    po = pos[0][1]
    assert po.po_number == "PPO00024046-1" and len(po.lines) == 39
    assert sum(l.amount for l in po.lines) == D("754596.00")


async def test_correction_override_alias_and_ack(pool):
    repo, case_id, _ = await _load_case(pool, "innerspace_red")
    pipe = ReconPipeline(repo)
    res = await pipe.recompute(TENANT, case_id)
    assert res.summary.money_at_risk == D("31350.00")

    # Correct the transport row: the auditor's 0 was "not covered" → billed at PO qty, no blocker.
    seg = next(s for s in await repo.case_segments(case_id) if s["role"] == "evidence")
    rows = await repo.evidence_rows(seg["id"])
    transport = next(r for r in rows if r.item.startswith("Transportation"))
    await repo.correct_evidence(TENANT, transport.key.split(":", 1)[1], {"verdict": "NOT_COVERED"}, "tester")
    res = await pipe.recompute(TENANT, case_id, actor="tester")
    assert res.summary.money_at_risk == 0

    # Acknowledge, then a recompute with the same result keeps ACKNOWLEDGED…
    await repo.acknowledge(TENANT, case_id, "tester", "checked")
    await pipe.recompute(TENANT, case_id)
    assert (await repo.case_row(TENANT, case_id))["status"] == "ACKNOWLEDGED"

    # …but an override that changes the result reopens it (E-CS-03).
    inv_seg = next(s for s in await repo.case_segments(case_id) if s["role"] == "invoice")
    lines = await repo.invoice_lines(inv_seg["id"])
    ten_ft = next(l for l in lines if "10 feet" in l.description)
    po = (await repo.supplier_pos(TENANT, SUPPLIER))[0][1]
    eight_ft = next(l for l in po.lines if "8 Fit" in l.description and "See" in l.description)
    await repo.set_override(TENANT, case_id, ten_ft.key, eight_ft.key, "tester")
    await repo.save_alias(TENANT, SUPPLIER, ten_ft.description, eight_ft.description, "tester")
    await pipe.recompute(TENANT, case_id)
    assert (await repo.case_row(TENANT, case_id))["status"] == "NEEDS_REVIEW"
    assert await repo.aliases(TENANT, SUPPLIER)


async def test_running_bills_on_one_po(pool):
    repo, first, inp = await _load_case(pool, "bosch")
    await ReconPipeline(repo).recompute(TENANT, first)
    # A second invoice for the same 6 units on the same PO → over PO.
    bill2 = await _bill(pool, type(inp.invoice)(invoice_no="26GJ/KMW/SI99999", invoice_date=inp.invoice.invoice_date,
                                                taxable=inp.invoice.taxable, total=inp.invoice.total,
                                                vendor=inp.invoice.vendor))
    po_id = str((await repo.case_row(TENANT, first))["po_id"])
    second = await repo.ensure_case(TENANT, SUPPLIER, bill_id=bill2, po_id=po_id)
    async with pool.acquire() as c:
        sb = await c.fetchval("SELECT stg_bill_id FROM fact_invoices WHERE invoice_id = $1::uuid", bill2)
        await c.execute("INSERT INTO stg_bill_line_items VALUES ($1, $2::uuid, 1, 'SPLIT AC 4.0TR HITACHI CASSETTE', "
                        "'84151010', 6, 'NOS', 95400, 572400, 18)", sb, TENANT)
    res = await ReconPipeline(repo).recompute(TENANT, second)
    assert any(h.code == "within_po_value" and not h.passed for h in res.header)
    assert res.summary.counts["BLOCKER"] >= 1


async def test_review_hub_adapter(pool):
    from backend_ocr.app.review.adapters.recon_variance import ReconVarianceAdapter
    from backend_ocr.app.review.types import FAMILIES, SEVERITIES, SUBJECT_TYPES
    async with pool.acquire() as c:
        await c.execute("DROP TABLE IF EXISTS dim_suppliers; CREATE TABLE dim_suppliers (supplier_id UUID, "
                        "tenant_id UUID, name TEXT, gstn TEXT, brand_id UUID, legal_name TEXT)")
    repo, case_id, _ = await _load_case(pool, "innerspace_red")
    await ReconPipeline(repo).recompute(TENANT, case_id)
    async with pool.acquire() as c:
        found = [f async for f in ReconVarianceAdapter().scan(c, TENANT, 50)]
    assert len(found) == 1
    f = found[0]
    assert f.family in FAMILIES and f.subject_type in SUBJECT_TYPES and f.severity in SEVERITIES
    assert f.severity == "HIGH" and f.money_at_risk == D("31350.00")
    # rh_finding_entities.entity_role CHECK: subject | related | counterparty | evidence (dev failed on "vendor").
    assert {e[2] for e in f.entities} <= {"subject", "related", "counterparty", "evidence"}
    assert f.deep_link.endswith(f"/documents?folder=recon&open=recon:{case_id}")
    assert any("Transportatio" in r[0] for r in f.evidence["rows"])
    await repo.acknowledge(TENANT, case_id, "tester", "ok")
    async with pool.acquire() as c:
        assert [f async for f in ReconVarianceAdapter().scan(c, TENANT, 50)] == []


async def test_a_po_without_a_number_is_flagged_not_crashed(pool):
    from backend_ocr.app.recon.types import ExtractedPO, POLine
    repo = ReconRepository(pool)
    doc = await _doc(pool, "no-number.pdf")
    [seg] = await repo.replace_segments(doc, TENANT, SUPPLIER, [{"kind": SegmentKind.PURCHASE_ORDER.value, "pages": [1]}])
    po = ExtractedPO(po_number="", lines=[POLine(sno=1, description="x", unit="NO", qty=D("1"), unit_price=D("1"), amount=D("1"))])
    assert await repo.save_extraction(TENANT, SUPPLIER, seg, SegmentKind.PURCHASE_ORDER.value, po) is None
    s = await repo.segment(TENANT, seg)
    assert s["status"] == "NEEDS_REVIEW" and any("No PO number" in w for w in s["warnings"])



async def test_orphaned_reads_are_requeued_at_startup_and_stuck_ones_later(pool):
    """A restart seconds after a file was claimed must not strand it (2026-11-13: two hours)."""
    repo = ReconRepository(pool)
    doc = await _doc(pool, "orphan.pdf")
    async with pool.acquire() as c:
        await c.execute("UPDATE vendor_documents SET recon_status = 'RUNNING', recon_started_at = now() WHERE id = $1::uuid", doc)
    assert await repo.reset_stale(25) == 0           # the periodic sweep leaves a fresh read alone
    assert await repo.reset_stale(0) == 1            # a starting worker owns every RUNNING row: re-queue it
    async with pool.acquire() as c:
        assert await c.fetchval("SELECT recon_status FROM vendor_documents WHERE id = $1::uuid", doc) == "PENDING"
