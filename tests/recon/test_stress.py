"""Adversarial inputs to the parts that decide money.

Not a re-run of the happy path. Every case here is something a real document
can contain and a careless implementation gets wrong: a zero where a divisor
is expected, a quantity with more precision than money has, a total that
arrives as a string, a line that is its own subtotal.

The rule each test defends: **the agent may decline, but it may not be
confidently wrong, and it may not crash a reconciliation.**
"""
from __future__ import annotations

from decimal import Decimal as D

import pytest

from backend_ocr.app.recon import keys, rollup
from backend_ocr.app.recon.engine import _pairing_confidence, same_consignment
from backend_ocr.app.recon.rules import audit_row_arithmetic, audit_row_value
from backend_ocr.app.recon import profiles
from backend_ocr.app.recon.types import EvidenceRow, LineResult, MatchMethod, ReconInput, Sourced


def line(**kw):
    kw.setdefault("ord", 1)
    kw.setdefault("kind", "po")
    kw.setdefault("description", "Item")
    return LineResult(**kw)


# ── division, zero and the empty case ──────────────────────────────────────

def test_a_case_of_nothing_does_not_divide_by_zero():
    """An invoice with no billed lines must not take 0/0 for an answer."""
    conf, weak = _pairing_confidence([])
    assert conf == D("1") and weak == []


def test_lines_that_sum_to_zero_do_not_divide_by_zero():
    """A charge and its credit cancelling out is a real invoice, not a crash."""
    conf, _ = _pairing_confidence([
        line(invoice_key="rl:1", billed_amt=D("500"), match_method=MatchMethod.EXACT, po_key="p"),
        line(invoice_key="rl:2", billed_amt=D("-500"), match_method=MatchMethod.EXACT, po_key="p"),
    ])
    # abs() on the weights, so equal and opposite lines still weigh something.
    assert conf == D("1")


def test_a_report_row_with_a_zero_rate_is_priced_at_zero_not_skipped():
    ev = EvidenceRow(key="e", item="Free issue", rate=D("0"), audit_qty=Sourced(value=D("5")))
    # A zero rate is a fact on the paper: the line is worth nothing, which is
    # a different statement from "we cannot price this row".
    assert audit_row_value(ev) == D("0")


def test_a_report_row_with_no_quantity_is_unpriceable_not_zero():
    ev = EvidenceRow(key="e", item="x", rate=D("10"))
    assert audit_row_value(ev) is None


# ── precision, scale and rounding ──────────────────────────────────────────

def test_fractional_quantities_do_not_drift():
    """408.5 SF at 190.25 is exact in Decimal and wrong in float."""
    ev = EvidenceRow(key="e", item="ACP", rate=D("190.25"), audit_qty=Sourced(value=D("408.5")))
    assert audit_row_value(ev) == D("77717.13")       # 408.5 x 190.25 = 77717.125


def test_a_very_large_invoice_still_adds_up():
    """Crore-scale CAPEX must not lose paise to a float somewhere."""
    big = [line(invoice_key=f"rl:{i}", po_key="p", billed_amt=D("9999999.99"),
                match_method=MatchMethod.EXACT) for i in range(50)]
    conf, _ = _pairing_confidence(big)
    assert conf == D("1")


def test_rollup_tolerates_a_rupee_and_not_a_lakh():
    assert rollup.find([D("100"), D("40"), D("30"), D("30.60")], invoice_total=D("100.60"))
    assert not rollup.find([D("100"), D("40"), D("30"), D("30000")], invoice_total=D("30070"))


# ── text, unicode and the things scanners emit ─────────────────────────────

@pytest.mark.parametrize("junk", ["", "   ", "—", "N/A", "​", "\t\n"])
def test_empty_and_junk_references_never_match(junk):
    """A blank on both sides is not agreement."""
    assert same_consignment(junk, junk, value_matches=True) is None


def test_a_reference_of_different_length_is_not_a_misreading():
    assert same_consignment("26GJ/KMW/SI15224", "26GJ/KMW/SI152240", value_matches=True) is None


def test_unicode_in_a_description_does_not_break_the_key():
    k = keys.build(leg="billing", description="Pipe ⌀25 mm — 90° bend, ±2 mm")
    assert k.key and len(k.key) <= 120


def test_a_description_of_only_punctuation_falls_to_position():
    k = keys.build(leg="billing", description="---", ordinal=4)
    assert k.basis in ("NORM_DESC", "ORDINAL")
    # Whatever it chose, it must not claim to be trustworthy on nothing.
    assert k.trusted is (k.basis != "ORDINAL")


# ── the identity ladder under duplicates ───────────────────────────────────

def test_many_identical_rows_all_get_distinct_keys():
    same = keys.build(leg="billing", description="Core cutting", unit="EA", rate=D("850"))
    out = keys.disambiguate([same] * 200)
    assert len({k.key for k in out}) == 200
    assert sum(1 for k in out if k.trusted) == 1, "only the first occurrence is trustworthy"


def test_a_disambiguated_key_never_claims_a_basis_it_no_longer_has():
    same = keys.build(leg="receipt", asset_code="CWIP1", description="x")
    out = keys.disambiguate([same, same])
    assert all((k.basis == "ORDINAL") == (not k.trusted) for k in out)


# ── the site report's own arithmetic ───────────────────────────────────────

def test_a_report_total_of_zero_against_a_priced_row_is_a_finding():
    why = audit_row_arithmetic(EvidenceRow(key="e", item="x", po_qty=D("3"),
                                           rate_after_discount=D("100"), amount=D("0")))
    assert why and "not 3" in why


def test_a_report_with_no_quantity_cannot_be_checked():
    assert audit_row_arithmetic(EvidenceRow(key="e", item="x", rate=D("10"), amount=D("30"))) is None


# ── rollup detection against hostile shapes ────────────────────────────────

def test_an_invoice_of_one_line_is_never_its_own_subtotal():
    assert not rollup.find([D("100")], invoice_total=D("100"))


def test_all_zero_lines_do_not_look_like_a_rollup():
    """Zeroes satisfy "the heads equal the rest" trivially; they must not."""
    assert not rollup.find([D("0"), D("0"), D("0"), D("0")], invoice_total=D("0"))


def test_a_none_amount_in_the_middle_does_not_break_detection():
    a = [D("100"), None, D("50"), D("30"), D("20")]
    r = rollup.find(a, invoice_total=D("100"))
    assert r.headings == (0,)


def test_a_negative_heading_is_not_a_heading():
    assert not rollup.find([D("-100"), D("-60"), D("-40")], invoice_total=D("-100"))


# ── the cost of asking ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_case_with_nothing_in_doubt_is_matched_once(monkeypatch):
    """Matching is O(n^2) scoring plus O(n^3) assignment — 0.2s at 100 lines,
    28s at 1000. The collector pass must not silently double that for every
    case, so its result is reused when no adjudication happens.
    """
    from backend_ocr.app.recon import pipeline as P

    calls = []
    real = P.reconcile

    def counting(inp, **kw):
        calls.append(kw.get("adjudicate"))
        return real(inp, **kw)

    monkeypatch.setattr(P, "reconcile", counting)
    pipe = P.ReconPipeline.__new__(P.ReconPipeline)
    pipe.adjudicate = None
    inp = ReconInput(po=None, invoice=None, config=profiles.DEFAULT)
    await pipe._adjudicated(inp, {}, {})
    assert len(calls) == 1, "nothing was in doubt, so one pass is all it should cost"


@pytest.mark.asyncio
async def test_the_deterministic_match_survives_an_adjudication_failure(monkeypatch):
    """If asking blows up, we keep the match we already had rather than
    starting again or failing the case."""
    from backend_ocr.app.recon import decisions as D
    from backend_ocr.app.recon import pipeline as P

    async def boom(*_a, **_k):
        raise RuntimeError("endpoint on fire")

    monkeypatch.setattr(D, "ENABLED", True)
    monkeypatch.setattr(D, "judge_pairs", boom)
    pipe = P.ReconPipeline.__new__(P.ReconPipeline)
    pipe.adjudicate = None
    inp = ReconInput(po=None, invoice=None, config=profiles.DEFAULT)
    res = await pipe._adjudicated(inp, {}, {})
    assert res is not None and res.summary is not None
