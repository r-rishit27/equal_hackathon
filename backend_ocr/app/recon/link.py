"""DocumentLinker — which case a document belongs to (03_LLD_BACKEND.md §13).

Pure scoring; the pipeline supplies the candidates. Exact references (PO
number, invoice number) decide outright. Otherwise store, amount, line overlap
and dates are weighed, and only a clear winner (≥ 0.85 and 0.15 ahead of the
runner-up) links automatically — anything else is the user's call.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from rapidfuzz import fuzz

from . import config as C
from .match import LineMatcher, cands_from_evidence, cands_from_invoice
from .clean import store_no
from .num import close
from .types import EvidenceRow, ExtractedPO, InvoiceLine, Party

W_REF, W_STORE, W_AMOUNT, W_OVERLAP, W_DATE = 0.45, 0.15, 0.15, 0.20, 0.05


@dataclass
class CaseView:
    """What the linker knows about one candidate case (or a bill/PO that has no case yet)."""
    target_type: str                      # case | bill | po
    target_id: str
    label: str
    case_id: str | None = None
    bill_id: str | None = None
    po_id: str | None = None
    invoice_no: str | None = None
    invoice_date: date | None = None
    invoice_total: Decimal | None = None
    invoice_taxable: Decimal | None = None
    po: ExtractedPO | None = None
    store_sn: str | None = None


@dataclass
class LinkCandidate:
    target_type: str
    target_id: str
    label: str
    score: float
    signals: dict = field(default_factory=dict)
    case_id: str | None = None
    bill_id: str | None = None
    po_id: str | None = None

    def to_json(self) -> dict:
        return asdict(self)


def norm_no(s: str | None) -> str:
    return re.sub(r"[^A-Z0-9]", "", (s or "").upper())


def po_base(s: str | None) -> str | None:
    m = re.search(r"PPO\s*0*(\d{5,})", s or "", re.I)
    return m.group(1).lstrip("0") if m else None


def is_foreign(vendor: Party, supplier_name: str | None, supplier_gstins: set[str]) -> bool:
    """A report section / document for another vendor (E-SG-04, E-IN-15).

    The vendor's own GSTIN settles it. Otherwise a clearly matching name wins over
    a GSTIN that doesn't: an auditor's sheet prints the buyer's GSTIN ("BATA GST
    NO.") right above the vendor, and a scan's GSTIN can be misread — the Yelanka
    Signage sheet ("INNERSPACE") was set aside as another vendor that way.
    """
    gst = {g.upper() for g in supplier_gstins or set()}
    if vendor.gstin and vendor.gstin.upper() in gst:
        return False
    name = None
    if vendor.name and supplier_name:
        a, b = _company(vendor.name), _company(supplier_name)
        name = max(fuzz.token_set_ratio(a, b), fuzz.partial_ratio(a, b),
                   fuzz.ratio(a.replace(" ", ""), b.replace(" ", "")))
        if name >= 85:
            return False
    if vendor.gstin and gst:
        return True
    return name is not None and name < 70


def _company(s: str) -> str:
    s = s.lower()
    s = re.sub(r"\b(pvt|private|ltd|limited|llp|co|company|india|enterprises?|projects?|head office|\d{4}-\d{2})\b", " ", s)
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def overlap(po: ExtractedPO | None, rows: list[EvidenceRow] | None = None,
            lines: list[InvoiceLine] | None = None) -> float:
    """Share of a document's item lines that match this PO's lines confidently."""
    if po is None or not po.lines:
        return 0.0
    cands = cands_from_evidence(rows or []) if rows is not None else cands_from_invoice(lines or [])
    if not cands:
        return 0.0
    pairs = LineMatcher().match(po.lines, cands)
    good = sum(1 for p in pairs if p.po_key and p.score >= C.MATCH_ACCEPT)
    return good / len(cands)


def score(view: CaseView, *, refs: dict | None = None, store_sn: str | None = None,
          amount: Decimal | None = None, amount_kind: str = "total", doc_date: date | None = None,
          rows: list[EvidenceRow] | None = None, lines: list[InvoiceLine] | None = None) -> LinkCandidate:
    refs = refs or {}
    sig: dict[str, float] = {}
    # ref: the document names this invoice or this PO
    inv_hit = view.invoice_no and norm_no(view.invoice_no) in {norm_no(x) for x in refs.get("invoice_nos", [])}
    po_hit = view.po is not None and po_base(view.po.po_number) in {po_base(x) for x in refs.get("po_numbers", [])}
    sig["ref"] = 1.0 if (inv_hit or po_hit) else 0.0
    vs = view.store_sn or (view.po.store_sn if view.po else None)
    a, b = store_no(store_sn), store_no(vs)
    sig["store"] = 1.0 if (a and b and a == b) else (0.5 if not a or not b else 0.0)
    target = view.invoice_total if amount_kind == "total" else view.invoice_taxable
    if amount is not None and target is not None:
        sig["amount"] = 1.0 if close(amount, target, Decimal("1"), Decimal("0")) else (
            0.5 if close(amount, target, Decimal("0"), Decimal("0.02")) else 0.0)
    else:
        sig["amount"] = 0.5
    if rows is not None or lines is not None:
        sig["overlap"] = round(overlap(view.po, rows=rows, lines=lines), 3)
    else:
        sig["overlap"] = 0.5
    po_date = view.po.po_date if view.po else None
    if doc_date and (po_date or view.invoice_date):
        lo = po_date or (view.invoice_date - timedelta(days=365))
        hi = (view.invoice_date or doc_date) + timedelta(days=120)
        sig["date"] = 1.0 if lo <= doc_date <= hi else 0.3
    else:
        sig["date"] = 0.5
    total = (W_REF * sig["ref"] + W_STORE * sig["store"] + W_AMOUNT * sig["amount"]
             + W_OVERLAP * sig["overlap"] + W_DATE * sig["date"])
    if sig["ref"] == 1.0:
        total = max(total, 0.95)
    # A report whose rows mostly match one PO is as good as a reference.
    if sig["overlap"] >= 0.6 and sig["store"] >= 0.5:
        total = max(total, 0.6 + 0.4 * sig["overlap"])
    return LinkCandidate(target_type=view.target_type, target_id=view.target_id, label=view.label,
                         score=round(min(total, 1.0), 3), signals=sig, case_id=view.case_id, bill_id=view.bill_id,
                         po_id=view.po_id)


def decide(cands: list[LinkCandidate]) -> LinkCandidate | None:
    ranked = sorted(cands, key=lambda c: -c.score)
    if not ranked:
        return None
    top = ranked[0]
    second = ranked[1].score if len(ranked) > 1 else 0.0
    if top.score >= C.LINK_AUTO_SCORE and top.score - second >= C.LINK_AUTO_MARGIN:
        return top
    return None


def top3(cands: list[LinkCandidate]) -> list[dict]:
    return [c.to_json() for c in sorted(cands, key=lambda c: -c.score)[:3]]


# ── PO ↔ invoice when the invoice doesn't print the PO number ─────────────────

def po_invoice_fit(po: ExtractedPO, inv_lines: list[InvoiceLine], *, inv_store: str | None = None,
                   inv_date: date | None = None, inv_amount: Decimal | None = None,
                   inv_po_ref: str | None = None) -> tuple[float, dict]:
    """How well an invoice fits a PO on content alone (05_USER_FLOWS.md F8).

    Some vendors print their own reference instead of Bata's PO number
    ("P00004731 dt. 16.Sep.26"). Then the lines decide: the share of the
    invoice's lines that match a PO line at the PO's rate, with store, dates
    and value as supporting signals. Hard stops: an invoice naming a different
    PPO number, a different store, or an invoice dated before its PO.
    """
    named = po_base(inv_po_ref)
    if named and named != po_base(po.po_number):
        return 0.0, {"po_ref": 0.0}
    if store_no(inv_store) and store_no(po.store_sn) and store_no(inv_store) != store_no(po.store_sn):
        return 0.0, {"store": 0.0}
    if inv_date and po.po_date and inv_date < po.po_date:
        return 0.0, {"date": 0.0}
    goods = [l for l in inv_lines if not l.is_charge]
    if not goods or not po.lines:
        overlap = 0.0
    else:
        by_po = {l.key: l for l in po.lines}
        pairs = LineMatcher().match(po.lines, cands_from_invoice(goods))
        rate_of = {l.key: (l.rate.value if l.rate else None) for l in goods}
        hits = 0
        for m in pairs:
            pl = by_po.get(m.po_key or "")
            r = rate_of.get(m.other_key)
            if pl is not None and r is not None and (close(Decimal(r), pl.unit_price) or abs(Decimal(r) - pl.unit_price) <= 1):
                hits += 1
        overlap = hits / len(goods)
    store = 1.0 if inv_store and po.store_sn else 0.5
    total = po.total or po.subtotal
    amount = 1.0 if (inv_amount is None or total is None or inv_amount <= total * Decimal("1.05")) else 0.3
    score = round(0.6 * overlap + 0.25 * store + 0.15 * amount, 3)
    return score, {"lines": round(overlap, 2), "store": store, "amount": amount}
