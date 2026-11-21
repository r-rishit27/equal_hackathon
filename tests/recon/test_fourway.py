"""The four invoice-centred comparisons (recon/fourway.py)."""
from decimal import Decimal as D

from backend_ocr.app.recon import fourway as F
from backend_ocr.app.recon.grn import GrnLine
from backend_ocr.app.recon.types import ExtractedInvoice, ExtractedPaymentAdvice, LineResult, PaymentAdviceLine


def line(**kw):
    base = dict(ord=1, kind="po", description="Insulated piping 25 mm", po_key="pol:1",
                invoice_key="rl:1", evidence_key="ev:1", invoice_text="Insulated piping 25 mm",
                evidence_text="Insulated piping 25 mm", billed_qty=D("100"), po_qty=D("100"),
                verified_qty=D("100"), po_rate=D("620"), billed_rate=D("620"),
                billed_amt=D("62000"), expected_amt=D("62000"))
    base.update(kw)
    return LineResult(**base)


def panel(panels, pair):
    return next(p for p in panels if p.pair == pair)


def check(p, field):
    return next(c for c in p.lines[0].checks if c.field == field)


# ── shape ─────────────────────────────────────────────────────────────────────

def test_there_are_always_four_panels_in_a_fixed_order():
    """A panel that cannot be filled still appears, so nothing looks forgotten."""
    panels = F.build([line()])
    assert [p.pair for p in panels] == list(F.PAIRS)


def test_each_panel_states_the_question_it_answers():
    for p in F.build([line()]):
        assert p.title and p.ask.endswith("?")


# ── invoice vs PO ─────────────────────────────────────────────────────────────

def test_a_clean_line_matches_on_every_field():
    p = panel(F.build([line()]), F.INVOICE_VS_PO)
    assert p.lines[0].state == F.MATCH
    assert {c.state for c in p.lines[0].checks} == {F.MATCH}


def test_a_rate_difference_shows_both_numbers():
    p = panel(F.build([line(billed_rate=D("700"))]), F.INVOICE_VS_PO)
    c = check(p, "rate")
    assert c.state == F.DIFFERS and c.invoice == "700" and c.other == "620"


def test_a_quantity_difference_is_caught():
    assert check(panel(F.build([line(billed_qty=D("120"))]), F.INVOICE_VS_PO), "qty").state == F.DIFFERS


def test_a_line_not_on_the_po_reads_as_missing_not_as_a_difference():
    """Billed with nothing ordered is an absence, not a disagreement."""
    p = panel(F.build([line(po_key=None, po_qty=None, po_rate=None, expected_amt=D("0"))]),
              F.INVOICE_VS_PO)
    assert p.lines[0].state == F.MISSING
    assert {c.state for c in p.lines[0].checks} == {F.MISSING}


def test_a_differing_description_is_reported():
    p = panel(F.build([line(invoice_text="Copper pipe 25mm")]), F.INVOICE_VS_PO)
    assert check(p, "description").state == F.DIFFERS


def test_wording_differences_that_normalise_away_are_a_match():
    p = panel(F.build([line(invoice_text="Insulated  Piping   25 MM")]), F.INVOICE_VS_PO)
    assert check(p, "description").state == F.MATCH


def test_the_worst_field_decides_the_line():
    p = panel(F.build([line(billed_rate=D("700"))]), F.INVOICE_VS_PO)
    assert p.lines[0].state == F.DIFFERS, "one bad field is enough to flag the line"


# ── invoice vs audit ──────────────────────────────────────────────────────────

def test_rate_and_amount_are_not_applicable_against_an_audit():
    """An auditor certifies what is there, not what it costs.

    Marking these 'missing' would read as a fault in the audit report.
    """
    p = panel(F.build([line()]), F.INVOICE_VS_AUDIT)
    assert check(p, "rate").state == F.NA and check(p, "amount").state == F.NA


def test_billing_more_than_was_verified_shows_up():
    p = panel(F.build([line(billed_qty=D("120"))]), F.INVOICE_VS_AUDIT)
    assert check(p, "qty").state == F.DIFFERS


def test_the_audit_panel_is_marked_unavailable_when_there_is_no_report():
    p = panel(F.build([line(evidence_key=None, verified_qty=None)]), F.INVOICE_VS_AUDIT)
    assert not p.available and "audit report" in p.absent_reason


# ── invoice vs GRN ────────────────────────────────────────────────────────────

def _grn(qty="100", amount="62000", desc="Insulated piping 25 mm"):
    return GrnLine(po_number="P1", qty_received=D(qty), description=desc,
                   rate=D("620"), amount=D(amount))


def test_the_grn_panel_says_why_it_is_empty():
    p = panel(F.build([line()]), F.INVOICE_VS_GRN)
    assert not p.available and "Dynamics" in p.absent_reason


def test_a_matching_receipt_clears_the_line():
    p = panel(F.build([line()], receipt_lines=[_grn()]), F.INVOICE_VS_GRN)
    assert p.lines[0].state == F.MATCH


def test_billing_more_than_was_received_is_caught():
    p = panel(F.build([line(billed_qty=D("120"))], receipt_lines=[_grn()]), F.INVOICE_VS_GRN)
    assert check(p, "qty").state == F.DIFFERS


def test_an_invoice_line_with_no_receipt_row_is_missing():
    p = panel(F.build([line()], receipt_lines=[_grn(desc="Something else")]), F.INVOICE_VS_GRN)
    assert check(p, "qty").state == F.MISSING


# ── invoice vs payment ────────────────────────────────────────────────────────

def _advice(base="101327.07", ref="SL8069260000321"):
    return ExtractedPaymentAdvice(
        total_base=D(base), total_tds=D("97.00"), total_net=D("101230.07"),
        lines=[PaymentAdviceLine(reference=ref, base_amount=D(base))])


def test_the_payment_panel_is_one_row_because_an_advice_settles_an_invoice():
    inv = ExtractedInvoice(invoice_no="SL8069260000321", total=D("101327.07"))
    p = panel(F.build([line()], payment=_advice(), invoice=inv), F.INVOICE_VS_PAYMENT)
    assert len(p.lines) == 1
    assert check(p, "qty").state == F.NA and check(p, "rate").state == F.NA


def test_settlement_compares_the_base_so_tds_is_not_read_as_a_shortfall():
    inv = ExtractedInvoice(invoice_no="SL8069260000321", total=D("101327.07"))
    p = panel(F.build([line()], payment=_advice(), invoice=inv), F.INVOICE_VS_PAYMENT)
    assert check(p, "amount").state == F.MATCH, "97 of TDS is withheld, not unpaid"


def test_a_short_settlement_is_flagged():
    inv = ExtractedInvoice(invoice_no="X", total=D("111327.07"))
    p = panel(F.build([line()], payment=_advice(), invoice=inv), F.INVOICE_VS_PAYMENT)
    assert check(p, "amount").state == F.DIFFERS


def test_the_payment_panel_says_why_it_is_empty():
    p = panel(F.build([line()]), F.INVOICE_VS_PAYMENT)
    assert not p.available and "Not paid yet" in p.absent_reason


# ── counts, for the dashboard headline ───────────────────────────────────────

def test_counts_summarise_a_panel():
    panels = F.build([line(), line(ord=2, invoice_key="rl:2", billed_rate=D("700")),
                      line(ord=3, invoice_key="rl:3", po_key=None, po_qty=None, po_rate=None)])
    c = panel(panels, F.INVOICE_VS_PO).counts
    assert c[F.MATCH] == 1 and c[F.DIFFERS] == 1 and c[F.MISSING] == 1


# ── a delivery proof as receipt evidence (POD standing in for the GRN) ───────

def _pod(value="675432", refs=("26GJ/KMW/SI15224",), waybill="1000 4128 4608"):
    from backend_ocr.app.recon.types import ExtractedPOD, Receipt
    return ExtractedPOD(waybill_no=waybill, invoice_nos=list(refs),
                        total_invoice_value=D(value), packages=18,
                        receipt=Receipt(receiver="Ravindra"))


def test_a_pod_answers_the_receipt_question_when_there_is_no_grn():
    p = panel(F.build([line(billed_amt=D("675432"))], pods=[_pod()]), F.INVOICE_VS_GRN)
    assert p.available and p.title == "Invoice vs delivery proof"


def test_a_pod_is_compared_on_value_not_on_item_quantities():
    """A POD proves packages and a consignment value, never "6 of this item".

    Showing per-line quantities against it would invent evidence the document
    does not carry (V§1 receipt_granularity).
    """
    p = panel(F.build([line(billed_amt=D("675432"))], pods=[_pod()]), F.INVOICE_VS_GRN)
    assert len(p.lines) == 1, "one consignment row, not one row per invoice line"
    assert check(p, "rate").state == F.NA
    # The quantity it DOES prove: packages delivered, stated as such.
    assert check(p, "qty").other == "18 packages"
    assert check(p, "amount").state == F.MATCH


def test_the_pod_value_is_compared_against_the_gross_invoice():
    """A carrier declares "Total Inv. Value" including tax.

    Comparing it against the taxable sum would report a difference of exactly
    the GST on every consignment — the same basis error as the arithmetic check.
    """
    inv = ExtractedInvoice(invoice_no="26GJ/KMW/SI15224", taxable=D("572400"), total=D("675432"))
    p = panel(F.build([line(billed_amt=D("572400"))], pods=[_pod(value="675432")], invoice=inv),
              F.INVOICE_VS_GRN)
    assert check(p, "amount").state == F.MATCH, "gross against gross, not gross against taxable"


def test_a_pod_whose_value_disagrees_is_flagged():
    p = panel(F.build([line(billed_amt=D("675432"))], pods=[_pod(value="500000")]), F.INVOICE_VS_GRN)
    assert check(p, "amount").state == F.DIFFERS


def test_the_panel_says_what_the_pod_can_and_cannot_prove():
    p = panel(F.build([line(billed_amt=D("675432"))], pods=[_pod()]), F.INVOICE_VS_GRN)
    assert "not item quantities" in p.note
    assert "Dynamics GRN" in p.note


def test_a_real_grn_still_wins_over_a_pod():
    """When the Dynamics extract exists it is the better evidence: line level."""
    g = GrnLine(po_number="P1", qty_received=D("100"), description="Insulated piping 25 mm",
                rate=D("620"), amount=D("62000"))
    p = panel(F.build([line()], receipt_lines=[g], pods=[_pod()]), F.INVOICE_VS_GRN)
    assert p.title == "Invoice vs GRN"
    assert check(p, "qty").state == F.MATCH, "line-level evidence, not just a value"


# ── a delivery proof must be evidence for THIS invoice ──────────────────────

def test_a_pod_for_another_invoice_is_not_used_as_receipt_evidence():
    """A POD can be attached to a case by hand.

    A waybill for a different consignment would otherwise confirm receipt of
    goods that never arrived against this bill — the worst kind of false pass.
    """
    inv = ExtractedInvoice(invoice_no="26GJ/KMW/SI15224", total=D("675432"))
    p = panel(F.build([line()], pods=[_pod(refs=("99XX/ZZ/0000001",))], invoice=inv),
              F.INVOICE_VS_GRN)
    assert not p.available
    assert "99XX/ZZ/0000001" in p.absent_reason and "not 26GJ/KMW/SI15224" in p.absent_reason


def test_a_pod_naming_this_invoice_is_used():
    inv = ExtractedInvoice(invoice_no="26GJ/KMW/SI15224", total=D("675432"))
    p = panel(F.build([line()], pods=[_pod(refs=("26GJ/KMW/SI15224",))], invoice=inv),
              F.INVOICE_VS_GRN)
    assert p.available


def test_a_scanner_misreading_still_counts_as_this_invoice():
    """G read as 6, W as 4, I as 1 — the Safexpress waybill. Same consignment."""
    inv = ExtractedInvoice(invoice_no="26GJ/KMW/SI15224", total=D("675432"))
    p = panel(F.build([line()], pods=[_pod(refs=("266J/KM4/S115224",))], invoice=inv),
              F.INVOICE_VS_GRN)
    assert p.available, "a misread reference is the same reference"


def test_a_pod_with_no_reference_at_all_is_still_used():
    """Some carriers print no invoice list. Absence is not contradiction —
    the value and signature checks still apply."""
    inv = ExtractedInvoice(invoice_no="26GJ/KMW/SI15224", total=D("675432"))
    p = panel(F.build([line()], pods=[_pod(refs=())], invoice=inv), F.INVOICE_VS_GRN)
    assert p.available


# ── accepted on an inference is not accepted on the paper ───────────────────

def _desc(p):
    """The reference check on the delivery-proof panel.

    Named `reference`, not `description`: it compares a waybill's invoice number
    against the invoice's own, and calling that "Item" on screen would misname
    what the reviewer is reading.
    """
    return next(c for c in p.lines[0].checks if c.field == "reference")


def test_an_inexact_reference_says_so_where_the_verdict_is_read():
    """The panel must not present an inference as a reading.

    The waybill does NOT carry this invoice's number. It is accepted because a
    scanner confusion plus a matching declared value make it the likeliest
    consignment — a judgement a person can check in seconds, so the panel asks
    them to rather than showing a tick.
    """
    inv = ExtractedInvoice(invoice_no="26GJ/KMW/SI15224", total=D("675432"))
    p = panel(F.build([line()], pods=[_pod(refs=("266J/KM4/S115224",))], invoice=inv),
              F.INVOICE_VS_GRN)
    assert p.available
    assert "266J/KM4/S115224" in p.confirm and "26GJ/KMW/SI15224" in p.confirm
    assert "Confirm it is this consignment" in p.confirm


def test_an_exact_reference_asks_nobody_to_confirm_anything():
    inv = ExtractedInvoice(invoice_no="26GJ/KMW/SI15224", total=D("675432"))
    p = panel(F.build([line()], pods=[_pod(refs=("26GJ/KMW/SI15224",))], invoice=inv),
              F.INVOICE_VS_GRN)
    assert p.confirm == ""


def test_the_reference_check_compares_the_invoice_against_the_waybill():
    """It used to compare the POD's reference to itself, which always matched.

    A check that cannot fail is not a check — it is a tick with a label.
    """
    inv = ExtractedInvoice(invoice_no="26GJ/KMW/SI15224", total=D("675432"))
    p = panel(F.build([line()], pods=[_pod(refs=("266J/KM4/S115224",))], invoice=inv),
              F.INVOICE_VS_GRN)
    c = _desc(p)
    assert c.state == F.DIFFERS
    assert c.invoice == "26GJ/KMW/SI15224" and c.other == "266J/KM4/S115224"


def test_an_exact_reference_reads_as_a_match_on_that_check():
    inv = ExtractedInvoice(invoice_no="26GJ/KMW/SI15224", total=D("675432"))
    p = panel(F.build([line()], pods=[_pod(refs=("26GJ/KMW/SI15224",))], invoice=inv),
              F.INVOICE_VS_GRN)
    assert _desc(p).state == F.MATCH


def test_with_no_receipt_evidence_the_panel_names_both_ways_to_get_some():
    """Naming only Dynamics reads as a missing feature, not a missing document.

    A signed delivery proof answers this leg too, and for CAPEX work it is the
    document that actually exists.
    """
    p = panel(F.build([line()]), F.INVOICE_VS_GRN)
    assert not p.available
    assert "delivery proof" in p.absent_reason and "Dynamics" in p.absent_reason


# ── a single-line consignment has nowhere else to be ───────────────────────

def test_one_line_and_a_matching_consignment_value_fills_the_receipt():
    """A POD cannot itemise packages — but with one line there is nothing to split.

    The declared value IS this line's value, so the quantity billed is the
    quantity received. Leaving the column blank here reports less than the
    document proves.
    """
    inv = ExtractedInvoice(invoice_no="26GJ/KMW/SI15224", total=D("675432"))
    l = line(billed_qty=D("6"), received_qty=D("6"))
    l.receipt_basis = "single_line_consignment"
    p = panel(F.build([l], pods=[_pod()], invoice=inv), F.INVOICE_VS_GRN)
    assert p.available
    # The consignment row, then the line it can only belong to.
    assert len(p.lines) == 2
    q = next(c for c in p.lines[1].checks if c.field == "qty")
    assert q.state == F.MATCH and q.invoice == "6" and q.other == "6"
    assert "one line, so what arrived arrived against it" in p.note


def test_without_a_derived_receipt_the_panel_still_says_what_it_cannot_prove():
    inv = ExtractedInvoice(invoice_no="26GJ/KMW/SI15224", total=D("675432"))
    p = panel(F.build([line()], pods=[_pod()], invoice=inv), F.INVOICE_VS_GRN)
    assert len(p.lines) == 1
    assert "does not itemise packages" in p.note


# ── a site report that prices the work is compared on price ────────────────

def test_a_priced_report_is_compared_on_rate_and_value():
    """Most of these reports carry a rate column; it was being read and dropped.

    The discounted rate is the one used — that is what the parties settled on,
    and the gross beside it is what it was discounted from.
    """
    l = line(billed_qty=D("3"), billed_rate=D("6700"), billed_amt=D("20100"),
             verified_qty=D("3"), evidence_key="ev:1")
    l.verified_rate, l.verified_amt = D("6365"), D("19095")
    p = panel(F.build([l]), F.INVOICE_VS_AUDIT)
    by = {c.field: c for c in p.lines[0].checks}
    assert by["rate"].state == F.DIFFERS and by["rate"].other == "6365"
    assert by["amount"].state == F.DIFFERS and by["amount"].other == "19095"
    assert "after the discount" in p.note


def test_a_report_that_only_counts_says_so_instead_of_showing_a_gap():
    """An auditor certifying what is there is not the same as costing it.

    With no rate on the paper, rate and value stay NA — a zero or a blank
    comparison would read as the site supporting nothing.
    """
    p = panel(F.build([line(verified_qty=D("3"), evidence_key="ev:1")]), F.INVOICE_VS_AUDIT)
    by = {c.field: c for c in p.lines[0].checks}
    assert by["rate"].state == F.NA and by["amount"].state == F.NA
    assert "nothing to compare on rate" in p.note
