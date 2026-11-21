"""Numbers as they appear on Indian invoices and audit sheets."""
from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

ZERO = Decimal("0")
_CURRENCY = re.compile(r"(₹|\bRs\.?|\bINR\b|/-)", re.I)
_ARITH = re.compile(r"=\s*(-?[\d.,]+)\s*$")


def D(v) -> Decimal:
    """Decimal from int/str/Decimal; floats go through str to avoid binary noise."""
    if isinstance(v, Decimal):
        return v
    if isinstance(v, float):
        return Decimal(repr(v))
    return Decimal(str(v))


def parse_inr(s) -> Decimal | None:
    """'1,26,312.00' → 126312.00; '₹ 11,28,945.59' → …; '(500)' → -500.

    Returns None — never 0 — for anything unreadable: '####', '-', '', 'n/a'.
    A cell like '348+102=450' resolves to the number after '='.
    """
    if s is None:
        return None
    if isinstance(s, (int, Decimal)):
        return D(s)
    if isinstance(s, float):
        return D(s)
    t = str(s).strip()
    if not t or "#" in t or t.lower() in {"-", "–", "—", "~", "n/a", "na", "nil"}:
        return None
    m = _ARITH.search(t)
    if m:
        t = m.group(1)
    t = _CURRENCY.sub("", t).strip()
    neg = t.startswith("(") and t.endswith(")")
    t = t.strip("()").replace(",", "").replace(" ", "")
    if t.endswith("-") and len(t) > 1:          # '1,000-' style trailing dash
        t = t[:-1]
    try:
        v = Decimal(t)
    except InvalidOperation:
        return None
    if not v.is_finite():
        return None
    return -v if neg else v


def round2(v: Decimal) -> Decimal:
    return v.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def close(a: Decimal | None, b: Decimal | None, abs_tol: Decimal = Decimal("0.5"),
          rel_tol: Decimal = Decimal("0.001")) -> bool:
    """Equal within an absolute OR relative tolerance."""
    if a is None or b is None:
        return False
    diff = abs(a - b)
    if diff <= abs_tol:
        return True
    base = max(abs(a), abs(b))
    return base > 0 and diff / base <= rel_tol


def fmt_inr(v: Decimal | None) -> str:
    """Indian grouping: 1234567.5 → '12,34,567.50'."""
    if v is None:
        return "—"
    v = round2(v)
    sign = "-" if v < 0 else ""
    whole, frac = f"{abs(v):.2f}".split(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        whole = ",".join(groups + [tail])
    return f"{sign}{whole}.{frac}"
