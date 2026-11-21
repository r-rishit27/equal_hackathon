"""Case → xlsx (03_LLD_BACKEND.md §15). Takes the same JSON the case API returns."""
from __future__ import annotations

import io

_LINE_COLS = [
    ("#", "ord"), ("Item (PO)", "description"), ("Invoice wording", "invoice_text"), ("Report wording", "evidence_text"),
    ("Unit", "unit"), ("PO qty", "po_qty"), ("Verified", "verified_qty"), ("Vendor claimed", "vendor_qty"),
    ("Billed", "billed_qty"), ("Expected qty", "expected_qty"), ("PO rate", "po_rate"), ("Billed rate", "billed_rate"),
    ("Expected ₹", "expected_amt"), ("Billed ₹", "billed_amt"), ("Δ ₹", "delta"), ("Severity", "severity"),
    ("Statuses", "statuses"), ("Match", "match_method"), ("Auditor remark", "remark"), ("Notes", "conflicts"),
]
_NUMERIC = {"po_qty", "verified_qty", "vendor_qty", "billed_qty", "expected_qty", "po_rate", "billed_rate",
            "expected_amt", "billed_amt", "delta"}


def _cell(key: str, v):
    if v is None:
        return None
    if isinstance(v, list):
        return ", ".join(str(x) for x in v)
    if key in _NUMERIC:
        try:
            return float(v)
        except (TypeError, ValueError):
            return v
    return v


def case_workbook(case: dict) -> bytes:
    import openpyxl
    from openpyxl.styles import Font
    wb = openpyxl.Workbook()
    s = case["summary"]
    ws = wb.active
    ws.title = "Summary"
    for k, label in [("invoice_no", "Invoice"), ("po_number", "PO"), ("store_sn", "Store"), ("status", "Status"),
                     ("po_total", "PO value"), ("expected_total", "Expected"), ("billed_total", "Billed"),
                     ("money_at_risk", "Money at risk"), ("under_billed", "Under-billed")]:
        ws.append([label, s.get(k)])
    ws.append([])
    ws.append(["Check", "Result", "Severity", "Detail"])
    for h in case.get("header", []):
        ws.append([h["label"], "OK" if h["passed"] else "Flag", h["severity"], h.get("detail")])
    lines = wb.create_sheet("Lines")
    lines.append([c for c, _ in _LINE_COLS])
    for c in lines[1]:
        c.font = Font(bold=True)
    for l in case.get("lines", []):
        if l.get("kind") in ("po", "not_in_po"):
            lines.append([_cell(k, l.get(k)) for _, k in _LINE_COLS])
    extra = wb.create_sheet("Report only")
    extra.append([c for c, _ in _LINE_COLS])
    for l in case.get("lines", []):
        if l.get("kind") in ("additional", "report_only"):
            extra.append([_cell(k, l.get(k)) for _, k in _LINE_COLS])
    src = wb.create_sheet("Sources")
    src.append(["Role", "File", "Pages", "Section"])
    for a in case.get("attached", []):
        src.append([a.get("role"), a.get("file_name"), ", ".join(str(p) for p in a.get("pages") or []),
                    a.get("section_title") or a.get("summary")])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
