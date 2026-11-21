"""Cash application engine — one test (or more) per edge case in
docs/receivables/04_EDGE_CASES.md. Pure: no database, no LLM."""
from __future__ import annotations

from datetime import date
from decimal import Decimal as D

import pytest

from backend_ocr.app.receivables.matching import (
    Customer, MatchConfig, OpenInvoice, Payment, RemittanceLine,
    invoice_referenced, match_payment, norm_name, resolve_number, token_windows,
)
from backend_ocr.app.receivables.policy import Policy, decide

ACME = Customer("c1", "Acme Trading Pvt Ltd", aliases=["ACME TRADING"])
BETA = Customer("c2", "Beta Retail LLP")


def inv(i, num, cust="c1", out="118000", total=None, taxable="100000", due=None, d=None, po=None,
        untouched=True, status="open", cur="INR"):
    return OpenInvoice(i, num, cust, D(out), D(total or out), D(taxable) if taxable else None,
                       invoice_date=d, due_date=due, po_number=po, untouched=untouched,
                       status=status, currency=cur)


def pay(amount, payer=None, narration=None, ref=None, on=date(2026, 11, 15), cust=None):
    return Payment(D(amount), on, payer, narration, ref, cust)


def run(p, invoices, customers=(ACME, BETA), **kw):
    r = match_payment(p, list(customers), invoices, **kw)
    return r, decide(r, Policy(), customer_tds_hint=next(
        (c.tds_rate_hint for c in customers if c.id == r.customer_id), None))


# ── helpers ────────────────────────────────────────────────────────────────────

def test_norm_name_strips_legal_suffixes():
    assert norm_name("M/s. Acme Trading Pvt. Ltd.") == "ACME TRADING"


def test_token_windows_rebuild_split_numbers():
    assert "INV24250045" in token_windows("NEFT/INV 24-25 0045/ACME")


def test_short_numeric_invoice_not_found_inside_utr():               # C11
    assert not invoice_referenced("1045", "NEFT-HDFCN52026110451234-ACME")
    assert invoice_referenced("1045", "NEFT-HDFCN520261199-ACME-INV 1045")


@pytest.mark.parametrize("quoted,expect", [("1045", "INV/24-25/1045"), ("INV/24-25/1054", "INV/24-25/1045")])
def test_resolve_number_suffix_and_typo(quoted, expect):                # C5
    pool = [inv("i1", "INV/24-25/1045"), inv("i2", "INV/24-25/2001")]
    got, how = resolve_number(quoted, pool)
    assert got and got.number == expect and how


# ── A. amount vs invoice ──────────────────────────────────────────────────────

def test_A1_exact_with_reference_auto():
    r, d = run(pay("118000", "ACME TRADING", "NEFT-HDFCN520261115-ACME TRADING-INV 1045"),
               [inv("i1", "INV-1045"), inv("i2", "INV-1046")])
    assert r.best.kind == "reference_exact" and d.action == "AUTO"


def test_A2_exact_amount_known_customer_auto():
    r, d = run(pay("59000", "ACME TRADING"), [inv("i1", "1045"), inv("i2", "1046", out="59000", taxable="50000")])
    assert r.best.kind == "amount_exact" and r.best.allocations[0].invoice_id == "i2"
    assert d.action == "AUTO"


def test_A3_partial_payment_goes_to_review():
    r, d = run(pay("50000", "ACME TRADING", "INV 1045"), [inv("i1", "1045")])
    assert r.best.kind == "reference_partial"
    assert r.best.allocations[0].amount_applied == D("50000")
    assert d.action == "REVIEW"


def test_A4_tds_not_inferred_on_part_paid_invoice():
    # 68,000 left; 66,000 would be "TDS" only if the invoice were untouched.
    r, _ = run(pay("66000", "ACME TRADING"), [inv("i1", "1045", out="68000", total="118000", untouched=False)])
    assert all(a.tds_amount == 0 for a in r.best.allocations)


def test_A4_last_instalment_exact_auto():
    r, d = run(pay("68000", "ACME TRADING", "INV 1045"),
               [inv("i1", "1045", out="68000", total="118000", untouched=False)])
    assert r.best.kind == "reference_exact" and d.action == "AUTO"


def test_A5_remittance_exact_auto():
    r, d = run(pay("177000", "ACME TRADING"), [inv("i1", "1045"), inv("i2", "1046", out="59000")],
               remittance=[RemittanceLine("1045", D("118000")), RemittanceLine("1046", D("59000"))])
    assert r.best.kind == "remittance" and len(r.best.allocations) == 2 and d.action == "AUTO"


def test_A6_oldest_first_review():
    invs = [inv("i1", "1", out="10000", due=date(2026, 9, 1)), inv("i2", "2", out="20000", due=date(2026, 10, 1)),
            inv("i3", "3", out="40000", due=date(2026, 11, 1))]
    r, d = run(pay("30000", "ACME TRADING"), invs)
    assert r.best.kind == "oldest_first" and {a.invoice_id for a in r.best.allocations} == {"i1", "i2"}
    assert d.action == "REVIEW"


def test_A7_combination_review():
    invs = [inv("i1", "1", out="10000", due=date(2026, 9, 1)), inv("i2", "2", out="25000", due=date(2026, 10, 1)),
            inv("i3", "3", out="40000", due=date(2026, 11, 1))]
    r, d = run(pay("50000", "ACME TRADING"), invs)
    assert r.best.kind == "combination" and {a.invoice_id for a in r.best.allocations} == {"i1", "i3"}
    assert d.action == "REVIEW"


def test_A8_two_equal_invoices_ambiguous():
    invs = [inv("i1", "1", out="59000", due=date(2026, 9, 1)), inv("i2", "2", out="59000", due=date(2026, 10, 1))]
    r, d = run(pay("59000", "ACME TRADING"), invs)
    assert r.best.kind == "amount_exact_ambiguous" and r.best.allocations[0].invoice_id == "i1"
    assert d.action == "REVIEW"


def test_A9_overpayment_leaves_credit():
    r, d = run(pay("120000", "ACME TRADING", "INV 1045"), [inv("i1", "1045")])
    assert r.best.kind == "reference_overpaid" and r.best.unapplied == D("2000") and d.action == "REVIEW"


def test_A10_more_than_owed():
    r, _ = run(pay("500000", "ACME TRADING"), [inv("i1", "1045")])
    assert r.best.kind == "overpaid" and r.best.unapplied == D("382000")


def test_A11_rounding_absorbed():
    r, d = run(pay("117999.50", "ACME TRADING", "INV 1045"), [inv("i1", "1045")])
    assert r.best.kind == "reference_exact" and r.best.allocations[0].amount_applied == D("117999.50")
    assert d.action == "AUTO"


# ── B. deductions ──────────────────────────────────────────────────────────────

def test_B1_tds_on_taxable_value():
    r, d = run(pay("116000", "ACME TRADING"), [inv("i1", "1045")])
    a = r.best.allocations[0]
    assert r.best.kind == "amount_tds" and a.tds_amount == D("2000") and a.tds_rate == D("2")
    assert d.action == "REVIEW"


def test_B1_tds_auto_when_trusted_rate_and_invoice_quoted():
    acme = Customer("c1", "Acme Trading Pvt Ltd", aliases=["ACME TRADING"], tds_rate_hint=D("2"))
    r = match_payment(pay("116000", "ACME TRADING", "INV 1045"), [acme], [inv("i1", "1045")])
    assert r.best.kind == "reference_tds"
    assert decide(r, Policy(trust_learned_tds=True), customer_tds_hint=D("2")).action == "AUTO"
    assert decide(r, Policy(), customer_tds_hint=D("2")).action == "REVIEW"


def test_B2_tds_on_gross_flagged():
    # 2% of 118,000 = 2,360 → 115,640
    r, d = run(pay("115640", "ACME TRADING"), [inv("i1", "1045")])
    assert r.best.kind == "amount_tds" and "TDS_ON_GROSS" in r.flags and d.action == "REVIEW"


def test_B4_tds_across_combination():
    invs = [inv("i1", "1", out="118000", taxable="100000", due=date(2026, 9, 1)),
            inv("i2", "2", out="59000", taxable="50000", due=date(2026, 10, 1)),
            inv("i3", "3", out="5000", taxable="4237", due=date(2026, 11, 1))]
    r, _ = run(pay("174000", "ACME TRADING"), invs)   # (118000-2000)+(59000-1000)
    assert r.best.kind == "combination"
    assert sum(a.tds_amount for a in r.best.allocations) == D("3000")


def test_B6_remittance_deduction_reason_coded():
    r, d = run(pay("110000", "ACME TRADING"), [inv("i1", "1045")],
               remittance=[RemittanceLine("1045", D("110000"), D("8000"), "damaged goods")])
    a = r.best.allocations[0]
    assert a.deduction_amount == D("8000") and a.reason_code == "DAMAGE" and d.action == "REVIEW"


def test_B8_debit_note_set_off():
    r, d = run(pay("113000", "ACME TRADING"), [inv("i1", "1045")],
               remittance=[RemittanceLine("1045", D("118000")), RemittanceLine("DN-77", D("-5000"))])
    a = r.best.allocations[0]
    assert a.amount_applied == D("113000") and a.deduction_amount == D("5000") and d.action == "REVIEW"


# ── C. missing / bad information ──────────────────────────────────────────────

def test_C1_unknown_payer_amount_only_never_auto():
    r, d = run(pay("59000", None, "BY CLG 004512"), [inv("i1", "1045", out="59000")])
    assert r.best.kind == "amount_only" and d.action == "REVIEW"


def test_C1_nothing_fits_unmatched():
    r, d = run(pay("12345", None, "BY CLG 004512"), [inv("i1", "1045")])
    assert r.best is None and d.action == "UNMATCHED"


def test_C5_remittance_typo_resolved_but_reviewed():
    r, d = run(pay("118000", "ACME TRADING"), [inv("i1", "INV/24-25/1045")],
               remittance=[RemittanceLine("1045", D("118000"))])
    # The remittance number needed reading as a typo, so the remittance on its own
    # would be reviewed; here the amount is also this customer's only exact open
    # invoice, which is an exact match in its own right.
    assert r.best.allocations[0].invoice_id == "i1" and d.action == "AUTO"


def test_C5_remittance_typo_alone_is_reviewed():
    invs = [inv("i1", "INV/24-25/1045"), inv("i2", "INV/24-25/2001")]   # same amount → amount is ambiguous
    r, d = run(pay("118000", "ACME TRADING"), invs, remittance=[RemittanceLine("1045", D("118000"))])
    assert r.best.kind == "remittance_adjusted" and r.best.allocations[0].invoice_id == "i1"
    assert d.action == "REVIEW"


def test_C6_remittance_short_of_payment():
    r, _ = run(pay("150000", "ACME TRADING"), [inv("i1", "1045")],
               remittance=[RemittanceLine("1045", D("118000"))])
    assert r.best.kind in ("remittance_partial", "overpaid") and r.best.unapplied == D("32000")


def test_C9_wrong_invoice_quoted_conflict():
    invs = [inv("i1", "1045", out="118000"), inv("i2", "1054", out="59000")]
    r, d = run(pay("59000", "ACME TRADING", "INV 1045"), invs)
    assert "CLUE_CONFLICT" in r.flags and d.action == "REVIEW"


def test_C10_po_number_quoted():
    r, d = run(pay("118000", None, "RTGS/UTIBR520261115/PO 4500012345"),
               [inv("i1", "1045", po="4500012345")])
    assert r.best.kind == "reference_exact" and r.customer_id == "c1"


# ── D. who paid ─────────────────────────────────────────────────────────────────

def test_D1_truncated_payer_fuzzy_review():
    acme = Customer("c1", "Acme Trading Pvt Ltd")
    r = match_payment(pay("59000", "ACME TRADIN"), [acme, BETA], [inv("i1", "1", out="59000")])
    assert r.customer_id == "c1" and r.best.confidence < D("0.95")
    assert decide(r, Policy()).action == "REVIEW"


def test_D3_alias_shared_by_two_customers():
    a = Customer("c1", "Acme Trading", aliases=["XYZ GROUP"])
    b = Customer("c2", "Acme Retail", aliases=["XYZ GROUP"])
    r = match_payment(pay("59000", "XYZ GROUP"), [a, b], [inv("i1", "1", out="59000")])
    assert "AMBIGUOUS_PAYER" in r.flags and decide(r, Policy()).action == "REVIEW"


def test_D4_cross_customer_payment_flagged():
    invs = [inv("i1", "A-1045", cust="c1", out="10000"), inv("i2", "B-2001", cust="c2", out="20000")]
    r, d = run(pay("30000", None, "NEFT/A-1045 B-2001"), invs)
    assert "CROSS_CUSTOMER" in r.flags and d.action == "REVIEW"


def test_D7_same_number_two_customers_disambiguated():
    invs = [inv("i1", "1045", cust="c1", out="118000"), inv("i2", "1045", cust="c2", out="59000")]
    r, _ = run(pay("118000", "ACME TRADING", "INV 1045"), invs)
    assert r.best.allocations[0].invoice_id == "i1"


# ── E / F. duplicates, invoice state ─────────────────────────────────────────

def test_E1_already_paid_invoice_quoted_again():
    paid = [inv("p1", "1045", out="0", total="118000")]
    r, d = run(pay("118000", "ACME TRADING", "INV 1045"), [inv("i2", "1046", out="59000")], paid_invoices=paid)
    assert "POSSIBLE_DUPLICATE" in r.flags and d.action != "AUTO"


def test_E1_recurring_amount_is_not_a_duplicate():
    paid = [inv("p1", "OCT-RET", out="0", total="50000", taxable="42372.88")]
    r, d = run(pay("50000", "ACME TRADING"), [inv("i1", "NOV-RET", out="50000", taxable="42372.88")],
               paid_invoices=paid)
    assert "POSSIBLE_DUPLICATE" not in r.flags and d.action == "AUTO"


def test_F1_disputed_invoice_flagged():
    r, d = run(pay("118000", "ACME TRADING", "INV 1045"), [inv("i1", "1045", status="disputed")])
    assert "DISPUTED_INVOICE" in r.flags and d.action == "REVIEW"


def test_F3_payment_before_invoice_date():
    r, d = run(pay("118000", "ACME TRADING", "INV 1045", on=date(2026, 11, 1)),
               [inv("i1", "1045", d=date(2026, 11, 10))])
    assert "ADVANCE" in r.flags and d.action == "REVIEW"


def test_F5_foreign_currency_flagged():
    r, _ = run(pay("118000", "ACME TRADING", "INV 1045"), [inv("i1", "1045", cur="USD")])
    assert "FOREIGN_CURRENCY" in r.flags


# ── G. scale ────────────────────────────────────────────────────────────────────

def test_G6_large_customer_is_bounded():
    import time
    invs = [inv(f"i{n}", f"{n:05d}", out=str(1000 + n * 7), taxable=None, due=date(2026, 1, 1 + n % 28))
            for n in range(3000)]
    t = time.perf_counter()
    match_payment(pay("987654.32", "ACME TRADING"), [ACME], invs, cfg=MatchConfig())
    assert time.perf_counter() - t < 2.0


def test_policy_auto_switch_off():
    r = match_payment(pay("118000", "ACME TRADING", "INV 1045"), [ACME], [inv("i1", "1045")])
    assert decide(r, Policy(auto_apply_enabled=False)).action == "REVIEW"


def test_payer_name_matches_ignoring_spaces():
    c = Customer("e", "Avenue E-Commerce Limited", aliases=["Avenue E-Commerce Limited"])
    r = match_payment(pay("50240", "AVENUE ECOMMERCE LTD"), [c], [inv("i1", "SL1", cust="e", out="50240")])
    assert r.customer_how == "known payer name" and decide(r, Policy()).action == "AUTO"
