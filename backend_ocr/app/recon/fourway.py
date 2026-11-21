"""The invoice against each supporting document, one panel per document.

The engine already decides everything; this only reshapes its verdict into the
four comparisons a person actually makes:

    invoice ↔ PO            was it ordered, at that rate?
    invoice ↔ audit report  was it verified on site?
    invoice ↔ GRN           was it received into Dynamics?
    invoice ↔ payment       was it settled, in full?

**The invoice is the spine.** Every panel compares the same invoice lines to a
different counterpart, so a reviewer reads one list four times rather than four
unrelated screens.

**Not every field means something in every pair**, and pretending otherwise is
how a screen becomes noise. An audit report certifies *quantities*, not prices,
so rate is `NA` there — not "missing", which would read as a fault. A payment
advice settles an *invoice*, not a line, so that panel is one row by nature.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from .normalize import norm

INVOICE_VS_PO = "INVOICE_VS_PO"
INVOICE_VS_AUDIT = "INVOICE_VS_AUDIT"
INVOICE_VS_GRN = "INVOICE_VS_GRN"
INVOICE_VS_PAYMENT = "INVOICE_VS_PAYMENT"
PAIRS = (INVOICE_VS_PO, INVOICE_VS_AUDIT, INVOICE_VS_GRN, INVOICE_VS_PAYMENT)

TITLES = {
    INVOICE_VS_PO: "Invoice vs PO",
    INVOICE_VS_AUDIT: "Invoice vs audit report",
    INVOICE_VS_GRN: "Invoice vs GRN",
    INVOICE_VS_PAYMENT: "Invoice vs payment",
}
ASKS = {
    INVOICE_VS_PO: "Was it ordered, at this rate?",
    INVOICE_VS_AUDIT: "Was it verified on site?",
    INVOICE_VS_GRN: "Was it received?",
    INVOICE_VS_PAYMENT: "Was it settled in full?",
}

MATCH, DIFFERS, MISSING, NA = "MATCH", "DIFFERS", "MISSING", "NA"


@dataclass
class Check:
    field: str                     # qty | rate | amount | description
    state: str                     # MATCH | DIFFERS | MISSING | NA
    invoice: str | None = None
    other: str | None = None


@dataclass
class Pairing:
    description: str
    key: str | None
    checks: list[Check] = field(default_factory=list)
    # How this line was paired with its counterpart. Every figure beside it is
    # only as good as that pairing: a weak match means the difference shown may
    # be between two unrelated items.
    match_method: str | None = None
    match_score: float = 0.0

    @property
    def state(self) -> str:
        """The worst thing said about this line, so a list can be scanned."""
        states = [c.state for c in self.checks if c.state != NA]
        if not states:
            return NA
        if DIFFERS in states:
            return DIFFERS
        if MISSING in states:
            return MISSING
        return MATCH


@dataclass
class Panel:
    pair: str
    title: str
    ask: str
    available: bool                # is the counterpart document present at all?
    absent_reason: str = ""        # why there is nothing to compare (available=False)
    note: str = ""                 # what this comparison does and does not prove
    confirm: str = ""              # an assumption a person has to agree with, verbatim
    lines: list[Pairing] = field(default_factory=list)

    @property
    def counts(self) -> dict[str, int]:
        out = {MATCH: 0, DIFFERS: 0, MISSING: 0, NA: 0}
        for l in self.lines:
            out[l.state] += 1
        return out


def _paired(l, checks: list[Check]) -> Pairing:
    """A pairing that remembers how its two sides were brought together."""
    m = getattr(l, "match_method", None)
    return Pairing(l.description, l.invoice_key, checks,
                   match_method=getattr(m, "value", m),
                   match_score=float(getattr(l, "match_score", 0.0) or 0.0))


def _num(v) -> str | None:
    if v is None:
        return None
    d = Decimal(str(v)).normalize()
    return format(d, "f")


def _cmp(fieldname: str, a, b, tol: Decimal) -> Check:
    """One numeric comparison. Absent on either side is MISSING, not a difference."""
    if a is None and b is None:
        return Check(fieldname, NA)
    if a is None or b is None:
        return Check(fieldname, MISSING, _num(a), _num(b))
    same = abs(Decimal(str(a)) - Decimal(str(b))) <= tol
    return Check(fieldname, MATCH if same else DIFFERS, _num(a), _num(b))


def _text(a: str | None, b: str | None, fieldname: str = "description") -> Check:
    """Two strings agree when they normalise to the same thing (vocabulary §17).

    `fieldname` because the same comparison serves different questions: item
    names on the PO and audit panels, an invoice reference on the delivery proof.
    Labelling a waybill number "Item" would misname what the reviewer is reading.
    """
    if not a or not b:
        return Check(fieldname, MISSING if (a or b) else NA, a, b)
    return Check(fieldname, MATCH if norm(a) == norm(b) else DIFFERS, a, b)


def build(lines, *, receipt_lines=None, payment=None, invoice=None, pods=None,
          qty_tol: Decimal = Decimal("0.01"), money_tol: Decimal = Decimal("1.00"),
          rate_tol: Decimal = Decimal("0.01")) -> list[Panel]:
    """Four panels from one engine result. Pure: no database, no I/O."""
    billed = [l for l in lines if getattr(l, "invoice_key", None)]
    return [
        _po_panel(billed, qty_tol, rate_tol, money_tol),
        _audit_panel(billed, qty_tol, rate_tol, money_tol),
        _grn_panel(billed, receipt_lines or [], qty_tol, money_tol, pods or [], invoice),
        _payment_panel(payment, invoice, money_tol),
    ]


def _po_panel(billed, qty_tol, rate_tol, money_tol) -> Panel:
    p = Panel(INVOICE_VS_PO, TITLES[INVOICE_VS_PO], ASKS[INVOICE_VS_PO], available=True)
    for l in billed:
        if l.po_key is None:
            # Billed with nothing ordered — every field is missing, and saying so
            # once is clearer than four separate complaints.
            p.lines.append(Pairing(l.description, l.invoice_key, [
                Check("qty", MISSING, _num(l.billed_qty), None),
                Check("rate", MISSING, _num(l.billed_rate), None),
                Check("amount", MISSING, _num(l.billed_amt), None),
                Check("description", MISSING, l.invoice_text or l.description, None)]))
            continue
        p.lines.append(_paired(l, [
            _cmp("qty", l.billed_qty, l.po_qty, qty_tol),
            _cmp("rate", l.billed_rate, l.po_rate, rate_tol),
            _cmp("amount", l.billed_amt, l.expected_amt, money_tol),
            _text(l.invoice_text or l.description, l.description)]))
    return p


def _audit_panel(billed, qty_tol, rate_tol=Decimal("0.01"), money_tol=Decimal("1.00")) -> Panel:
    seen = [l for l in billed if l.evidence_key or l.verified_qty is not None]
    if not seen:
        return Panel(INVOICE_VS_AUDIT, TITLES[INVOICE_VS_AUDIT], ASKS[INVOICE_VS_AUDIT],
                     available=False, absent_reason="No audit report on this case yet")
    p = Panel(INVOICE_VS_AUDIT, TITLES[INVOICE_VS_AUDIT], ASKS[INVOICE_VS_AUDIT], available=True)
    priced = False
    for l in billed:
        # Many site reports DO price the work — a rate column, often with the
        # discounted rate beside it. Where the report carries one, rate and
        # value are real comparisons; where it does not, they stay NA, because
        # an auditor certifying what is there is not the same as costing it.
        rate = getattr(l, "verified_rate", None)
        amt = getattr(l, "verified_amt", None)
        priced = priced or rate is not None
        p.lines.append(_paired(l, [
            _cmp("qty", l.billed_qty, l.verified_qty, qty_tol),
            _cmp("rate", l.billed_rate, rate, rate_tol) if rate is not None else Check("rate", NA),
            _cmp("amount", l.billed_amt, amt, money_tol) if amt is not None else Check("amount", NA),
            _text(l.invoice_text or l.description, l.evidence_text or l.description)]))
    p.note = ("Rate and value are the site report's own, after the discount where it prints "
              "one. The PO remains what is payable." if priced else
              "This report certifies quantities only, so there is nothing to compare on rate.")
    return p


def _same_invoice(a: str, b: str, *, value_matches: bool) -> str | None:
    """Why the reference on the carrier's paper is this invoice, or None.

    Same rule the POD header check uses, so the panel and the check can never
    disagree about whether a waybill belongs to this bill (engine.same_consignment).
    The *reason* comes back rather than a yes, because "same reference" and
    "two letters differ and the value agrees" are not the same news and the panel
    has to say which one it is.
    """
    from .engine import same_consignment
    return same_consignment(a, b, value_matches=value_matches)


def _grn_panel(billed, receipt_lines, qty_tol, money_tol, pods=(), invoice=None) -> Panel:
    if not receipt_lines and pods:
        # No MSD extract, but a signed delivery proof is receipt evidence for
        # goods — it is what the business actually has for this purchase.
        #
        # It answers the receipt question at its OWN granularity though: a POD
        # proves "18 packages worth ₹6,75,432 reached this address", never "6 of
        # this item". Showing per-line quantities against it would invent
        # evidence the document does not carry (V§1 receipt_granularity).
        pod = pods[0]
        # Before using a delivery proof as receipt evidence, make sure it is
        # evidence for THIS invoice. A POD can be attached to a case by hand,
        # and a waybill for a different consignment would otherwise confirm
        # receipt of goods that never arrived against this bill.
        named = [str(x) for x in (getattr(pod, "invoice_nos", None) or []) if x]
        want = getattr(invoice, "invoice_no", None) if invoice else None
        inv_gross_for_ref = getattr(invoice, "total", None) if invoice else None
        declared = getattr(pod, "total_invoice_value", None)
        value_ok = (inv_gross_for_ref is not None and declared is not None
                    and abs(Decimal(str(inv_gross_for_ref)) - Decimal(str(declared))) <= money_tol)
        why = next((w for x in named if (w := _same_invoice(x, want, value_matches=value_ok))), None) \
            if (want and named) else "same reference"
        if want and named and not why:
            return Panel(INVOICE_VS_GRN, "Invoice vs delivery proof", ASKS[INVOICE_VS_GRN],
                         available=False,
                         absent_reason=(f"This delivery proof names {', '.join(named)}, not {want}. "
                                        "It is not used as receipt evidence for this invoice."))
        # Accepted on an inference, not on the paper: say so where the reviewer
        # reads the verdict, rather than showing a tick that hides the assumption.
        assumed = why if (why and why != "same reference") else None
        p = Panel(INVOICE_VS_GRN, "Invoice vs delivery proof",
                  "Was it received?", available=True)
        # A carrier declares the invoice's GROSS value — "Total Inv. Value" is
        # what the consignment is worth including tax. Comparing it against the
        # taxable sum would report a difference of exactly the GST on every
        # consignment.
        inv_gross = (getattr(invoice, "total", None) if invoice else None)
        if inv_gross is None:
            inv_gross = sum((l.billed_amt for l in billed), Decimal("0"))
        packages = getattr(pod, "packages", None)
        p.lines.append(Pairing(
            f"Consignment · {getattr(pod, 'waybill_no', None) or 'no waybill number'}", None, [
                # What the POD actually proves was delivered: packages, not items.
                Check("qty", MATCH if packages else NA,
                      None, f"{packages} packages" if packages else None),
                Check("rate", NA),
                _cmp("amount", inv_gross, getattr(pod, "total_invoice_value", None), money_tol),
                # The real comparison: the invoice's number against what the
                # carrier's paper says. Comparing the POD's reference to itself,
                # as this once did, always matched and proved nothing.
                _text(want or None, ", ".join(named) or None, "reference")]))
        # Where the consignment had only one line to be, the engine filled the
        # receipt quantity (engine._receipt_from_consignment). Show it: the
        # reviewer asked whether it was received, and here the answer is per
        # line, not only per consignment.
        derived = [l for l in billed if getattr(l, "receipt_basis", None) == "single_line_consignment"]
        for l in derived:
            p.lines.append(_paired(l, [
                _cmp("qty", l.billed_qty, l.received_qty, qty_tol),
                Check("rate", NA), Check("amount", NA),
                _text(l.invoice_text or l.description, l.invoice_text or l.description)]))
        p.note = (
            ("The quantity is the whole consignment: this bill has one line, so what arrived "
             "arrived against it. " if derived else
             "It confirms the consignment and its value, not item quantities — a delivery proof "
             "does not itemise packages. ")
            + "Load the Dynamics GRN for a line-by-line receipt.")
        # Kept separate from the note because it is not information — it is a
        # question for a person, and a screen that buries it has assumed the
        # answer on their behalf.
        if assumed:
            p.confirm = (f"The waybill reads {', '.join(named)}, not {want} — {assumed}. "
                         "Confirm it is this consignment before relying on it.")
        return p
    if not receipt_lines:
        # Two different documents answer this leg, and naming only one of them
        # reads as a missing feature rather than a missing document. Either
        # would do: the carrier's signed proof, or the Dynamics extract.
        return Panel(INVOICE_VS_GRN, TITLES[INVOICE_VS_GRN], ASKS[INVOICE_VS_GRN],
                     available=False,
                     absent_reason=("Nothing here proves receipt yet. Attach the signed delivery "
                                    "proof for this invoice, or load the goods receipt from "
                                    "Dynamics for a line-by-line check."))
    by_norm: dict[str, object] = {}
    for g in receipt_lines:
        k = norm(g.description or g.item_code or "")
        if k:
            by_norm.setdefault(k, g)
    p = Panel(INVOICE_VS_GRN, TITLES[INVOICE_VS_GRN], ASKS[INVOICE_VS_GRN], available=True)
    for l in billed:
        g = by_norm.get(norm(l.invoice_text or l.description or ""))
        p.lines.append(_paired(l, [
            _cmp("qty", l.billed_qty, getattr(g, "qty_received", None), qty_tol),
            _cmp("rate", l.billed_rate, getattr(g, "rate", None), Decimal("0.01")),
            _cmp("amount", l.billed_amt, getattr(g, "amount", None), money_tol),
            _text(l.invoice_text or l.description, getattr(g, "description", None))]))
    return p


def _payment_panel(payment, invoice, money_tol) -> Panel:
    if payment is None:
        return Panel(INVOICE_VS_PAYMENT, TITLES[INVOICE_VS_PAYMENT], ASKS[INVOICE_VS_PAYMENT],
                     available=False, absent_reason="Not paid yet, or no remittance advice loaded")
    p = Panel(INVOICE_VS_PAYMENT, TITLES[INVOICE_VS_PAYMENT], ASKS[INVOICE_VS_PAYMENT], available=True)
    # A remittance advice settles an invoice, not a line: one row, by nature.
    inv_total = getattr(invoice, "total", None) if invoice else None
    checks = [
        Check("qty", NA), Check("rate", NA),
        # The base amount, not the net: TDS is withheld, not unpaid.
        _cmp("amount", inv_total, getattr(payment, "total_base", None), money_tol),
        _text(getattr(invoice, "invoice_no", None), (payment.references[0] if payment.references else None)),
    ]
    p.lines.append(Pairing(getattr(invoice, "invoice_no", None) or "Invoice", None, checks))
    return p
