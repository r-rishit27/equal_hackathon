"""Golden tests: the 4 Bata sample sets must reconcile exactly as the hand
analysis says (docs/bata-recon/07_TEST_PLAN.md §3).
"""
from __future__ import annotations

from decimal import Decimal as D

import pytest

from backend_ocr.app.recon.assemble import match_case, reconcile
from backend_ocr.app.recon.types import CaseStatus, LineStatus as S, MatchMethod, Severity, from_json, to_json, ReconResult

from .golden import load


def _by_desc(res, prefix):
    hits = [l for l in res.lines if l.description.lower().startswith(prefix.lower())]
    assert hits, f"no line starting {prefix!r}"
    return hits[0]


def _header(res, code):
    return next(h for h in res.header if h.code == code)


def _with(res, status):
    return [l for l in res.lines if status in l.statuses]


# ── Bosch: PO ↔ invoice ↔ POD, one line ──────────────────────────────────────────

def test_bosch():
    res = reconcile(load("bosch"))
    s = res.summary
    assert s.expected_total == D("572400.00") == s.billed_total
    assert s.money_at_risk == 0 and s.under_billed == 0
    assert [l.statuses for l in res.lines] == [[S.MATCHED]]
    assert res.lines[0].invoice_text.endswith("(W/O CONN. KIT)")
    assert _header(res, "tax_regime").passed
    assert _header(res, "pod_matches").passed
    assert _header(res, "delivery_timeliness").passed
    pt = _header(res, "payment_terms")
    assert not pt.passed and pt.severity == Severity.REVIEW
    assert s.counts == {"BLOCKER": 0, "REVIEW": 1, "INFO": 0}


# ── Anjile: 39-line PO, annexure invoice, typed JPC audit ─────────────────────────

def test_anjile_totals():
    res = reconcile(load("anjile"))
    s = res.summary
    assert s.expected_total == D("636740.50")
    assert s.billed_total == D("634890.50")
    assert s.under_billed == D("1850.00")
    assert s.money_at_risk == 0
    assert s.counts["BLOCKER"] == 0
    assert _header(res, "header_vs_annexure").passed
    assert _header(res, "tax_regime").passed


def test_anjile_every_invoice_line_matched():
    inv_m, _ = match_case(load("anjile"))
    assert len([m for m in inv_m if m.po_key]) == 36
    assert not [l for l in reconcile(load("anjile")).lines if l.kind == "not_in_po"]


def test_anjile_truncated_po_line_matched_by_rate_and_through_invoice_wording():
    res = reconcile(load("anjile"))
    l = next(l for l in res.lines if l.po_key == "po:34")      # PO text is only "Supply & Installation"
    assert l.invoice_text == "Supply & Installation of 15 MM Air Punch Valve"
    assert l.evidence_text == "Supply & Installation of 15 MM Dia Air Puch Valve"
    assert l.statuses == [S.MATCHED]


def test_anjile_mcp_hooter_under_billed():
    l = _by_desc(reconcile(load("anjile")), "Supply and Installation MCP Hooter")
    assert l.invoice_key is None and l.verified_qty == 1 and l.delta == D("-1850.00")
    assert S.UNDER_BILLED in l.statuses and l.severity == Severity.REVIEW


def test_anjile_rule_categories():
    res = reconcile(load("anjile"))
    capped = {l.description.split()[0] for l in _with(res, S.OVER_EXECUTED_CAPPED)}
    assert capped == {"Acousting", "Butterfly", "Drain"}       # insulation, lining, valve, drain
    assert len(_with(res, S.OVER_EXECUTED_CAPPED)) == 4
    assert len(_with(res, S.NOT_VERIFIABLE)) == 3              # scaffolding, panel prog., FAS integration
    assert {l.po_key for l in _with(res, S.NOT_DONE)} == {"po:27", "po:28"}   # fault isolator, input module
    assert all(l.severity == Severity.INFO for l in _with(res, S.NOT_DONE))
    assert len(_with(res, S.ADDITIONAL_ON_SITE)) == 5
    assert len(_with(res, S.UNDER_USED)) == 13


# ── Inner Space Civil: scanned invoice detail, handwritten Matolia audit ──────────

def test_civil_exact_when_blank_audit_means_not_done():
    res = reconcile(load("innerspace_civil", blank_audit_means="NOT_DONE"))
    s = res.summary
    assert s.expected_goods == D("949608.55")
    assert s.expected_total == D("956733.55") == s.billed_total
    assert s.money_at_risk == 0 and s.under_billed == 0
    assert s.counts["BLOCKER"] == 0


def test_civil_default_asks_about_blank_mccb():
    res = reconcile(load("innerspace_civil"))
    l = _by_desc(res, "MAIN INCOMER MCCB")
    assert S.UNDER_BILLED in l.statuses and l.severity == Severity.REVIEW
    assert res.summary.under_billed == D("13680.00")


def test_civil_capping_and_conflicts():
    res = reconcile(load("innerspace_civil"))
    capped = {l.description for l in _with(res, S.OVER_EXECUTED_CAPPED)}
    for item in ("Gypsum False Ceiling", "Orient tiles", "Painting Plastic Emulsion", "Add point PVC"):
        assert any(c.startswith(item) for c in capped), item
    panel = _by_desc(res, "INTEGRATED MAIN LT PANEL")
    assert S.DESCRIPTION_CONFLICT in panel.statuses
    assert any("type-d" in c and "type-e" in c for c in panel.conflicts)
    alu = _by_desc(res, "Aluminium Armored Cable")
    assert alu.billed_qty == 2 and S.UOM_CONFLICT in alu.statuses and alu.severity == Severity.REVIEW


def test_civil_not_billable_items():
    res = reconcile(load("innerspace_civil"))
    pvc = _by_desc(res, "PVC Conduit 25 mm")                  # "Not allowed separately"
    assert pvc.expected_qty == 0 and S.NOT_DONE in pvc.statuses
    malba = _by_desc(res, "Malba Disposal")                    # not in scope → PO qty
    assert malba.expected_qty == 3 and S.NOT_VERIFIABLE in malba.statuses
    for d in ("Dismenlitng of Light", "Dismentling of false ceiling", "Dismentling of store furniture"):
        assert _by_desc(res, d).expected_qty == 0
    not_in_po = {l.description.split()[0] for l in res.lines if l.kind == "not_in_po"}
    assert not_in_po == {"8", "Floor"}
    assert all(l.severity == Severity.INFO for l in res.lines if l.kind == "not_in_po")


def test_civil_report_rows_from_another_po_are_info():
    res = reconcile(load("innerspace_civil"))
    other = [l for l in res.lines if l.kind == "report_only"]
    assert len(other) == 7 and all(l.severity == Severity.INFO for l in other)


def test_civil_low_confidence_reading_that_agrees_is_info():
    l = _by_desc(reconcile(load("innerspace_civil")), "EntranceFa")
    assert l.needs_review_cell and S.UNCHECKED_READING in l.statuses and l.severity == Severity.INFO


# ── Inner Space Red Furniture ─────────────────────────────────────────────────────

def test_red_goods_and_headers():
    res = reconcile(load("innerspace_red"))
    s = res.summary
    assert s.expected_goods == D("545985.90")
    arith = _header(res, "invoice_arithmetic")
    assert not arith.passed and "5,45,973.90" in arith.detail
    assert not _header(res, "handwritten_corrections").passed
    assert _header(res, "header_vs_annexure").passed


def test_red_transport_billed_but_audit_zero_is_blocker():
    res = reconcile(load("innerspace_red"))
    t = _by_desc(res, "Transportatio")
    assert t.verified_qty == 0 and t.billed_qty == 1
    assert S.NOT_DONE in t.statuses and t.severity == Severity.BLOCKER
    assert res.summary.money_at_risk == D("31350.00")


def test_red_packing_fixed_vs_percent():
    fixed = _by_desc(reconcile(load("innerspace_red")), "Furniture Packing")
    assert fixed.expected_amt == D("28078.00") and fixed.billed_amt == D("27299.30")
    assert S.PCT_CHARGE_MISMATCH in fixed.statuses and fixed.severity == Severity.REVIEW
    pct = _by_desc(reconcile(load("innerspace_red", charge_rules={"packing": "PERCENT_OF_GOODS"})), "Furniture Packing")
    assert pct.expected_amt == D("27299.30") and pct.statuses == [S.MATCHED]


def test_red_shelf_size_conflict_and_remark():
    l = _by_desc(reconcile(load("innerspace_red")), "Metal Shelf CRC sheet with PC led")
    assert l.billed_qty == 60 and l.expected_qty == 60
    assert S.DESCRIPTION_CONFLICT in l.statuses and S.AUDITOR_REMARK in l.statuses
    assert "removed" in l.remark
    assert S.RATE_LOWER not in l.statuses                      # 2,105.00 vs 2,105.20 is within tolerance


def test_red_truncated_dimension_is_not_a_conflict():
    l = _by_desc(reconcile(load("innerspace_red")), "Wall low Base 1200")
    assert l.statuses == [S.MATCHED]


def test_red_zero_qty_extras_on_invoice_are_info():
    res = reconcile(load("innerspace_red"))
    extras = [l for l in res.lines if l.kind == "not_in_po"]
    assert len(extras) == 4 and all(l.severity == Severity.INFO for l in extras)


# ── Cross-cutting ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("name", ["bosch", "anjile", "innerspace_civil", "innerspace_red"])
def test_status_and_json_roundtrip(name):
    res = reconcile(load(name))
    assert res.summary.status == CaseStatus.NEEDS_REVIEW
    again = from_json(ReconResult, to_json(res))
    assert to_json(again) == to_json(res)


def test_overrides_win_and_aliases_apply():
    inp = load("innerspace_red")
    inv_m, _ = match_case(inp, overrides={"inv:16": "po:16"})       # user: "10 feet" is the 8 ft channel
    m = next(m for m in inv_m if m.other_key == "inv:16")
    assert m.po_key == "po:16" and m.method == MatchMethod.HUMAN
    inv_m, _ = match_case(inp, overrides={"inv:9": None})            # user: not in this PO
    assert next(m for m in inv_m if m.other_key == "inv:9").po_key is None


def test_cumulative_billing_on_same_po():
    inp = load("bosch")
    inp.prior_billed_qty = {"po:1": D("2")}
    inp.prior_billed_value = D("190800")
    res = reconcile(inp)
    assert S.OVER_PO in res.lines[0].statuses and res.lines[0].severity == Severity.BLOCKER
    assert not _header(res, "within_po_value").passed
