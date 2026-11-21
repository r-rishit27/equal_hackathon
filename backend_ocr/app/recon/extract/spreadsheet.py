"""SpreadsheetMapper — xlsx/csv uploads (03_LLD_BACKEND.md §10.9).

Reuses core.vendor_doc_tables.parse_spreadsheet (header detection, Indian number
coercion). Each sheet's columns are mapped to roles by header name; a sheet with
an audit-qty column is evidence, one with PO qty + rate and no audit column is a
PO, anything else is reference only. Unclear mappings are flagged (E-IN-05).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from rapidfuzz import fuzz

from ..num import parse_inr, round2
from ..types import EvidenceRow, ExtractedOther, ExtractedPO, POLine, PVSection, SegmentKind, Sourced

_ROLES = {
    "item": ["item name", "item", "description", "particulars", "material description", "product"],
    "unit": ["unit", "uom"],
    "po_qty": ["qty as per po", "po qty", "qty", "quantity", "ordered qty"],
    "vendor_qty": ["vendor qty", "given qty", "given vendor qty", "claimed qty"],
    "audit_qty": ["audit qty", "verified qty", "actual qty", "measured qty"],
    "rate": ["rate after 5%", "rate", "unit price", "unit rate", "price"],
    "amount": ["amount", "total", "value"],
    "remark": ["remarks", "remark", "notes"],
}


@dataclass
class SheetDoc:
    sheet: str
    kind: SegmentKind
    roles: dict[str, str]
    confidence: float
    doc: object
    warnings: list[str] = field(default_factory=list)


def column_roles(columns: list[str]) -> tuple[dict[str, str], float]:
    """role → column name, and the weakest header match (0–1)."""
    used: set[str] = set()
    out: dict[str, str] = {}
    weakest = 1.0
    for role in ("audit_qty", "vendor_qty", "po_qty", "item", "unit", "rate", "amount", "remark"):
        best, score = None, 0.0
        for c in columns:
            if c in used:
                continue
            cl = re.sub(r"\s+", " ", str(c).lower()).strip()
            s = max(fuzz.ratio(cl, n) for n in _ROLES[role]) / 100
            if any(cl.startswith(n) for n in _ROLES[role]):
                s = max(s, 0.92)
            if s > score:
                best, score = c, s
        if best is not None and score >= 0.75:
            out[role] = best
            used.add(best)
            weakest = min(weakest, score)
    return out, weakest


def map_sheets(file_name: str, contents: bytes) -> list[SheetDoc]:
    from ...core.vendor_doc_tables import parse_spreadsheet
    out = []
    for meta, rows in parse_spreadsheet(file_name, contents):
        cols = [c["name"] for c in meta["columns"]]
        roles, conf = column_roles(cols)
        g = lambda r, k: r.get(roles[k]) if k in roles else None
        if "item" not in roles:
            out.append(SheetDoc(meta["sheet_name"], SegmentKind.OTHER, roles, conf,
                                ExtractedOther(llm_label=f"Spreadsheet: {meta['sheet_name']}")))
            continue
        if "audit_qty" in roles:
            ev = []
            for n, r in rows:
                item = str(g(r, "item") or "").strip()
                if not item:
                    continue
                aq = parse_inr(g(r, "audit_qty"))
                vq = parse_inr(g(r, "vendor_qty"))
                ev.append(EvidenceRow(key=f"tmp:x:{n}", sno=n, item=item, unit=g(r, "unit"),
                                      po_qty=parse_inr(g(r, "po_qty")),
                                      vendor_qty=Sourced(value=vq) if vq is not None else None,
                                      audit_qty=Sourced(value=aq) if aq is not None else None,
                                      remark=(str(g(r, "remark")).strip() or None) if g(r, "remark") else None,
                                      rate_after_discount=parse_inr(g(r, "rate"))))
            sd = SheetDoc(meta["sheet_name"], SegmentKind.PV_SECTION, roles, conf,
                          PVSection(section_title=meta["sheet_name"], layout="generic", rows=ev))
        elif "po_qty" in roles and "rate" in roles:
            lines = []
            for n, r in rows:
                item, q, p = str(g(r, "item") or "").strip(), parse_inr(g(r, "po_qty")), parse_inr(g(r, "rate"))
                if item and q is not None and p is not None:
                    a = parse_inr(g(r, "amount"))
                    lines.append(POLine(sno=len(lines) + 1, description=item, unit=g(r, "unit"), qty=q, unit_price=p,
                                        amount=a if a is not None else round2(q * p)))
            sd = SheetDoc(meta["sheet_name"], SegmentKind.PURCHASE_ORDER, roles, conf,
                          ExtractedPO(po_number="", lines=lines))
        else:
            sd = SheetDoc(meta["sheet_name"], SegmentKind.OTHER, roles, conf,
                          ExtractedOther(llm_label=f"Spreadsheet: {meta['sheet_name']}"))
        if conf < 0.8:
            sd.warnings.append("column headers unclear — confirm which column is which")
        out.append(sd)
    return out
