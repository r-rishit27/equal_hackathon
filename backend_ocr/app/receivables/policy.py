"""The decision policy: what the agent may do alone (05_HUMAN_IN_THE_LOOP.md).

Pure. The engine says how well a payment is explained; the policy says whether
that is good enough to act on without a person, using the tenant's settings.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from .matching import MatchResult

# The only explanations that account for the amount to the rupee with nothing held back.
AUTO_KINDS = frozenset({"remittance", "reference_exact", "amount_exact"})
TDS_KINDS = frozenset({"reference_tds", "amount_tds"})


@dataclass(frozen=True)
class Policy:
    auto_apply_enabled: bool = True
    auto_apply_threshold: Decimal = Decimal("0.95")
    amount_tolerance: Decimal = Decimal("1.00")
    writeoff_tolerance: Decimal = Decimal("0")
    tds_rates: tuple[Decimal, ...] = (Decimal("0.1"), Decimal("1"), Decimal("2"), Decimal("5"), Decimal("10"))
    trust_learned_tds: bool = False

    @classmethod
    def from_row(cls, row: dict | None) -> "Policy":
        if not row:
            return cls()
        return cls(
            auto_apply_enabled=bool(row["auto_apply_enabled"]),
            auto_apply_threshold=Decimal(str(row["auto_apply_threshold"])),
            amount_tolerance=Decimal(str(row["amount_tolerance"])),
            writeoff_tolerance=Decimal(str(row["writeoff_tolerance"])),
            tds_rates=tuple(Decimal(str(r)) for r in (row["tds_rates"] or [])) or cls.tds_rates,
            trust_learned_tds=bool(row["trust_learned_tds"]),
        )

    def to_json(self) -> dict:
        return {
            "auto_apply_enabled": self.auto_apply_enabled,
            "auto_apply_threshold": str(self.auto_apply_threshold),
            "amount_tolerance": str(self.amount_tolerance),
            "writeoff_tolerance": str(self.writeoff_tolerance),
            "tds_rates": [str(r) for r in self.tds_rates],
            "trust_learned_tds": self.trust_learned_tds,
        }


@dataclass
class Decision:
    action: str                      # AUTO | REVIEW | UNMATCHED
    reason: str
    flags: list[str] = field(default_factory=list)


def _pct(v: Decimal) -> str:
    return f"{(Decimal(v) * 100).quantize(Decimal('1'))}%"


def decide(result: MatchResult, policy: Policy, *, customer_tds_hint: Decimal | None = None) -> Decision:
    best = result.best
    if best is None or not best.allocations:
        return Decision("UNMATCHED", "Nothing among the open invoices explains this payment", result.flags)
    if result.flags:
        return Decision("REVIEW", "Flagged: " + ", ".join(result.flags), result.flags)
    if not policy.auto_apply_enabled:
        return Decision("REVIEW", "Auto-apply is switched off for this company")
    if best.unapplied > 0:
        return Decision("REVIEW", "Money would be left on account — a person decides what happens to it")
    # Graduated autonomy: TDS at the rate a person already confirmed for this
    # customer, on an invoice the customer quoted (off unless the tenant opts in).
    if best.kind == "reference_tds" and policy.trust_learned_tds and customer_tds_hint is not None:
        rates = {a.tds_rate for a in best.allocations if a.tds_amount}
        if rates == {customer_tds_hint}:
            return Decision("AUTO", f"TDS at this customer's confirmed rate {customer_tds_hint}%")
    if best.confidence < policy.auto_apply_threshold:
        return Decision("REVIEW", f"{_pct(best.confidence)} sure — below the {_pct(policy.auto_apply_threshold)} needed to apply on its own")
    if best.kind in AUTO_KINDS:
        if any(a.deduction_amount for a in best.allocations):
            return Decision("REVIEW", "A deduction is involved — a person confirms it")
        return Decision("AUTO", "Exact match")
    return Decision("REVIEW", "Matches of this kind always need a person to confirm")
