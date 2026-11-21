"""Named rule profiles (RECON_IMPLEMENTATION_PLAN.md §5).

A client's billing policy is configuration, not code. `RuleConfig`'s defaults
stay as they shipped so existing tenants are unaffected; a profile is an
explicit, named departure from them.

Bata's profile is not a preference — every value traces to a statement made on
the call of 16 November 2026, recorded in `QUESTIONS_FOR_BATA.md`. Each one
carries the rule number it implements so a future reader can check it against
the source rather than guess why it is set.
"""
from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

from .types import RuleConfig

DEFAULT = RuleConfig()

BATA = RuleConfig(
    # R2: "the rate is fixed on the PO"; any variation needs a new PO, so the
    # shipped ±₹0.50 tolerance must not absorb an overcharge.
    rate_must_equal=True,
    # R2/R3: payable is the audit-certified quantity, capped at the PO.
    cap_at_po=True,
    # R7: "below 100 rupees it just gets booked; more than 100 goes for
    # exceptional approval" — absolute rupees, both directions (19 Nov 2026).
    invoice_vs_receipt_tol=Decimal("100.00"),
    # Confirmed 18 Nov 2026: per invoice, not per line.
    variance_scope="invoice",
    # R6: "one invoice cannot be processed against two POs" — prohibited.
    single_po_per_invoice=True,
)

PROFILES: dict[str, RuleConfig] = {"default": DEFAULT, "bata": BATA}


def resolve(name: str | None, **overrides) -> RuleConfig:
    """Profile by name, with optional per-tenant overrides applied on top.

    An unknown name falls back to the default rather than raising: a typo in a
    tenant setting must not stop reconciliation, and the default is the
    conservative choice (wider tolerances flag less, never pay more).
    """
    base = PROFILES.get((name or "default").strip().lower(), DEFAULT)
    return replace(base, **overrides) if overrides else base


def describe(cfg: RuleConfig) -> dict[str, str]:
    """The settings that decide money, for the audit trail and the run header."""
    return {
        "rate_must_equal": str(cfg.rate_must_equal),
        "cap_at_po": str(cfg.cap_at_po),
        "invoice_vs_receipt_tol": str(cfg.invoice_vs_receipt_tol),
        "variance_scope": cfg.variance_scope,
        "single_po_per_invoice": str(cfg.single_po_per_invoice),
        "rate_abs_tol": str(cfg.rate_abs_tol),
        "money_tol": str(cfg.money_tol),
    }
