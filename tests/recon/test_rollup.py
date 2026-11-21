"""Section headings that carry the subtotal of the lines beneath them.

The real case: `IS-HO-26-27-120` opens with two headings worth ₹7,49,170.79
and then lists thirty-six lines that come to exactly the same. Counted
naively the invoice reads twice its own total, and the whole of it is reported
as billed above support.

These tests are mostly about the detector REFUSING. Dropping a line that was a
genuine charge understates an invoice, and an understated invoice is the one
error nobody downstream catches.
"""
from __future__ import annotations

from decimal import Decimal as D

from backend_ocr.app.recon import rollup


def amounts(*xs):
    return [None if x is None else D(str(x)) for x in xs]


# ── the real invoice ───────────────────────────────────────────────────────

REAL_HEADS = [466769.65, 282401.14]
REAL_TOTAL = D("749170.79")
# The first eighteen detail lines, as printed. The last stands for the
# remaining eighteen and is computed, not guessed, so the fixture balances to
# the paisa the way the real invoice does.
_PRINTED = [37760.00, 12770.55, 32709.60, 159300.00, 4602.00, 5310.00, 13806.00,
            8850.00, 14868.00, 2596.00, 35423.60, 4425.00, 2548.80, 14750.00,
            11800.00, 10620.00, 27193.10, 12390.00]
REAL_DETAIL = [*_PRINTED, float(REAL_TOTAL - sum(D(str(x)) for x in _PRINTED))]


def test_the_real_invoice_is_recognised():
    a = amounts(*REAL_HEADS, *REAL_DETAIL)
    r = rollup.find(a, invoice_total=REAL_TOTAL)
    assert r.headings == (0, 1)
    assert r.subtotal == D("749170.79") and r.detail == D("749170.79")


def test_the_detail_lines_alone_are_what_is_billed():
    a = amounts(*REAL_HEADS, *REAL_DETAIL)
    r = rollup.find(a, invoice_total=REAL_TOTAL)
    billed = sum(x for i, x in enumerate(a) if i not in r.headings)
    assert billed == REAL_TOTAL, "counting the headings too would bill ₹14,98,341.58"


def test_interleaved_sections_are_not_attributed():
    """The real invoice lists every detail alphabetically across both sections.

    There is no contiguous run under either heading, so saying which section a
    line belongs to would be invention. Reported as nothing, not as a guess.
    """
    r = rollup.find(amounts(*REAL_HEADS, *REAL_DETAIL), invoice_total=REAL_TOTAL)
    assert r.belongs_to == {}


def test_sections_printed_in_runs_are_attributed():
    a = amounts(100, 50, 60, 40, 20, 30)          # 100 = 60+40, 50 = 20+30
    r = rollup.find(a, invoice_total=D("150"))
    assert r.headings == (0, 1)
    assert r.belongs_to == {2: 0, 3: 0, 4: 1, 5: 1}


# ── everything it must refuse ──────────────────────────────────────────────

def test_without_a_stated_total_it_declines():
    """Nothing to corroborate against. Two halves that balance each other
    could as easily be an invoice that happens to be symmetrical."""
    assert not rollup.find(amounts(100, 60, 40), invoice_total=None)


def test_halves_that_balance_but_do_not_match_the_total_are_left_alone():
    """Some other structure we do not understand. Acting on it would delete a
    real charge."""
    assert not rollup.find(amounts(100, 60, 40), invoice_total=D("200"))


def test_an_ordinary_invoice_is_untouched():
    a = amounts(1000, 2000, 3000, 4000)
    assert not rollup.find(a, invoice_total=D("10000"))


def test_too_few_details_to_be_a_section():
    """One line equal to the next is a coincidence, not a heading."""
    assert not rollup.find(amounts(100, 100), invoice_total=D("100"))
    assert not rollup.find(amounts(100, 60, 40), invoice_total=D("100"), min_details=3)


def test_a_heading_cannot_be_zero_or_negative():
    assert not rollup.find(amounts(0, 10, 20, 30), invoice_total=D("60"))


def test_rounding_on_a_printed_invoice_is_tolerated():
    r = rollup.find(amounts(100, 33.33, 33.33, 33.34), invoice_total=D("100"))
    assert r.headings == (0,)


def test_a_rupee_out_is_tolerated_but_a_hundred_is_not():
    assert rollup.find(amounts(100, 40, 30, 30.60), invoice_total=D("100.60"))
    assert not rollup.find(amounts(100, 40, 30, 130), invoice_total=D("200"))


def test_it_gives_up_rather_than_reading_half_an_invoice():
    """A partial match means the reading is wrong, and a wrong reading here
    removes a charge somebody is owed."""
    # Heads 100+50 = 150, but the rest comes to 140: no clean split.
    assert not rollup.find(amounts(100, 50, 60, 40, 40), invoice_total=D("140"))


def test_the_number_of_sections_is_bounded():
    """A bill has sections; it does not have forty."""
    a = amounts(*[1] * 40, *[40])
    assert not rollup.find(a, invoice_total=D("40"))
