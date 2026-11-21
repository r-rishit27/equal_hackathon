"""The recon vocabulary (docs/reconciliation/RECON_VOCABULARY.md ↔ backend_ocr/app/recon/vocab.py) and its use in the DB.

Unit tests: the registry is complete for every internal code Recon emits, every mapped value is a known code,
and the document and the registry agree. DB tests (RECON_TEST_DB_URL): the generated code columns carry the
right codes through extraction, correction and recompute, and the foreign keys hold.
"""
from __future__ import annotations

import os
import re
import uuid
from pathlib import Path

import pytest

from backend_ocr.app.recon import vocab as V
from backend_ocr.app.recon.types import AuditVerdict, DocClass, LineStatus, MatchMethod, SegmentKind, Severity

ROOT = Path(__file__).resolve().parents[2]
DOC = (ROOT / "docs/reconciliation/RECON_VOCABULARY.md").read_text()
ENGINE = (ROOT / "backend_ocr/app/recon/engine.py").read_text()


def test_every_code_is_written_in_the_vocabulary_document():
    missing = [f"{k}.{c}" for k, items in V.CODES.items() for c, *_ in items if not re.search(rf"`{c}`|\b{c}\b", DOC)]
    assert not missing, f"codes in recon/vocab.py but not in docs/reconciliation/RECON_VOCABULARY.md: {missing}"


def test_every_kind_is_named_in_the_document():
    assert not [k for k in V.CODES if f"`{k}`" not in DOC]


def test_mapped_values_are_known_codes():
    pairs = [(V.DOC_CLASS_ROLE, "doc_role"), (V.SEGMENT_KIND_ROLE, "doc_role"), (V.SEGMENT_KIND_LEG, "recon_leg"),
             (V.SEGMENT_KIND_GRANULARITY, "receipt_granularity"), (V.LAYOUT_PV_FORMAT, "pv_format"),
             (V.LAYOUT_EVIDENCE_LAYER, "evidence_layer"), (V.VERDICT_STATUS, "verification_status"),
             (V.SEVERITY_OUTCOME, "recon_outcome"), (V.MATCH_METHOD, "match_method"),
             (V.COLUMN_QTY_ROLE, "qty_role"), (V.COLUMN_RATE_ROLE, "rate_role")]
    bad = [(kind, c) for m, kind in pairs for c in m.values() if not V.code_known(kind, c)]
    bad += [(k, c) for k, _t, c, _x in V.ALIASES if not V.code_known(k, c)]
    bad += [("charge_type", c) for c, _p in V.CHARGE_PATTERNS if not V.code_known("charge_type", c)]
    assert not bad


def test_every_internal_code_is_mapped_or_deliberately_roleless():
    roleless_pages, roleless_parts = {"TERMS_CONDITIONS", "OTHER"}, {"OTHER", "IGNORED"}
    assert {d.value for d in DocClass} == set(V.DOC_CLASS_ROLE) | roleless_pages
    assert {k.value for k in SegmentKind} == set(V.SEGMENT_KIND_ROLE) | roleless_parts
    assert {v.value for v in AuditVerdict} == set(V.VERDICT_STATUS) | {"UNKNOWN"}
    assert {s.value for s in Severity} == set(V.SEVERITY_OUTCOME)
    assert {m.value for m in MatchMethod} == set(V.MATCH_METHOD) | {"NONE"}
    assert {s.value for s in LineStatus} == {c for c, *_ in V.CODES["recon_line_status"]}


def test_every_header_check_the_engine_emits_is_a_check_code():
    emitted = {c.upper() for c in re.findall(r'self\._add\("([a-z_]+)"', ENGINE)}
    known = {c for c, *_ in V.CODES["recon_check_code"]}
    assert emitted and emitted <= known, emitted - known


def test_codes_are_unique_and_shaped():
    for kind, items in V.CODES.items():
        codes = [c for c, *_ in items]
        assert len(codes) == len(set(codes)), kind
        assert all(re.fullmatch(r"[A-Z][A-Z0-9_]*", c) for c in codes), kind
        parents = {p for *_, p in items if p}
        if kind == "work_package":
            assert parents <= set(codes)


def test_units_and_ambiguity():
    assert [V.uom_code(u) for u in ("Nos", "NO", "SF", "sft", "m2", "M", "Rft", "NA", "%")] == \
        ["EA", "EA", "SQFT", "SQFT", "SQM", "RMT", "RFT", "LS", "PCT"]
    assert V.uom_family("SQM") == "AREA" and V.uom_code("For Soutl") is None
    # §18: a bare QTY is resolved by document, never globally
    qty = {(ctx, c) for k, t, c, ctx in V.ALIASES if k == "qty_role" and t == "QTY"}
    assert qty == {("PHYSICAL_VERIFICATION_REPORT", "QTY_ORDERED"), ("TAX_INVOICE", "QTY_INVOICED")}


def test_scope_charge_and_value_history():
    assert V.scope_exclusion_source("NOT_COVERED", "As per Bata Instruction not in scope") == "CLIENT_INSTRUCTION"
    assert V.scope_exclusion_source("NOT_COVERED", "certificate needed. Out of audit") == "CERTIFICATE_PENDING"
    assert V.scope_exclusion_source("NOT_COVERED", None) == "AUDITOR_SCOPE"
    assert V.scope_exclusion_source("VERIFIED", "instruction") is None
    # §17: the auditor's words decide the code, whatever bucket the classifier used for billing
    bata = "As per Bata Instruction not in scope"
    for verdict in ("NOT_COUNTABLE", "ADDITIONAL", "NOT_COVERED"):
        assert (V.verification_status(verdict, bata), V.scope_exclusion_source(verdict, bata)) == \
            ("NOT_IN_SCOPE", "CLIENT_INSTRUCTION")
    assert V.verification_status("NOT_COUNTABLE", "Tonnage could not be checked") == "NOT_VERIFIABLE"
    assert V.verification_status("VERIFIED", bata) == "VERIFIED"
    assert V.charge_type("Packing and forwarding Charges 3%") == "PACKING_FORWARDING"
    assert V.charge_type("Malba Disposal") == "DEBRIS_DISPOSAL"
    assert V.value_history_from_raw("~~18~~ 15") == [{"was": 18.0, "now": 15.0, "kind": "HANDWRITTEN_CORRECTION"}]
    assert V.value_history_from_raw("[548] 602")[0]["now"] == 602.0
    assert V.value_history_from_raw("348+102 = 450") == []


def test_learned_aliases_cannot_be_global():
    ddl = next(s for s in V.VOCAB_DDL if "vocab_aliases (" in s)
    assert "CHECK (source = 'SEED' OR scope_tenant_id IS NOT NULL)" in ddl


# ── against Postgres ──────────────────────────────────────────────────────────
DB_URL = os.getenv("RECON_TEST_DB_URL")
db = pytest.mark.skipif(not DB_URL, reason="RECON_TEST_DB_URL not set")


@db
async def test_generated_codes_follow_extraction_and_correction(pool):
    from .test_repo_db import TENANT, _load_case
    repo, case_id, _ = await _load_case(pool, "innerspace_red")
    from backend_ocr.app.recon.pipeline import ReconPipeline
    await ReconPipeline(repo).recompute(TENANT, case_id)               # writes line results and header checks
    async with pool.acquire() as c:
        segs = {r["kind"]: dict(r) for r in await c.fetch(
            "SELECT kind, doc_role, recon_leg, receipt_granularity, pv_format, evidence_layer FROM recon_doc_segments "
            "WHERE tenant_id = $1::uuid", TENANT)}
        ev = await c.fetch("SELECT id, verdict, auto_verdict, remark, verification_status, scope_exclusion_source, "
                           "line_origin, uom, uom_family, unit FROM recon_evidence_rows WHERE tenant_id = $1::uuid", TENANT)
        inv = await c.fetch("SELECT is_charge, description, line_origin, charge_type, pricing_basis "
                            "FROM recon_invoice_lines WHERE tenant_id = $1::uuid", TENANT)
        checks = await c.fetch("SELECT code, check_code, outcome FROM recon_header_checks WHERE tenant_id = $1::uuid",
                               TENANT)
        results = await c.fetch("SELECT severity, outcome FROM recon_line_results WHERE tenant_id = $1::uuid", TENANT)
    assert segs["PURCHASE_ORDER"]["doc_role"] == "PURCHASE_ORDER" and segs["PURCHASE_ORDER"]["recon_leg"] == "COMMITMENT"
    pv = segs["PV_SECTION"]
    assert (pv["doc_role"], pv["recon_leg"], pv["receipt_granularity"]) == \
        ("PHYSICAL_VERIFICATION_REPORT", "RECEIPT", "ITEM_QTY")
    assert segs["TAX_INVOICE"]["recon_leg"] == "BILLING"
    assert ev and all(r["auto_verdict"] for r in ev)                   # every row saved with its meaning
    for r in ev:
        effective = r["verdict"] or r["auto_verdict"]
        assert r["verification_status"] == V.verification_status(effective, r["remark"])
        assert r["scope_exclusion_source"] == V.scope_exclusion_source(effective, r["remark"])
        assert r["uom"] == V.uom_code(r["unit"])
    for r in inv:
        assert r["line_origin"] == ("CHARGE" if r["is_charge"] else "CONTRACT_LINE")
        if r["is_charge"]:
            assert r["charge_type"] == V.charge_type(r["description"])
    assert checks and all(r["check_code"] == r["code"].upper() for r in checks)
    assert {r["outcome"] for r in checks} <= {"PASS", "WARN", "HOLD", "FAIL"}
    assert results and all(r["outcome"] == V.SEVERITY_OUTCOME[r["severity"]] for r in results)

    # a reviewer's correction moves the generated status and lands in value_history
    row = next(r for r in ev if r["auto_verdict"] == "VERIFIED")
    await repo.correct_evidence(TENANT, str(row["id"]), {"verdict": "NOT_COVERED", "remark": "As per Bata instructions"},
                                "tester")
    async with pool.acquire() as c:
        r = await c.fetchrow("SELECT verification_status, scope_exclusion_source, value_history "
                             "FROM recon_evidence_rows WHERE id = $1", row["id"])
    assert (r["verification_status"], r["scope_exclusion_source"]) == ("NOT_IN_SCOPE", "CLIENT_INSTRUCTION")
    import json
    hist = json.loads(r["value_history"])
    assert hist[-1]["field"] == "verdict" and hist[-1]["kind"] == "REVIEWER_CORRECTION" and hist[-1]["by"] == "tester"

    # correcting a quantity to 0 re-classifies the row: the auditor's meaning follows the number
    other = next(r for r in ev if r["auto_verdict"] == "VERIFIED" and r["id"] != row["id"])
    await repo.correct_evidence(TENANT, str(other["id"]), {"audit_qty": 0}, "tester")
    async with pool.acquire() as c:
        r2 = await c.fetchrow("SELECT auto_verdict, verification_status FROM recon_evidence_rows WHERE id = $1",
                              other["id"])
    assert (r2["auto_verdict"], r2["verification_status"]) == ("NOT_DONE", "NOT_EXECUTED")


@db
async def test_a_code_in_use_cannot_be_removed(pool):
    """The generated columns reference vocab_codes: a code a row carries can be deprecated, never deleted."""
    import asyncpg
    from .test_repo_db import TENANT, _doc
    doc = await _doc(pool, "fk.pdf")
    async with pool.acquire() as c:
        seg = await c.fetchval("INSERT INTO recon_doc_segments (doc_id, tenant_id, supplier_id, kind, pages) "
                               "VALUES ($1::uuid, $2::uuid, $2::uuid, 'POD', '{1}') RETURNING id", doc, TENANT)
        assert await c.fetchval("SELECT doc_role FROM recon_doc_segments WHERE id = $1", seg) == "PROOF_OF_DELIVERY"
        other = await c.fetchval("INSERT INTO recon_doc_segments (doc_id, tenant_id, supplier_id, kind, pages) "
                                 "VALUES ($1::uuid, $2::uuid, $2::uuid, 'OTHER', '{2}') RETURNING id", doc, TENANT)
        assert await c.fetchval("SELECT doc_role FROM recon_doc_segments WHERE id = $1", other) is None
        with pytest.raises(asyncpg.ForeignKeyViolationError):
            await c.execute("DELETE FROM vocab_codes WHERE kind = 'receipt_granularity' AND code = 'CONSIGNMENT'")


@db
def test_sync_is_idempotent_and_never_deletes_codes():
    import psycopg2
    conn = psycopg2.connect(DB_URL)
    try:
        with conn.cursor() as cur:
            first = V.sync(cur)
            second = V.sync(cur)
            assert second["columns_built"] == 0 and second["codes"] == first["codes"]
            cur.execute("INSERT INTO vocab_codes (kind, code, label, tier, version_added) "
                        "VALUES ('qty_role', 'QTY_TEST_RETIRED', 'x', 'L', 'v0') ON CONFLICT DO NOTHING")
            V.sync(cur)
            cur.execute("SELECT deprecated FROM vocab_codes WHERE kind = 'qty_role' AND code = 'QTY_TEST_RETIRED'")
            assert cur.fetchone()[0] is True                               # deprecated, still there
            cur.execute("DELETE FROM vocab_codes WHERE code = 'QTY_TEST_RETIRED'")
            with pytest.raises(psycopg2.errors.CheckViolation):
                cur.execute("INSERT INTO vocab_aliases (kind, code, alias_text, alias_norm, source) "
                            "VALUES ('qty_role', 'QTY_CLAIMED', 'Contractor Claim', 'contractor claim', 'HUMAN')")
        conn.rollback()
    finally:
        conn.close()


@pytest.fixture
async def pool():
    if not DB_URL:
        pytest.skip("RECON_TEST_DB_URL not set")
    import asyncpg

    from backend_ocr.app.recon.schema import DDL

    from .test_repo_db import STUBS
    from .vocab_db import apply_vocab
    p = await asyncpg.create_pool(DB_URL, min_size=1, max_size=4)
    async with p.acquire() as c:
        await c.execute(STUBS)
        for stmt in DDL:
            await c.execute(stmt)
    apply_vocab(DB_URL)
    yield p
    await p.close()
