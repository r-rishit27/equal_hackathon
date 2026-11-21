"""Unit tests for the pure recon core: numbers, normalisation, rules, Hungarian."""
from __future__ import annotations

import random
import time
from decimal import Decimal as D

import pytest

from backend_ocr.app.recon.match import Cand, LineMatcher, hungarian
from backend_ocr.app.recon.normalize import canon_unit, norm, same_unit, variant_conflicts, variant_tokens
from backend_ocr.app.recon.num import close, fmt_inr, parse_inr
from backend_ocr.app.recon.rules import BillingRule, VerdictClassifier, is_boilerplate
from backend_ocr.app.recon.types import AuditVerdict as V, ChargeBasis, EvidenceRow, POLine, RuleConfig, Sourced


# ── num ──────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,want", [
    ("1,26,312.00", D("126312.00")), ("₹ 11,28,945.59", D("1128945.59")), ("6,75,432.00", D("675432.00")),
    ("2,105.2", D("2105.2")), ("(500)", D("-500")), ("Rs. 1,000/-", D("1000")), ("348+102=450", D("450")),
    (12, D("12")), ("11.1", D("11.1")),
])
def test_parse_inr(raw, want):
    assert parse_inr(raw) == want


@pytest.mark.parametrize("raw", ["####", "#####", "-", "", "n/a", None, "abc", "~"])
def test_parse_inr_unreadable_is_none_not_zero(raw):
    assert parse_inr(raw) is None


def test_close_and_fmt():
    assert close(D("2105.00"), D("2105.20"))
    assert not close(D("2105"), D("2120"))
    assert fmt_inr(D("1128945.59")) == "11,28,945.59"
    assert fmt_inr(D("-1850")) == "-1,850.00"
    assert fmt_inr(D("999")) == "999.00"


# ── normalize ────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,want", [
    ("PANAL PROGRAMMI NG AND INTEGRATIO N WITH MALL", "panel programming and integration with mall"),
    ("Supply & Installation of 22 Guage Duct", "22 gauge duct"),
    ("8 point 5 TR AHU Make Waves Zeco", "8.5 tr ahu"),
    ("Providing and fixing of Fau Isolater", "fau isolator"),
    ("INTEGRATED MAIN LT PANEL TYPE E", "integrated main lt panel type e"),
    ("Supply & Installation", "supply installation"),          # never empty
])
def test_norm(raw, want):
    assert norm(raw) == want


def test_variant_tokens_and_conflicts():
    assert variant_tokens("Wall low Base 1200x450x10 0mm") == {"1200x450x100"}
    assert variant_tokens("4.0TR cassette") == variant_tokens("4 TR cassette") == {"4tr"}
    assert variant_conflicts(variant_tokens("Panel Type D"), variant_tokens("Panel TYPE E")) == ["type-d≠type-e"]
    assert variant_conflicts(variant_tokens("Shelf 600"), variant_tokens("Shelf 1200")) == ["600#≠1200#"]
    assert variant_conflicts(variant_tokens("8 Way TPN board"), variant_tokens("8 way SPN board")) == ["pole-tpn≠pole-spn"]
    assert variant_conflicts(variant_tokens("Base 1200x450x10"), variant_tokens("Base 1200x450x100mm")) == []
    assert variant_conflicts(variant_tokens("channel 10 feet"), variant_tokens("channel 8 Fit")) == ["10ft≠8ft"]


def test_units():
    assert canon_unit("Sq mtrs.") == canon_unit("SM") == canon_unit("Sqmt") == "sqm"
    assert canon_unit("No.") == canon_unit("EACH") == "nos"
    assert same_unit("RMT", "m") is True
    assert same_unit("SF", "m") is False
    assert same_unit(None, "m") is None


# ── rules ────────────────────────────────────────────────────────────────────────

def _row(audit=None, remark=None, **kw):
    return EvidenceRow(key="e", item="x", audit_qty=None if audit is None else Sourced(value=D(str(audit))),
                       remark=remark, **kw)


@pytest.mark.parametrize("audit,remark,want", [
    (4, None, V.VERIFIED), (0, None, V.NOT_DONE), (None, "Not covered in audit.", V.NOT_COVERED),
    (None, "As per Bata Instruction not in scope", V.NOT_COUNTABLE), (None, "Out of Audit", V.NOT_COVERED),
    (None, "The work is not done/performed.", V.NOT_DONE), (0, "Not allowed separately", V.NOT_DONE),
    (None, "Tonnage could not be checked", V.NOT_COUNTABLE), (None, None, V.UNKNOWN),
    (3, "Two units are situated above the false ceiling.", V.VERIFIED),
])
def test_verdicts(audit, remark, want):
    assert VerdictClassifier().classify(_row(audit, remark)) == want


def test_verdict_config():
    assert VerdictClassifier(RuleConfig(blank_audit_means=V.NOT_DONE)).classify(_row()) == V.NOT_DONE
    cfg = RuleConfig(verdict_overrides={"lump sum": V.NOT_COUNTABLE})
    assert VerdictClassifier(cfg).classify(_row(None, "Included in lump sum")) == V.NOT_COUNTABLE
    assert VerdictClassifier().classify(_row(5, row_type="additional")) == V.ADDITIONAL


def test_billing_rule():
    r = BillingRule()
    assert r.expected_qty(D("1531"), _row(1665)) == (D("1531"), V.VERIFIED)
    assert r.expected_qty(D("70"), _row("30.8")) == (D("30.8"), V.VERIFIED)
    assert r.expected_qty(D("3"), _row(None, "not in scope")) == (D("3"), V.NOT_COUNTABLE)
    assert r.expected_qty(D("3"), _row(None, "not done")) == (D("0"), V.NOT_DONE)
    assert r.expected_qty(D("3"), None) == (D("3"), V.UNKNOWN)
    assert BillingRule(RuleConfig(cap_at_po=False)).expected_qty(D("10"), _row(12)) == (D("12"), V.VERIFIED)
    assert r.expected_charge(ChargeBasis.MIN, D("28078"), D("5"), D("545985.90")) == D("27299.30")
    assert r.expected_charge(ChargeBasis.FIXED, D("28078"), D("5"), D("545985.90")) == D("28078")


def test_boilerplate():
    assert is_boilerplate("-")
    assert is_boilerplate("The work is related to X. Verification is done through measurement.")
    assert not is_boilerplate("Two units are situated above the false ceiling.")


# ── Hungarian / matcher ──────────────────────────────────────────────────────────

def _brute(cost):
    import itertools
    n, m = len(cost), len(cost[0])
    best = min(itertools.permutations(range(m), n), key=lambda p: sum(cost[i][p[i]] for i in range(n)))
    return sum(cost[i][best[i]] for i in range(n))


@pytest.mark.parametrize("n,m", [(1, 1), (3, 3), (3, 5), (5, 3), (6, 6)])
def test_hungarian_optimal(n, m):
    rnd = random.Random(n * 10 + m)
    for _ in range(5):
        cost = [[rnd.random() for _ in range(m)] for _ in range(n)]
        pairs = hungarian(cost)
        assert len(pairs) == min(n, m)
        assert len({i for i, _ in pairs}) == len({j for _, j in pairs}) == len(pairs)
        got = sum(cost[i][j] for i, j in pairs)
        want = _brute(cost) if n <= m else _brute([list(r) for r in zip(*cost)])
        assert abs(got - want) < 1e-9


def test_hungarian_fast_enough():
    rnd = random.Random(1)
    cost = [[rnd.random() for _ in range(80)] for _ in range(80)]
    t = time.perf_counter()
    hungarian(cost)
    assert time.perf_counter() - t < 1.0


def _po(sno, desc, rate, unit="NO", qty=1):
    return POLine(sno=sno, description=desc, unit=unit, qty=D(str(qty)), unit_price=D(str(rate)), amount=D("0"))


def test_duplicate_rates_resolved_by_name():
    po = [_po(1, "Butterfly Valve Make Zoloto", 4200, qty=3), _po(2, "Pendent type SR sprinkler", 4200, qty=14)]
    c = [Cand(key="a", text="Supply & Installation of Pendent Type SR Sprinkler", unit="Nos", rate=D("4200")),
         Cand(key="b", text="Supply & Installation of Butterfly valve for Ahu", unit="Nos", rate=D("4200"))]
    got = {m.other_key: m.po_key for m in LineMatcher().match(po, c)}
    assert got == {"a": "po:2", "b": "po:1"}


def test_adjudicator_guardrail():
    po = [_po(1, "Copper wire for panel", 320, unit="RMT"), _po(2, "Thermostat wire", 165, unit="RMT")]
    c = [Cand(key="x", text="Cable laying work misc", unit="sqm", rate=D("999"))]
    calls = []

    def adjudicate(cand, ranked):
        calls.append(cand.key)
        return ranked[0][0].key, 0.95, "looks similar"

    assert LineMatcher(adjudicate=adjudicate).match(po, c) == []      # rate and unit both disagree → rejected


def test_model_null_stand_ins_are_none():
    from backend_ocr.app.recon.extract.base import party, text
    assert text("null") is None and text(" None ") is None and text("N/A") is None and text("") is None
    assert text("AMP/26-27/000|null") == "AMP/26-27/000"
    assert text("60% Advance") == "60% Advance"
    p = party({"name": "null", "gstin": "null"})
    assert p.name == "" and p.gstin is None


async def test_invoice_extractor_drops_literal_nulls():
    from backend_ocr.app.recon.extract.base import ExtractContext
    from backend_ocr.app.recon.extract.invoice import InvoiceExtractor
    from backend_ocr.app.recon.llm import FakeLLM
    from backend_ocr.app.recon.pages import PageInfo
    from backend_ocr.app.recon.segment import Segment
    from backend_ocr.app.recon.types import DocClass, SegmentKind
    llm = FakeLLM({
        "invoice_header": {"invoice_no": "AMP/26-27/070", "payment_terms": "null", "po_ref": "PPO00024046-1",
                           "taxable": "100", "total": "118", "igst": "18", "corrections": [{"printed": "null", "handwritten": "null"}]},
        "invoice_annexure": {"invoice_no": "AMP/26-27/000|null", "lines": [{"sno": 1, "description": "Pipe", "unit": "null",
                                                                             "qty": "1", "rate": "100", "amount": "100"}]},
    })
    pages = {1: PageInfo(index=1, text="x " * 100 + "1", has_text_layer=True), 2: PageInfo(index=2, text="y " * 100 + "2", has_text_layer=True)}
    seg = Segment(kind=SegmentKind.TAX_INVOICE, pages=[1, 2], classes=[DocClass.TAX_INVOICE, DocClass.INVOICE_ANNEXURE])
    inv = await InvoiceExtractor().extract(seg, ExtractContext("t", "s", llm=llm, pages=pages))
    assert inv.payment_terms is None and inv.corrections == []
    assert inv.annexure_lines[0].unit is None
    assert inv.warnings == [] or all("null" not in w for w in inv.warnings)


def test_clean_hints_from_the_model():
    from backend_ocr.app.recon.clean import fit, gstin
    assert gstin("29AKRPP8699K1ZO|null") == "29AKRPP8699K1ZO"
    assert gstin("29AABC81043121|null") is None        # misread on a scan: check digit fails
    assert gstin("null|null") is None and gstin("29AABCB1043Q1Z") is None
    assert fit("1859", 16) == "1859" and fit("x" * 30, 16) == "x" * 16 and fit("null", 16) is None


def test_po_invoice_fit_on_content():
    from backend_ocr.app.recon.link import po_invoice_fit
    from backend_ocr.app.recon.types import ExtractedPO, InvoiceLine
    from datetime import date
    po = ExtractedPO(po_number="PPO00024378-1", po_date=date(2026, 3, 24), store_sn="1859", total=D("100000"),
                     lines=[_po(1, "Gypsum false ceiling", 95, unit="SF", qty=400), _po(2, "MCCB 63A TPN", 4560, qty=3),
                            _po(3, "LED panel 2x2", 1250, qty=20)])
    inv = [InvoiceLine(key="a", description="Gypsum ceiling", unit="SF", rate=Sourced(value=D("95"))),
           InvoiceLine(key="b", description="MCCB 63 A TPN", unit="NO", rate=Sourced(value=D("4560"))),
           InvoiceLine(key="c", description="LED Panel 2 x 2", unit="NO", rate=Sourced(value=D("1250")))]
    sc, sig = po_invoice_fit(po, inv, inv_store="1859", inv_date=date(2026, 9, 10), inv_amount=D("60000"),
                             inv_po_ref="P00004731 dt. 16.Sep.26")
    assert sc >= 0.85 and sig["lines"] == 1.0
    # Hard stops: another PPO number named, another store, or dated before the PO.
    assert po_invoice_fit(po, inv, inv_po_ref="PPO00099999")[0] == 0
    assert po_invoice_fit(po, inv, inv_store="9621")[0] == 0
    assert po_invoice_fit(po, inv, inv_date=date(2026, 1, 1))[0] == 0
    # Lines at other rates don't make it a match.
    other = [InvoiceLine(key=l.key, description=l.description, unit=l.unit, rate=Sourced(value=D("1"))) for l in inv]
    assert po_invoice_fit(po, other, inv_store="1859")[0] < 0.85


# ── a scanned file must not be able to take the server down (2026-11-13) ─────────

SCAN = "Civil po by Inner Sapce/1_New Town Yelanka Bangalore 1859 S.pdf"


@pytest.mark.skipif(not __import__("os").path.exists(SCAN), reason="sample scan not in this checkout")
async def test_scanned_pages_go_to_the_model_as_small_jpegs_four_at_a_time():
    import fitz
    from backend_ocr.app.recon.extract.base import ExtractContext
    from backend_ocr.app.recon.llm import FakeLLM
    from backend_ocr.app.recon.pages import PageReader
    sizes: list[list[int]] = []

    def answer(text, images):
        assert all(b[:2] == b"\xff\xd8" for b in images)               # JPEG, not PNG
        sizes.append([len(b) for b in images])
        return {"po_number": "PPO00024378-1", "lines": [{"sno": len(sizes)}]}
    reader = PageReader()
    doc = fitz.open(SCAN)
    ctx = ExtractContext("t", "s", llm=FakeLLM({"po": answer}), reader=reader, doc=doc)
    r = await ctx.vision("po", "prompt", list(range(1, len(doc) + 1)))
    assert [len(s) for s in sizes] == [4, 4, 3]                        # 11 pages, never more than 4 per request
    assert max(sum(s) for s in sizes) < 3_000_000                      # each request well under 3 MB
    assert r["po_number"] == "PPO00024378-1" and len(r["lines"]) == 3   # lists merged across batches


def test_reading_stops_cleanly_when_memory_is_short(monkeypatch):
    from backend_ocr.app.recon import memory
    monkeypatch.setattr(memory, "available_mb", lambda: 120)
    with pytest.raises(memory.MemoryPressure):
        memory.ensure_headroom(250)
    monkeypatch.setattr(memory, "available_mb", lambda: None)        # no /proc (macOS): never blocks
    memory.ensure_headroom(250)


async def test_an_audit_sheet_titled_po_is_not_taken_for_a_po():
    from backend_ocr.app.recon.classify import PageClassifier
    from backend_ocr.app.recon.llm import FakeLLM
    from backend_ocr.app.recon.pages import PageInfo
    from backend_ocr.app.recon.types import DocClass
    llm = FakeLLM({"classify_page": [
        {"doc_class": "PURCHASE_ORDER", "confidence": 0.8, "section_title": "FURNITURE PO", "po_number": None,
         "has_audit_columns": True, "vendor_gstin": "29AABCB1043Q1ZI|null"},
        {"doc_class": "PURCHASE_ORDER", "confidence": 0.8, "section_title": "AC HS PO", "po_number": None,
         "has_audit_columns": False},
        {"doc_class": "PURCHASE_ORDER", "confidence": 0.9, "po_number": "PPO00024378-1", "has_audit_columns": False},
    ]})
    pages = [PageInfo(index=i, text="", has_text_layer=False) for i in (1, 2, 3)]
    labels = await PageClassifier(llm).classify(pages, images={1: b"x", 2: b"x", 3: b"x"})
    assert [l.doc_class for l in labels] == [DocClass.PV_SHEET_SCANNED, DocClass.PV_SHEET_SCANNED, DocClass.PURCHASE_ORDER]
    assert labels[0].vendor_gstin == "29AABCB1043Q1ZI"               # "|null" echo cleaned


# ── the Yelanka report (2026-11-14): one auditor's file, read as a whole ───────────

def test_store_numbers_and_document_numbers():
    from backend_ocr.app.recon.clean import doc_number_ok, store_no
    assert store_no("Shop No 1859") == store_no("1859") == store_no("SN 01859") == "1859"
    assert store_no(None) is None and store_no("abc") is None
    assert not doc_number_ok("1859", "Shop No 1859")          # the store number is not a PO / invoice number
    assert not doc_number_ok("1859-1")                        # too short to be one
    assert doc_number_ok("PPO00024378-1", "1859") and doc_number_ok("IS-HO-26-27-120", "1859")
    assert doc_number_ok("P00004731") and not doc_number_ok(None)


async def test_sheet_pages_beside_their_sheet_are_not_pos_whatever_number_the_model_claims():
    from backend_ocr.app.recon.classify import PageClassifier
    from backend_ocr.app.recon.llm import FakeLLM
    from backend_ocr.app.recon.pages import PageInfo
    from backend_ocr.app.recon.segment import Segmenter
    from backend_ocr.app.recon.types import DocClass, SegmentKind
    interior = "FAMILY - INTERIOR & ELECTRICAL - RACKS PO"
    llm = FakeLLM({"classify_page": [
        {"doc_class": "PV_NARRATIVE", "confidence": 0.9},
        # The model "reads" the PO number the sheet checks off pages that print none.
        {"doc_class": "PURCHASE_ORDER", "section_title": interior, "po_number": "PPO00024378", "vendor_name": "Bata"},
        {"doc_class": "PV_SHEET_SCANNED", "section_title": interior, "vendor_name": "VANDEEPRAKASH"},
        {"doc_class": "PURCHASE_ORDER", "section_title": interior, "po_number": "BATA-70001", "vendor_name": "Bata"},
        {"doc_class": "INVOICE_ANNEXURE", "section_title": "AC LS PO", "vendor_name": "ATSPIRE"},
    ]})
    pages = [PageInfo(index=i, text="", has_text_layer=False) for i in range(1, 6)]
    labels = await PageClassifier(llm).classify(pages, images={i: b"x" for i in range(1, 6)})
    assert [l.doc_class for l in labels[1:]] == [DocClass.PV_SHEET_SCANNED] * 4
    segs = Segmenter().segment(labels)
    assert [(s.kind, s.pages) for s in segs] == [(SegmentKind.PV_SECTION, [2, 3, 4]), (SegmentKind.PV_SECTION, [5])]


async def test_a_real_po_beside_a_report_stays_a_po():
    from backend_ocr.app.recon.classify import PageClassifier
    from backend_ocr.app.recon.llm import FakeLLM
    from backend_ocr.app.recon.pages import PageInfo
    from backend_ocr.app.recon.types import DocClass
    llm = FakeLLM({"classify_page": [
        {"doc_class": "PV_SHEET_SCANNED", "section_title": "FURNITURE PO"},
        {"doc_class": "PURCHASE_ORDER", "po_number": "PPO00024378-1", "section_title": None},
    ]})
    pages = [PageInfo(index=i, text="", has_text_layer=False) for i in (1, 2)]
    labels = await PageClassifier(llm).classify(pages, images={1: b"x", 2: b"x"})
    assert labels[1].doc_class == DocClass.PURCHASE_ORDER


def test_a_sheet_naming_the_vendor_is_not_foreign_because_it_shows_the_buyers_gstin():
    from backend_ocr.app.recon.link import is_foreign
    from backend_ocr.app.recon.types import Party
    sup, gst = "Inner Space -Head Office 2026-27", {"29AKRPP8699K1ZO"}
    assert not is_foreign(Party(name="INNERSPACE", gstin="29AABCB1043Q1ZI"), sup, gst)   # Bata's GSTIN, misplaced
    assert not is_foreign(Party(name="", gstin="29AKRPP8699K1ZO"), sup, gst)
    assert is_foreign(Party(name="VOLTAS LIMITED", gstin="29AAACV2809D1ZI"), sup, gst)
    assert is_foreign(Party(name="VDM Enterprises"), sup, gst)


def test_store_signal_ignores_the_label_printed_with_the_number():
    from backend_ocr.app.recon.link import CaseView, score
    from backend_ocr.app.recon.types import ExtractedPO
    v = CaseView(target_type="case", target_id="c", label="x", po=ExtractedPO(po_number="PPO1", store_sn="1859"))
    assert score(v, store_sn="Shop No 1859").signals["store"] == 1.0
    assert score(v, store_sn="Shop No 8255").signals["store"] == 0.0


async def test_a_sheet_is_read_twice_by_two_models_and_disagreements_are_flagged(monkeypatch):
    from backend_ocr.app.recon.extract.base import ExtractContext
    from backend_ocr.app.recon.extract.pv_sheet import ScannedSheetExtractor
    from backend_ocr.app.recon.llm import FakeLLM
    from backend_ocr.app.recon.segment import Segment
    from backend_ocr.app.recon.types import SegmentKind
    head = {"section_title": "FAMILY- INTERIOR + ELECTRICAL + RACKS PO", "store_sn": "1859",
            "vendor": {"name": "INNERSPACE", "gstin": "29AKRPP8699K1ZO"}}
    a = {**head, "rows": [
        {"item": "Gypsum False Ceiling India Gypsum", "po_qty": "1,531", "rate": "80", "rate_after_discount": "76",
         "vendor_qty": "1838", "audit_qty": "1665"},
        {"item": "Wall Mirror", "po_qty": "48", "vendor_qty": "48", "audit_qty": "40", "remark": "Without frame"},
        {"item": "Orient tiles Kajaria Timber Oak", "po_qty": "1,531", "vendor_qty": "1820", "audit_qty": "1693"}]}
    b = {**head, "rows": [                                   # the check model misses a row and reads 1683
        {"item": "Gypsum False Ceiling", "vendor_qty": "1838", "audit_qty": "1665"},
        {"item": "Orient tiles Kajaria Timber Oak", "vendor_qty": "1820", "audit_qty": "1683"}]}
    llm = FakeLLM({"sheet_rows": a, "sheet_rows_check": b})
    ctx = ExtractContext(tenant_id="t", supplier_id="s", llm=llm)
    monkeypatch.setattr(ExtractContext, "png", lambda self, i, dpi=None: b"img")
    sec = await ScannedSheetExtractor().extract(Segment(kind=SegmentKind.PV_SECTION, pages=[4]), ctx)
    got = [(r.item.split()[0], r.audit_qty.value if r.audit_qty else None, r.needs_review) for r in sec.rows]
    assert got == [("Gypsum", D("1665"), False), ("Wall", D("40"), True), ("Orient", D("1693"), True)]
    assert sec.rows[2].audit_qty.alternatives == ["1693", "1683"]
    assert sec.rows[0].rate_after_discount == D("76") and sec.rows[1].remark == "Without frame"
    assert sec.vendor.gstin == "29AKRPP8699K1ZO" and sec.store_sn == "1859"


def test_reasoning_models_get_their_own_sampling_settings():
    from backend_ocr.app.recon.llm import _sampling
    assert _sampling("gpt-4o", 100) == {"temperature": 0, "max_tokens": 100}
    s = _sampling("gpt-5.4", 100)
    assert s["max_completion_tokens"] == 100 and "temperature" not in s
