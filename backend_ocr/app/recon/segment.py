"""Segmenter — pages → logical documents (03_LLD_BACKEND.md §9).

One file is rarely one document: an invoice PDF is a tax invoice plus its
detail annexure; a PO carries pages of terms; an auditor's store report is a
narrative plus a sheet per vendor and PO plus signed field sheets.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .classify import PageLabel
from .types import DocClass, SegmentKind

_KIND = {
    DocClass.PURCHASE_ORDER: SegmentKind.PURCHASE_ORDER,
    DocClass.TAX_INVOICE: SegmentKind.TAX_INVOICE,
    DocClass.INVOICE_ANNEXURE: SegmentKind.TAX_INVOICE,
    DocClass.PV_ANNEXURE_TYPED: SegmentKind.PV_SECTION,
    DocClass.PV_SHEET_SCANNED: SegmentKind.PV_SECTION,
    DocClass.POD: SegmentKind.POD,
    DocClass.DELIVERY_CHALLAN: SegmentKind.POD,
    DocClass.GRN: SegmentKind.POD,
    DocClass.APPROVAL_MEMO: SegmentKind.APPROVAL_MEMO,
    DocClass.MEASUREMENT_SHEET: SegmentKind.OTHER,
    DocClass.OTHER: SegmentKind.OTHER,
}


@dataclass
class Segment:
    kind: SegmentKind
    pages: list[int]
    classes: list[DocClass] = field(default_factory=list)
    llm_label: str | None = None
    section_title: str | None = None
    vendor_name: str | None = None
    vendor_gstin: str | None = None
    store_sn: str | None = None
    confidence: float = 1.0
    support_pages: list[int] = field(default_factory=list)   # narrative / field sheets / terms that inform it
    po_numbers: list[str] = field(default_factory=list)

    def to_row(self) -> dict:
        return {"kind": self.kind.value, "pages": self.pages, "llm_label": self.llm_label,
                "section_title": self.section_title, "vendor_name": self.vendor_name,
                "vendor_gstin": self.vendor_gstin, "store_sn": self.store_sn, "confidence": self.confidence}


def _heading(t: str | None) -> str:
    return re.sub(r"[^A-Z]", "", (t or "").upper())


class Segmenter:
    def segment(self, labels: list[PageLabel]) -> list[Segment]:
        segs: list[Segment] = []
        narrative: list[int] = []
        report_store: str | None = None
        field_sheets: list[PageLabel] = []
        cur: Segment | None = None

        for lab in labels:
            c = lab.doc_class
            if lab.method == "blank":
                if cur:
                    cur.support_pages.append(lab.page_index)
                continue
            if c == DocClass.PV_NARRATIVE:
                narrative.append(lab.page_index)
                report_store = report_store or lab.store_sn
                cur = None
                continue
            if c == DocClass.PV_FIELD_SHEET:
                field_sheets.append(lab)
                continue
            if c == DocClass.TERMS_CONDITIONS:
                if cur and cur.kind in (SegmentKind.PURCHASE_ORDER, SegmentKind.TAX_INVOICE):
                    cur.support_pages.append(lab.page_index)
                continue
            kind = _KIND.get(c, SegmentKind.OTHER)
            if cur and self._continues(cur, lab, kind):
                cur.pages.append(lab.page_index)
                cur.classes.append(c)
                cur.po_numbers += [p for p in lab.po_numbers if p not in cur.po_numbers]
                cur.confidence = min(cur.confidence, lab.confidence)
                cur.store_sn = cur.store_sn or lab.store_sn
                continue
            cur = Segment(kind=kind, pages=[lab.page_index], classes=[c], llm_label=lab.llm_label,
                          section_title=lab.section_title if kind == SegmentKind.PV_SECTION else None,
                          vendor_name=lab.vendor_name, vendor_gstin=lab.vendor_gstin,
                          store_sn=lab.store_sn, confidence=lab.confidence, po_numbers=list(lab.po_numbers))
            segs.append(cur)

        for s in segs:
            if s.kind == SegmentKind.PV_SECTION:
                s.support_pages = narrative + [f.page_index for f in field_sheets]
                s.store_sn = s.store_sn or report_store
        if field_sheets and not any(s.kind == SegmentKind.PV_SECTION for s in segs):
            # Field sheets alone are still evidence.
            segs.append(Segment(kind=SegmentKind.PV_SECTION, pages=[f.page_index for f in field_sheets],
                                classes=[DocClass.PV_FIELD_SHEET], store_sn=report_store,
                                support_pages=narrative, confidence=min(f.confidence for f in field_sheets)))
        return segs

    @staticmethod
    def _continues(cur: Segment, lab: PageLabel, kind: SegmentKind) -> bool:
        if lab.is_continuation and cur.kind in (SegmentKind.PV_SECTION, SegmentKind.TAX_INVOICE, SegmentKind.PURCHASE_ORDER):
            return True
        if kind != cur.kind:
            return False
        if kind == SegmentKind.PURCHASE_ORDER:
            # Same PO number (or no number on the page) → same PO.
            return not lab.po_numbers or not cur.po_numbers or bool(set(lab.po_numbers) & set(cur.po_numbers))
        if kind == SegmentKind.TAX_INVOICE:
            # A header page followed by its annexure merges; two header pages are two invoices.
            return not (lab.doc_class == DocClass.TAX_INVOICE and DocClass.TAX_INVOICE in cur.classes
                        and DocClass.INVOICE_ANNEXURE not in cur.classes and len(cur.pages) >= 1
                        and lab.po_numbers and cur.po_numbers and not set(lab.po_numbers) & set(cur.po_numbers))
        if kind == SegmentKind.PV_SECTION:
            # The sheet's heading decides: the same heading is the same sheet, whatever vendor name or
            # GSTIN the model picked off each page (it reads "Bata" off one page and the vendor off the next).
            a, b = _heading(lab.section_title), _heading(cur.section_title)
            if a and b:
                return a == b
            if lab.vendor_gstin and cur.vendor_gstin and lab.vendor_gstin != cur.vendor_gstin:
                return False
            if lab.vendor_name and cur.vendor_name and lab.vendor_name.lower() != cur.vendor_name.lower():
                return False
            return True
        if kind in (SegmentKind.APPROVAL_MEMO, SegmentKind.POD):
            return False
        return kind == SegmentKind.OTHER and cur.llm_label == lab.llm_label
