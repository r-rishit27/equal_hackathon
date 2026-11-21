"""Bata's confirmed business rules (QUESTIONS_FOR_BATA.md, call of 16 Nov 2026).

Covers acceptance tests 13, 15 and 16 of RECON_IMPLEMENTATION_PLAN.md §12:
the ₹100 receipt variance, the single-PO prohibition, and the fixed PO rate.
"""
from decimal import Decimal as D

import pytest

from backend_ocr.app.recon import profiles
from backend_ocr.app.recon.assemble import reconcile
from backend_ocr.app.recon.engine import HeaderChecks, LineChecks, _po_refs
from backend_ocr.app.recon.types import (
    CaseStatus, ExtractedInvoice, ExtractedPO, InvoiceLine, LineStatus, MatchPair, POLine, ReconInput,
    RuleConfig, Sourced, sval,
)


def _inp(**kw):
    cfg = kw.pop("config", None) or RuleConfig()
    inv = ExtractedInvoice(invoice_no="UR/26-27/0417", **{k: kw.pop(k) for k in list(kw)
                                                          if k in ("po_ref", "taxable")})
    po = kw.pop("po", None)
    return ReconInput(invoice=inv, po=po, config=cfg, **kw)


def _checks(inp) -> dict[str, object]:
    return {c.code: c for c in HeaderChecks(inp).run()}


# ── test 13: the ₹100 threshold ───────────────────────────────────────────────

def test_variance_below_threshold_passes_silently():
    c = _checks(_inp(taxable=D("100099"), receipt_total=D("100000")))["receipt_variance"]
    assert c.passed, "₹99 over the receipt is booked without an exception"


def test_variance_at_exactly_the_threshold_passes():
    c = _checks(_inp(taxable=D("100100"), receipt_total=D("100000")))["receipt_variance"]
    assert c.passed, "₹100 is the limit, not the first failure"


def test_variance_above_threshold_routes_to_costing():
    c = _checks(_inp(taxable=D("100101"), receipt_total=D("100000")))["receipt_variance"]
    assert not c.passed
    assert c.evidence["routes_to"] == "costing_team"
    assert "costing team approval required" in c.detail


def test_threshold_is_absolute_not_a_percentage():
    """On a large invoice ₹100 is a far tighter rule than any percentage band."""
    big = _checks(_inp(taxable=D("750000"), receipt_total=D("749800")))["receipt_variance"]
    assert not big.passed, "₹200 on ₹7.5 lakh is 0.027% and must still fail"


def test_invoice_below_the_receipt_also_raises_an_exception():
    """Confirmed by Bata, 19 Nov 2026: an exception is needed in that case too.

    Under-billing is not money at risk, but it means more was received than is
    being charged for — a GRN or vendor-billing problem a person must see.
    """
    c = _checks(_inp(taxable=D("90000"), receipt_total=D("100000")))["receipt_variance"]
    assert not c.passed
    assert c.evidence["direction"] == "under"
    assert "below the receipt" in c.detail


def test_under_billing_within_the_threshold_still_passes():
    c = _checks(_inp(taxable=D("99950"), receipt_total=D("100000")))["receipt_variance"]
    assert c.passed, "₹50 under is inside the ₹100 band, in either direction"


def test_over_and_under_are_distinguished_for_routing():
    over = _checks(_inp(taxable=D("100500"), receipt_total=D("100000")))["receipt_variance"]
    under = _checks(_inp(taxable=D("99500"), receipt_total=D("100000")))["receipt_variance"]
    assert over.evidence["direction"] == "over"
    assert under.evidence["direction"] == "under"
    assert "costing team" in over.detail and "costing team" not in under.detail


def test_check_abstains_when_there_is_no_receipt_leg():
    """No GRN yet (it arrives as an MSD extract, plan §7) ⇒ no verdict at all.

    An abstention must not look like a pass.
    """
    assert "receipt_variance" not in _checks(_inp(taxable=D("100000")))


def test_threshold_is_configurable():
    cfg = RuleConfig(invoice_vs_receipt_tol=D("500"))
    c = _checks(_inp(taxable=D("100400"), receipt_total=D("100000"), config=cfg))["receipt_variance"]
    assert c.passed, "a tenant with a different band gets it from config, not a code change"


# ── test 15: one PO per invoice ───────────────────────────────────────────────

@pytest.mark.parametrize("ref,expected", [
    ("PPO00024046", ["24046"]),
    ("PPO00024046 / PPO00024102", ["24046", "24102"]),
    ("4500087255 & 4500087301", ["4500087255", "4500087301"]),
    ("PPO00024046, PPO00024046", ["24046"]),          # the same PO twice is one PO
    ("", []),
    (None, []),
])
def test_po_refs_extraction(ref, expected):
    assert _po_refs(ref) == expected


def test_one_po_per_invoice_passes_quietly():
    assert "single_po" not in _checks(_inp(po_ref="PPO00024046", taxable=D("1000")))


def test_invoice_citing_two_pos_fails_validation():
    c = _checks(_inp(po_ref="PPO00024046 / PPO00024102", taxable=D("1000")))["single_po"]
    assert not c.passed
    assert c.severity.name in ("BLOCKER", "RED", "R", "FAIL") or not c.passed
    assert c.evidence["po_refs"] == ["24046", "24102"]
    assert "cannot be processed against two POs" in c.detail


def test_single_po_rule_can_be_turned_off():
    cfg = RuleConfig(single_po_per_invoice=False)
    assert "single_po" not in _checks(_inp(po_ref="PPO1111 / PPO2222", taxable=D("1000"), config=cfg))


# ── test 16 / R2: the PO rate is fixed ────────────────────────────────────────

def _rate_statuses(billed: str, po_rate: str, **cfg) -> set[str]:
    """Run the line engine for one PO line billed at `billed` against `po_rate`."""
    po_line = POLine(sno=1, description="Insulated refrigerant piping 25 mm", unit="RFT",
                     qty=D("100"), unit_price=D(po_rate), amount=D(po_rate) * D("100"))
    inv_line = InvoiceLine(key="rl:1", sno=1, description="Insulated refrigerant piping 25 mm",
                           unit="RFT", qty=Sourced(value=D("100")), rate=Sourced(value=D(billed)),
                           amount=Sourced(value=D(billed) * D("100")))
    po = ExtractedPO(po_number="PPO00024046", lines=[po_line], total=D("1000000"))
    inv = ExtractedInvoice(invoice_no="I-1", po_ref="PPO00024046", annexure_lines=[inv_line],
                           taxable=D(billed) * D("100"))
    inp = ReconInput(po=po, invoice=inv, config=RuleConfig(**cfg),
                     invoice_matches=[MatchPair(po_key=po_line.key, other_key="rl:1",
                                                score=1.0, method="EXACT_KEY")])
    return {s for r in LineChecks(inp).run() for s in r.statuses}


def test_rate_just_above_po_is_tolerated_by_default():
    """The shipped default absorbs ₹0.49 — which is wrong for Bata."""
    assert "RATE_HIGHER" not in _rate_statuses("620.49", "620")


def test_rate_just_above_po_fails_when_the_rate_is_fixed():
    """R2: the PO rate is fixed; any rate change needs a new PO.

    This is the behavioural difference the Bata profile buys. Without it, a
    vendor billing ₹0.49 over on every line of a long invoice passes silently.
    """
    assert "RATE_HIGHER" in _rate_statuses("620.49", "620", rate_must_equal=True)


def test_rate_equal_to_po_passes_under_both_settings():
    assert "RATE_HIGHER" not in _rate_statuses("620", "620")
    assert "RATE_HIGHER" not in _rate_statuses("620", "620", rate_must_equal=True)


def test_rate_below_po_is_not_escalated_by_the_fixed_rate_rule():
    """Billing less than agreed is informational, not a blocker, either way."""
    assert "RATE_HIGHER" not in _rate_statuses("600", "620", rate_must_equal=True)


# ── R5: the credit-note lifecycle ─────────────────────────────────────────────

def _case(extra_lines=(), billed_rate="620", receipt_total=None, **cfg):
    """A clean one-line PO and invoice, plus any extra invoice lines."""
    po_line = POLine(sno=1, description="Insulated refrigerant piping 25 mm", unit="RFT",
                     qty=D("100"), unit_price=D("620"), amount=D("62000"))
    inv_lines = [InvoiceLine(key="rl:1", sno=1, description="Insulated refrigerant piping 25 mm",
                             unit="RFT", qty=Sourced(value=D("100")),
                             rate=Sourced(value=D(billed_rate)),
                             amount=Sourced(value=D(billed_rate) * D("100")))]
    inv_lines += list(extra_lines)
    taxable = sum((sval(l.amount) for l in inv_lines), D("0"))
    po = ExtractedPO(po_number="PPO00024046", lines=[po_line], total=D("62000"), subtotal=D("62000"))
    inv = ExtractedInvoice(invoice_no="I-1", po_ref="PPO00024046", annexure_lines=inv_lines,
                           taxable=taxable)
    inp = ReconInput(po=po, invoice=inv, config=RuleConfig(**cfg), receipt_total=receipt_total,
                     invoice_matches=[MatchPair(po_key=po_line.key, other_key="rl:1",
                                                score=1.0, method="EXACT_KEY")])
    return reconcile(inp)


_SCAFFOLD = InvoiceLine(key="rl:2", sno=2, description="Scaffolding charges", unit="LS",
                        qty=Sourced(value=D("1")), rate=Sourced(value=D("11800")),
                        amount=Sourced(value=D("11800")))


def test_out_of_po_line_waits_on_a_credit_note():
    """The Bata scaffolding case: ₹11,800 billed although the PO excluded it."""
    res = _case(extra_lines=[_SCAFFOLD])
    assert res.summary.status == CaseStatus.AWAITING_CREDIT_NOTE, \
        "the next action is the vendor's, so this is not merely 'needs review'"


def test_the_out_of_po_line_carries_its_remedy():
    res = _case(extra_lines=[_SCAFFOLD])
    line = next(l for l in res.lines if LineStatus.NOT_IN_PO in l.statuses)
    assert line.remedy is not None
    assert "credit note" in line.remedy.lower()
    assert "new PO" in line.remedy, "the balance needs a fresh PO, not an amendment"


def test_the_excess_is_counted_as_money_at_risk():
    res = _case(extra_lines=[_SCAFFOLD])
    assert res.summary.money_at_risk >= D("11800")


def test_a_rate_breach_alongside_still_needs_a_person_first():
    """A credit note does not fix a rate above the PO — that needs a new PO."""
    res = _case(extra_lines=[_SCAFFOLD], billed_rate="700", rate_must_equal=True)
    assert res.summary.status == CaseStatus.NEEDS_REVIEW


def test_a_clean_invoice_with_a_receipt_reconciles():
    """A receipt leg must exist before anything can be called reconciled.

    Without one there is nothing confirming the work was done, so the case parks
    (R10) — see test_profiles.test_an_invoice_with_no_receipt_leg_is_parked.
    """
    res = _case(receipt_total=D("62000"))
    assert res.summary.status == CaseStatus.RECONCILED


def test_a_clean_invoice_without_any_receipt_parks():
    assert _case().summary.status == CaseStatus.AWAITING_RECEIPT


def test_rate_must_equal_is_off_by_default():
    """Existing tenants keep the tolerance they were configured with."""
    assert RuleConfig().rate_must_equal is False
    assert RuleConfig().rate_abs_tol == D("0.50")


def test_bata_profile_values_match_the_call():
    cfg = RuleConfig(rate_must_equal=True, invoice_vs_receipt_tol=D("100"))
    assert cfg.rate_must_equal
    assert cfg.invoice_vs_receipt_tol == D("100.00")
    assert cfg.variance_scope == "invoice"
    assert cfg.single_po_per_invoice
    assert cfg.cap_at_po, "payable is capped at the PO quantity (R2/R3)"


# ── reconciliation is on the taxable amount, not the tax-inclusive one ───────

def _line_with_printed(printed, tax_rate=None, qty="6", rate="95400"):
    po_line = POLine(sno=1, description="4 TR Cassette Unit Inverter AC", unit="NO",
                     qty=D(qty), unit_price=D(rate), amount=D(qty) * D(rate))
    inv_line = InvoiceLine(key="rl:1", sno=1, description="4 TR Cassette Unit Inverter AC",
                           unit="NO", qty=Sourced(value=D(qty)), rate=Sourced(value=D(rate)),
                           amount=Sourced(value=D(printed)),
                           tax_rate=D(tax_rate) if tax_rate else None)
    po = ExtractedPO(po_number="PPO00030541", lines=[po_line], total=D("572400"), subtotal=D("572400"))
    inv = ExtractedInvoice(invoice_no="I-1", po_ref="PPO00030541", annexure_lines=[inv_line],
                           taxable=D("572400"))
    return reconcile(ReconInput(po=po, invoice=inv, config=profiles.BATA, receipt_total=D("572400"),
                                invoice_matches=[MatchPair(po_key=po_line.key, other_key="rl:1",
                                                           score=1.0, method="EXACT")]))


def test_a_tax_inclusive_printed_amount_is_not_an_arithmetic_error():
    """The Bata/Bosch case: 6 x 95,400 = 5,72,400, printed 6,75,432 (+18% GST).

    The line is correct. Flagging it sent a reviewer to check arithmetic that
    was never wrong.
    """
    res = _line_with_printed("675432", tax_rate="18")
    line = res.lines[0]
    assert LineStatus.ARITHMETIC not in line.statuses
    # And it says nothing at all: a line that reconciles should be silent. A
    # note on every tax-inclusive line buries the few that need reading.
    assert not any("printed amount" in c for c in line.conflicts)


def test_the_taxable_amount_is_what_gets_compared():
    res = _line_with_printed("675432", tax_rate="18")
    line = res.lines[0]
    assert line.billed_amt == D("572400"), "qty x rate, not the tax-inclusive print"
    assert line.delta == D("0")


def test_a_genuinely_wrong_amount_is_still_caught():
    """Not a tax multiple — this one really does not add up."""
    res = _line_with_printed("600000", tax_rate="18")
    assert LineStatus.ARITHMETIC in res.lines[0].statuses


def test_an_exact_printed_amount_says_nothing_at_all():
    res = _line_with_printed("572400", tax_rate="18")
    assert LineStatus.ARITHMETIC not in res.lines[0].statuses
    assert not any("printed amount" in c for c in res.lines[0].conflicts)


def test_without_a_tax_rate_a_mismatch_is_still_an_error():
    """Nothing to explain it with, so it stays a finding."""
    res = _line_with_printed("675432", tax_rate=None)
    assert LineStatus.ARITHMETIC in res.lines[0].statuses


# ── a carrier's waybill is a scan: the reference is misread, not different ───

from backend_ocr.app.recon.engine import _ocr_same  # noqa: E402


@pytest.mark.parametrize("pod_ref,invoice_no,same", [
    # The real Safexpress waybill: G read as 6, W as 4, I as 1.
    ("266J/KM4/S115224", "26GJ/KMW/SI15224", True),
    ("26GJ/KMW/SI15224", "26GJ/KMW/SI15224", True),
    ("0CT/I5/8O", "OCT/15/80", True),      # O/0, I/1 both ways
    ("ABC/T1/22", "ABC/11/22", False),     # T is not a 1: too eager a pair invites false matches
    # A different consignment is NOT a misreading, whatever it looks like.
    ("266J/KM4/S115225", "26GJ/KMW/SI15224", False),
    ("266J/KM4/S11522", "26GJ/KMW/SI15224", False),   # dropped character
    ("AAA/111/222", "BBB/111/222", False),
    ("", "26GJ/KMW/SI15224", False),
])
def test_ocr_confusable_reference_matching(pod_ref, invoice_no, same):
    assert _ocr_same(pod_ref, invoice_no) is same


def _pod_case(pod_ref, pod_value="675432", invoice_total="675432"):
    from backend_ocr.app.recon.types import ExtractedPOD, Receipt
    import datetime
    po_line = POLine(sno=1, description="AC", unit="NO", qty=D("6"), unit_price=D("95400"),
                     amount=D("572400"))
    po = ExtractedPO(po_number="PPO00030541", lines=[po_line], total=D("572400"))
    inv = ExtractedInvoice(invoice_no="26GJ/KMW/SI15224", po_ref="PPO00030541",
                           taxable=D("572400"), total=D(invoice_total))
    pod = ExtractedPOD(waybill_no="1000 4128 4608", invoice_nos=[pod_ref],
                       total_invoice_value=D(pod_value),
                       receipt=Receipt(receiver="Ravindra", date=datetime.date(2026, 9, 21)))
    return {c.code: c for c in HeaderChecks(
        ReconInput(po=po, invoice=inv, pods=[pod], config=profiles.BATA)).run()}


def test_a_misread_reference_passes_when_the_value_corroborates_it():
    """The POD's own total is the second fact that makes it safe."""
    c = _pod_case("266J/KM4/S115224")["pod_matches"]
    assert c.passed
    assert "characters a scanner confuses" in c.detail
    assert c.evidence["misread_reference"]


def test_a_misread_reference_still_fails_when_the_value_disagrees():
    """One confusable spelling is not enough on its own.

    Without a corroborating fact a spelling allowance could absorb a genuinely
    different consignment.
    """
    c = _pod_case("266J/KM4/S115224", pod_value="999999")["pod_matches"]
    assert not c.passed


def test_a_genuinely_different_reference_still_fails():
    c = _pod_case("266J/KM4/S115225")["pod_matches"]
    assert not c.passed and "POD lists" in c.detail


def test_an_exact_reference_passes_quietly():
    c = _pod_case("26GJ/KMW/SI15224")["pod_matches"]
    assert c.passed and not c.evidence.get("misread_reference")


# ── a misread letter is this consignment; a changed digit is another one ────

from backend_ocr.app.recon.engine import same_consignment  # noqa: E402


def test_a_misread_letter_with_a_matching_value_is_this_invoice():
    """The real waybill: K read as A, which no honest fold list contains."""
    why = same_consignment("266J/AM4/S115224", "26GJ/KMW/SI15224", value_matches=True)
    assert why and "letter" in why


def test_a_changed_digit_is_the_next_invoice_not_a_misreading():
    """Digits carry the sequence.

    Accepting a trailing-digit difference would confirm receipt of goods that
    arrived against a different bill — even with an identical declared value,
    which consecutive invoices can share.
    """
    assert same_consignment("266J/KM4/S115225", "26GJ/KMW/SI15224", value_matches=True) is None


def test_without_a_matching_value_a_letter_difference_is_not_enough():
    assert same_consignment("266J/AM4/S115224", "26GJ/KMW/SI15224", value_matches=False) is None


def test_an_exact_reference_needs_no_corroboration():
    assert same_consignment("26GJ/KMW/SI15224", "26GJ/KMW/SI15224", value_matches=False) == "same reference"


def test_an_unrelated_reference_is_refused_however_the_money_looks():
    assert same_consignment("99XX/ZZ/0000001", "26GJ/KMW/SI15224", value_matches=True) is None


# ── corroborated is not read: the case carries the assumption ───────────────

def test_a_corroborated_reference_raises_its_own_flag():
    """The engine must not settle this quietly.

    The paper does not carry this invoice's number. It is accepted on an
    inference about a scanner plus a value that agrees — so the case says what
    was assumed and asks a person to confirm it.
    """
    checks = _pod_case("266J/KM4/S115224")
    f = checks["pod_invoice_ref_match"]
    assert not f.passed
    assert f.severity.value == "REVIEW", "it must not block a payment the value and stamp support"
    assert "confirm this waybill is for this invoice" in f.detail.lower()
    assert f.evidence["pod_reference"] == "266J/KM4/S115224"
    assert f.evidence["invoice_no"] == "26GJ/KMW/SI15224"
    assert f.evidence["basis"] == "corroborated_by_value"


def test_an_exact_reference_raises_no_flag_to_confirm():
    assert "pod_invoice_ref_match" not in _pod_case("26GJ/KMW/SI15224")


def test_a_reference_that_is_refused_outright_raises_no_confirm_flag():
    """pod_matches already fails. A second ask would double-count one problem."""
    checks = _pod_case("266J/KM4/S115225")
    assert not checks["pod_matches"].passed
    assert "pod_invoice_ref_match" not in checks


# ── the receipt column, where a delivery proof can honestly fill it ─────────

def _single_line_case(pod_value="675432", invoice_total="675432", qty="6"):
    from backend_ocr.app.recon.types import ExtractedPOD, Receipt
    import datetime
    po_line = POLine(sno=1, description="AC", unit="NO", qty=D(qty), unit_price=D("95400"),
                     amount=D("572400"))
    po = ExtractedPO(po_number="PPO00030541", lines=[po_line], total=D("572400"))
    inv_line = InvoiceLine(key="rl:1", sno=1, description="AC", unit="NO",
                           qty=Sourced(value=D(qty)), rate=Sourced(value=D("95400")),
                           amount=Sourced(value=D("572400")))
    inv = ExtractedInvoice(invoice_no="26GJ/KMW/SI15224", po_ref="PPO00030541",
                           annexure_lines=[inv_line], taxable=D("572400"), total=D(invoice_total))
    pod = ExtractedPOD(waybill_no="1000 4128 4608", invoice_nos=["26GJ/KMW/SI15224"],
                       total_invoice_value=D(pod_value),
                       receipt=Receipt(receiver="Ravindra", date=datetime.date(2026, 9, 21)))
    return ReconInput(po=po, invoice=inv, pods=[pod], config=profiles.BATA,
                      invoice_matches=[MatchPair(po_key=po_line.key, other_key="rl:1",
                                                 score=1.0, method="EXACT")])


def _lines(inp):
    from backend_ocr.app.recon.engine import LineChecks
    return LineChecks(inp).run()


def test_a_one_line_bill_takes_its_receipt_from_the_consignment():
    out = _lines(_single_line_case())
    billed = [l for l in out if l.invoice_key]
    assert len(billed) == 1
    assert billed[0].received_qty == billed[0].billed_qty
    assert billed[0].receipt_basis == "single_line_consignment"


def test_a_consignment_worth_something_else_fills_nothing():
    """Without the value agreeing, the proof may be for a different bill."""
    out = _lines(_single_line_case(pod_value="500000"))
    assert all(l.received_qty is None for l in out if l.invoice_key)


# ── a person can answer the question, and the answer is about those words ──

def _pod_case_confirmed(confirmed, pod_ref="266J/KM4/S115224"):
    import datetime
    from backend_ocr.app.recon.types import ExtractedPOD, Receipt
    po_line = POLine(sno=1, description="AC", unit="NO", qty=D("6"), unit_price=D("95400"),
                     amount=D("572400"))
    po = ExtractedPO(po_number="PPO00030541", lines=[po_line], total=D("572400"))
    inv = ExtractedInvoice(invoice_no="26GJ/KMW/SI15224", po_ref="PPO00030541",
                           taxable=D("572400"), total=D("675432"))
    pod = ExtractedPOD(waybill_no="1000 4128 4608", invoice_nos=[pod_ref],
                       total_invoice_value=D("675432"),
                       receipt=Receipt(receiver="Ravindra", date=datetime.date(2026, 9, 21)))
    return {c.code: c for c in HeaderChecks(
        ReconInput(po=po, invoice=inv, pods=[pod], config=profiles.BATA,
                   confirmed_checks=confirmed)).run()}


def test_a_confirmation_settles_the_check_and_names_who_gave_it():
    checks = _pod_case_confirmed({"pod_invoice_ref_match": {
        "shown": "266J/KM4/S115224|26GJ/KMW/SI15224", "actor": "priya@bata", "at": None}})
    c = checks["pod_invoice_ref_match"]
    assert c.passed and "confirmed by priya@bata" in c.detail
    assert c.evidence["confirmed_by"] == "priya@bata"


def test_a_confirmation_given_about_other_words_does_not_carry_over():
    """The document was read again and the reference came out differently.

    The stored yes was about a different pair of strings, so it says nothing
    about this one — the check asks again rather than coasting on it.
    """
    checks = _pod_case_confirmed(
        {"pod_invoice_ref_match": {"shown": "SOMETHING/ELSE|26GJ/KMW/SI15224", "actor": "priya@bata"}})
    assert not checks["pod_invoice_ref_match"].passed


def test_an_unanswered_check_still_asks():
    assert not _pod_case_confirmed({})["pod_invoice_ref_match"].passed


def test_the_check_publishes_what_a_confirmation_would_be_about():
    """The screen sends `shown` back, so an answer is tied to what was on it."""
    c = _pod_case_confirmed({})["pod_invoice_ref_match"]
    assert c.evidence["confirmable"] == "266J/KM4/S115224|26GJ/KMW/SI15224"


# ── the receipt leg compares like with like ────────────────────────────────

def _variance_case(receipt, basis, taxable="572400", total="675432"):
    inv = ExtractedInvoice(invoice_no="I-1", taxable=D(taxable), total=D(total))
    return {c.code: c for c in HeaderChecks(
        ReconInput(po=None, invoice=inv, receipt_total=D(receipt), receipt_basis=basis,
                   config=profiles.BATA)).run()}


def test_a_carrier_value_is_held_against_the_invoice_gross():
    """A POD declares what the consignment is worth including tax.

    Against the taxable sum it would differ by exactly the GST on every
    consignment — a red check on every correctly delivered invoice.
    """
    c = _variance_case("675432", "gross")["receipt_variance"]
    assert c.passed and "incl. tax" in c.detail


def test_a_dynamics_receipt_is_held_against_the_taxable_sum():
    """A GRN books goods at the PO price, which excludes tax."""
    c = _variance_case("572400", "taxable")["receipt_variance"]
    assert c.passed and "incl. tax" not in c.detail


def test_holding_a_gross_receipt_against_the_taxable_sum_would_fail():
    """The bug this basis exists to prevent, stated as a test."""
    c = _variance_case("675432", "taxable")["receipt_variance"]
    assert not c.passed


# ── an invoice that prints no PO number is not a finding ───────────────────

def _po_ref_case(po_ref):
    po_line = POLine(sno=1, description="AC", unit="NO", qty=D("1"), unit_price=D("100"), amount=D("100"))
    po = ExtractedPO(po_number="PPO00030541", lines=[po_line], total=D("100"))
    inv = ExtractedInvoice(invoice_no="I-1", po_ref=po_ref, taxable=D("100"), total=D("100"))
    return {c.code: c for c in HeaderChecks(ReconInput(po=po, invoice=inv, config=profiles.BATA)).run()}


def test_no_po_number_on_the_invoice_raises_nothing():
    """Bata, 20 Nov 2026: plenty of vendors never print one.

    The case is linked to its PO by other means, and a Review that every such
    invoice fails teaches reviewers to scroll past the checks.
    """
    assert "po_reference" not in _po_ref_case(None)


def test_the_wrong_po_number_is_still_a_blocker():
    """An invoice billed against another PO would consume this one in silence."""
    c = _po_ref_case("PPO00099999")["po_reference"]
    assert not c.passed and c.severity.value == "BLOCKER"


def test_the_right_po_number_passes():
    assert _po_ref_case("PPO00030541")["po_reference"].passed


# ── the site report's own rate ─────────────────────────────────────────────

def test_the_discounted_rate_is_the_one_the_site_supports():
    """A report printing 6700 struck through and 6365 agreed means 6365.

    Taking the gross would overstate what the site supports by the discount
    the parties had already agreed.
    """
    from backend_ocr.app.recon.engine import _audit_rate, _audit_value
    from backend_ocr.app.recon.types import EvidenceRow, Sourced
    ev = EvidenceRow(key="ev:1", item="Flush Door", rate=D("6700"),
                     rate_after_discount=D("6365"), audit_qty=Sourced(value=D("3")))
    assert _audit_rate(ev) == D("6365")
    assert _audit_value(ev) == D("19095")


def test_a_report_with_no_discount_uses_the_rate_it_prints():
    from backend_ocr.app.recon.engine import _audit_rate
    from backend_ocr.app.recon.types import EvidenceRow
    assert _audit_rate(EvidenceRow(key="ev:1", item="X", rate=D("10"))) == D("10")


def test_a_report_with_no_rate_values_nothing():
    """A zero would read as "the site supports nothing", which is a lie."""
    from backend_ocr.app.recon.engine import _audit_rate, _audit_value
    from backend_ocr.app.recon.types import EvidenceRow, Sourced
    ev = EvidenceRow(key="ev:1", item="X", audit_qty=Sourced(value=D("5")))
    assert _audit_rate(ev) is None and _audit_value(ev) is None


# ── the site report's own arithmetic ───────────────────────────────────────

def _ev_row(**kw):
    from backend_ocr.app.recon.types import EvidenceRow
    return EvidenceRow(key="ev:1", item="Flush Door", **kw)


def test_a_printed_total_that_adds_up_says_nothing():
    """QTY 3 · AFTER 5% 6,365 · TOTAL 19,095 — the real row from the scan."""
    from backend_ocr.app.recon.rules import audit_row_arithmetic
    assert audit_row_arithmetic(_ev_row(po_qty=D("3"), rate=D("6700"),
                                        rate_after_discount=D("6365"),
                                        amount=D("19095"))) is None


def test_a_misread_rate_is_caught_by_the_row_s_own_total():
    """A rate read as 6,365 when it says 6,866 is invisible on a scan.

    Nothing else contradicts it — until the total printed beside it does.
    """
    from backend_ocr.app.recon.rules import audit_row_arithmetic
    why = audit_row_arithmetic(_ev_row(po_qty=D("3"), rate_after_discount=D("6365"),
                                       amount=D("20598")))
    assert why and "20,598.00" in why and "19,095.00" in why


def test_the_check_extends_the_ordered_quantity_not_the_audited_one():
    """These reports price the PO line, whatever the auditor then certified.

    Checking against the audited quantity would raise a difference on every
    row the auditor corrected, which is most of the interesting ones.
    """
    from backend_ocr.app.recon.rules import audit_row_arithmetic
    from backend_ocr.app.recon.types import Sourced
    assert audit_row_arithmetic(_ev_row(po_qty=D("3"), rate_after_discount=D("6365"),
                                        amount=D("19095"),
                                        audit_qty=Sourced(value=D("1")))) is None


def test_a_row_without_a_printed_total_is_not_a_finding():
    from backend_ocr.app.recon.rules import audit_row_arithmetic
    assert audit_row_arithmetic(_ev_row(po_qty=D("3"), rate_after_discount=D("6365"))) is None


def test_a_list_rate_with_no_discount_column_is_not_a_disagreement():
    """₹50.00 on the report against ₹47.50 on the PO is the 5% discount.

    The report is saying what the rate was discounted FROM. Calling that a
    conflict would flag every discounted line on every case.
    """
    from backend_ocr.app.recon.types import EvidenceRow, PVSection, Sourced
    po_line = POLine(sno=1, description="Vinyl", unit="SF", qty=D("10"),
                     unit_price=D("47.50"), amount=D("475"))
    po = ExtractedPO(po_number="PPO1", lines=[po_line], total=D("475"))
    inv = ExtractedInvoice(invoice_no="I-1", po_ref="PPO1", taxable=D("475"), total=D("475"))
    ev = EvidenceRow(key="ev:1", item="Vinyl", rate=D("50"), audit_qty=Sourced(value=D("10")))
    sec = PVSection(rows=[ev])
    from backend_ocr.app.recon.engine import LineChecks
    out = LineChecks(ReconInput(
        po=po, invoice=inv, evidence=[sec], config=profiles.BATA,
        evidence_matches=[MatchPair(po_key=po_line.key, other_key="ev:1", score=1.0, method="EXACT")])).run()
    assert not [c for l in out for c in l.conflicts if "not the PO rate" in c]


def test_a_line_the_auditor_found_undone_is_worth_nothing_not_unknown():
    """The report prices it; the auditor certified none of it.

    Zero is the answer, and it is a different answer from "we cannot price
    this row", which is what None means.
    """
    from backend_ocr.app.recon.rules import audit_row_value
    from backend_ocr.app.recon.types import Sourced
    assert audit_row_value(_ev_row(rate=D("6704"), audit_qty=Sourced(value=D("0")))) == D("0")


def test_a_row_the_report_does_not_price_has_no_value_at_all():
    from backend_ocr.app.recon.rules import audit_row_value
    from backend_ocr.app.recon.types import Sourced
    assert audit_row_value(_ev_row(audit_qty=Sourced(value=D("4")))) is None


def test_the_viewer_and_the_case_price_a_row_the_same_way():
    """One definition, two screens. They must never disagree about the paper."""
    from backend_ocr.app.recon import engine, rules
    assert engine._audit_rate is rules.audit_row_rate
    assert engine._audit_value is rules.audit_row_value


# ── how much of the billed value rests on a pairing we are sure of ─────────

def _conf(lines):
    from backend_ocr.app.recon.engine import _pairing_confidence
    return _pairing_confidence(lines)


def _rl(amt, *, method="EXACT", score=1.0, po=True, inv=True, desc="Item"):
    from backend_ocr.app.recon.types import LineResult, MatchMethod
    return LineResult(ord=1, kind="po", description=desc,
                      po_key="pol:1" if po else None, invoice_key="rl:1" if inv else None,
                      billed_amt=D(amt), match_method=MatchMethod(method), match_score=score)


def test_confidence_is_weighted_by_money_not_by_line_count():
    """One shaky pairing on a large line must not hide behind many tidy small ones.

    It is the large line that decides whether the invoice can be paid.
    """
    lines = [_rl("500000", method="SCORE", score=0.5)] + [_rl("500") for _ in range(40)]
    conf, _ = _conf(lines)
    assert conf < D("0.6"), "a line-count average would have reported about 0.99"


def test_an_exact_pairing_counts_whole():
    conf, weakest = _conf([_rl("1000"), _rl("2000")])
    assert conf == D("1") and weakest == []


def test_a_billed_line_with_no_counterpart_counts_for_nothing():
    """Nothing has been compared with it, so it supports no confidence at all."""
    conf, _ = _conf([_rl("1000"), _rl("1000", po=False, method="NONE", score=0)])
    assert conf == D("0.5")


def test_a_case_with_no_po_has_no_confidence_rather_than_zero():
    """Waiting for a document is not the same problem as a bad pairing.

    Reported as 0 it would sit at the bottom of a confidence chart beside a
    case whose matching is genuinely untrustworthy.
    """
    conf, _ = _conf([_rl("1000", po=False, method="NONE", score=0)])
    assert conf is None


def test_the_weakest_lines_are_named_worst_money_first():
    lines = [_rl("100", method="SCORE", score=0.4, desc="small doubt"),
             _rl("90000", method="SCORE", score=0.4, desc="big doubt"),
             _rl("5000")]
    _conf_, weakest = _conf(lines)
    assert [w["description"] for w in weakest] == ["big doubt", "small doubt"]
