"""Invoice lines that are subtotals of other lines on the same invoice.

Some vendors bill in two levels. `IS-HO-26-27-120` opens with

    1  Supply Installation of HVAC Work                    4,66,769.65
    2  Supply & Installation of Sprinkler & FAS System     2,82,401.14
    3  2 Way mixing Valve make Siemens Honeywell              37,760.00
    4  Supply & Installation of 22 Gauge Duct                 12,770.55
    …                                                    (to line 38)

Lines 3–38 come to exactly ₹7,49,170.79 — the same as lines 1 and 2 together,
and the same as the invoice's own total. Lines 1 and 2 are **section headings
carrying a subtotal**; the work is charged once, underneath. Added up naively
the bill reads ₹14,98,341.58 against a total of ₹7,49,171: every rupee counted
twice, and all of it landing in "billed above what is supported".

A subtotal line is unmatchable as well as uncountable. "Supply Installation of
HVAC Work" is not an item any purchase order lists, so it sits unmatched
forever, holding a case's confidence down for a reason no reviewer can act on.

**Two things this deliberately does not do.**

It does not read the words. Nothing keys on "supply", "installation" or
"work" — vendors write what they like, and a rule built on one vendor's
vocabulary breaks on the next. The test is arithmetic.

It does not guess which heading a given detail line belongs to. On this
invoice the details are listed alphabetically across both sections, so there is
no contiguous run under either heading and any attribution would be invented.
Knowing the headings are duplicates is what stops the double count; knowing
which section each line sits in is a nicety, and it is reported only where the
lines really do fall in order (`attribute`).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from .num import ZERO

#: Two lines summing to a third is a coincidence to worry about; several is
#: not. A heading set must cover at least this many detail lines.
MIN_DETAILS = 3

#: Rounding on a printed invoice, not room for disagreement.
TOL = Decimal("1.00")

#: A bill has sections, not forty of them.
MAX_HEADINGS = 8


@dataclass(frozen=True)
class Rollups:
    """The heading lines on an invoice, and what makes us sure of them."""
    headings: tuple[int, ...]              # indices into the line list
    subtotal: Decimal                      # what the headings add up to
    detail: Decimal                        # what everything else adds up to
    #: index → heading index, only where the sections are printed in runs.
    belongs_to: dict[int, int] = field(default_factory=dict)

    def __bool__(self) -> bool:
        return bool(self.headings)


NONE = Rollups(headings=(), subtotal=ZERO, detail=ZERO)


def find(amounts: list[Decimal | None], *, invoice_total: Decimal | None,
         tol: Decimal = TOL, min_details: int = MIN_DETAILS) -> Rollups:
    """Which leading lines are subtotals of the rest.

    Requires **both** halves of the evidence, and reports nothing without them:

    1. the candidate headings add up to everything below them, and
    2. everything below them adds up to the invoice's own total.

    The second is what separates a duplicated bill from a coincidence. Without
    a stated total there is nothing to corroborate against, so it declines —
    dropping a line that was a real charge understates an invoice, and an
    understated invoice is the error nobody downstream catches.
    """
    if invoice_total is None:
        return NONE
    vals = [None if a is None else Decimal(str(a)) for a in amounts]
    n = len(vals)
    total = Decimal(str(invoice_total))

    for k in range(1, min(MAX_HEADINGS, n - min_details) + 1):
        heads = vals[:k]
        if any(a is None or a <= ZERO for a in heads):
            break
        rest = [a for a in vals[k:] if a is not None]
        if len(rest) < min_details:
            break
        head_sum, rest_sum = sum(heads, ZERO), sum(rest, ZERO)
        if abs(head_sum - rest_sum) > tol:
            continue
        if abs(rest_sum - total) > tol:
            # They balance each other but not the invoice: this is some other
            # structure, and we do not understand it well enough to act.
            continue
        return Rollups(headings=tuple(range(k)), subtotal=head_sum, detail=rest_sum,
                       belongs_to=attribute(vals, k, tol))
    return NONE


def attribute(vals: list[Decimal | None], k: int, tol: Decimal = TOL) -> dict[int, int]:
    """Which heading each detail belongs to — only when they are printed in runs.

    Walks the details in order, cutting a section each time the running total
    reaches that heading's figure. If the cuts do not come out exactly, the
    sections are interleaved (as they are on the real invoice, which lists
    every detail alphabetically across both sections) and this returns nothing
    rather than a plausible-looking guess.
    """
    out: dict[int, int] = {}
    pos, run, head = k, ZERO, 0
    for j in range(k, len(vals)):
        if vals[j] is None:
            continue
        if head >= k:
            return {}
        run += vals[j]
        out[j] = head
        if abs(run - vals[head]) <= tol:
            head += 1
            run = ZERO
        elif run > vals[head] + tol:
            return {}
    return out if head == k and run == ZERO else {}
