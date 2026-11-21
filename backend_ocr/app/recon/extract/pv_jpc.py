"""JpcAnnexureExtractor — typed physical-verification annexures (03_LLD_BACKEND.md §10.3).

J P Chawla's report prints each annexure as a real table with a text layer:
Sr · Vendor · Work · FA Code · Item Name · Unit · Qty as per PO (A) · Given/Vendor
Qty (B) · Verified Qty (C) · C−A · C−B · Remarks. pymupdf's table finder reads it
exactly, so these rows carry confidence 1.0 and never need a human check.
Rows past the PO list are tagged "Additional work" in the FA Code column.
"""
from __future__ import annotations

import re
from collections import Counter

from ..types import EvidenceRow, Party, PVSection
from .base import ExtractContext, Extractor, dec, parse_date, src

_COLS = {
    "sno": ("sr",), "vendor": ("vendor",), "work": ("work",), "fa": ("fa code",), "item": ("item name",),
    "unit": ("unit",), "po": ("qty as per", "(a)"), "given": ("given", "(b)"), "verified": ("verified qty", "(c)"),
    "remarks": ("remark",),
}


def _clean(v) -> str:
    return re.sub(r"\s+", " ", str(v or "")).strip()


def _map_header(row: list) -> dict[str, int]:
    out: dict[str, int] = {}
    cells = [_clean(c).lower() for c in row]
    for key, needles in _COLS.items():
        for i, c in enumerate(cells):
            if i in out.values():
                continue
            if key == "verified" and ("vs" in c):
                continue
            if all(n in c for n in needles[:1]) and (len(needles) == 1 or any(n in c for n in needles)):
                out[key] = i
                break
    return out


class JpcAnnexureExtractor(Extractor):
    version = "jpc1"

    async def extract(self, seg, ctx: ExtractContext) -> PVSection:
        rows: list[EvidenceRow] = []
        vendors: Counter = Counter()
        assert ctx.doc is not None
        for i in seg.pages:
            page = ctx.doc[i - 1]
            for table in page.find_tables().tables:
                data = table.extract()
                if not data:
                    continue
                hidx = next((k for k, r in enumerate(data) if any("item name" in _clean(c).lower() for c in r)), None)
                if hidx is None:
                    continue
                cols = _map_header(data[hidx])
                if "item" not in cols or "verified" not in cols:
                    continue
                cells = table.rows
                for k, r in enumerate(data[hidx + 1:], start=hidx + 1):
                    get = lambda key: _clean(r[cols[key]]) if key in cols and cols[key] < len(r) else ""
                    item = get("item")
                    if not item or not get("sno").isdigit():
                        continue
                    vendors[get("vendor")] += 1
                    po_qty = dec(get("po"))
                    additional = "additional" in get("fa").lower() or po_qty is None
                    bbox = None
                    try:
                        cb = cells[k].cells[cols["verified"]]
                        bbox = [round(x, 1) for x in cb] if cb else None
                    except (IndexError, AttributeError, TypeError):
                        pass
                    remark = get("remarks") or None
                    rows.append(EvidenceRow(
                        key=f"tmp:{i}:{k}", sno=int(get("sno")), asset_code=get("fa") if get("fa") not in ("-", "") else None,
                        item=item, unit=get("unit") or None, po_qty=po_qty,
                        vendor_qty=src(get("given")), audit_qty=src(get("verified"), 1.0, page=i, bbox=bbox,
                                                                     raw=get("verified")),
                        audit_qty_raw=get("verified") or None, remark=remark,
                        row_type="additional" if additional else "po"))
        vendor = vendors.most_common(1)[0][0] if vendors else (seg.vendor_name or "")
        narrative = ctx.narrative_text
        date = None
        m = re.search(r"Date of audit\s*:?\s*([\d./-]+)", narrative or "")
        if m:
            date = parse_date(m.group(1))
        auditor = "J P Chawla & Co. LLP" if "chawla" in (narrative or "").lower() else None
        sec = PVSection(auditor=auditor, store_sn=seg.store_sn, verification_date=date,
                        vendor=Party(name=vendor), section_title=seg.section_title, layout="jpc_typed",
                        rows=rows, extractor_version=self.version)
        others = [v for v in vendors if v and v != vendor]
        if others:
            sec.warnings.append(f"section also lists rows for: {', '.join(others)}")
        return sec
