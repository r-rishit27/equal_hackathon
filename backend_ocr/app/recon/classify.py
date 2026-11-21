"""PageClassifier — what each page is (03_LLD_BACKEND.md §8).

Rules first (exact phrases these documents always carry), the LLM only for
pages the rules can't place (scans, unfamiliar formats). Hints — store number,
GSTINs, PO numbers, a section title — are pulled from every page regardless of
class; they drive segmentation and linking.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import config as C
from .clean import fit, gstin, text
from .llm import LLM
from .pages import PageInfo
from .types import DocClass

GSTIN = re.compile(r"\b(\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z])\b")
PO_NO = re.compile(r"\bPPO\s?\d{8}(?:-\d+)?\b")
_STORE = [re.compile(p, re.I) for p in (
    r"\bPO\s+SN\s*(\d{3,5})\b", r"\bSN\s*(\d{3,5})\b", r"Store\s*No\.?.{0,40}?_(\d{3,5})\b",
    r"Shop\s*No\s*:?-?\s*(\d{3,5})\b", r"\((\d{4})\)", r"\b(\d{4})\s*BATA\s+SHOE\s+STORE",
)]
_SECTION = re.compile(r"\b([A-Z][A-Z &+\-]{2,60}\bPO)\b")

_RULES: list[tuple[DocClass, list[list[str]]]] = [
    # (class, any-of [all-of phrases]) — matched case-insensitively against the page text. Order matters:
    # an invoice mentions "consignee" and "waybill", so invoices are tested before POD.
    (DocClass.PV_ANNEXURE_TYPED, [["qty as per po", "verified qty"]]),
    (DocClass.PV_FIELD_SHEET, [["actual measured qty"], ["mounted", "unmounted", "damaged"]]),
    (DocClass.PV_SHEET_SCANNED, [["audit qty", "vendor qty"]]),
    (DocClass.PV_NARRATIVE, [["physical verification", "scope"], ["physical verification", "disclaimer"],
                             ["physical verification", "methodology"], ["site visit", "physical verification"],
                             ["report on physical verification"], ["physical verification", "conclusion"],
                             ["physical verification", "audit findings"]]),
    (DocClass.APPROVAL_MEMO, [["internal memo", "approver"], ["memo ref", "approver"]]),
    (DocClass.INVOICE_ANNEXURE, [["details of invoice"], ["performa invoice"], ["proforma invoice"]]),
    (DocClass.PURCHASE_ORDER, [["purchase order", "purchase requisition"]]),
    (DocClass.TAX_INVOICE, [["tax invoice", "gstin"], ["e-invoice", "irn"], ["invoice no", "gstin", "total"]]),
    (DocClass.POD, [["waybill", "consignee"], ["consignor", "consignee"], ["proof of delivery"]]),
    (DocClass.TERMS_CONDITIONS, [["standard terms & conditions"], ["general condition of sale"]]),
]
_ANNEX_TITLE = re.compile(r"Annexure-\s*(\d+)\s*:\s*Reporting on physical verification related to\s+([^\n]+)", re.I)
_NUMBER = re.compile(r"\d[\d,]*\.\d{2}\b")
_PPO = re.compile(r"PPO\s*0*\d{5,}", re.I)
_CONTINUES = {DocClass.INVOICE_ANNEXURE, DocClass.PV_ANNEXURE_TYPED, DocClass.PURCHASE_ORDER,
              DocClass.PV_SHEET_SCANNED}

CLASSIFY_PROMPT = """You classify one page of a document that a finance team uploaded to reconcile vendor bills.
Classes:
PURCHASE_ORDER — the BUYER's own purchase order: printed by the buyer (e.g. Bata logo, the words "Purchase order",
  a PO number like PPO00024378, "Terms of payment", delivery/billing address columns, Unit Pr./Amt. columns).
TERMS_CONDITIONS (only terms text), TAX_INVOICE (vendor tax invoice header page), INVOICE_ANNEXURE (invoice detail
page listing items with qty/rate/amount), PV_NARRATIVE (an auditor's physical-verification report text: scope,
disclaimer, conclusion), PV_ANNEXURE_TYPED (typed verification table with PO qty / vendor qty / verified qty columns),
PV_SHEET_SCANNED — an AUDITOR's sheet checking work against a PO: columns such as 'Vendor Qty', 'Audit Qty',
  'Verified', 'Remarks', often handwritten numbers, an auditor's stamp or signature. Its heading often NAMES the PO
  it checks ("FURNITURE PO", "FAMILY - INTERIOR & ELECTRICAL - RACKS PO", "AC HS PO") — that does NOT make it a
  purchase order. If a page has audit/verified quantity columns it is PV_SHEET_SCANNED, never PURCHASE_ORDER.
PV_FIELD_SHEET (site sheet with Mounted/Unmounted/Damaged boxes), POD (proof of delivery / waybill / LR / delivery
challan with receipt stamp), APPROVAL_MEMO (internal approval memo with approver statuses), GRN, MEASUREMENT_SHEET, OTHER.
Return JSON. Use JSON null (not the text "null") for anything not on the page:
{"doc_class": "...", "confidence": 0-1, "llm_label": short name if OTHER else null,
 "vendor_name": the vendor/supplier named on the page or null, "vendor_gstin": that vendor's 15-character GSTIN or null,
 "section_title": e.g. "FURNITURE PO" or null, "store_sn": store number like "1859" or null,
 "po_number": a printed PO number like "PPO00024378-1" or null,
 "has_audit_columns": true if the table has vendor/audit/verified quantity or remarks columns,
 "is_continuation": true if this page continues a table from the previous page with no header of its own}."""


@dataclass
class PageLabel:
    page_index: int
    doc_class: DocClass
    confidence: float
    method: str                                 # rule | llm | default
    llm_label: str | None = None
    vendor_name: str | None = None
    vendor_gstin: str | None = None
    section_title: str | None = None
    store_sn: str | None = None
    po_numbers: list[str] = field(default_factory=list)
    gstins: list[str] = field(default_factory=list)
    is_continuation: bool = False
    printed_po: str | None = None               # the model's reading of a printed PO number (scans)

    def hints(self) -> dict:
        return {"vendor_name": self.vendor_name, "vendor_gstin": self.vendor_gstin, "section_title": self.section_title,
                "store_sn": self.store_sn, "po_numbers": self.po_numbers, "gstins": self.gstins,
                "is_continuation": self.is_continuation}


def hints_from_text(text: str) -> dict:
    out: dict = {"gstins": list(dict.fromkeys(GSTIN.findall(text or ""))),
                 "po_numbers": list(dict.fromkeys(m.replace(" ", "") for m in PO_NO.findall(text or "")))}
    for rx in _STORE:
        m = rx.search(text or "")
        if m:
            out["store_sn"] = m.group(1)
            break
    ann = _ANNEX_TITLE.search(text or "")
    if ann:
        title = re.sub(r"\s+", " ", ann.group(2)).strip()
        out["section_title"] = f"Annexure-{ann.group(1)}: {title}"
    else:
        sec = _SECTION.search(text or "")
        if sec and "PURCHASE" not in sec.group(1):
            out["section_title"] = re.sub(r"\s+", " ", sec.group(1)).strip()
    return out


def rule_class(text: str) -> DocClass | None:
    low = (text or "").lower()
    for cls, alternatives in _RULES:
        if any(all(p in low for p in group) for group in alternatives):
            return cls
    return None


class PageClassifier:
    def __init__(self, llm: LLM | None = None) -> None:
        self.llm = llm

    async def classify(self, pages: list[PageInfo], images: dict[int, bytes] | None = None) -> list[PageLabel]:
        """`images`: page index → small PNG, for pages without a text layer (rendered by the caller)."""
        out: list[PageLabel] = []
        for p in pages:
            h = hints_from_text(p.text)
            cls = rule_class(p.text) if p.text else None
            prev = out[-1] if out else None
            if p.blank or (p.has_text_layer and len(p.text.split()) < 40 and cls is None):
                lab = PageLabel(page_index=p.index, doc_class=DocClass.OTHER, confidence=1.0, method="blank")
            elif cls is not None:
                lab = PageLabel(page_index=p.index, doc_class=cls, confidence=0.95, method="rule")
            elif p.has_text_layer and prev and prev.doc_class in _CONTINUES and len(_NUMBER.findall(p.text)) >= 4:
                lab = PageLabel(page_index=p.index, doc_class=prev.doc_class, confidence=0.8, method="rule",
                                is_continuation=True, section_title=prev.section_title,
                                vendor_gstin=prev.vendor_gstin, vendor_name=prev.vendor_name)
            elif self.llm is not None:
                img = (images or {}).get(p.index)
                r = await self.llm.json("classify_page", CLASSIFY_PROMPT,
                                        text=(p.text or "")[:1500] or None, images=[img] if img else None,
                                        model=C.FAST_MODEL)
                try:
                    dc = DocClass(r.get("doc_class", "OTHER"))
                except ValueError:
                    dc = DocClass.OTHER
                # An auditor's sheet names the PO it checks ("FURNITURE PO"); the model can take that for a PO.
                # A Bata PO prints its PPO number and has no audit columns — without both, it isn't one.
                if dc == DocClass.PURCHASE_ORDER and (r.get("has_audit_columns") is True
                                                      or (not p.has_text_layer and not _PPO.search(text(r.get("po_number")) or ""))):
                    dc = DocClass.PV_SHEET_SCANNED
                # The model's hints, cleaned: "…|null" echoes dropped, a GSTIN kept only when its
                # check digit holds (scans misread them: "29AABC81043121"), sizes fitted to storage.
                lab = PageLabel(page_index=p.index, doc_class=dc, confidence=float(r.get("confidence") or 0.5),
                                method="llm", llm_label=text(r.get("llm_label")), vendor_name=text(r.get("vendor_name")),
                                vendor_gstin=gstin(r.get("vendor_gstin")), section_title=text(r.get("section_title")),
                                store_sn=fit(r.get("store_sn"), 16), is_continuation=bool(r.get("is_continuation")),
                                printed_po=text(r.get("po_number")))
            else:
                lab = PageLabel(page_index=p.index, doc_class=DocClass.OTHER, confidence=0.0, method="default")
            lab.gstins = h["gstins"]
            lab.po_numbers = h["po_numbers"]
            lab.store_sn = lab.store_sn or h.get("store_sn")
            lab.section_title = lab.section_title or h.get("section_title")
            if not lab.vendor_gstin and lab.doc_class in (DocClass.PV_SHEET_SCANNED,) and h["gstins"]:
                lab.vendor_gstin = next((g for g in h["gstins"] if "AABCB1043Q" not in g), None)
            out.append(lab)
        return _within_report(out)


_PO_HEADING = re.compile(r"\bP\.?\s?O\.?$", re.I)
_PV = {DocClass.PV_SHEET_SCANNED, DocClass.PV_ANNEXURE_TYPED, DocClass.PV_NARRATIVE}


def _within_report(labels: list[PageLabel]) -> list[PageLabel]:
    """One file, read as a whole: an auditor's report is a sheet per PO, each headed "<WORK> PO".

    Read one page at a time, the model takes some of those sheets for the PO or
    the invoice they check (the Yelanka report: pages 3 and 5 of the Interior
    sheet as POs, the AC LS sheet as an invoice). In a file that holds audit
    sheets, a page headed "… PO" that prints no PPO number is one more sheet, and
    a page between two pages of the same sheet belongs to it.
    """
    if not any(l.doc_class in _PV for l in labels):
        return labels
    suspect = (DocClass.PURCHASE_ORDER, DocClass.INVOICE_ANNEXURE, DocClass.TAX_INVOICE)

    def no_ppo(l: PageLabel) -> bool:
        return not l.po_numbers and not _PPO.search(l.printed_po or "")

    def heading(l: PageLabel) -> str:
        return re.sub(r"[^A-Z]", "", (l.section_title or "").upper())

    # Two passes, so a run of sheet pages spreads: page 5 joins page 4 once page 3 has.
    for _ in range(2):
        for i, l in enumerate(labels):
            if l.method != "llm" or l.doc_class not in suspect:
                continue
            near = [labels[j] for j in (i - 1, i + 1) if 0 <= j < len(labels)]
            # Beside a page of the same sheet: one more page of it — whatever PO number the model
            # claims (it "read" PPO00024378 off sheet pages that print none, knowing the PO they check).
            same_sheet = any(n.doc_class == DocClass.PV_SHEET_SCANNED and heading(n) and heading(n) == heading(l)
                             for n in near)
            if same_sheet or (no_ppo(l) and _PO_HEADING.search((l.section_title or "").strip())):
                l.doc_class = DocClass.PV_SHEET_SCANNED
                l.method = "report"
    return labels
