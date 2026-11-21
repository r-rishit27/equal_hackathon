"""Load the hand-verified golden fixtures (tests/recon/fixtures/golden/*.json).

The JSON is compact — lines are arrays — because it is typed in by hand from
the Bata sample documents (docs/BATA_RECON_ANALYSIS_AND_PLAN.md). This module
expands it into recon types. Only numbers and descriptions are stored; the
source PDFs stay out of git.

    PO line:        [sno, description, unit, qty, rate]
    invoice line:   [sno, description, unit, qty, rate, amount, {opts}]   opts: hsn, is_charge, charge_pct
    evidence row:   [sno, item, unit, po_qty, vendor_qty, audit_qty, remark, {opts}]
                    opts: row_type, rate, rate_after_discount, needs_review, confidence, damaged, unmounted
"""
from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

from backend_ocr.app.recon.num import round2
from backend_ocr.app.recon.types import (
    Approval, AuditVerdict, ChargeBasis, Correction, EvidenceRow, ExtractedInvoice, ExtractedMemo,
    ExtractedPO, ExtractedPOD, InvoiceLine, Party, POLine, PVSection, Receipt, ReconInput, RuleConfig,
    Sourced, TaxBlock, TaxRegime,
)

GOLDEN = Path(__file__).parent / "fixtures" / "golden"


def _d(v) -> Decimal | None:
    return None if v is None else Decimal(str(v))


def _date(v) -> date | None:
    return None if v is None else date.fromisoformat(v)


def _party(d: dict | None) -> Party:
    d = d or {}
    return Party(name=d.get("name", ""), gstin=d.get("gstin"), account=d.get("account"))


def _src(v, conf: float = 1.0) -> Sourced | None:
    return None if v is None else Sourced(value=_d(v), confidence=conf)


def load_po(d: dict) -> ExtractedPO:
    lines = [POLine(sno=s, description=desc, unit=u, qty=_d(q), unit_price=_d(r), amount=round2(_d(q) * _d(r)))
             for s, desc, u, q, r in d["lines"]]
    return ExtractedPO(
        po_number=d["po_number"], po_date=_date(d.get("po_date")), vendor=_party(d.get("vendor")),
        buyer_gstin=d.get("buyer_gstin"), store_sn=d.get("store_sn"), store_name=d.get("store_name"),
        payment_terms=d.get("payment_terms"), delivery_date=_date(d.get("delivery_date")),
        lines=lines, subtotal=_d(d.get("subtotal")), tax=_d(d.get("tax", 0)), total=_d(d.get("total")),
    )


def _inv_line(prefix: str, row: list) -> InvoiceLine:
    sno, desc, unit, qty, rate, amount, *rest = row
    opts = rest[0] if rest else {}
    return InvoiceLine(
        key=f"{prefix}:{sno}", sno=sno, description=desc, unit=unit, hsn=opts.get("hsn"),
        qty=_src(qty), rate=_src(rate), amount=_src(amount),
        is_charge=opts.get("is_charge", False), charge_pct=_d(opts.get("charge_pct")),
    )


def load_invoice(d: dict) -> ExtractedInvoice:
    t = d.get("tax", {})
    return ExtractedInvoice(
        invoice_no=d["invoice_no"], invoice_date=_date(d.get("invoice_date")), vendor=_party(d.get("vendor")),
        buyer_gstin=d.get("buyer_gstin"), place_of_supply=d.get("place_of_supply"), po_ref=d.get("po_ref"),
        payment_terms=d.get("payment_terms"),
        header_lines=[_inv_line("h", r) for r in d.get("header_lines", [])],
        annexure_lines=[_inv_line("inv", r) for r in d.get("annexure_lines", [])],
        printed_subtotal=_d(d.get("printed_subtotal")), taxable=_d(d.get("taxable")),
        tax=TaxBlock(regime=TaxRegime(t.get("regime", "NONE")), cgst=_d(t.get("cgst", 0)),
                     sgst=_d(t.get("sgst", 0)), igst=_d(t.get("igst", 0)), rate=_d(t.get("rate"))),
        round_off=_d(d.get("round_off", 0)), total=_d(d.get("total")),
        corrections=[Correction(**c) for c in d.get("corrections", [])],
    )


def _ev_row(section: int, row: list) -> EvidenceRow:
    sno, item, unit, po_qty, vendor_qty, audit_qty, remark, *rest = row
    o = rest[0] if rest else {}
    return EvidenceRow(
        key=f"ev{section}:{sno}", sno=sno, item=item, unit=unit, po_qty=_d(po_qty),
        vendor_qty=_src(vendor_qty), audit_qty=_src(audit_qty, o.get("confidence", 1.0)), remark=remark,
        row_type=o.get("row_type", "po"), rate=_d(o.get("rate")),
        rate_after_discount=_d(o.get("rate_after_discount")), needs_review=o.get("needs_review", False),
        damaged=o.get("damaged"), unmounted=o.get("unmounted"),
    )


def load_section(i: int, d: dict) -> PVSection:
    return PVSection(
        auditor=d.get("auditor"), store_sn=d.get("store_sn"), verification_date=_date(d.get("verification_date")),
        vendor=_party(d.get("vendor")), section_title=d.get("section_title"), layout=d.get("layout", "generic"),
        rows=[_ev_row(i, r) for r in d["rows"]],
    )


def load_pod(d: dict) -> ExtractedPOD:
    r = d.get("receipt", {})
    return ExtractedPOD(
        waybill_no=d.get("waybill_no"), carrier=d.get("carrier"), invoice_nos=d.get("invoice_nos", []),
        total_invoice_value=_d(d.get("total_invoice_value")), packages=d.get("packages"),
        weight=_d(d.get("weight")), ship_date=_date(d.get("ship_date")),
        receipt=Receipt(stamp_text=r.get("stamp_text"), receiver=r.get("receiver"), date=_date(r.get("date"))),
    )


def load_memo(d: dict) -> ExtractedMemo:
    return ExtractedMemo(
        memo_ref=d.get("memo_ref"), subject=d.get("subject"), store_sn=d.get("store_sn"),
        vendor_name=d.get("vendor_name"),
        approvals=[Approval(approver=a[0], status=a[1], date=_date(a[2]), remark=a[3] if len(a) > 3 else None)
                   for a in d.get("approvals", [])],
    )


def load(name: str, **config) -> ReconInput:
    d = json.loads((GOLDEN / f"{name}.json").read_text())
    cfg = RuleConfig()
    for k, v in config.items():
        if k == "blank_audit_means":
            v = AuditVerdict(v)
        if k == "charge_rules":
            v = {p: ChargeBasis(b) for p, b in v.items()}
        setattr(cfg, k, v)
    return ReconInput(
        po=load_po(d["po"]) if d.get("po") else None,
        invoice=load_invoice(d["invoice"]) if d.get("invoice") else None,
        evidence=[load_section(i, s) for i, s in enumerate(d.get("evidence", []))],
        pods=[load_pod(p) for p in d.get("pods", [])],
        memos=[load_memo(m) for m in d.get("memos", [])],
        other_invoice_numbers=d.get("other_invoice_numbers", []),
        config=cfg,
    )
