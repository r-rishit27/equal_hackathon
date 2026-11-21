"""ReconEngine — pure: ReconInput in, ReconResult out (03_LLD_BACKEND.md §11).

No DB, no network, no LLM. Matching has already happened (ReconInput carries
the MatchPairs); this module applies Bata's rule and the header/line checks.
"""
from __future__ import annotations

import re
from datetime import date
from decimal import Decimal

from . import config as C
from .normalize import norm, same_unit, variant_conflicts, variant_tokens
from .num import ZERO, close, fmt_inr, round2
from . import rules as rules_mod
from .rules import BillingRule, is_boilerplate
from .types import (
    AuditVerdict, CaseStatus, EvidenceRow, HeaderCheck, InvoiceLine, LineResult, LineStatus,
    MatchMethod, MatchPair, POLine, ReconInput, ReconResult, ReconSummary, Severity, max_severity, sval,
)

B, R, I, OK = Severity.BLOCKER, Severity.REVIEW, Severity.INFO, Severity.OK

_STATUS_SEVERITY = {
    LineStatus.RATE_HIGHER: B, LineStatus.RATE_LOWER: I, LineStatus.OVER_PO: B,
    LineStatus.OVER_VERIFIED: B, LineStatus.UNDER_BILLED: R, LineStatus.UNDER_USED: I,
    LineStatus.OVER_EXECUTED_CAPPED: I, LineStatus.NOT_VERIFIABLE: I, LineStatus.ADDITIONAL_ON_SITE: R,
    LineStatus.DESCRIPTION_CONFLICT: R, LineStatus.UOM_CONFLICT: R, LineStatus.DAMAGED_UNMOUNTED: R,
    LineStatus.AUDITOR_REMARK: I, LineStatus.PCT_CHARGE_MISMATCH: R, LineStatus.ARITHMETIC: R,
    LineStatus.REPORT_ONLY: I, LineStatus.MATCHED: OK,
    # NOT_DONE, NOT_IN_PO, NO_EVIDENCE, UNCHECKED_READING depend on context — set explicitly.
}

_PO_NO = re.compile(r"PPO\s*0*(\d{5,})", re.I)
_STATE_NAMES = {
    "jammu": "01", "himachal": "02", "punjab": "03", "chandigarh": "04", "uttarakhand": "05", "haryana": "06",
    "delhi": "07", "rajasthan": "08", "uttar pradesh": "09", "bihar": "10", "assam": "18", "west bengal": "19",
    "jharkhand": "20", "odisha": "21", "chhattisgarh": "22", "madhya pradesh": "23", "gujarat": "24",
    "maharashtra": "27", "karnataka": "29", "goa": "30", "kerala": "32", "tamil nadu": "33",
    "telangana": "36", "andhra": "37",
}


def _po_no(s: str | None) -> str | None:
    m = _PO_NO.search(s or "")
    return m.group(1).lstrip("0") if m else None


# A PO reference field quoting more than one order ("PPO00024046 / PPO00024102",
# "4500087255 & 4500087301"). Bare 5+ digit runs count too, since vendors often
# type the number without the PPO prefix.
_PO_ANY = re.compile(r"(?:PPO\s*0*)?(\d{5,})", re.I)


def _po_refs(s: str | None) -> list[str]:
    """Every distinct PO number quoted in one reference field, order preserved."""
    out: list[str] = []
    for m in _PO_ANY.finditer(s or ""):
        n = m.group(1).lstrip("0")
        if n and n not in out:
            out.append(n)
    return out


# Characters a scanner confuses on a carrier's waybill (vocabulary §16). Each
# group collapses to one representative, so two references that differ only in
# these positions compare equal.
# Only pairs that genuinely collapse in print or handwriting. Each extra pair
# widens what counts as "the same reference", so the list stays short: T/1 and
# Q/0 were dropped as over-eager. W/4 earns its place from a real Safexpress
# waybill where KMW read as KM4.
_OCR_FOLD = str.maketrans({
    "O": "0", "D": "0",
    "I": "1", "L": "1",
    "S": "5", "B": "8", "G": "6", "Z": "2", "W": "4",
})


def _ocr_same(a: str | None, b: str | None) -> bool:
    """Do these two references differ only by characters a reader confuses?

    Same length is required: a dropped or extra character is a different
    reference, not a misread one.
    """
    x, y = _invno(a), _invno(b)
    if not x or not y or len(x) != len(y):
        return False
    return x.translate(_OCR_FOLD) == y.translate(_OCR_FOLD)


#: Things that appear where a reference should be and mean "there isn't one".
#: Compared after `_invno` has stripped punctuation, so "N/A" arrives as "NA".
_NOT_A_REFERENCE = frozenset({"NA", "NIL", "NONE", "NOTAPPLICABLE", "XX", "XXX", "0", "00", "-"})


def same_consignment(pod_ref: str | None, invoice_no: str | None, *, value_matches: bool) -> str | None:
    """Is the reference on a carrier's paper this invoice? Returns why, or None.

    Three ways to say yes, in descending confidence:

    1. it reads the same;
    2. it differs only in characters a scanner confuses (G/6, I/1, W/4);
    3. it differs in a character or two that are NOT confusable, **and** the
       waybill's declared value matches the invoice exactly.

    The third rung exists because a real Safexpress waybill was read as
    `266J/AM4/S115224` for `26GJ/KMW/SI15224` — K as A, which no honest fold
    list contains. Widening the fold to cover it would let genuinely different
    references through; an exact value match is the stronger, safer signal.
    Two characters is the ceiling: past that it is not a reading of this one.
    """
    a, b = _invno(pod_ref), _invno(invoice_no)
    if not a or not b:
        return None
    # A placeholder is not a reference. Two documents both saying "N/A" agree
    # about nothing, and treating that as a match confirms receipt of goods
    # against a bill neither of them names. Found by stress-testing the
    # comparison with the junk scanners actually emit.
    if a in _NOT_A_REFERENCE or b in _NOT_A_REFERENCE:
        return None
    if a == b:
        return "same reference"
    if _ocr_same(a, b) and value_matches:
        return "characters a scanner confuses; the declared value matches"
    if value_matches and len(a) == len(b):
        diff = [(x, y) for x, y in zip(a.translate(_OCR_FOLD), b.translate(_OCR_FOLD)) if x != y]
        # Letters only. Digits carry the invoice's sequence, so an unexplained
        # digit difference is the next invoice, not a misreading of this one —
        # and accepting it would confirm receipt of goods that never arrived
        # against this bill. A misread letter (K as A) carries no such meaning.
        if 0 < len(diff) <= 2 and all(not x.isdigit() and not y.isdigit() for x, y in diff):
            n = len(diff)
            return (f"reference differs in {n} letter{'s' if n > 1 else ''} the scanner misread; "
                    f"the declared value matches exactly")
    return None


# The site report's own rate and value live in rules.py, where the viewer can
# reach them too: the case table and the document must never disagree about
# what the paper says.
_audit_rate = rules_mod.audit_row_rate
_audit_value = rules_mod.audit_row_value


def _leg_cover(inp, lines, pairing: Decimal | None) -> dict[str, float | None]:
    """How much of the bill each supporting document actually accounts for.

    A finance manager's question about a document is not "did it arrive" but
    "how much of this invoice does it cover". Weighted by money throughout,
    for the same reason the pairing confidence is: a document that covers
    thirty small lines and misses the one large one has not covered the
    invoice.

    None, not zero, where the document is absent. An audit report that has not
    arrived is not an audit report performing badly, and a dash says that
    where an 0% would accuse it.
    """
    billed = [l for l in lines if l.invoice_key and not l.is_charge]
    total = sum((abs(l.billed_amt) for l in billed), ZERO)
    out: dict[str, float | None] = {"po": None, "evidence": None, "pod": None, "payment": None}
    if total == 0:
        return out
    if inp.po is not None:
        out["po"] = float(pairing) if pairing is not None else None
    if inp.evidence:
        certified = sum((abs(l.billed_amt) for l in billed if l.evidence_key), ZERO)
        out["evidence"] = float(round(certified / total, 4))
    if inp.pods or getattr(inp, "receipt_lines", None):
        received = sum((abs(l.billed_amt) for l in billed if l.received_qty is not None), ZERO)
        # A delivery proof covers the consignment even where it cannot speak
        # per line; the receipt check reports that separately.
        out["pod"] = float(round(received / total, 4)) if received else 0.0
    if inp.payment is not None:
        paid = getattr(inp.payment, "total_base", None)
        inv = inp.invoice.total if inp.invoice else None
        out["payment"] = (float(round(min(Decimal(str(paid)) / Decimal(str(inv)), Decimal("1")), 4))
                          if paid and inv else None)
    return out


def _pairing_confidence(lines) -> tuple[Decimal | None, list[dict]]:
    """How much of the billed value rests on a pairing we are sure of.

    Weighted by money on purpose. Averaged over lines, one shaky pairing on a
    ₹5,00,000 item would disappear behind forty tidy ₹500 ones — and it is the
    ₹5,00,000 that decides whether this invoice can be paid.

    An exact or human-confirmed pairing counts whole; a scored one counts for
    what it scored; a billed line with no counterpart at all counts for
    nothing, because nothing has been compared with it.
    """
    billed = [l for l in lines if l.invoice_key]
    total = sum((abs(l.billed_amt) for l in billed), ZERO)
    if not billed or total == 0:
        return Decimal("1"), []
    # Nothing has been paired because nothing has arrived to pair against.
    if not any(l.po_key for l in lines):
        return None, []
    sure = {MatchMethod.EXACT, MatchMethod.HUMAN}
    scored = []
    for l in billed:
        c = (Decimal("1") if l.match_method in sure
             else Decimal(str(l.match_score or 0)) if l.po_key
             else ZERO)
        scored.append((l, c))
    conf = sum((abs(l.billed_amt) * c for l, c in scored), ZERO) / total
    weakest = [{"description": l.description, "amount": str(round2(l.billed_amt)),
                "confidence": float(round(c, 3)),
                "method": getattr(l.match_method, "value", l.match_method)}
               for l, c in sorted(scored, key=lambda t: (t[1], -abs(t[0].billed_amt)))
               if c < Decimal("0.85")][:5]
    return round(conf, 4), weakest


def _state(s: str | None) -> str | None:
    if not s:
        return None
    m = re.search(r"\b(\d{2})\b", s)
    if m:
        return m.group(1)
    low = s.lower()
    return next((code for name, code in _STATE_NAMES.items() if name in low), None)


def _invno(s: str | None) -> str:
    return re.sub(r"[^A-Z0-9]", "", (s or "").upper())


class _Line:
    """Builder for one LineResult so statuses and severity stay consistent."""

    def __init__(self, **kw) -> None:
        self.r = LineResult(**kw)
        self._sev: list[Severity] = []

    def add(self, status: LineStatus, severity: Severity | None = None) -> None:
        if status not in self.r.statuses:
            self.r.statuses.append(status)
        self._sev.append(severity if severity is not None else _STATUS_SEVERITY[status])

    def done(self) -> LineResult:
        if not self.r.statuses:
            self.add(LineStatus.MATCHED)
        self.r.severity = max_severity(self._sev)
        return self.r


class LineChecks:
    def __init__(self, inp: ReconInput) -> None:
        self.inp = inp
        self.cfg = inp.config
        self.rule = BillingRule(self.cfg)

    def run(self) -> list[LineResult]:
        inp, cfg = self.inp, self.cfg
        po_lines = inp.po.lines if inp.po else []
        inv_lines = inp.invoice.lines if inp.invoice else []
        inv_by = {l.key: l for l in inv_lines}
        ev_rows = [r for sec in inp.evidence for r in sec.rows]
        ev_by = {r.key: r for r in ev_rows}
        inv_m: dict[str, MatchPair] = {m.po_key: m for m in inp.invoice_matches if m.po_key and m.other_key in inv_by}
        ev_m: dict[str, list[MatchPair]] = {}
        for m in inp.evidence_matches:
            if m.po_key and m.other_key in ev_by:
                ev_m.setdefault(m.po_key, []).append(m)
        has_pv = bool(ev_rows)
        has_other_evidence = bool(inp.pods)

        out: list[LineResult] = []
        charges: list[tuple[_Line, POLine, InvoiceLine | None]] = []
        goods_expected = ZERO
        for p in po_lines:
            m = inv_m.get(p.key)
            inv = inv_by.get(m.other_key) if m else None
            basis = self.rule.charge_basis(p.description)
            evs = [ev_by[x.other_key] for x in ev_m.get(p.key, [])]
            ln = self._po_line(p, m, inv, None if basis else evs, has_pv, has_other_evidence)
            if basis is not None:
                charges.append((ln, p, inv))
            else:
                if not (inv and inv.is_charge):
                    goods_expected += ln.r.expected_amt
                out.append(ln.done())
        for ln, p, inv in charges:
            self._charge(ln, p, inv, goods_expected)
            out.append(ln.done())
        out.sort(key=lambda r: [p.key for p in po_lines].index(r.po_key) if r.po_key else 0)

        matched_inv = {m.other_key for m in inp.invoice_matches if m.po_key}
        for l in inv_lines:
            if l.is_rollup:
                continue        # a subtotal of lines already counted below it
            if l.key not in matched_inv:
                out.append(self._not_in_po(l).done())
        matched_ev = {m.other_key for m in inp.evidence_matches if m.po_key}
        for r in ev_rows:
            if r.key not in matched_ev:
                out.append(self._report_row(r).done())
        for i, r in enumerate(out):
            r.ord = i + 1
        self._receipt_from_consignment(out)
        return out

    def _receipt_from_consignment(self, out: list[LineResult]) -> None:
        """Fill the receipt column from a delivery proof, where it is unambiguous.

        A POD proves a consignment: so many packages, worth so much, signed for
        at the site. It cannot say how much of ITEM 3 arrived, because the
        packages are not itemised — which is why the receipt column is blank
        whenever a bill has several lines (V§1 receipt_granularity).

        One case is not ambiguous. When the invoice bills exactly ONE line and
        the proof's declared value is that invoice's gross, the consignment
        cannot have been split across lines, because there is only one line for
        it to be. The quantity billed is then the quantity received, and leaving
        the column blank reports less than the document actually proves.

        Everything else stays blank. Two lines and one consignment value admits
        many splits, and inventing one would put a number a reviewer trusts
        against evidence that does not carry it.
        """
        if getattr(self.inp, "receipt_lines", None):
            return                                   # a real GRN answers per line
        billed = [r for r in out if r.invoice_key and not r.is_charge]
        if len(billed) != 1 or billed[0].received_qty is not None:
            return
        inv = self.inp.invoice
        gross = inv.total if inv else None
        if gross is None:
            return
        for pod in self.inp.pods:
            if pod.total_invoice_value is None:
                continue
            if close(pod.total_invoice_value, gross, self.cfg.money_tol, ZERO):
                billed[0].received_qty = billed[0].billed_qty
                # The carrier's declared value, which includes tax — that is
                # what the consignment is worth, and on a one-line bill it is
                # what arrived against this line.
                billed[0].received_amt = pod.total_invoice_value
                billed[0].receipt_basis = "single_line_consignment"
                return

    # ── per PO line ────────────────────────────────────────────────────────────
    def _received_for(self, p: POLine):
        """What the goods receipt says arrived against this PO line.

        A Dynamics GRN is per line, so it can answer at item level. Matching
        prefers the PO line number the extract carries, then the item code,
        then the normalised description — an ERP export and a PO describe the
        same line very differently.

        Returns (qty, value), either of which is None when the extract does not
        say — which reads as "not received" nowhere: an absent receipt is
        reported by its own check, not by a zero here.
        """
        rows = getattr(self.inp, "receipt_lines", None)
        if not rows:
            return None, None
        want_no = str(p.sno) if p.sno is not None else None
        want_desc = norm(p.description or "")
        total = None
        value = None
        for g in rows:
            same = ((want_no and str(getattr(g, "po_line_no", "") or "").strip() == want_no)
                    or (getattr(g, "item_code", None)
                        and norm(str(g.item_code)) == norm(p.description or ""))
                    or (want_desc and norm(str(getattr(g, "description", "") or "")) == want_desc))
            if not same:
                continue
            if getattr(g, "qty_received", None) is not None:
                total = (total or Decimal(0)) + g.qty_received
            amt = getattr(g, "amount", None)
            if amt is None and getattr(g, "rate", None) is not None \
                    and getattr(g, "qty_received", None) is not None:
                amt = g.qty_received * g.rate
            if amt is not None:
                value = (value or Decimal(0)) + Decimal(str(amt))
        return total, value

    def _po_line(self, p: POLine, m: MatchPair | None, inv: InvoiceLine | None,
                 evs: list[EvidenceRow] | None, has_pv: bool, has_other_evidence: bool) -> _Line:
        cfg = self.cfg
        ev = evs[0] if evs else None
        billed_qty = (sval(inv.qty) or ZERO) if inv else ZERO
        billed_rate = sval(inv.rate) if inv else None
        printed_amt = sval(inv.amount) if inv else None
        if inv and billed_rate is not None:
            billed_amt = round2(billed_qty * billed_rate)
        else:
            billed_amt = printed_amt or ZERO
        received, received_value = self._received_for(p)
        exp_qty, verdict = self.rule.expected_qty(p.qty, ev) if evs is not None else (p.qty, None)
        expected_amt = round2(exp_qty * p.unit_price)
        ln = _Line(
            ord=0, kind="po", description=p.description, po_key=p.key,
            invoice_key=inv.key if inv else None, evidence_key=ev.key if ev else None,
            invoice_text=inv.description if inv else None, evidence_text=ev.item if ev else None,
            unit=p.unit, po_qty=p.qty, verified_qty=sval(ev.audit_qty) if ev else None,
            verified_rate=_audit_rate(ev), verified_amt=_audit_value(ev),
            vendor_qty=sval(ev.vendor_qty) if ev else None,
            billed_qty=billed_qty, expected_qty=exp_qty, po_rate=p.unit_price, billed_rate=billed_rate,
            received_qty=received, received_amt=received_value,
            receipt_basis="grn" if received is not None else None,
            expected_amt=expected_amt, billed_amt=billed_amt, delta=round2(billed_amt - expected_amt),
            verdict=verdict, match_method=m.method if m else MatchMethod.NONE,
            match_score=m.score if m else 0.0, conflicts=list(m.conflicts) if m else [],
            remark=ev.remark if ev else None, is_charge=bool(inv and inv.is_charge),
        )
        # The PO is the contract, so a differing site rate never becomes the
        # basis for payment — but it is worth saying out loud, because one of
        # the two documents is wrong about what was agreed.
        if ev is not None and (why := rules_mod.audit_row_arithmetic(ev)):
            ln.r.conflicts.append(f"site report: {why}")
        # Only where the report prints the SETTLED rate. A row carrying the
        # list rate and no discount column differs from the PO by exactly the
        # discount — ₹50.00 against ₹47.50 on the real Inner Space case — and
        # reporting that as a disagreement would flag every discounted line
        # for saying what it was discounted from.
        site_rate = ev.rate_after_discount if ev is not None else None
        if site_rate is not None and p.unit_price is not None \
                and not close(site_rate, p.unit_price, cfg.rate_abs_tol, cfg.rate_rel_tol):
            ln.r.conflicts.append(
                f"site report rate ₹{fmt_inr(site_rate)} is not the PO rate ₹{fmt_inr(p.unit_price)}")

        prior = self.inp.prior_billed_qty.get(p.key, ZERO)

        if billed_rate is not None and billed_qty > 0:
            if billed_rate > p.unit_price and not (
                    # R2 (Bata): the PO rate is fixed, so a rate above it is never
                    # within tolerance — a rate change requires a new PO.
                    False if cfg.rate_must_equal
                    else close(billed_rate, p.unit_price, cfg.rate_abs_tol, cfg.rate_rel_tol)):
                ln.add(LineStatus.RATE_HIGHER)
            elif billed_rate < p.unit_price and not close(billed_rate, p.unit_price, cfg.rate_abs_tol, cfg.rate_rel_tol):
                ln.add(LineStatus.RATE_LOWER)
        if prior + billed_qty > p.qty + cfg.qty_tol:
            ln.add(LineStatus.OVER_PO)
        if verdict == AuditVerdict.VERIFIED and ev is not None:
            audit = sval(ev.audit_qty) or ZERO
            if billed_qty > audit + cfg.qty_tol:
                ln.add(LineStatus.OVER_VERIFIED)
            if audit > p.qty + cfg.qty_tol and billed_qty <= p.qty + cfg.qty_tol and billed_qty >= p.qty - cfg.qty_tol:
                ln.add(LineStatus.OVER_EXECUTED_CAPPED)
        if verdict == AuditVerdict.NOT_DONE:
            ln.add(LineStatus.NOT_DONE, B if billed_qty > cfg.qty_tol else I)
        if verdict in (AuditVerdict.NOT_COVERED, AuditVerdict.NOT_COUNTABLE):
            ln.add(LineStatus.NOT_VERIFIABLE)
        if billed_qty < exp_qty - cfg.qty_tol:
            ln.add(LineStatus.UNDER_BILLED)
        if cfg.flag_under_use and prior + billed_qty < p.qty - cfg.qty_tol:
            ln.add(LineStatus.UNDER_USED)
        if evs is not None and ev is None:
            if has_pv:
                ln.add(LineStatus.NO_EVIDENCE, R)
            elif not has_other_evidence:
                ln.add(LineStatus.NO_EVIDENCE, I)
        elif ev is not None and verdict == AuditVerdict.UNKNOWN:
            # Auditor listed the item but left the cell blank with no remark.
            ln.add(LineStatus.NO_EVIDENCE, R)
        if len(evs or []) > 1:
            ln.r.conflicts.append(f"listed {len(evs)} times in the report")
            ln.add(LineStatus.AUDITOR_REMARK, R)
        if inv is not None and ev is not None:
            for c in variant_conflicts(variant_tokens(inv.description), variant_tokens(ev.item)):
                ln.r.conflicts.append(f"invoice vs report: {c}")
        if ln.r.conflicts and (m is not None or ev is not None):
            ln.add(LineStatus.DESCRIPTION_CONFLICT)
        if inv is not None and same_unit(p.unit, inv.unit) is False:
            ln.add(LineStatus.UOM_CONFLICT, R if billed_qty > 0 else I)
        if ev is not None and ((ev.damaged or 0) > 0 or (ev.unmounted or 0) > 0):
            ln.add(LineStatus.DAMAGED_UNMOUNTED)
        if ev is not None and verdict == AuditVerdict.VERIFIED and not is_boilerplate(ev.remark):
            ln.add(LineStatus.AUDITOR_REMARK)
        if ev is not None and self._unchecked(ev):
            ln.r.needs_review_cell = True
            agrees = billed_qty == exp_qty
            ln.add(LineStatus.UNCHECKED_READING, I if agrees else R)
        self._arith(ln, inv)
        return ln

    def _charge(self, ln: _Line, p: POLine, inv: InvoiceLine | None, goods_expected: Decimal) -> None:
        basis = self.rule.charge_basis(p.description)
        pct = inv.charge_pct if inv else None
        expected = self.rule.expected_charge(basis, round2(p.qty * p.unit_price), pct, goods_expected)
        r = ln.r
        r.expected_amt = expected
        r.expected_qty = p.qty
        if inv and sval(inv.amount) is not None and (pct is not None or sval(inv.rate) is None):
            r.billed_amt = sval(inv.amount)          # % charges: the printed amount is the claim
        r.delta = round2(r.billed_amt - expected)
        # Charge lines aren't qty-checked: drop the qty statuses computed for them.
        keep = (LineStatus.RATE_HIGHER,) if pct is not None else (LineStatus.RATE_HIGHER, LineStatus.ARITHMETIC)
        r.statuses = [s for s in r.statuses if s in keep]
        r.conflicts = [c for c in r.conflicts if not c.startswith("printed amount")] if pct is not None else r.conflicts
        ln._sev = [_STATUS_SEVERITY[s] for s in r.statuses]
        if inv is None:
            ln.add(LineStatus.UNDER_BILLED) if expected > 0 else None
        elif abs(r.delta) > self.cfg.money_tol:
            ln.add(LineStatus.PCT_CHARGE_MISMATCH, B if r.delta > 0 else R)
        r.remark = (f"{basis.value.replace('_', ' ').lower()}"
                    + (f"; billed as {pct}% of goods ₹{fmt_inr(goods_expected)}" if pct is not None else ""))

    def _not_in_po(self, l: InvoiceLine) -> _Line:
        qty = sval(l.qty) or ZERO
        rate = sval(l.rate)
        amt = round2(qty * rate) if rate is not None else (sval(l.amount) or ZERO)
        ln = _Line(ord=0, kind="not_in_po", description=l.description, invoice_key=l.key,
                   invoice_text=l.description, unit=l.unit, billed_qty=qty, billed_rate=rate,
                   billed_amt=amt, delta=amt, is_charge=l.is_charge)
        ln.add(LineStatus.NOT_IN_PO, B if (qty > self.cfg.qty_tol or amt > self.cfg.money_tol) else I)
        # R5: the remedy is fixed, so say it rather than leaving a reviewer to
        # work it out. An email approval does NOT make this line payable on this
        # PO (docs/reconciliation/QUESTIONS_FOR_BATA.md §2).
        ln.r.remedy = (f"Obtain a credit note from the vendor for {fmt_inr(amt)}; "
                       "the balance needs a new PO and a new invoice")
        self._arith(ln, l)
        return ln

    def _report_row(self, r: EvidenceRow) -> _Line:
        additional = r.row_type == "additional"
        ln = _Line(ord=0, kind="additional" if additional else "report_only", description=r.item,
                   evidence_key=r.key, evidence_text=r.item, unit=r.unit, po_qty=r.po_qty,
                   verified_qty=sval(r.audit_qty), vendor_qty=sval(r.vendor_qty), remark=r.remark,
                   verdict=AuditVerdict.ADDITIONAL if additional else None)
        ln.add(LineStatus.ADDITIONAL_ON_SITE if additional else LineStatus.REPORT_ONLY)
        if self._unchecked(r):
            ln.r.needs_review_cell = True
            ln.add(LineStatus.UNCHECKED_READING, I)
        return ln

    def _unchecked(self, r: EvidenceRow) -> bool:
        a = r.audit_qty
        return r.needs_review or (a is not None and a.confidence < C.CELL_ACCEPT_CONF)

    def _arith(self, ln: _Line, inv: InvoiceLine | None) -> None:
        """Does the line's own arithmetic hold?

        Reconciliation is on the **taxable** amount — what is agreed on the PO
        and certified on site is the pre-tax figure. Some vendors print the
        tax-inclusive amount on the line anyway, and comparing that against
        qty x rate flagged a perfectly correct line: 6 x 95,400 = 5,72,400, but
        the line printed 6,75,432, which is the same number plus 18% GST.
        """
        if inv is None:
            return
        q, rt, a = sval(inv.qty), sval(inv.rate), sval(inv.amount)
        if q is None or rt is None or a is None:
            return
        taxable = round2(q * rt)
        if abs(taxable - a) <= self.cfg.money_tol:
            return
        # The printed figure may be this line's amount with its own tax added.
        if inv.tax_rate:
            gross = round2(taxable * (Decimal(1) + Decimal(inv.tax_rate) / Decimal(100)))
            if abs(gross - a) <= self.cfg.money_tol:
                # Correct, just quoted inclusive of tax. Nothing to tell anyone:
                # a line that reconciles should be silent, and a note on every
                # such line buries the handful that actually need reading.
                return
        ln.r.conflicts.append(f"printed amount {fmt_inr(a)} ≠ {q} × {rt} = {fmt_inr(taxable)}")
        ln.add(LineStatus.ARITHMETIC)


class HeaderChecks:
    def __init__(self, inp: ReconInput) -> None:
        self.inp = inp
        self.cfg = inp.config
        self.out: list[HeaderCheck] = []

    def _confirmed(self, code: str, shown: str) -> dict | None:
        """A person's answer to this exact question, or None.

        `shown` is what they were looking at when they answered. If the document
        is read again and the reference comes out differently, the stored answer
        no longer applies — it was given about other words — so the check asks
        again rather than passing on the strength of a stale yes.
        """
        d = self.inp.confirmed_checks.get(code)
        if not d or d.get("shown") != shown:
            return None
        return d

    def _add(self, code: str, label: str, passed: bool, fail_sev: Severity, detail: str = "", **ev) -> None:
        self.out.append(HeaderCheck(code=code, label=label, severity=OK if passed else fail_sev,
                                    passed=passed, detail=detail, evidence=ev))

    def run(self) -> list[HeaderCheck]:
        inv, po = self.inp.invoice, self.inp.po
        if inv is not None and po is not None:
            self._po_reference()
            self._within_po_value()
            self._payment_terms()
        if inv is not None:
            self._single_po()
            self._receipt_variance()
        self._grn_vs_audit()
        self._payment()
        if inv is not None:
            self._tax_regime()
            self._arithmetic()
            self._header_vs_annexure()
            self._corrections()
            self._duplicate()
        self._vendor_identity()
        self._buyer()
        self._store()
        self._dates()
        self._pods()
        self._approvals()
        return self.out

    def _po_reference(self) -> None:
        """Does the invoice quote the right PO — when it quotes one at all?

        An invoice with no PO number printed on it is not a finding (Bata,
        20 Nov 2026). Plenty of their vendors never print one, the case is
        linked to its PO by other means, and raising a Review that every such
        invoice fails teaches reviewers to scroll past the checks.

        Quoting the WRONG one still is: an invoice billed against a different
        PO would otherwise consume this PO's value in silence.
        """
        a, b = _po_no(self.inp.invoice.po_ref), _po_no(self.inp.po.po_number)
        if a is None:
            return
        self._add("po_reference", "PO number on invoice", a == b, B,
                  "" if a == b else f"Invoice quotes {self.inp.invoice.po_ref}, case PO is {self.inp.po.po_number}")

    def _within_po_value(self) -> None:
        inv, po = self.inp.invoice, self.inp.po
        if inv.taxable is None or po.total is None:
            return
        billed = self.inp.prior_billed_value + inv.taxable
        ok = billed <= po.total + self.cfg.money_tol
        detail = f"Billed ₹{fmt_inr(billed)} of PO ₹{fmt_inr(po.total)}"
        if self.inp.prior_billed_value:
            detail += f" (incl. ₹{fmt_inr(self.inp.prior_billed_value)} on earlier invoices)"
        self._add("within_po_value", "Within PO value", ok, B, detail)

    def _payment(self) -> None:
        """The PAYMENT leg: does the remittance advice settle this invoice, in full?

        Three separate questions, kept apart because they fail for different
        reasons and route to different people:

        * the advice's arithmetic (net = base − TDS) — the payer's own document
          disagreeing with itself;
        * whether the advice names this invoice at all;
        * whether the amount settled equals what was billed.
        """
        adv = self.inp.payment
        if adv is None:
            return
        # 1. the advice's own arithmetic
        bad = [l for l in adv.lines
               if l.base_amount is not None and l.net_amount is not None
               and abs(round2(l.base_amount - l.tds_amount) - l.net_amount) > self.cfg.money_tol]
        if adv.lines:
            self._add("payment_arithmetic", "Payment advice adds up", not bad, B,
                      "" if not bad else
                      "; ".join(f"{l.reference}: {fmt_inr(l.base_amount)} − {fmt_inr(l.tds_amount)} "
                                f"≠ {fmt_inr(l.net_amount)}" for l in bad),
                      lines=[l.reference for l in bad])
        inv = self.inp.invoice
        if inv is None:
            return
        # 2. does it name this invoice? The payer's reference is their own ERP
        #    document number, so accept a match on either side's number.
        want = _invno(inv.invoice_no)
        named = any(_invno(r) == want or want in _invno(r) or _invno(r) in want
                    for r in adv.references if r)
        self._add("payment_reference", "Payment advice names this invoice", named, B,
                  "" if named else
                  f"Advice settles {', '.join(adv.references) or 'nothing we can read'}, "
                  f"invoice is {inv.invoice_no}",
                  references=adv.references, invoice_no=inv.invoice_no)
        # 3. was the full billed amount settled?
        if inv.total is not None and adv.total_base is not None:
            short = round2(inv.total - adv.total_base)
            ok = abs(short) <= self.cfg.money_tol
            self._add("payment_settled_in_full", "Invoice settled in full", ok, I,
                      "" if ok else
                      f"Billed {fmt_inr(inv.total)}, settled {fmt_inr(adv.total_base)} "
                      f"({'short by ' + fmt_inr(short) if short > 0 else 'over by ' + fmt_inr(-short)})",
                      billed=str(inv.total), settled=str(adv.total_base), difference=str(short),
                      tds=str(adv.total_tds) if adv.total_tds is not None else None)

    def _grn_vs_audit(self) -> None:
        """Does the GRN match what the auditor certified? (R3/R8)

        Bata raises the GRN from the certified quantity, so the two agree by
        construction. A difference is a finding about the GRN — somebody keyed
        it differently, or it was raised before the audit — and the wording says
        so, because routing it at the vendor would send people to argue with the
        wrong party.
        """
        lines = self.inp.receipt_lines
        if not lines:
            return
        rows = [r for s in self.inp.evidence for r in s.rows]
        if not rows:
            return
        from .grn import compare_with_audit
        bad = compare_with_audit(lines, rows, qty_tol=self.cfg.qty_tol)
        counts = {k: sum(1 for d in bad if d.kind == k)
                  for k in ("QTY_DIFFERS", "RECEIVED_NOT_CERTIFIED", "CERTIFIED_NOT_RECEIVED")}
        detail = ""
        if bad:
            parts = []
            if counts["QTY_DIFFERS"]:
                ex = next(d for d in bad if d.kind == "QTY_DIFFERS")
                parts.append(f"{counts['QTY_DIFFERS']} line(s) differ "
                             f"(e.g. {ex.label}: certified {ex.certified}, GRN {ex.received})")
            if counts["RECEIVED_NOT_CERTIFIED"]:
                parts.append(f"{counts['RECEIVED_NOT_CERTIFIED']} GRN line(s) with no certified quantity")
            if counts["CERTIFIED_NOT_RECEIVED"]:
                parts.append(f"{counts['CERTIFIED_NOT_RECEIVED']} certified line(s) not on the GRN")
            detail = "; ".join(parts) + " — check how the GRN was raised, not the vendor's invoice"
        self._add("grn_vs_audit", "GRN matches the audit report", not bad, I, detail,
                  counts=counts,
                  examples=[{"line": d.label, "certified": str(d.certified), "grn": str(d.received),
                             "kind": d.kind, "matched_on": d.basis} for d in bad[:5]])

    def _single_po(self) -> None:
        """R6: one invoice may never be processed against two POs.

        Bata has prohibited it outright and told vendors so, which makes this a
        validation failure rather than a variance to weigh.
        """
        if not self.cfg.single_po_per_invoice:
            return
        refs = _po_refs(self.inp.invoice.po_ref)
        if len(refs) > 1:
            self._add("single_po", "One PO per invoice", False, R,
                      f"Invoice quotes {len(refs)} PO numbers: {', '.join(refs)}. "
                      "One invoice cannot be processed against two POs — the vendor must bill them separately.",
                      po_refs=refs)

    def _receipt_variance(self) -> None:
        """R7: invoice over the receipt (GRN) by more than the threshold.

        Abstains when no receipt total is available rather than guessing — the
        GRN arrives as a Microsoft Dynamics extract (plan §7) and until it does
        this check has nothing to compare against. An abstention is visible in
        `abstained`; it is not a pass.
        """
        inv = self.inp.invoice
        receipt, basis = self.inp.receipt_total, self.inp.receipt_basis
        if receipt is None:
            # No Dynamics extract, but a signed delivery proof states what the
            # consignment is worth — and states it INCLUDING tax, which is what
            # a carrier declares. That is the receipt leg for this purchase, so
            # the check runs against it rather than abstaining.
            #
            # Derived here rather than in the loader so that every caller of
            # the engine sees it. While it lived in `CaseBuilder`, the same
            # documents reconciled differently depending on how they arrived.
            declared = [p.total_invoice_value for p in self.inp.pods
                        if p.total_invoice_value is not None]
            if declared:
                receipt, basis = sum(declared[1:], declared[0]), "gross"
        # Compare like with like. A carrier declares what the consignment is
        # worth INCLUDING tax; a Dynamics GRN books goods at the PO price,
        # which excludes it. Holding either against the wrong side of the
        # invoice reports a difference of exactly the GST, every time.
        billed = inv.total if basis == "gross" else inv.taxable
        if receipt is None or billed is None:
            return
        gap = round2(billed - receipt)
        # Both directions raise an exception (Bata, 19 Nov 2026). Over-billing is
        # money at risk; under-billing means we received more than we are being
        # charged for, which is a receipt or GRN problem and still needs a person.
        ok = abs(gap) <= self.cfg.invoice_vs_receipt_tol
        detail = (f"Invoice ₹{fmt_inr(billed)}"
                  + (" incl. tax" if basis == "gross" else "")
                  + f" vs receipt ₹{fmt_inr(receipt)} "
                    f"(difference ₹{fmt_inr(gap)}, threshold ₹{fmt_inr(self.cfg.invoice_vs_receipt_tol)})")
        if not ok:
            detail += (" — costing team approval required" if gap > 0
                       else " — invoice is below the receipt; check the GRN and the vendor's billing")
        self._add("receipt_variance", "Invoice within receipt value", ok, B, detail,
                  invoice=str(billed), basis=basis, receipt=str(receipt), gap=str(gap),
                  direction="over" if gap > 0 else ("under" if gap < 0 else "equal"),
                  threshold=str(self.cfg.invoice_vs_receipt_tol), scope=self.cfg.variance_scope,
                  routes_to="costing_team" if not ok else None)

    def _payment_terms(self) -> None:
        a, b = self.inp.invoice.payment_terms, self.inp.po.payment_terms
        if not a or not b:
            return
        n = lambda s: re.sub(r"[^a-z0-9%]", "", s.lower())
        self._add("payment_terms", "Payment terms", n(a) == n(b), R, f"PO: {b} · Invoice: {a}")

    def _tax_regime(self) -> None:
        inv = self.inp.invoice
        seller = (inv.vendor.gstin or "")[:2] or None
        pos = _state(inv.place_of_supply) or (inv.buyer_gstin or "")[:2] or None
        t = inv.tax
        if not seller or not pos or inv.taxable is None:
            return
        inter = seller != pos
        if inter:
            ok = t.igst > 0 and t.cgst == 0 and t.sgst == 0
            detail = f"Inter-state ({seller} → {pos}): IGST expected"
        else:
            ok = t.igst == 0 and t.cgst > 0 and close(t.cgst, t.sgst, Decimal("0.02"), Decimal("0"))
            detail = f"Intra-state ({seller}): CGST + SGST expected"
        tax = t.igst + t.cgst + t.sgst
        if ok and t.rate is not None:
            want = round2(inv.taxable * t.rate / Decimal(100))
            if not close(tax, want, self.cfg.money_tol, Decimal("0")):
                ok = False
                detail += f"; tax ₹{fmt_inr(tax)} ≠ {t.rate}% of ₹{fmt_inr(inv.taxable)} = ₹{fmt_inr(want)}"
        self._add("tax_regime", "GST type and amount", ok, B, detail)

    def _arithmetic(self) -> None:
        inv = self.inp.invoice
        problems = []
        goods = [l for l in inv.lines if not l.is_charge and sval(l.amount) is not None]
        if inv.printed_subtotal is not None and goods:
            s = sum((sval(l.amount) for l in goods), ZERO)
            if not close(s, inv.printed_subtotal, self.cfg.money_tol, Decimal("0")):
                problems.append(f"line amounts add up to ₹{fmt_inr(s)}, sub total printed ₹{fmt_inr(inv.printed_subtotal)}")
        if inv.taxable is not None and inv.total is not None:
            t = inv.tax
            want = inv.taxable + t.igst + t.cgst + t.sgst + inv.round_off
            if not close(want, inv.total, self.cfg.money_tol, Decimal("0")):
                problems.append(f"taxable + tax = ₹{fmt_inr(want)}, total printed ₹{fmt_inr(inv.total)}")
        self._add("invoice_arithmetic", "Invoice arithmetic", not problems, R, "; ".join(problems))

    def _header_vs_annexure(self) -> None:
        inv = self.inp.invoice
        if not inv.annexure_lines or inv.taxable is None:
            return
        problems = []
        if inv.header_lines:
            h = sum((sval(l.amount) or ZERO for l in inv.header_lines), ZERO)
            if not close(h, inv.taxable, self.cfg.money_tol, Decimal("0")):
                problems.append(f"header lines ₹{fmt_inr(h)} ≠ taxable ₹{fmt_inr(inv.taxable)}")
        if inv.printed_subtotal is not None:
            charges = sum((sval(l.amount) or ZERO for l in inv.annexure_lines if l.is_charge), ZERO)
            a = inv.printed_subtotal + charges
        else:
            a = sum((sval(l.amount) or ZERO for l in inv.annexure_lines), ZERO)
        if not close(a, inv.taxable, self.cfg.money_tol, Decimal("0")):
            problems.append(f"detail page totals ₹{fmt_inr(a)} ≠ taxable ₹{fmt_inr(inv.taxable)}")
        self._add("header_vs_annexure", "Invoice = its detail page", not problems, B, "; ".join(problems))

    def _corrections(self) -> None:
        c = self.inp.invoice.corrections
        if c:
            self._add("handwritten_corrections", "Handwritten changes on invoice", False, R,
                      "; ".join(f"{x.field}: printed {x.printed}, written {x.handwritten}" for x in c))

    def _duplicate(self) -> None:
        inv = self.inp.invoice
        mine = {_invno(inv.invoice_no)} | {_invno(c.printed) for c in inv.corrections if c.field == "invoice_no"}
        hits = [n for n in self.inp.other_invoice_numbers if _invno(n) in mine]
        self._add("duplicate_invoice", "Not billed before", not hits, B,
                  f"Same number already on: {', '.join(hits)}" if hits else "")

    def _vendor_identity(self) -> None:
        seen: dict[str, str] = {}
        if self.inp.po and self.inp.po.vendor.gstin:
            seen["PO"] = self.inp.po.vendor.gstin
        if self.inp.invoice and self.inp.invoice.vendor.gstin:
            seen["Invoice"] = self.inp.invoice.vendor.gstin
        for s in self.inp.evidence:
            if s.vendor.gstin:
                seen[f"Report ({s.section_title or 'section'})"] = s.vendor.gstin
        if len(seen) < 2:
            return
        ok = len({g.upper() for g in seen.values()}) == 1
        self._add("vendor_identity", "Same vendor GSTIN everywhere", ok, B,
                  "" if ok else " · ".join(f"{k}: {v}" for k, v in seen.items()))

    def _buyer(self) -> None:
        po, inv = self.inp.po, self.inp.invoice
        if po and inv and po.buyer_gstin and inv.buyer_gstin:
            ok = po.buyer_gstin.upper() == inv.buyer_gstin.upper()
            self._add("buyer_gstin", "Billed to the PO's Bata GSTIN", ok, R,
                      "" if ok else f"PO: {po.buyer_gstin} · Invoice: {inv.buyer_gstin}")

    def _store(self) -> None:
        sns: dict[str, str] = {}
        if self.inp.po and self.inp.po.store_sn:
            sns["PO"] = self.inp.po.store_sn
        for s in self.inp.evidence:
            if s.store_sn:
                sns["Report"] = s.store_sn
        for m in self.inp.memos:
            if m.store_sn:
                sns["Memo"] = m.store_sn
        if len(sns) >= 2:
            ok = len({v.lstrip("0") for v in sns.values()}) == 1
            self._add("store_consistency", "Same store on every document", ok, R,
                      " · ".join(f"{k}: {v}" for k, v in sns.items()))

    def _dates(self) -> None:
        po, inv = self.inp.po, self.inp.invoice
        problems = []
        if po and inv and po.po_date and inv.invoice_date and inv.invoice_date < po.po_date:
            problems.append(f"invoice {inv.invoice_date:%d-%m-%Y} is before the PO {po.po_date:%d-%m-%Y}")
        for s in self.inp.evidence:
            if po and po.po_date and s.verification_date and s.verification_date < po.po_date:
                problems.append(f"report dated {s.verification_date:%d-%m-%Y}, before the PO")
        if problems:
            self._add("date_order", "Dates in order", False, R, "; ".join(problems))

    def _pods(self) -> None:
        inv, po = self.inp.invoice, self.inp.po
        for pod in self.inp.pods:
            problems = []
            misread = None
            if inv:
                if pod.invoice_nos and _invno(inv.invoice_no) not in {_invno(n) for n in pod.invoice_nos}:
                    # A carrier's waybill is a scan of handwriting and dot-matrix
                    # print, so the reference differs from the invoice by exactly
                    # the characters a reader confuses (vocabulary §16
                    # OCR_CHAR_CONFUSION). Treat that as the same reference, but
                    # only when the document's own value agrees too — one
                    # corroborating fact, so a genuinely different consignment
                    # cannot be absorbed by a spelling allowance.
                    value_agrees = (pod.total_invoice_value is not None and inv.total is not None
                                    and close(pod.total_invoice_value, inv.total,
                                              self.cfg.money_tol, Decimal("0")))
                    why = next((w for n in pod.invoice_nos
                                if (w := same_consignment(n, inv.invoice_no, value_matches=value_agrees))),
                               None)
                    if why:
                        # Corroborated is not the same as read. The reference on
                        # the paper is NOT this invoice's number, and the reason
                        # it is accepted is an inference about a scanner plus a
                        # value that agrees — both of which a person can check in
                        # seconds and a machine should not settle alone. So the
                        # POD is used as receipt evidence, and the case carries a
                        # flag saying exactly what was assumed.
                        misread = (f"POD reads {pod.invoice_nos[0]}, the invoice is {inv.invoice_no} "
                                   f"— {why}")
                    else:
                        problems.append(f"POD lists {', '.join(pod.invoice_nos)}, not {inv.invoice_no}")
                if pod.total_invoice_value is not None and inv.total is not None and \
                        not close(pod.total_invoice_value, inv.total, self.cfg.money_tol, Decimal("0")):
                    problems.append(f"POD value ₹{fmt_inr(pod.total_invoice_value)} ≠ invoice total ₹{fmt_inr(inv.total)}")
            if pod.receipt.date is None and not pod.receipt.stamp_text:
                problems.append("no receipt stamp or date")
            self._add("pod_matches", "Delivery proof matches invoice", not problems, B,
                      "; ".join(problems) or (misread or ""), waybill=pod.waybill_no,
                      misread_reference=misread)
            if misread and not problems:
                # Its own check, at REVIEW: it must not block a payment the value
                # and the stamp both support, and it must not disappear into a
                # tick either. Somebody confirms the waybill is this consignment.
                shown = f"{pod.invoice_nos[0]}|{inv.invoice_no if inv else ''}"
                ok = self._confirmed("pod_invoice_ref_match", shown)
                self._add("pod_invoice_ref_match", "POD names the invoice", bool(ok), R,
                          misread + (f" — confirmed by {ok['actor']}" if ok
                                     else " — confirm this waybill is for this invoice"),
                          waybill=pod.waybill_no, pod_reference=pod.invoice_nos[0],
                          invoice_no=inv.invoice_no if inv else None,
                          basis="corroborated_by_value",
                          needs=None if ok else "human_confirmation",
                          confirmable=shown,
                          confirmed_by=ok["actor"] if ok else None,
                          confirmed_at=ok.get("at") if ok else None,
                          confirmed_note=ok.get("note") if ok else None)
            due = po.delivery_date if po else None
            if po and due is None:
                dd = [l.delivery_date for l in po.lines if l.delivery_date]
                due = max(dd) if dd else None
            got = pod.receipt.date
            if due and got:
                late = (got - due).days
                if late <= 0:
                    self._add("delivery_timeliness", "Delivered on time", True, R,
                              f"Received {got:%d-%m-%Y}, due {due:%d-%m-%Y}")
                else:
                    pen = self.penalty(late)
                    self._add("delivery_timeliness", "Delivered on time", False, R,
                              f"{late} days late (due {due:%d-%m-%Y}, received {got:%d-%m-%Y})"
                              + (f"; PO penalty ₹{fmt_inr(pen)}" if pen else ""), penalty=str(pen or 0))

    def penalty(self, late_days: int) -> Decimal | None:
        po = self.inp.po
        if not po or not po.penalties or po.subtotal is None:
            return None
        total = ZERO
        for t in po.penalties:
            if late_days < t.days_from:
                continue
            if t.per_day:
                days = (min(late_days, t.days_to) if t.days_to else late_days) - t.days_from + 1
                total += po.subtotal * t.pct / 100 * days
            else:
                total = po.subtotal * t.pct / 100     # bands replace, they don't stack
        return round2(total)

    def _approvals(self) -> None:
        for m in self.inp.memos:
            pending = [a.approver for a in m.approvals if a.status.strip().lower() != "approved"]
            remarks = "; ".join(f"{a.approver}: {a.remark}" for a in m.approvals if a.remark)
            self._add("approvals", f"Approval memo {m.memo_ref or ''}".strip(), not pending, I,
                      (f"Pending: {', '.join(pending)}" if pending else "All approved") + (f" · {remarks}" if remarks else ""))


class ReconEngine:
    version = C.ENGINE_VERSION

    def run(self, inp: ReconInput) -> ReconResult:
        lines = LineChecks(inp).run()
        header = HeaderChecks(inp).run()
        return ReconResult(header=header, lines=lines, summary=self._summary(inp, lines, header),
                           engine_version=self.version)

    @staticmethod
    def _summary(inp: ReconInput, lines: list[LineResult], header: list[HeaderCheck]) -> ReconSummary:
        counts = {s.value: 0 for s in (B, R, I)}
        for l in lines:
            if l.severity in (B, R, I):
                counts[l.severity.value] += 1
        for h in header:
            if not h.passed and h.severity in (B, R, I):
                counts[h.severity.value] += 1
        conf, weakest = _pairing_confidence(lines)
        po_lines = [l for l in lines if l.kind == "po"]
        goods = [l for l in po_lines if not l.is_charge and LineStatus.PCT_CHARGE_MISMATCH not in l.statuses]
        risk = sum((l.delta for l in lines if l.delta > 0 and l.severity.rank >= R.rank), ZERO)
        for h in header:
            if h.code == "delivery_timeliness" and h.evidence.get("penalty"):
                risk += Decimal(h.evidence["penalty"])
        under = sum((-l.delta for l in lines if l.delta < 0 and (
            LineStatus.UNDER_BILLED in l.statuses or LineStatus.PCT_CHARGE_MISMATCH in l.statuses)), ZERO)
        # R5: out-of-PO lines have a prescribed remedy — a vendor credit note —
        # so the case waits on that document rather than on a reviewer's opinion.
        # Only when the credit note is the *only* outstanding thing: a rate
        # breach or a quantity over the PO still needs a person first.
        out_of_po = [l for l in lines if LineStatus.NOT_IN_PO in l.statuses]
        other_findings = [l for l in lines
                          if l.severity.rank >= R.rank and LineStatus.NOT_IN_PO not in l.statuses]
        # Two header checks fail *because of* the out-of-PO lines, not
        # independently of them: the invoice is booked at full value, so it
        # exceeds both the PO value and the receipt. Bata's process expects
        # exactly that and clears it with the credit note, so they are not
        # separate findings when the excess accounts for them.
        excess = sum((l.delta for l in out_of_po), ZERO)
        explained = set()
        if out_of_po:
            for h in header:
                if h.code not in ("within_po_value", "receipt_variance") or h.passed:
                    continue
                over = Decimal(h.evidence.get("gap") or 0) if h.code == "receipt_variance" else None
                if over is None:
                    billed = inp.invoice.taxable if inp.invoice and inp.invoice.taxable is not None else ZERO
                    po_total = inp.po.total if inp.po and inp.po.total is not None else ZERO
                    over = billed + inp.prior_billed_value - po_total
                if over <= excess + inp.config.money_tol:
                    explained.add(h.code)
        header_findings = [h for h in header
                           if not h.passed and h.severity in (B, R) and h.code not in explained]
        # R10: no receipt leg at all — the invoice arrived before the audit
        # report. Not a failure, and not a reconciliation either.
        no_receipt = (not any(s.rows for s in inp.evidence) and inp.receipt_total is None
                      and not inp.pods)
        if inp.po is None:
            status = CaseStatus.AWAITING_PO
        elif inp.invoice is None:
            status = CaseStatus.AWAITING_INVOICE
        # The credit note is checked first: it is an actionable claim on the
        # vendor with money attached, whereas waiting for the audit report is an
        # ordinary stage of the process. A case that needs both should show the
        # one somebody has to act on.
        elif out_of_po and not other_findings and not header_findings:
            status = CaseStatus.AWAITING_CREDIT_NOTE
        elif no_receipt and not other_findings and not header_findings:
            status = CaseStatus.AWAITING_RECEIPT
        elif counts["BLOCKER"] or counts["REVIEW"]:
            status = CaseStatus.NEEDS_REVIEW
        else:
            status = CaseStatus.RECONCILED
        return ReconSummary(
            po_total=inp.po.subtotal if inp.po else None,
            expected_goods=round2(sum((l.expected_amt for l in goods), ZERO)),
            expected_total=round2(sum((l.expected_amt for l in po_lines), ZERO)),
            billed_goods=round2(sum((l.billed_amt for l in lines if not l.is_charge), ZERO)),
            invoice_total=(inp.invoice.total if inp.invoice else None),
            billed_total=inp.invoice.taxable if inp.invoice and inp.invoice.taxable is not None
            else round2(sum((l.billed_amt for l in lines), ZERO)),
            rollup_lines=[{"sno": l.sno, "description": l.description,
                           "amount": str(sval(l.amount))}
                          for l in (inp.invoice.lines if inp.invoice else []) if l.is_rollup],
            money_at_risk=round2(risk), under_billed=round2(under), counts=counts, status=status,
            confidence=conf, confidence_weakest=weakest,
            leg_cover=_leg_cover(inp, lines, conf),
        )
