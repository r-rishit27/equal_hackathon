"""The cash application matcher: one incoming payment → the invoices it pays.

Pure functions over plain dataclasses — no database, no LLM — so every rule is
unit-testable and every suggestion explains itself. Design:
docs/receivables/02_LLD.md §6, edge cases: docs/receivables/04_EDGE_CASES.md.

1. **Who paid** — chosen customer → confirmed payer alias → quoted invoice/PO
   numbers → remittance → fuzzy payer name. An alias shared by several customers
   is AMBIGUOUS_PAYER and never auto-applies.
2. **What it pays** — candidates from: remittance lines; invoice / PO numbers
   quoted in the narration; the customer's open invoices (exact, net of TDS,
   oldest-first, any 2–4 combination, partial, overpaid); an amount-only search
   when the payer is unknown. Each carries a confidence and its clues.
3. **Flags** — conflicting clues, duplicates, advances, cross-customer and
   foreign-currency payments are flagged; any flag forces review (policy.py).

TDS (India): customers deduct TDS before paying, on the pre-GST taxable value
(CBDT circular 23/2017), so the receipt is `total − rate × taxable`. The engine
also recognises TDS wrongly taken on the GST-inclusive total (flag TDS_ON_GROSS).
TDS is never inferred on an invoice that has already been part-paid.
"""
from __future__ import annotations

import itertools
import re
from dataclasses import dataclass, field, asdict
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

ZERO = Decimal("0")
CENT = Decimal("0.01")
MAX_COMBO_INVOICES = 20
MAX_COMBO_SIZE = 4
MAX_COMBOS_REPORTED = 5
DEFAULT_TDS_RATES = (Decimal("0.1"), Decimal("1"), Decimal("2"), Decimal("5"), Decimal("10"))


def inr(v) -> str:
    """₹ with Indian digit grouping, for the reasons a person reads: 157350 → ₹1,57,350.00."""
    d = money(v)
    sign, d = ("−" if d < 0 else ""), abs(d)
    whole, frac = f"{d:.2f}".split(".")
    head, tail = whole[:-3], whole[-3:]
    while len(head) > 2:
        tail = head[-2:] + "," + tail
        head = head[:-2]
    return f"{sign}₹{head + ',' if head else ''}{tail}.{frac}"


def money(v) -> Decimal:
    if v is None or v == "":
        return ZERO
    return Decimal(str(v)).quantize(CENT, rounding=ROUND_HALF_UP)


# ── Inputs ────────────────────────────────────────────────────────────────────

@dataclass
class MatchConfig:
    tolerance: Decimal = Decimal("1.00")          # rupees of rounding, per invoice
    tds_rates: tuple[Decimal, ...] = DEFAULT_TDS_RATES


@dataclass
class Customer:
    id: str
    name: str
    aliases: list[str] = field(default_factory=list)
    tds_rate_hint: Decimal | None = None
    pan: str | None = None


@dataclass
class OpenInvoice:
    id: str
    number: str
    customer_id: str
    outstanding: Decimal
    total: Decimal
    taxable: Decimal | None = None
    invoice_date: date | None = None
    due_date: date | None = None
    po_number: str | None = None
    currency: str = "INR"
    status: str = "open"
    # True while nothing has been received or deducted: TDS is only taken off a
    # fresh invoice, never off the balance of a part-paid one.
    untouched: bool = True


@dataclass
class Payment:
    amount: Decimal
    received_on: date | None = None
    payer_name: str | None = None
    narration: str | None = None
    reference: str | None = None
    customer_id: str | None = None


@dataclass
class RemittanceLine:
    invoice_number: str
    amount_paid: Decimal
    deduction_amount: Decimal = ZERO
    deduction_reason: str | None = None


# ── Output ────────────────────────────────────────────────────────────────────

@dataclass
class Allocation:
    invoice_id: str
    invoice_number: str
    amount_applied: Decimal
    tds_amount: Decimal = ZERO
    deduction_amount: Decimal = ZERO
    reason_code: str | None = None
    reason_note: str | None = None
    tds_rate: Decimal | None = None


@dataclass
class Suggestion:
    kind: str
    confidence: Decimal
    customer_id: str | None
    allocations: list[Allocation]
    clues: list[str]
    unapplied: Decimal = ZERO

    def to_json(self) -> dict:
        return _jsonable(asdict(self))

    def invoice_ids(self) -> frozenset[str]:
        return frozenset(a.invoice_id for a in self.allocations)


def _jsonable(v):
    if isinstance(v, dict):
        return {k: _jsonable(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_jsonable(x) for x in v]
    if isinstance(v, Decimal):
        return str(v)
    if isinstance(v, date):
        return v.isoformat()
    return v


@dataclass
class MatchResult:
    customer_id: str | None
    customer_how: str | None
    best: Suggestion | None
    alternatives: list[Suggestion]
    flags: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_json(self) -> dict:
        return {
            "customer_id": self.customer_id,
            "customer_how": self.customer_how,
            "best": self.best.to_json() if self.best else None,
            "alternatives": [a.to_json() for a in self.alternatives],
            "flags": list(self.flags),
            "notes": list(self.notes),
        }


# ── Text normalisation ───────────────────────────────────────────────────────

_SUFFIXES = re.compile(
    r"\b(M S|MS|THE|PVT|PRIVATE|LTD|LIMITED|LLP|INC|CO|COMPANY|CORP|CORPORATION|INDIA|IND|P)\b")


def norm_name(s: str | None) -> str:
    """'M/s. Acme Trading Pvt. Ltd.' → 'ACME TRADING'."""
    if not s:
        return ""
    s = re.sub(r"[^A-Z0-9 ]", " ", s.upper())
    s = _SUFFIXES.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip()


def norm_ref(s: str | None) -> str:
    """Invoice / PO / reference numbers compared on letters and digits only."""
    return re.sub(r"[^A-Z0-9]", "", (s or "").upper())


def token_windows(text: str | None, max_window: int = 4) -> set[str]:
    """Every run of 1–4 adjacent alphanumeric tokens, joined and normalised.

    Narrations split numbers apart ("INV 24-25 0045"); the windows rebuild them
    ("INV24250045") so they can be looked up by indexed equality on number_norm
    instead of a LIKE scan. Lone tokens shorter than 3 characters are dropped.
    """
    toks = re.findall(r"[A-Z0-9]+", (text or "").upper())
    out: set[str] = set()
    for i in range(len(toks)):
        for w in range(1, max_window + 1):
            if i + w > len(toks):
                break
            joined = "".join(toks[i:i + w])
            if len(joined) >= 3 and len(joined) <= 40:
                out.add(joined)
    return out


def invoice_referenced(number: str, text: str | None) -> bool:
    """Is invoice `number` quoted in free text (a narration, a memo)?

    A short all-digit number ("1045") must stand alone in the raw text, or it
    would match inside every UTR and account number on the line (edge case C11).
    """
    n = norm_ref(number)
    if len(n) < 3 or not text:
        return False
    if n.isdigit() and len(n) < 6:
        return re.search(rf"(?<![0-9A-Za-z]){re.escape(n)}(?![0-9])", text) is not None
    return n in token_windows(text) or (len(n) >= 6 and n in norm_ref(text))


def _edit1(a: str, b: str) -> bool:
    """True when a and b differ by at most one substitution, insertion, deletion or adjacent swap."""
    if a == b:
        return True
    la, lb = len(a), len(b)
    if abs(la - lb) > 1:
        return False
    if la == lb:
        diff = [i for i in range(la) if a[i] != b[i]]
        if len(diff) == 1:
            return True
        return len(diff) == 2 and diff[1] == diff[0] + 1 and a[diff[0]] == b[diff[1]] and a[diff[1]] == b[diff[0]]
    if la > lb:
        a, b = b, a
    i = 0
    while i < len(a) and a[i] == b[i]:
        i += 1
    return a[i:] == b[i + 1:]


def resolve_number(quoted: str, pool: list["OpenInvoice"]) -> tuple["OpenInvoice | None", str | None]:
    """Find the invoice a customer meant by `quoted` (edge case C5).

    Exact on normalised form first; then a unique suffix match ("1045" →
    "INV/24-25/1045"); then a unique one-character slip. Returns (invoice, how).
    """
    q = norm_ref(quoted)
    if not q:
        return None, None
    exact = [i for i in pool if norm_ref(i.number) == q]
    if len(exact) == 1:
        return exact[0], None
    if len(exact) > 1:
        return None, f"'{quoted}' matches {len(exact)} invoices"
    if len(q) >= 3:
        suffix = [i for i in pool if norm_ref(i.number).endswith(q) or q.endswith(norm_ref(i.number))]
        if len(suffix) == 1:
            return suffix[0], f"'{quoted}' read as {suffix[0].number}"
    if len(q) >= 4:
        near = [i for i in pool if _edit1(norm_ref(i.number), q)]
        if len(near) == 1:
            return near[0], f"'{quoted}' looks like a typo for {near[0].number}"
    return None, None


# ── Customer identification ──────────────────────────────────────────────────

def identify_customer(payment: Payment, customers: list[Customer], invoices: list[OpenInvoice]
                      ) -> tuple[str | None, str | None, Decimal, list[str]]:
    """(customer_id, how, confidence, flags) for who sent the money."""
    by_id = {c.id: c for c in customers}
    if payment.customer_id and payment.customer_id in by_id:
        return payment.customer_id, "chosen", Decimal("1"), []

    payer = norm_name(payment.payer_name)
    if payer:
        # Space-insensitive: banks strip punctuation, so "E-Commerce" arrives as
        # "ECOMMERCE" while the invoice reads "E COMMERCE" once normalised.
        squash = payer.replace(" ", "")
        hits = [c for c in customers
                if squash in {norm_name(a).replace(" ", "") for a in [*c.aliases, c.name]}]
        if len(hits) == 1:
            return hits[0].id, "known payer name", Decimal("1"), []
        if len(hits) > 1:
            return None, None, ZERO, ["AMBIGUOUS_PAYER"]

    text = " ".join(filter(None, [payment.narration, payment.reference]))
    quoted = {i.customer_id for i in invoices
              if invoice_referenced(i.number, text) or (i.po_number and invoice_referenced(i.po_number, text))}
    if len(quoted) == 1:
        return quoted.pop(), "invoice / PO number in narration", Decimal("1"), []

    hay = payer or norm_name(payment.narration)
    if hay:
        try:
            from rapidfuzz import fuzz
        except ImportError:   # pragma: no cover — rapidfuzz is in requirements
            return None, None, ZERO, []
        best, score = None, 0.0
        for c in customers:
            for cand in [c.name, *c.aliases]:
                cn = norm_name(cand)
                if len(cn) < 3:
                    continue
                s = fuzz.token_set_ratio(hay, cn) if payer else fuzz.partial_ratio(cn, hay)
                if s > score:
                    best, score = c, s
        if best and score >= 90:
            return best.id, f"payer name resembles {best.name}", Decimal("0.9"), []
        if best and score >= 80:
            return best.id, f"payer name loosely resembles {best.name}", Decimal("0.75"), []
    return None, None, ZERO, []


# ── Candidate builders ───────────────────────────────────────────────────────

class _Ctx:
    def __init__(self, payment: Payment, cfg: MatchConfig, hint: Decimal | None):
        self.p = payment
        self.cfg = cfg
        self.hint = hint

    def close(self, a: Decimal, b: Decimal, n: int = 1) -> bool:
        return abs(a - b) <= self.cfg.tolerance * n

    def rates(self) -> list[Decimal]:
        """TDS rates to try, the customer's usual one first."""
        rates = list(self.cfg.tds_rates)
        if self.hint is not None:
            if self.hint in rates:
                rates.remove(self.hint)
            rates.insert(0, self.hint)
        return rates


def _tds_on(inv: OpenInvoice, rate: Decimal, gross: bool = False) -> Decimal:
    base = inv.total if gross or not inv.taxable else inv.taxable
    return money(base * rate / 100)


def _full(inv: OpenInvoice) -> Allocation:
    return Allocation(inv.id, inv.number, inv.outstanding)


def _net_of_tds(inv: OpenInvoice, rate: Decimal, gross: bool = False) -> Allocation:
    tds = _tds_on(inv, rate, gross)
    base = "on the GST-inclusive total" if gross else ("on taxable value" if inv.taxable else "on the total (no taxable value read)")
    return Allocation(inv.id, inv.number, inv.outstanding - tds, tds_amount=tds, reason_code="TDS",
                      reason_note=f"TDS @ {rate.normalize()}% {base}", tds_rate=rate)


def _fix_rounding(allocs: list[Allocation], amount: Decimal, ctx: _Ctx) -> list[Allocation]:
    """Within tolerance, make the allocations add to the payment exactly; the
    rounding goes into the last line's TDS when it has one, else its amount."""
    diff = amount - sum((a.amount_applied for a in allocs), ZERO)
    if allocs and diff and abs(diff) <= ctx.cfg.tolerance * len(allocs):
        last = allocs[-1]
        last.amount_applied += diff
        if last.tds_amount:
            last.tds_amount = max(ZERO, last.tds_amount - diff)
    return allocs


def _age_key(i: OpenInvoice):
    return (i.due_date or i.invoice_date or date.max, i.number)


def _from_remittance(ctx: _Ctx, lines: list[RemittanceLine], invoices: list[OpenInvoice],
                     customer_id: str | None) -> Suggestion | None:
    pool = [i for i in invoices if i.customer_id == customer_id] if customer_id else invoices
    pool = pool or invoices
    allocs: list[Allocation] = []
    missing, notes, setoff = [], [], ZERO
    setoff_refs: list[str] = []
    for ln in lines:
        paid = money(ln.amount_paid)
        if paid < 0:   # debit / credit note set off by the customer (B8)
            setoff += -paid
            setoff_refs.append(ln.invoice_number)
            continue
        inv, how = resolve_number(ln.invoice_number, pool)
        if not inv:
            missing.append(ln.invoice_number + (f" ({how})" if how else ""))
            continue
        if how:
            notes.append(how)
        ded = money(ln.deduction_amount)
        reason = (ln.deduction_reason or "").strip()
        tds = ZERO
        code = None
        if ded:
            if "TDS" in reason.upper():
                tds, ded, code = ded, ZERO, "TDS"
            else:
                code = _reason_code(reason)
        allocs.append(Allocation(inv.id, inv.number, paid, tds_amount=tds, deduction_amount=ded,
                                 reason_code=code, reason_note=reason or None))
    if not allocs:
        return None
    if setoff:
        # The note reduces what the customer pays on their largest invoice in the advice.
        target = max(allocs, key=lambda a: a.amount_applied)
        target.amount_applied -= setoff
        target.deduction_amount += setoff
        target.reason_code = target.reason_code or "DEBIT_NOTE"
        target.reason_note = f"Set off: {', '.join(setoff_refs)}"
    total = sum((a.amount_applied for a in allocs), ZERO)
    exact = ctx.close(total, ctx.p.amount, len(allocs)) and not missing and not notes and not setoff
    clues = [f"The remittance advice lists {len(lines)} line{'' if len(lines) == 1 else 's'}"] + notes
    if missing:
        clues.append(f"Not found among open invoices: {', '.join(missing)}")
    if setoff:
        clues.append(f"The customer set off {inr(setoff)} against {', '.join(setoff_refs)}")
    clues.append("The remittance accounts for the whole payment" if ctx.close(total, ctx.p.amount, len(allocs))
                 else f"The remittance accounts for {inr(total)} of {inr(ctx.p.amount)}")
    inv_by_id = {i.id: i for i in pool}
    cust = customer_id or inv_by_id[allocs[0].invoice_id].customer_id
    if exact:
        _fix_rounding(allocs, ctx.p.amount, ctx)
    accounts = ctx.close(total, ctx.p.amount, len(allocs)) and not missing
    if exact:
        kind, conf = "remittance", Decimal("1")
    elif accounts:
        # Explains every rupee, but only after reading a typo'd number or a set-off:
        # strong enough to lead, never strong enough to apply alone (policy.AUTO_KINDS).
        _fix_rounding(allocs, ctx.p.amount, ctx)
        kind, conf = "remittance_adjusted", Decimal("0.95")
    else:
        kind, conf = "remittance_partial", Decimal("0.8")
    return Suggestion(kind, conf, cust, allocs, clues, unapplied=max(ZERO, ctx.p.amount - total))


_REASON_WORDS = (
    ("DISCOUNT", ("discount", "cash disc", "early pay")),
    ("BANK_CHARGES", ("bank charge", "bank chg", "wire fee", "commission")),
    ("SHORT_SUPPLY", ("short supply", "short qty", "shortage", "short received")),
    ("DAMAGE", ("damage", "defect", "broken", "rejected")),
    ("RATE_DIFF", ("rate diff", "price diff", "rate difference")),
    ("DEBIT_NOTE", ("debit note", "dn ", "credit note", "cn ")),
    ("FX", ("exchange", "forex", "fx")),
)


def _reason_code(text: str) -> str:
    t = f" {text.lower()} "
    for code, words in _REASON_WORDS:
        if any(w in t for w in words):
            return code
    return "OTHER"


def _from_references(ctx: _Ctx, invoices: list[OpenInvoice]) -> list[Suggestion]:
    text = " ".join(filter(None, [ctx.p.narration, ctx.p.reference]))
    by_inv = [i for i in invoices if invoice_referenced(i.number, text)]
    by_po = [i for i in invoices if i not in by_inv and i.po_number and invoice_referenced(i.po_number, text)]
    refs = by_inv or by_po
    if not refs:
        return []
    custs = {i.customer_id for i in refs}
    cust = refs[0].customer_id if len(custs) == 1 else None
    nums = ", ".join(i.number for i in refs)
    if by_inv:
        clue = f"Invoice number{'s' if len(refs) > 1 else ''} {nums} quoted in the narration"
    else:
        clue = f"PO {refs[0].po_number} quoted in the narration → {nums}"
    owed = sum((i.outstanding for i in refs), ZERO)
    amt = ctx.p.amount
    n = len(refs)
    if ctx.close(owed, amt, n):
        return [Suggestion("reference_exact", Decimal("1"), cust,
                           _fix_rounding([_full(i) for i in refs], amt, ctx),
                           [clue, "Amount equals what those invoices owe"])]
    if all(i.untouched for i in refs):
        for gross in (False, True):
            for r in ctx.rates():
                net = sum((i.outstanding - _tds_on(i, r, gross) for i in refs), ZERO)
                if ctx.close(net, amt, n):
                    why = (f"Amount equals those invoices less {r.normalize()}% TDS "
                           + ("on the GST-inclusive total — TDS should be on the taxable value" if gross
                              else "on the taxable value"))
                    return [Suggestion("reference_tds", Decimal("0.92") if not gross else Decimal("0.8"), cust,
                                       _fix_rounding([_net_of_tds(i, r, gross) for i in refs], amt, ctx),
                                       [clue, why])]
    if amt > owed:
        return [Suggestion("reference_overpaid", Decimal("0.8"), cust, [_full(i) for i in refs],
                           [clue, f"Payment is {inr(amt - owed)} more than they owe — the rest stays on account"],
                           unapplied=amt - owed)]
    # Short: fill the quoted invoices oldest first and leave the remainder open.
    allocs, left = [], amt
    for i in sorted(refs, key=_age_key):
        if left <= 0:
            break
        take = min(left, i.outstanding)
        allocs.append(Allocation(i.id, i.number, take))
        left -= take
    return [Suggestion("reference_partial", Decimal("0.75"), cust, allocs,
                       [clue, f"Payment is {inr(owed - amt)} short of what they owe — a part-payment, or a "
                              "deduction the customer hasn't explained; the balance stays open"])]


def _from_customer(ctx: _Ctx, invoices: list[OpenInvoice], customer_id: str,
                   cust_conf: Decimal) -> list[Suggestion]:
    pool = sorted((i for i in invoices if i.customer_id == customer_id), key=_age_key)
    if not pool:
        return []
    amt = ctx.p.amount
    out: list[Suggestion] = []

    def add(kind, conf, allocs, clues, unapplied=ZERO):
        out.append(Suggestion(kind, (conf * cust_conf).quantize(Decimal("0.001")), customer_id,
                              allocs, clues, unapplied))

    exact = [i for i in pool if ctx.close(i.outstanding, amt)]
    if len(exact) == 1:
        add("amount_exact", Decimal("0.97"), _fix_rounding([_full(exact[0])], amt, ctx),
            [f"{exact[0].number} is this customer's only open invoice for {inr(amt)}"])
    elif len(exact) > 1:
        add("amount_exact_ambiguous", Decimal("0.7"), _fix_rounding([_full(exact[0])], amt, ctx),
            [f"{len(exact)} open invoices are for {inr(amt)} ({', '.join(i.number for i in exact)}) — "
             f"took the oldest, {exact[0].number}"])

    found_tds = False
    for gross in (False, True):
        for r in ctx.rates():
            net = [i for i in pool if i.untouched and ctx.close(i.outstanding - _tds_on(i, r, gross), amt)]
            if len(net) == 1:
                usual = " — this customer's usual rate" if ctx.hint == r else ""
                base = "GST-inclusive total (TDS should be on taxable value)" if gross else "taxable value"
                add("amount_tds", Decimal("0.75") if gross else (Decimal("0.9") if usual else Decimal("0.85")),
                    _fix_rounding([_net_of_tds(net[0], r, gross)], amt, ctx),
                    [f"{net[0].number} less {r.normalize()}% TDS on its {base} equals the payment{usual}"])
                found_tds = True
                break
        if found_tds:
            break

    # Oldest first: customers often clear their oldest dues in one transfer (A6).
    run, acc = ZERO, []
    for i in pool[:MAX_COMBO_INVOICES]:
        run += i.outstanding
        acc.append(i)
        if len(acc) > 1 and ctx.close(run, amt, len(acc)):
            add("oldest_first", Decimal("0.88"), _fix_rounding([_full(x) for x in acc], amt, ctx),
                [f"Pays the {len(acc)} oldest open invoices exactly ({', '.join(x.number for x in acc)})"])
            break
        if run > amt + ctx.cfg.tolerance * len(acc):
            break

    if not any(s.kind == "oldest_first" for s in out) and not exact:
        combos = _combinations(ctx, pool[:MAX_COMBO_INVOICES])
        if len(combos) == 1:
            add("combination", Decimal("0.82"), combos[0][0], [combos[0][1]])
        elif len(combos) > 1:
            add("combination_ambiguous", Decimal("0.6"), combos[0][0],
                [combos[0][1], f"{len(combos)}{'+' if len(combos) > MAX_COMBOS_REPORTED else ''} different sets "
                               "of invoices add up to this amount — pick the right one"])

    if not out:
        first = pool[0]
        owed = sum((i.outstanding for i in pool), ZERO)
        if amt < first.outstanding:
            add("oldest_partial", Decimal("0.5"), [Allocation(first.id, first.number, amt)],
                [f"Less than the oldest open invoice {first.number} owes — likely a part-payment; "
                 "the balance stays open"])
        elif amt > owed:
            add("overpaid", Decimal("0.6"), [_full(i) for i in pool],
                [f"More than everything this customer owes ({inr(owed)}) — the rest stays on account"],
                unapplied=amt - owed)
        else:
            # Covers some invoices but adds up to none: fill oldest first, rest on the next one.
            allocs, left = [], amt
            for i in pool:
                if left <= 0:
                    break
                take = min(left, i.outstanding)
                allocs.append(Allocation(i.id, i.number, take))
                left -= take
            add("oldest_partial", Decimal("0.45"), allocs,
                [f"No set of invoices adds up to {inr(amt)}; filled oldest first — the last one stays part-paid"])
    return out


def _combinations(ctx: _Ctx, pool: list[OpenInvoice]):
    """Sets of 2–4 open invoices that add to the payment, gross or net of one TDS rate (A7, B4)."""
    amt = ctx.p.amount
    found: list[tuple[list[Allocation], str]] = []
    for size in range(2, min(MAX_COMBO_SIZE, len(pool)) + 1):
        for combo in itertools.combinations(pool, size):
            if ctx.close(sum((i.outstanding for i in combo), ZERO), amt, size):
                found.append((_fix_rounding([_full(i) for i in combo], amt, ctx),
                              f"{size} open invoices add up to the payment ({', '.join(i.number for i in combo)})"))
            elif all(i.untouched for i in combo):
                for r in ctx.rates():
                    if ctx.close(sum((i.outstanding - _tds_on(i, r) for i in combo), ZERO), amt, size):
                        found.append((_fix_rounding([_net_of_tds(i, r) for i in combo], amt, ctx),
                                      f"{size} open invoices less {r.normalize()}% TDS add up to the payment "
                                      f"({', '.join(i.number for i in combo)})"))
                        break
            if len(found) > MAX_COMBOS_REPORTED:
                return found
    return found


# ── Flags ──────────────────────────────────────────────────────────────────────

def _flags(ctx: _Ctx, best: Suggestion | None, cands: list[Suggestion], invoices: list[OpenInvoice],
           paid_invoices: list[OpenInvoice], customer_id: str | None) -> list[str]:
    flags: list[str] = []
    if not best:
        return _duplicate_flags(ctx, best, paid_invoices, customer_id)
    by_id = {i.id: i for i in invoices}
    chosen = [by_id[a.invoice_id] for a in best.allocations if a.invoice_id in by_id]

    # C9: the quoted invoice and the amount point at different invoices.
    ref = next((c for c in cands if c.kind.startswith("reference_")), None)
    amt = next((c for c in cands if c.kind in ("amount_exact", "amount_tds")), None)
    if ref and amt and ref.invoice_ids() != amt.invoice_ids() and ref.kind != "reference_exact":
        flags.append("CLUE_CONFLICT")
    if len({i.customer_id for i in chosen}) > 1:
        flags.append("CROSS_CUSTOMER")
    if ctx.p.received_on and any(i.invoice_date and i.invoice_date > ctx.p.received_on for i in chosen):
        flags.append("ADVANCE")
    if any((i.currency or "INR") != "INR" for i in chosen):
        flags.append("FOREIGN_CURRENCY")
    if any(i.status == "disputed" for i in chosen):
        flags.append("DISPUTED_INVOICE")
    if any(a.reason_note and "GST-inclusive" in a.reason_note for a in best.allocations):
        flags.append("TDS_ON_GROSS")
    flags += _duplicate_flags(ctx, best, paid_invoices, customer_id)
    return flags


# Explanations that account for the money with an open invoice; when one of these
# fits, an equal paid invoice is just a recurring amount (a monthly retainer), not
# a duplicate.
_EXPLAINED = frozenset({"remittance", "remittance_adjusted", "reference_exact", "reference_tds", "amount_exact", "amount_tds",
                        "oldest_first", "combination"})


def _duplicate_flags(ctx: _Ctx, best: Suggestion | None, paid_invoices: list[OpenInvoice],
                     customer_id: str | None) -> list[str]:
    """E1: the narration quotes an invoice that is already paid, or nothing open
    explains the amount but a paid invoice of this customer was for exactly it."""
    text = " ".join(filter(None, [ctx.p.narration, ctx.p.reference]))
    explained = best is not None and best.kind in _EXPLAINED
    for i in paid_invoices:
        if customer_id and i.customer_id != customer_id:
            continue
        if invoice_referenced(i.number, text):
            return ["POSSIBLE_DUPLICATE"]
        if not explained and ctx.close(i.total, ctx.p.amount):
            return ["POSSIBLE_DUPLICATE"]
    return []


# ── Entry point ──────────────────────────────────────────────────────────────

def match_payment(payment: Payment, customers: list[Customer], invoices: list[OpenInvoice],
                  remittance: list[RemittanceLine] | None = None, *,
                  cfg: MatchConfig | None = None,
                  paid_invoices: list[OpenInvoice] | None = None) -> MatchResult:
    """Best explanation of `payment` against the open invoices, with alternatives and flags.

    `invoices` are candidate open invoices (already narrowed by the repository);
    disputed ones may be included so they can be shown, but they are flagged.
    `paid_invoices` are the identified customer's recently paid invoices, for
    duplicate detection.
    """
    cfg = cfg or MatchConfig()
    payment.amount = money(payment.amount)
    open_invs = [i for i in invoices if i.outstanding > 0 and i.status in ("open", "partially_paid", "disputed")]
    cid, how, cconf, flags = identify_customer(payment, customers, open_invs)
    hint = next((c.tds_rate_hint for c in customers if c.id == cid), None)
    ctx = _Ctx(payment, cfg, hint)

    cands: list[Suggestion] = []
    if remittance:
        s = _from_remittance(ctx, remittance, open_invs, cid)
        if s:
            cands.append(s)
            cid = cid or s.customer_id
    cands += _from_references(ctx, open_invs)
    if cid:
        cands += _from_customer(ctx, open_invs, cid, cconf)
    elif not cands:
        # No idea who paid: a unique exact amount across everyone is worth showing,
        # never worth applying (C1, C8).
        exact = [i for i in open_invs if ctx.close(i.outstanding, payment.amount)]
        if len(exact) == 1:
            cands.append(Suggestion("amount_only", Decimal("0.6"), exact[0].customer_id,
                                    _fix_rounding([_full(exact[0])], payment.amount, ctx),
                                    [f"Payer not recognised; {exact[0].number} is the only open invoice "
                                     f"anywhere for {inr(payment.amount)}"]))

    if how and how != "chosen":
        for s in cands:
            # "payer name resembles X" reads on its own; the exact ways read as "identified by …".
            s.clues.insert(0, how[0].upper() + how[1:] if how.startswith("payer name") and how != "payer name"
                           else f"Customer identified by {how}")

    # Same invoices, same amounts → keep the more confident explanation only.
    uniq: dict[tuple, Suggestion] = {}
    for s in sorted(cands, key=lambda s: s.confidence, reverse=True):
        key = tuple(sorted((a.invoice_id, a.amount_applied) for a in s.allocations))
        uniq.setdefault(key, s)
    ranked = list(uniq.values())
    best = ranked[0] if ranked else None
    if best and not cid:
        cid = best.customer_id
    flags = flags + _flags(ctx, best, cands, open_invs, paid_invoices or [], cid)
    return MatchResult(cid, how, best, ranked[1:4], sorted(set(flags)))
