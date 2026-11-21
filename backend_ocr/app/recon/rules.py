"""Bata's billing rule (03_LLD_BACKEND.md §11; proof in BATA_RECON_ANALYSIS_AND_PLAN.md §4).

    billable qty = min(PO qty, verified qty), at the PO rate
    items the auditor could not count  → PO qty
    items the auditor found not done   → 0
    items found on site but not in PO  → 0 (needs a PO amendment)
"""
from __future__ import annotations

import re
from decimal import Decimal

from .num import ZERO, round2
from .types import AuditVerdict, ChargeBasis, EvidenceRow, RuleConfig, sval

_NOT_COVERED = re.compile(r"not covered|out of audit|^\s*n/?a\s*\.?$", re.I)
_NOT_COUNTABLE = re.compile(
    r"not in scope|as per bata instruction|tonnage could not|could not be checked|best judg", re.I)
_NOT_DONE = re.compile(
    r"not done|not performed|not installed|not found|not allowed separately|not executed|not supplied", re.I)

# Remarks that say nothing beyond "we measured it".
_BOILERPLATE = re.compile(
    r"^\s*(-|–|—|nil|ok|na|n/a)?\s*$|verification\s+is\s+done\s+through|^the (work|item)( or work)? is related to", re.I)


class VerdictClassifier:
    """What the auditor's row says about an item (§11.1). Order matters."""

    def __init__(self, config: RuleConfig | None = None) -> None:
        self.config = config or RuleConfig()
        self._overrides = [(re.compile(p, re.I), v) for p, v in self.config.verdict_overrides.items()]

    def classify(self, row: EvidenceRow) -> AuditVerdict:
        if row.row_type == "additional":
            return AuditVerdict.ADDITIONAL
        if row.verdict is not None:
            return row.verdict
        remark = (row.remark or "").strip()
        audit = sval(row.audit_qty)
        for rx, verdict in self._overrides:
            if remark and rx.search(remark):
                return verdict
        if audit is None or audit == 0:
            if remark and _NOT_DONE.search(remark):
                return AuditVerdict.NOT_DONE
            if remark and _NOT_COVERED.search(remark):
                return AuditVerdict.NOT_COVERED
            if remark and _NOT_COUNTABLE.search(remark):
                return AuditVerdict.NOT_COUNTABLE
        if audit is None:
            return self.config.blank_audit_means
        if audit == 0:
            return AuditVerdict.NOT_DONE
        return AuditVerdict.VERIFIED


def is_boilerplate(remark: str | None) -> bool:
    return not remark or bool(_BOILERPLATE.search(remark))


class BillingRule:
    def __init__(self, config: RuleConfig | None = None) -> None:
        self.config = config or RuleConfig()
        self.verdicts = VerdictClassifier(self.config)

    def expected_qty(self, po_qty: Decimal, row: EvidenceRow | None) -> tuple[Decimal, AuditVerdict]:
        if row is None:
            return po_qty, AuditVerdict.UNKNOWN
        v = self.verdicts.classify(row)
        if v in (AuditVerdict.NOT_COVERED, AuditVerdict.NOT_COUNTABLE, AuditVerdict.UNKNOWN):
            return po_qty, v
        if v in (AuditVerdict.NOT_DONE, AuditVerdict.ADDITIONAL):
            return ZERO, v
        audit = sval(row.audit_qty) or ZERO
        return (min(po_qty, audit) if self.config.cap_at_po else audit), v

    def charge_basis(self, description: str) -> ChargeBasis | None:
        for pattern, basis in self.config.charge_rules.items():
            if re.search(pattern, description or "", re.I):
                return basis
        return None

    def expected_charge(self, basis: ChargeBasis, po_amount: Decimal, pct: Decimal | None,
                        goods_expected: Decimal) -> Decimal:
        if basis == ChargeBasis.FIXED or pct is None:
            return po_amount
        by_pct = round2(pct / Decimal(100) * goods_expected)
        if basis == ChargeBasis.PERCENT_OF_GOODS:
            return by_pct
        return min(by_pct, po_amount)


def audit_row_rate(ev: EvidenceRow) -> Decimal | None:
    """The rate the report settled on: after the discount where it prints one."""
    if ev is None:
        return None
    return ev.rate_after_discount if ev.rate_after_discount is not None else ev.rate


def audit_row_value(ev: EvidenceRow) -> Decimal | None:
    """What the AUDITED quantity is worth at the report's own rate.

    Zero where the auditor certified nothing — and that zero is the point: the
    line is priced on the paper and none of it was done, so the site supports
    nothing for it. None where the report carries no rate at all, since a zero
    there would say the same thing about a row we simply cannot price.
    """
    rate = audit_row_rate(ev)
    qty = sval(ev.audit_qty) if ev is not None else None
    if rate is None or qty is None:
        return None
    return round2(qty * rate)


def audit_row_arithmetic(ev: EvidenceRow, tol: Decimal = Decimal("1.00")) -> str | None:
    """Does the total the site report prints agree with its own rate and quantity?

    These reports extend the **ordered** quantity, not the audited one — a row
    reading `QTY 3 · RATE 6,700 · AFTER 5% 6,365 · TOTAL 19,095` is 3 × 6,365,
    even where the auditor went on to certify something else. So the check is
    against `po_qty`, and checking it against the audited quantity would raise
    a difference on every row the auditor corrected.

    A disagreement is almost always a misread figure: these are scans, and a
    rate read as 6,365 when it says 6,866 is invisible until its own total
    contradicts it. Returns the sentence to show, or None when it adds up or
    the row does not carry enough to check.
    """
    rate = ev.rate_after_discount if ev.rate_after_discount is not None else ev.rate
    if rate is None or ev.po_qty is None or ev.amount is None:
        return None
    want = round2(ev.po_qty * rate)
    if abs(want - ev.amount) <= tol:
        return None
    return (f"printed total ₹{ev.amount:,.2f} is not {ev.po_qty:g} × ₹{rate:,.2f} "
            f"(₹{want:,.2f}) — check the figures on the scan")
