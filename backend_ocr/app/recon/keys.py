"""Stable line identity (docs/reconciliation/RECON_IMPLEMENTATION_PLAN.md §6.1).

Why this exists
---------------
Line identity used to be the row's surrogate uuid (`ev:<uuid>`, `rl:<uuid>`,
assigned in `repo._save_*`). Re-extraction deletes and re-inserts those rows, so
every uuid changes and every reviewer decision keyed on it is orphaned — the
"22 of 26 confirmed matches lost" result in the architecture bake-off.

A *natural* key is derived from what the document itself prints, so the same
printed line yields the same key on every extraction of that document.

The ladder, strongest first
---------------------------
1. ``ASSET_CODE``    the asset / FA code printed on the row
2. ``PRINTED_NO``    printed serial number **plus** the normalised description
3. ``NORM_DESC``     normalised description + unit + rate fingerprint
4. ``ORDINAL``       position in the table — a last resort, and NOT trusted

Position alone is never rungs 1–3. The bake-off showed that carrying a decision
forward by position put a battery correction onto the wrong line (an MCP hooter)
with no warning. Rung 4 exists so that every row *has* a key, but it is marked
untrusted (confidence below ``TRUST_FLOOR``) and the caller must ask a human to
re-confirm rather than migrate a decision silently.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from decimal import Decimal

from .normalize import norm

# A key basis at or above this confidence may carry a decision across a
# re-extraction unattended. Below it, the decision needs a human re-confirm.
TRUST_FLOOR = 0.80

CONFIDENCE: dict[str, float] = {
    "ASSET_CODE": 0.99,
    "PRINTED_NO": 0.95,
    "NORM_DESC": 0.85,
    "ORDINAL": 0.40,   # deliberately below TRUST_FLOOR
    "HUMAN": 1.00,     # a reviewer bound this line by hand
}

_KEY_MAX = 120          # recon_*.natural_key is VARCHAR(120)
_CODE_CLEAN = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class LineKey:
    """A natural key plus how it was derived."""
    key: str
    basis: str
    confidence: float

    @property
    def trusted(self) -> bool:
        return self.confidence >= TRUST_FLOOR


def _h(*parts: object) -> str:
    """Short, stable digest of the parts. Bounds key length and hides raw text."""
    raw = "\x1f".join("" if p is None else str(p) for p in parts)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def _code(v: str) -> str:
    return _CODE_CLEAN.sub("-", v.strip().lower()).strip("-")


def _money(v: Decimal | float | int | None) -> str:
    """Rate/amount fingerprint. Quantised so 850 and 850.00 agree."""
    if v is None:
        return ""
    try:
        return format(Decimal(str(v)).quantize(Decimal("0.0001")).normalize(), "f")
    except Exception:
        return str(v)


def _fit(key: str) -> str:
    return key if len(key) <= _KEY_MAX else f"{key[:_KEY_MAX - 13]}~{_h(key)}"


def build(
    *,
    leg: str,
    asset_code: str | None = None,
    sno: int | None = None,
    description: str | None = None,
    unit: str | None = None,
    rate: Decimal | float | int | None = None,
    ordinal: int | None = None,
) -> LineKey:
    """Derive the strongest available natural key for one line.

    `leg` namespaces the key so a PO line, an invoice line and an audit row that
    happen to print the same thing never collide.
    """
    lg = _code(leg or "x")
    desc_norm = norm(description) if description else ""

    if asset_code and _code(asset_code) not in ("", "-", "na", "n-a", "nil"):
        return LineKey(_fit(f"{lg}/a/{_code(asset_code)}"), "ASSET_CODE", CONFIDENCE["ASSET_CODE"])

    if sno is not None and desc_norm:
        return LineKey(_fit(f"{lg}/n/{sno}/{_h(desc_norm)}"), "PRINTED_NO", CONFIDENCE["PRINTED_NO"])

    if desc_norm:
        return LineKey(_fit(f"{lg}/d/{_h(desc_norm, _code(unit or ''), _money(rate))}"),
                       "NORM_DESC", CONFIDENCE["NORM_DESC"])

    return LineKey(_fit(f"{lg}/o/{ordinal if ordinal is not None else sno or 0}"),
                   "ORDINAL", CONFIDENCE["ORDINAL"])


def for_evidence_row(row, ordinal: int | None = None) -> LineKey:
    """Natural key for a `types.EvidenceRow` (audit report / site sheet)."""
    return build(leg="receipt", asset_code=row.asset_code, sno=row.sno, description=row.item,
                 unit=row.unit, rate=row.rate_after_discount or row.rate, ordinal=ordinal)


def for_invoice_line(line, ordinal: int | None = None) -> LineKey:
    """Natural key for a `types.InvoiceLine`."""
    return build(leg="billing", sno=line.sno, description=line.description, unit=line.unit,
                 rate=line.rate.value if line.rate else None, ordinal=ordinal)


def for_po_line(line, ordinal: int | None = None) -> LineKey:
    """Natural key for a `types.POLine`."""
    return build(leg="commitment", sno=line.sno, description=line.description, unit=line.unit,
                 rate=line.unit_price, ordinal=ordinal)


def disambiguate(keys: list[LineKey]) -> list[LineKey]:
    """Make keys unique within one document.

    Two rows can legitimately derive the same key (the same item billed twice on
    one invoice). A duplicate gets an occurrence suffix, and — because the pairing
    of occurrence to row is now positional — it drops to ORDINAL **basis and**
    confidence, so a decision on it is re-confirmed rather than migrated silently.

    The basis matters as much as the number. Keeping the original basis left
    rows reading `ASSET_CODE` at confidence 0.40 — claiming to be identified by
    a printed code while scored as identified by position. A reviewer reads the
    basis to understand *how* a line was recognised, and that one was lying;
    13 such rows were sitting in dev. The key still carries the code it came
    from, so nothing is lost by saying plainly that the pairing is positional.
    """
    seen: dict[str, int] = {}
    out: list[LineKey] = []
    for k in keys:
        n = seen.get(k.key, 0)
        seen[k.key] = n + 1
        if n == 0:
            out.append(k)
        else:
            out.append(LineKey(_fit(f"{k.key}#{n + 1}"), "ORDINAL", CONFIDENCE["ORDINAL"]))
    return out
