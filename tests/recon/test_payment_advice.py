"""The PAYMENT leg (vocabulary §2.6), built from a real remittance advice.

Source document: Pothys Retail Private Ltd → Bata India Limited, clearing date
31/07/2026, UTR AXISCN1422960051. Every figure below is that document's.

Note the direction: here Bata is the *payee*, so this exercises the receivable
side. The type is payer/payee rather than vendor/buyer precisely so one shape
serves both.
"""
from datetime import date
from decimal import Decimal as D

from backend_ocr.app.recon.engine import HeaderChecks
from backend_ocr.app.recon.types import (
    ExtractedInvoice, ExtractedPaymentAdvice, PaymentAdviceLine, ReconInput, RuleConfig,
)


def _advice(**kw) -> ExtractedPaymentAdvice:
    base = dict(
        payer_name="Pothys Retail Private Ltd", payer_gstin="33AALCP2218B1ZX",
        payee_name="BATA INDIA LIMITED", payee_gstin="27AABCB1043Q1ZM",
        payment_date=date(2026, 7, 31), clearing_date=date(2026, 7, 31),
        utr_no="AXISCN1422960051", payment_doc_no="2620098349", cheque_no=None,
        profit_center="CHR-LF-PC", segment_name="Chrompet", run_id="CHY00",
        total_base=D("101327.07"), total_tds=D("97.00"), total_net=D("101230.07"),
        lines=[PaymentAdviceLine(
            reference="SL8069260000321", document_date=date(2026, 6, 26),
            document_type="Vendor Invoice", credit_debit="Credit",
            base_amount=D("101327.07"), tds_amount=D("97.00"), net_amount=D("101230.07"))],
    )
    base.update(kw)
    return ExtractedPaymentAdvice(**base)


def _checks(advice=None, invoice=None, **cfg):
    inp = ReconInput(invoice=invoice, po=None, payment=advice, config=RuleConfig(**cfg))
    return {c.code: c for c in HeaderChecks(inp).run()}


# ── the document reads correctly ──────────────────────────────────────────────

def test_the_real_advice_is_internally_consistent():
    a = _advice()
    line = a.lines[0]
    assert line.base_amount - line.tds_amount == line.net_amount == D("101230.07")
    assert a.total_net == D("101230.07")


def test_references_are_exposed_for_matching():
    assert _advice().references == ["SL8069260000321"]


def test_tds_is_recorded_not_assumed():
    """₹97 on ₹1,01,327.07 is ~0.096% — not a standard 194C rate.

    The engine records what the document says and does not try to re-derive the
    rate: a wrong assumption here would manufacture a discrepancy on every
    advice where TDS was computed on a different base.
    """
    a = _advice()
    assert a.total_tds == D("97.00")


# ── payment_arithmetic ────────────────────────────────────────────────────────

def test_arithmetic_passes_on_the_real_document():
    assert _checks(_advice())["payment_arithmetic"].passed


def test_arithmetic_fails_when_net_disagrees_with_base_minus_tds():
    bad = _advice(lines=[PaymentAdviceLine(
        reference="SL8069260000321", base_amount=D("101327.07"), tds_amount=D("97.00"),
        net_amount=D("101300.00"))])
    c = _checks(bad)["payment_arithmetic"]
    assert not c.passed
    assert "SL8069260000321" in c.detail


def test_no_advice_means_no_payment_checks_at_all():
    """Absent PAYMENT leg must not look like a passed one."""
    out = _checks(None, ExtractedInvoice(invoice_no="SL8069260000321"))
    assert "payment_arithmetic" not in out
    assert "payment_reference" not in out


# ── payment_reference ─────────────────────────────────────────────────────────

def test_advice_naming_the_invoice_passes():
    inv = ExtractedInvoice(invoice_no="SL8069260000321", total=D("101327.07"))
    assert _checks(_advice(), inv)["payment_reference"].passed


def test_advice_for_a_different_invoice_is_flagged():
    inv = ExtractedInvoice(invoice_no="AMP/26-27/070", total=D("101327.07"))
    c = _checks(_advice(), inv)["payment_reference"]
    assert not c.passed
    assert "SL8069260000321" in c.detail


def test_reference_match_tolerates_the_payers_own_prefixing():
    """The payer quotes their ERP document number, which often embeds ours."""
    inv = ExtractedInvoice(invoice_no="8069260000321", total=D("101327.07"))
    assert _checks(_advice(), inv)["payment_reference"].passed


# ── payment_settled_in_full ───────────────────────────────────────────────────

def test_full_settlement_passes():
    inv = ExtractedInvoice(invoice_no="SL8069260000321", total=D("101327.07"))
    assert _checks(_advice(), inv)["payment_settled_in_full"].passed


def test_short_settlement_is_reported_with_the_gap():
    inv = ExtractedInvoice(invoice_no="SL8069260000321", total=D("111327.07"))
    c = _checks(_advice(), inv)["payment_settled_in_full"]
    assert not c.passed
    assert c.evidence["difference"] == "10000.00"
    assert "short by" in c.detail


def test_settlement_compares_the_base_not_the_net():
    """TDS is withheld, not unpaid.

    Comparing the invoice to the net amount would flag every TDS deduction as a
    short payment — which is the most common false exception in this leg.
    """
    inv = ExtractedInvoice(invoice_no="SL8069260000321", total=D("101327.07"))
    c = _checks(_advice(), inv)["payment_settled_in_full"]
    assert c.passed, "₹97 of TDS must not read as a shortfall"
    assert c.evidence["tds"] == "97.00"
