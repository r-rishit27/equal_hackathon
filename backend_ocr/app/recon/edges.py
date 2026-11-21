"""The match surface as a rebuildable projection (docs/reconciliation/RECON_IMPLEMENTATION_PLAN.md §3, R-III).

Rule R-III: *wipe it, rebuild it, lose nothing.* Everything here is derived from
`recon_line_results` and `recon_decisions`; nothing is authored in an edge. That
is the difference between this and Plan B, where reviewer confirmations lived in
the graph and a rebuild destroyed them (0 of 23 survived in the bake-off).

The shape matches what a graph projection would hold, so if TigerGraph is ever
adopted it loads from these same rows and nothing above this layer changes.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

# Edge kinds. One per question the rules actually ask.
BILLS_AGAINST = "BILLS_AGAINST"    # an invoice line bills against a PO line
CERTIFIES = "CERTIFIES"            # an audit/evidence row certifies a PO line
RECEIVED_FOR = "RECEIVED_FOR"      # a receipt (GRN/POD) covers a PO line
PAID_BY = "PAID_BY"                # an invoice is settled by a payment advice
COVERED_BY = "COVERED_BY"          # an invoice line is offset by a credit note

KINDS = (BILLS_AGAINST, CERTIFIES, RECEIVED_FOR, PAID_BY, COVERED_BY)


@dataclass(frozen=True, order=True)
class Edge:
    """One derived relationship.

    Ordered and frozen so a rebuild can be compared with `==` on the whole set —
    which is exactly how acceptance test 7 is written.
    """
    kind: str
    src_key: str
    dst_key: str
    method: str = ""
    score: float = 0.0
    confirmed: bool = False

    def identity(self) -> tuple[str, str, str]:
        """What makes two edges the same edge, ignoring how they were scored."""
        return (self.kind, self.src_key, self.dst_key)


def derive(line_results: Iterable, *, confirmed_keys: set[str] | None = None,
           payment_refs: Iterable[tuple[str, str]] = ()) -> list[Edge]:
    """Build the edge set for one case.

    `line_results` are `types.LineResult`s — they already carry the alignment the
    engine used (`po_key`, `invoice_key`, `evidence_key`) plus how it was found.
    `confirmed_keys` are the `other_key`s a reviewer confirmed, so a confirmation
    shows on the edge without being *stored* only there.
    `payment_refs` are `(invoice_key, payment_key)` pairs for the PAYMENT leg.

    Deterministic: same inputs, same list, same order.
    """
    confirmed_keys = confirmed_keys or set()
    out: list[Edge] = []
    for l in line_results:
        po, inv, ev = getattr(l, "po_key", None), getattr(l, "invoice_key", None), getattr(l, "evidence_key", None)
        method = getattr(getattr(l, "match_method", None), "value", "") or ""
        score = float(getattr(l, "match_score", 0.0) or 0.0)
        if po and inv:
            out.append(Edge(kind=BILLS_AGAINST, src_key=inv, dst_key=po, method=method,
                            score=score, confirmed=inv in confirmed_keys))
        if po and ev:
            out.append(Edge(kind=CERTIFIES, src_key=ev, dst_key=po, method=method,
                            score=score, confirmed=ev in confirmed_keys))
    for inv_key, pay_key in payment_refs:
        if inv_key and pay_key:
            out.append(Edge(kind=PAID_BY, src_key=inv_key, dst_key=pay_key, method="REFERENCE", score=1.0))
    # Sorted so a rebuild is byte-identical regardless of row order from the DB.
    return sorted(set(out))


def diff(a: Iterable[Edge], b: Iterable[Edge]) -> tuple[list[Edge], list[Edge]]:
    """Edges only in `a`, and edges only in `b` — for verifying a rebuild."""
    sa, sb = set(a), set(b)
    return sorted(sa - sb), sorted(sb - sa)
