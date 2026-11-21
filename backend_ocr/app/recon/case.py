"""CaseBuilder — a case's documents in the DB → ReconInput for the engine.

Human decisions are applied here, not in the engine: corrected evidence cells
come from recon_evidence_rows (the correction overwrote the value), and match
overrides / vendor aliases are handed to the matcher by pipeline.recompute.
"""
from __future__ import annotations

import logging
from decimal import Decimal

from . import rollup
from .repo import ReconRepository, load_extracted
from .types import (
    ExtractedInvoice, ExtractedMemo, ExtractedOther, ExtractedPO, ExtractedPOD, Party, PVSection, ReconInput,
    RuleConfig, SegmentKind, TaxBlock, TaxRegime, sval,
)

logger = logging.getLogger(__name__)


def _state_code(place: str | None) -> str | None:
    return place


class CaseBuilder:
    def __init__(self, repo: ReconRepository) -> None:
        self.repo = repo

    async def load_input(self, tenant: str, case_id: str, config: RuleConfig | None = None) -> tuple[ReconInput, dict]:
        case = await self.repo.case_row(tenant, case_id)
        if case is None:
            raise LookupError(case_id)
        segs = await self.repo.case_segments(case_id)

        po: ExtractedPO | None = None
        if case["po_id"]:
            po = await self.repo.load_po(tenant, str(case["po_id"]))

        invoice: ExtractedInvoice | None = None
        inv_seg = next((s for s in segs if s["role"] == "invoice"), None)
        if inv_seg is None and case.get("invoice_segment_id"):
            inv_seg = await self.repo.segment(tenant, str(case["invoice_segment_id"]))
        if inv_seg and inv_seg.get("extracted_json"):
            invoice = load_extracted(SegmentKind.TAX_INVOICE.value, inv_seg["extracted_json"])
            db_lines = await self.repo.invoice_lines(inv_seg["id"])
            if invoice.annexure_lines:
                invoice.annexure_lines = db_lines
            else:
                invoice.header_lines = db_lines
        bill = await self.repo.bill(tenant, str(case["bill_id"])) if case["bill_id"] else None
        if bill:
            bill_lines = await self.repo.bill_lines(tenant, bill["stg_bill_id"])
            if invoice is None:
                invoice = self._invoice_from_bill(bill, bill_lines)
            else:
                invoice.invoice_no = invoice.invoice_no or bill["invoice_number"]

        evidence: list[PVSection] = []
        pods: list[ExtractedPOD] = []
        memos: list[ExtractedMemo] = []
        for s in segs:
            if s["role"] not in ("evidence", "pod", "memo", "other"):
                continue
            doc = load_extracted(s["kind"], s.get("extracted_json"))
            if isinstance(doc, PVSection):
                doc.rows = await self.repo.evidence_rows(s["id"])
                evidence.append(doc)
            elif isinstance(doc, ExtractedOther) and doc.rows:
                rows = await self.repo.evidence_rows(s["id"])
                evidence.append(PVSection(section_title=doc.llm_label, rows=rows, layout="generic"))
            elif isinstance(doc, ExtractedPOD):
                pods.append(doc)
            elif isinstance(doc, ExtractedMemo):
                memos.append(doc)

        prior_qty, prior_value = ({}, Decimal(0))
        if case["po_id"]:
            prior_qty, prior_value = await self.repo.prior_billing(tenant, str(case["po_id"]), case_id)
        others = await self.repo.other_invoice_numbers(tenant, str(case["supplier_id"]),
                                                       str(case["bill_id"]) if case["bill_id"] else None)
        # The RECEIPT leg's value, when a GRN has been loaded for this PO. None
        # keeps the ±₹100 check abstaining rather than comparing against zero
        # (plan §7); it activates by itself the moment an extract arrives.
        receipt_total, receipt_lines, receipt_basis = None, [], "taxable"
        if po is not None and po.po_number:
            try:
                receipt_total = await self.repo.grn_receipt_total(tenant, po.po_number)
                receipt_lines = await self.repo.grn_lines(tenant, po.po_number)
            except Exception:
                receipt_total, receipt_lines = None, []
        # The delivery-proof fallback is NOT applied here. It used to be, and
        # that made `CaseBuilder` the only place a POD could answer the receipt
        # leg: `reconcile(inp)` on the same documents silently skipped the
        # ±₹100 check, and the golden test comparing the two paths failed. The
        # rule belongs with the rules — see engine._receipt_variance.

        # Section headings that carry the subtotal of other lines on the same
        # invoice. Marked before anything else sees the lines, so neither the
        # matcher nor the totals ever count the work twice (rollup.py). Any
        # failure here leaves the invoice exactly as it was read.
        if invoice is not None:
            try:
                found = rollup.find([sval(l.amount) for l in invoice.lines],
                                    invoice_total=invoice.total)
                for i in found.headings:
                    invoice.lines[i].is_rollup = True
                if found:
                    logger.info("[recon] case=%s invoice %s: %d heading line(s) worth %s "
                                "are subtotals of the %s below them — excluded from billing",
                                case_id, invoice.invoice_no, len(found.headings),
                                found.subtotal, found.detail)
            except Exception:
                logger.exception("[recon] rollup detection failed for case=%s", case_id)

        # Answers a person has already given about this case's checks. Loaded
        # here so a recompute honours them instead of asking twice.
        try:
            confirmed = await self.repo.case_decisions(tenant, case_id, as_of=case.get("as_of"))
        except Exception:
            confirmed = {}

        inp = ReconInput(po=po, invoice=invoice, evidence=evidence, pods=pods, memos=memos,
                         prior_billed_qty=prior_qty, prior_billed_value=prior_value,
                         other_invoice_numbers=others, receipt_total=receipt_total,
                         receipt_lines=receipt_lines, receipt_basis=receipt_basis,
                         confirmed_checks=confirmed,
                         config=config or RuleConfig())
        return inp, case

    @staticmethod
    def _invoice_from_bill(bill: dict, lines) -> ExtractedInvoice:
        igst = bill.get("igst_amount") or Decimal(0)
        cgst = bill.get("cgst_amount") or Decimal(0)
        sgst = bill.get("sgst_amount") or Decimal(0)
        rate = None
        if igst:
            rate = bill.get("igst_rate")
        elif cgst and bill.get("cgst_rate") is not None and bill.get("sgst_rate") is not None:
            rate = bill["cgst_rate"] + bill["sgst_rate"]
        return ExtractedInvoice(
            invoice_no=bill["invoice_number"] or "", invoice_date=bill.get("invoice_date"),
            vendor=Party(gstin=bill.get("gstin_seller")), place_of_supply=bill.get("place_of_supply"),
            header_lines=lines, taxable=bill.get("taxable_amount") or bill.get("subtotal"),
            tax=TaxBlock(regime=TaxRegime.IGST if igst else (TaxRegime.CGST_SGST if cgst else TaxRegime.NONE),
                         igst=igst, cgst=cgst, sgst=sgst, rate=rate),
            total=bill.get("total_amount"))
