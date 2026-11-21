"""DocumentsView — what was read from each of a case's documents, before any reconciling.

The case screen opens on this: every attached document (PO, invoice, site audit
sections, delivery proof, approval memo) with its header fields and its line
table, exactly as extracted, with human corrections applied. It loads through
the same repository calls CaseBuilder uses, so the numbers shown here are the
numbers the engine reconciled — never a second, divergent reading.

Output shape per document (JSON-safe once passed through the router's _j):
  {id, role, kind, title, source, file_name, doc_id, pages, warnings,
   fields: [{label, value, fmt}],               fmt: text | money | qty | date | pct
   tables: [{title, columns: [{key, label, fmt, code?}], rows: [{..., _flag, _alts}]},
   vocab: {doc_role, recon_leg, receipt_granularity, pv_format, evidence_layer}}
Codes are from the recon vocabulary (docs/RECON_VOCABULARY.md, recon/vocab.py); column `code` is a qty_role / rate_role.
"""
from __future__ import annotations

from decimal import Decimal

from .extract.base import text as _t
from . import vocab
from .num import parse_inr
from .repo import ReconRepository, load_extracted
from . import rules
from .rules import VerdictClassifier
from .types import (
    AuditVerdict, EvidenceRow, ExtractedInvoice, ExtractedMemo, ExtractedOther, ExtractedPO, ExtractedPOD,
    InvoiceLine, PVSection, SegmentKind, Sourced,
)

_ROLE_ORDER = {"po": 0, "invoice": 1, "evidence": 2, "pod": 3, "memo": 4, "other": 5}

_VERDICT_LABEL = {
    AuditVerdict.VERIFIED: "Counted", AuditVerdict.NOT_DONE: "Not done", AuditVerdict.NOT_COVERED: "Not covered",
    AuditVerdict.NOT_COUNTABLE: "Not countable", AuditVerdict.ADDITIONAL: "Extra on site",
    AuditVerdict.UNKNOWN: "Blank",
}

_LAYOUT_LABEL = {"jpc_typed": "Typed annexure", "matolia_scan": "Scanned sheet (handwritten)", "generic": "Table"}


def _f(label: str, value, fmt: str = "text") -> dict | None:
    if value is None or value == "" or value == []:
        return None
    return {"label": label, "value": value, "fmt": fmt}


def _fields(*items) -> list[dict]:
    return [x for x in items if x]


def _v(s: Sourced | None):
    return s.value if s else None


def _pages(p) -> list[int]:
    return list(p or [])


class DocumentsView:
    def __init__(self, repo: ReconRepository) -> None:
        self.repo = repo
        self.verdicts = VerdictClassifier()

    async def for_case(self, tenant: str, case_id: str) -> list[dict]:
        """Every document on the case, each row carrying its comparison with the others (`_cmp`)."""
        case = await self.repo.case_row(tenant, case_id)
        if case is None:
            raise LookupError(case_id)
        segs = await self.repo.case_segments(case_id)
        docs = await self._case_docs(tenant, case, segs)
        lines, header = await self.repo.results(case_id)
        by_key = _lines_by_key(lines)
        # One context per document, not one shared across them: each carries
        # the checks about itself.
        for d in docs:
            d["case"] = _context(case, docs, header, role=d["role"])
            field = _ROLE_KEY.get(d["role"])
            for t in d["tables"]:
                for r in t["rows"]:
                    r["_cmp"] = _cmp(by_key.get((field, r.get("_key")))) if field else None
        return docs

    async def for_file(self, tenant: str, doc: dict) -> dict:
        """One uploaded file: each part as read, compared against its invoice's other documents when linked."""
        self._supplier = str(doc["supplier_id"])
        segs, seen = [], set()
        for sg in await self.repo.segments_for_doc(str(doc["id"])):
            if sg["id"] not in seen:
                seen.add(sg["id"])
                segs.append(sg)
        cases: dict[str, list[dict]] = {}
        parts = []
        for sg in segs:
            sg["file_name"], sg["doc_id"] = doc["file_name"], doc["id"]
            cid = str(sg["case_id"]) if sg.get("case_id") else None
            part = None
            if cid and sg["status"] not in ("FOREIGN", "IGNORED"):
                if cid not in cases:
                    try:
                        cases[cid] = await self.for_case(tenant, cid)
                    except LookupError:
                        cases[cid] = []
                part = next((x for x in cases[cid] if x["id"] == sg["id"]), None)
            if part is None:
                part = await self.for_segment(sg)
            part["status"] = sg["status"]
            part["vendor_name"] = sg.get("vendor_name")
            parts.append(part)
        name = doc["file_name"] or ""
        return {
            "id": str(doc["id"]), "file_name": name, "uploaded_at": doc.get("uploaded_at"), "uploaded_by": doc.get("uploaded_by"),
            "recon_status": doc.get("recon_status"), "error": doc.get("recon_error"),
            "download": f"/api/vendors/{self._supplier}/documents/{doc['id']}/download", "file_type": _file_type(name),
            "parts": parts,
        }

    async def for_segment(self, sg: dict) -> dict:
        """A part that isn't on an invoice's case (yet): what was read, with nothing to compare against."""
        self._supplier = getattr(self, "_supplier", None) or str(sg.get("supplier_id"))
        sg.setdefault("role", None)
        doc = load_extracted(sg["kind"], sg.get("extracted_json"))
        if isinstance(doc, ExtractedPO):
            d = self._po(doc, sg, doc)
        elif isinstance(doc, ExtractedInvoice):
            d = self._invoice(doc, await self.repo.invoice_lines(sg["id"]), sg, None)
        elif isinstance(doc, PVSection):
            d = self._pv(doc, await self.repo.evidence_rows(sg["id"]), sg)
        elif isinstance(doc, ExtractedPOD):
            d = self._pod(doc, sg)
        elif isinstance(doc, ExtractedMemo):
            d = self._memo(doc, sg)
        elif isinstance(doc, ExtractedOther):
            d = self._other(doc, await self.repo.evidence_rows(sg["id"]) if doc.rows else [], sg)
        else:
            role = {"PURCHASE_ORDER": "po", "TAX_INVOICE": "invoice", "PV_SECTION": "evidence", "POD": "pod",
                    "APPROVAL_MEMO": "memo"}.get(sg["kind"], "other")
            d = self._base(sg, role, sg["kind"], sg.get("section_title") or sg.get("llm_label") or "Part of the file", "upload")
        d["case"] = None
        return d

    async def _case_docs(self, tenant: str, case: dict, segs: list[dict]) -> list[dict]:
        self._supplier = str(case["supplier_id"])
        segs.sort(key=lambda s: _ROLE_ORDER.get(s["role"], 9))
        out: list[dict] = []

        po_seg = next((s for s in segs if s["role"] == "po"), None)
        if case.get("po_id"):
            po = await self.repo.load_po(tenant, str(case["po_id"]))
            if po:
                read = load_extracted(SegmentKind.PURCHASE_ORDER.value, po_seg.get("extracted_json")) if po_seg else None
                out.append(self._po(po, po_seg, read))

        inv_seg = next((s for s in segs if s["role"] == "invoice"), None)
        if inv_seg is None and case.get("invoice_segment_id"):
            inv_seg = await self.repo.segment(tenant, str(case["invoice_segment_id"]))
        bill = await self.repo.bill(tenant, str(case["bill_id"])) if case.get("bill_id") else None
        if inv_seg and inv_seg.get("extracted_json"):
            inv = load_extracted(SegmentKind.TAX_INVOICE.value, inv_seg["extracted_json"])
            db_lines = await self.repo.invoice_lines(inv_seg["id"])
            out.append(self._invoice(inv, db_lines, inv_seg, bill))
        elif bill:
            from .case import CaseBuilder
            lines = await self.repo.bill_lines(tenant, bill["stg_bill_id"])
            inv = CaseBuilder._invoice_from_bill(bill, lines)
            d = self._invoice(inv, lines, None, bill)
            if bill.get("upload_id"):
                # The bill's own file, through the same route the bill review screen uses.
                d.update(download=f"/api/docs/{bill['upload_id']}", file_type="pdf",
                         file_name=f"Bill {bill.get('invoice_number') or ''}".strip())
            out.append(d)

        for s in segs:
            if s["role"] in ("po", "invoice"):
                continue
            doc = load_extracted(s["kind"], s.get("extracted_json"))
            if isinstance(doc, PVSection):
                out.append(self._pv(doc, await self.repo.evidence_rows(s["id"]), s))
            elif isinstance(doc, ExtractedPOD):
                out.append(self._pod(doc, s))
            elif isinstance(doc, ExtractedMemo):
                out.append(self._memo(doc, s))
            elif isinstance(doc, ExtractedOther):
                rows = await self.repo.evidence_rows(s["id"]) if doc.rows else []
                out.append(self._other(doc, rows, s))
        return out

    # ── per document ──────────────────────────────────────────────────────────
    def _base(self, seg: dict | None, role: str, kind: str, title: str, source: str) -> dict:
        doc_id = str(seg["doc_id"]) if seg and seg.get("doc_id") else None
        name = (seg.get("file_name") or "") if seg else ""
        return {
            # The original file, through the vendor-documents download route (tenant-checked, streamed).
            "download": f"/api/vendors/{self._supplier}/documents/{doc_id}/download" if doc_id else None,
            "file_type": _file_type(name) if doc_id else None,
            "id": seg["id"] if seg else f"{role}:system", "role": role, "kind": kind, "title": title, "source": source,
            "file_name": seg.get("file_name") if seg else None, "doc_id": str(seg["doc_id"]) if seg and seg.get("doc_id") else None,
            "pages": _pages(seg.get("pages")) if seg else [], "link_method": seg.get("link_method") if seg else None,
            "warnings": list((seg.get("warnings") or []) if seg else []), "fields": [], "tables": [],
            "vocab": _part_vocab(seg, kind),
        }

    def _po(self, po: ExtractedPO, seg: dict | None, read: ExtractedPO | None) -> dict:
        d = self._base(seg, "po", SegmentKind.PURCHASE_ORDER.value, f"PO {po.po_number}",
                       "upload" if seg else "register")
        vendor = (read.vendor.name if read and read.vendor.name else None) or po.vendor.name or None
        line_sum = sum((l.amount for l in po.lines), Decimal(0))
        d["fields"] = _fields(
            _f("PO number", po.po_number), _f("Revision", po.revision if po.revision and po.revision > 1 else None),
            _f("PO date", po.po_date, "date"), _f("Delivery by", po.delivery_date, "date"),
            _f("Vendor", vendor), _f("Vendor GSTIN", po.vendor.gstin), _f("Billed to (Bata GSTIN)", po.buyer_gstin),
            _f("Store", " · ".join(x for x in (po.store_sn, po.store_name) if x) or None),
            _f("Requisition", " · ".join(x for x in (po.requisition_no, po.requisition_name) if x) or None),
            _f("Payment terms", po.payment_terms),
            _f("Sub total", po.subtotal, "money"), _f("Tax", po.tax, "money"), _f("PO total", po.total, "money"),
            _f("Lines", len(po.lines), "qty"), _f("Sum of line amounts", line_sum, "money"),
        )
        if po.penalties:
            d["fields"].append(_f("Late delivery penalty", "; ".join(
                f"{p.days_from}{'–' + str(p.days_to) if p.days_to is not None else '+'} days: {p.pct}%"
                f"{' per day' if p.per_day else ''}" for p in po.penalties)))
        if po.subtotal is not None and abs(line_sum - po.subtotal) > 1:
            d["warnings"].append(f"Line amounts add up to {line_sum}, the PO prints {po.subtotal}")
        d["tables"] = [{
            "title": "PO lines",
            "columns": [_c("sno", "#", "qty"), _c("description", "Item"), _c("unit", "Unit"), _c("qty", "Qty", "qty"),
                        _c("rate", "Rate", "money"), _c("amount", "Amount", "money"),
                        _c("delivery", "Delivery", "date")],
            "rows": [{"_key": l.key, "sno": l.sno, "description": l.description, "unit": _t(l.unit), "qty": l.qty, "rate": l.unit_price,
                      "amount": l.amount, "delivery": l.delivery_date,
                      "_flag": _arith_flag(l.qty, l.unit_price, l.amount)} for l in po.lines],
        }]
        return d

    def _invoice(self, inv: ExtractedInvoice, db_lines: list[InvoiceLine], seg: dict | None, bill: dict | None) -> dict:
        d = self._base(seg, "invoice", SegmentKind.TAX_INVOICE.value, f"Invoice {inv.invoice_no or (bill or {}).get('invoice_number') or ''}".strip(),
                       "upload" if seg else "bill")
        t = inv.tax
        lines = db_lines if seg else (inv.header_lines or db_lines)
        is_annex = bool(seg and inv.annexure_lines)
        line_sum = sum((_v(l.amount) or Decimal(0) for l in lines if not l.is_charge), Decimal(0))
        charges = sum((_v(l.amount) or Decimal(0) for l in lines if l.is_charge), Decimal(0))
        d["fields"] = _fields(
            _f("Invoice number", inv.invoice_no or (bill or {}).get("invoice_number")),
            _f("Invoice date", inv.invoice_date, "date"), _f("IRN", inv.irn),
            _f("Vendor", inv.vendor.name or None), _f("Vendor GSTIN", inv.vendor.gstin),
            _f("Billed to (Bata GSTIN)", inv.buyer_gstin), _f("Place of supply", inv.place_of_supply),
            _f("PO number on invoice", inv.po_ref), _f("Payment terms", inv.payment_terms),
            _f("Goods total printed", inv.printed_subtotal, "money"),
            _f("Taxable value", inv.taxable, "money"),
            _f("GST type", {"IGST": "IGST (inter-state)", "CGST_SGST": "CGST + SGST (intra-state)"}.get(t.regime.value)),
            _f("GST rate", t.rate, "pct"),
            _f("CGST", t.cgst or None, "money"), _f("SGST", t.sgst or None, "money"), _f("IGST", t.igst or None, "money"),
            _f("Round off", inv.round_off or None, "money"), _f("Invoice total", inv.total, "money"),
            _f("Lines", len(lines), "qty"), _f("Sum of line amounts", line_sum, "money"),
            _f("Charges (packing, transport…)", charges or None, "money"),
        )
        for c in inv.corrections:
            d["warnings"].append(f"Handwritten correction on {c.field}: printed {c.printed}, written {c.handwritten}"
                                 + (f" (page {c.page})" if c.page else ""))
        if bill and seg:
            if bill.get("total_amount") is not None and inv.total is not None and abs(Decimal(bill["total_amount"]) - inv.total) > 1:
                d["warnings"].append(f"The bill in Onsumm says total {bill['total_amount']}; this reading says {inv.total}")
        d["tables"] = [{
            "title": "Invoice annexure lines" if is_annex else "Invoice lines",
            "columns": [_c("sno", "#", "qty"), _c("description", "Item"), _c("hsn", "HSN"), _c("unit", "Unit"),
                        _c("qty", "Qty", "qty"), _c("rate", "Rate", "money"), _c("amount", "Amount", "money"),
                        _c("tax_rate", "GST %", "pct")],
            "rows": [{"_key": l.key, "sno": l.sno, "description": l.description + (" (charge)" if l.is_charge else ""), "hsn": _t(l.hsn),
                      "unit": _t(l.unit), "qty": _v(l.qty), "rate": _v(l.rate), "amount": _v(l.amount), "tax_rate": l.tax_rate,
                      "_flag": _low_conf(l.qty) or _arith_flag(_v(l.qty), _v(l.rate), _v(l.amount)),
                      "_page": next((x.page for x in (l.qty, l.amount, l.rate) if x and x.page), None)} for l in lines],
        }]
        if seg and inv.annexure_lines and inv.header_lines:
            d["tables"].append({
                "title": "Invoice first page (summary lines)",
                "columns": [_c("description", "Item"), _c("hsn", "HSN"), _c("qty", "Qty", "qty"),
                            _c("rate", "Rate", "money"), _c("amount", "Amount", "money")],
                "rows": [{"description": l.description, "hsn": _t(l.hsn), "qty": _v(l.qty), "rate": _v(l.rate),
                          "amount": _v(l.amount)} for l in inv.header_lines],
            })
        return d

    def _pv(self, sec: PVSection, rows: list[EvidenceRow], seg: dict) -> dict:
        title = sec.section_title or "Site audit"
        d = self._base(seg, "evidence", SegmentKind.PV_SECTION.value, title, "upload")
        n_check = sum(1 for r in rows if r.needs_review)
        d["fields"] = _fields(
            _f("Auditor", sec.auditor), _f("Verified on", sec.verification_date, "date"),
            _f("Store", sec.store_sn), _f("Vendor", sec.vendor.name or None), _f("Vendor GSTIN", sec.vendor.gstin),
            _f("Section", sec.section_title), _f("Read as", _LAYOUT_LABEL.get(sec.layout, sec.layout)),
            _f("Rows", len(rows), "qty"),
            _f("Extra items found on site", sum(1 for r in rows if r.row_type == "additional") or None, "qty"),
            _f("Handwritten values to check", n_check or None, "qty"),
        )
        has = lambda attr: any(getattr(r, attr) not in (None, "", 0) for r in rows)   # noqa: E731
        cols = [_c("sno", "#", "qty"), _c("item", "Item"), _c("unit", "Unit"), _c("po_qty", "PO qty", "qty")]
        if any(r.vendor_qty for r in rows):
            cols.append(_c("vendor_qty", "Vendor claimed", "qty"))
        cols += [_c("audit_qty", "Audited", "qty"), _c("verdict", "Meaning")]
        if has("mounted") or has("unmounted") or has("damaged"):
            cols += [_c("mounted", "Mounted", "qty"), _c("unmounted", "Unmounted", "qty"), _c("damaged", "Damaged", "qty")]
        if has("rate"):
            cols.append(_c("rate", "Rate", "money"))
        if has("rate_after_discount"):
            cols.append(_c("rate_after_discount", "Rate after discount", "money"))
        if has("rate") or has("rate_after_discount"):
            # What the AUDITED quantity is worth at the report's own rate: the
            # number a reviewer is actually reconciling, and until now the one
            # thing this table made them work out for themselves.
            cols.append(_c("value", "Value of audited ₹", "money"))
        if has("amount"):
            # The report's own total, shown as printed. We never substitute our
            # own multiplication for it — the point is to compare the two.
            cols.append(_c("amount", "Total as printed", "money"))
        cols.append(_c("remark", "Auditor remark"))
        d["tables"] = [{"title": "Audit rows", "columns": cols, "rows": [self._ev_row(r) for r in rows]}]
        return d

    def _ev_row(self, r: EvidenceRow) -> dict:
        v = r.verdict or self.verdicts.classify(r)
        alts = r.audit_qty.alternatives if r.audit_qty else []
        flag = None
        if r.needs_review:
            flag = "Two readings disagree" if alts else "Handwriting to check"
        # A scan can misread a rate without anything looking wrong — until the
        # row's own printed total contradicts it.
        flag = flag or rules.audit_row_arithmetic(r)
        audit = _v(r.audit_qty)
        raw = _t(r.audit_qty_raw)
        if raw is not None and audit is not None and parse_inr(raw) == audit:
            raw = None                       # "1.00" for 1 — nothing worth showing
        return {
            "_key": r.key, "id": r.key[3:] if r.key.startswith("ev:") else None, "sno": r.sno,
            "item": r.item + (" (extra, not in PO)" if r.row_type == "additional" else ""), "unit": _t(r.unit),
            "po_qty": r.po_qty, "vendor_qty": _v(r.vendor_qty), "audit_qty": audit,
            "audit_raw": raw, "verdict": _VERDICT_LABEL.get(v, v.value if v else None),
            "mounted": r.mounted, "unmounted": r.unmounted, "damaged": r.damaged, "rate": r.rate,
            "rate_after_discount": r.rate_after_discount, "amount": r.amount,
            "value": rules.audit_row_value(r),
            "remark": _t(r.remark), "_flag": flag, "_alts": alts,
            "_page": r.audit_qty.page if r.audit_qty else None,
        }

    def _pod(self, p: ExtractedPOD, seg: dict) -> dict:
        d = self._base(seg, "pod", SegmentKind.POD.value, f"Delivery proof {p.waybill_no or ''}".strip(), "upload")
        d["fields"] = _fields(
            _f("Waybill / LR", p.waybill_no), _f("Carrier", p.carrier), _f("Shipped on", p.ship_date, "date"),
            _f("Invoices on it", ", ".join(p.invoice_nos) or None), _f("Invoice value", p.total_invoice_value, "money"),
            _f("Packages", p.packages, "qty"), _f("Weight", p.weight, "qty"),
            _f("Received by", p.receipt.receiver), _f("Received on", p.receipt.date, "date"),
            _f("Receipt stamp", p.receipt.stamp_text),
        )
        return d

    def _memo(self, m: ExtractedMemo, seg: dict) -> dict:
        d = self._base(seg, "memo", SegmentKind.APPROVAL_MEMO.value, f"Approval memo {m.memo_ref or ''}".strip(), "upload")
        d["fields"] = _fields(_f("Memo", m.memo_ref), _f("Subject", m.subject), _f("Store", m.store_sn),
                              _f("Vendor", m.vendor_name))
        if m.approvals:
            d["tables"] = [{"title": "Approvals",
                            "columns": [_c("approver", "Approver"), _c("status", "Status"), _c("date", "Date", "date"),
                                        _c("remark", "Remark")],
                            "rows": [{"approver": a.approver, "status": a.status, "date": a.date, "remark": a.remark}
                                     for a in m.approvals]}]
        if m.body:
            d["fields"].append(_f("Text", m.body))
        return d

    def _other(self, o: ExtractedOther, rows: list[EvidenceRow], seg: dict) -> dict:
        d = self._base(seg, seg.get("role") or "other", SegmentKind.OTHER.value, o.llm_label or "Other document", "upload")
        d["fields"] = _fields(_f("What it is", o.llm_label), _f("Summary", o.summary),
                              *[_f(k, v) for k, v in (o.key_values or {}).items()])
        if rows:
            d["tables"] = [{"title": "Rows",
                            "columns": [_c("item", "Item"), _c("unit", "Unit"), _c("po_qty", "PO qty", "qty"),
                                        _c("audit_qty", "Quantity", "qty"), _c("remark", "Remark")],
                            "rows": [self._ev_row(r) for r in rows]}]
        return d


def _file_type(name: str) -> str:
    ext = (name or "").lower().rsplit(".", 1)[-1]
    if ext == "pdf":
        return "pdf"
    if ext in ("png", "jpg", "jpeg", "webp", "gif", "tif", "tiff", "heic"):
        return "image"
    if ext in ("xlsx", "xlsm", "xls", "csv"):
        return "sheet"
    return "other"


# Which line-result key points at a row of each kind of document.
_ROLE_KEY = {"po": "po_key", "invoice": "invoice_key", "evidence": "evidence_key", "other": "evidence_key"}

_CMP_FIELDS = ("po_qty", "po_rate", "billed_qty", "billed_rate", "verified_qty", "vendor_qty", "expected_qty",
               "expected_amt", "billed_amt", "delta", "statuses", "severity", "verdict", "conflicts", "kind", "match_method",
               "match_score", "remark",
               # The priced side of the audit leg. Without these, opening the site
               # report showed its rate and left the invoice's beside it unsaid —
               # the one comparison that screen exists to make.
               "verified_rate", "verified_amt", "received_qty", "received_amt")


def _lines_by_key(lines: list[dict]) -> dict[tuple[str, str], dict]:
    out: dict[tuple[str, str], dict] = {}
    for l in lines:
        for f in ("po_key", "invoice_key", "evidence_key"):
            if l.get(f):
                out.setdefault((f, l[f]), l)
    return out


def _cmp(line: dict | None) -> dict | None:
    """The reconciled line a row took part in — what the other documents say about it."""
    if not line:
        return None
    d = {k: line.get(k) for k in _CMP_FIELDS}
    d["id"] = line.get("id")
    d["reviewed"] = bool(line.get("reviewed"))
    return d


def _context(case: dict, docs: list[dict], header: list[dict], role: str | None = None) -> dict:
    """How many ways this invoice is checked, and the case's headline numbers.

    With `role`, the checks are narrowed to the ones about THAT document plus
    the invoice itself — someone who opened the site report is asking how the
    site report compares with the bill, not what the payment advice said
    (vocab.CHECK_DOCUMENT).
    """
    roles = {d["role"] for d in docs}
    coverage = {"po": "po" in roles, "invoice": "invoice" in roles, "evidence": "evidence" in roles, "pod": "pod" in roles}
    s = case.get("summary_json") or {}
    return {
        "id": str(case["id"]), "ref": f"RC-{int(case['ref_no']):04d}" if case.get("ref_no") else None,
        "invoice_no": case.get("invoice_no"), "po_number": case.get("po_number"),
        "store_sn": case.get("store_sn"), "status": case["status"], "coverage": coverage,
        "ways": sum(1 for v in coverage.values() if v),
        "totals": {"po_total": s.get("po_total"), "expected_total": s.get("expected_total"),
                   "billed_total": s.get("billed_total"), "invoice_total": s.get("invoice_total"),
                   "money_at_risk": case.get("money_at_risk"),
                   "under_billed": case.get("under_billed")},
        "counts": case.get("counts") or {},
        "checks": [{"code": h["code"], "label": h["label"], "severity": h["severity"], "passed": h["passed"],
                    "detail": h.get("detail")} for h in header
                   if role in (None, "invoice")
                   or vocab.CHECK_DOCUMENT.get(h["code"], "invoice") == role],
        # What this screen is showing, so it can say so rather than claiming to
        # be the whole reconciliation.
        "scope": role,
    }


def _c(key: str, label: str, fmt: str = "text") -> dict:
    """A table column. `code` is its vocabulary role (QTY_VERIFIED, RATE_NET, …) where it has one."""
    code = vocab.COLUMN_QTY_ROLE.get(key) or vocab.COLUMN_RATE_ROLE.get(key)
    return {"key": key, "label": label, "fmt": fmt, **({"code": code} if code else {})}


def _part_vocab(seg: dict | None, kind: str) -> dict:
    """A part's vocabulary codes (docs/RECON_VOCABULARY.md): from the segment's generated columns when it
    has a row, else from its kind (a PO from the register, a bill already in the app)."""
    seg = seg or {}
    layout = None
    ex = seg.get("extracted_json")
    if isinstance(ex, dict):
        layout = ex.get("layout")
    return {
        "doc_role": seg.get("doc_role") or vocab.SEGMENT_KIND_ROLE.get(kind),
        "recon_leg": seg.get("recon_leg") or vocab.SEGMENT_KIND_LEG.get(kind),
        "receipt_granularity": seg.get("receipt_granularity") or vocab.SEGMENT_KIND_GRANULARITY.get(kind),
        "pv_format": seg.get("pv_format") or vocab.LAYOUT_PV_FORMAT.get(layout or ""),
        "evidence_layer": seg.get("evidence_layer") or vocab.LAYOUT_EVIDENCE_LAYER.get(layout or ""),
    }


def _low_conf(s: Sourced | None) -> str | None:
    return "Low-confidence reading" if s and s.confidence < 0.9 else None


def _arith_flag(q, r, a) -> str | None:
    """qty × rate ≠ amount on the document itself (beyond ₹1 rounding)."""
    if q is None or r is None or a is None:
        return None
    try:
        if abs(Decimal(q) * Decimal(r) - Decimal(a)) > 1:
            return f"Qty × rate = {round(Decimal(q) * Decimal(r), 2)}, the document prints {a}"
    except Exception:
        return None
    return None
