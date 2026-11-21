"""POExtractor — Bata's ERP purchase order print (03_LLD_BACKEND.md §10.1).

The PO has a text layer, so it is read deterministically from word positions:
column edges come from the header row (S.No. · Description · Delivery · Qty ·
Unit · Unit Pr. · Amt. · HSN/SAC), a line starts where a serial number and a
delivery date sit, and the narrow Description column is collected downwards
until the next line. No model is involved; a PO in an unknown layout (or a
scan) goes to the LLM fallback.
"""
from __future__ import annotations

import re
from decimal import Decimal

from ..num import round2
from ..types import ExtractedPO, Party, PenaltyTerm, POLine
from .base import ExtractContext, Extractor, dec, parse_date

_DATE = re.compile(r"^\d{2}-\d{2}-\d{4}$")
_NUM = re.compile(r"^[\d,]+(\.\d+)?$")
_HEADER_STOP = {"BATA", "Milestone", "Gurugram", "Currency", "Sales", "PROPOSED"}

PO_PROMPT = """Extract this purchase order as JSON:
{"po_number": "...", "po_date": "dd-mm-yyyy", "vendor": {"name": "...", "gstin": "...", "account": "..."},
 "buyer_gstin": "...", "payment_terms": "...", "requisition_no": "...", "requisition_name": "...",
 "lines": [{"sno": 1, "description": "full text, joined across wrapped lines", "unit": "...", "qty": "...",
            "unit_price": "...", "amount": "...", "delivery_date": "dd-mm-yyyy"}],
 "subtotal": "...", "tax": "...", "total": "..."}
Copy numbers exactly as printed. Skip terms-and-conditions text."""


def _center(w) -> float:
    return (w[0] + w[2]) / 2


class POExtractor(Extractor):
    version = "po1"

    async def extract(self, seg, ctx: ExtractContext) -> ExtractedPO:
        pages = [ctx.pages[i] for i in seg.pages if i in ctx.pages]
        if pages and all(p.has_text_layer and p.words for p in pages):
            po = self.from_words(pages)
            if po is not None and po.lines:
                self._header(po, "\n".join(p.text for p in pages))
                self._penalties(po, "\n".join(ctx.pages[i].text for i in [*seg.pages, *seg.support_pages]
                                               if i in ctx.pages))
                self._check(po)
                return po
        return await self._llm(seg, ctx)

    # ── text layer ─────────────────────────────────────────────────────────────
    def from_words(self, pages) -> ExtractedPO | None:
        lines: list[POLine] = []
        for p in pages:
            ws = p.words
            hdr = [w for w in ws if w[4] == "S.No."]
            if not hdr:
                continue
            hy = hdr[0][1]
            row_hdr = sorted((w for w in ws if abs(w[1] - hy) < 3), key=lambda w: w[0])
            names = [w[4] for w in row_hdr]
            try:
                x_desc = row_hdr[names.index("Description")][0]
                x_deliv = row_hdr[names.index("Delivery")][0]
                x_qty = row_hdr[names.index("Qty")][0]
                i_unit = names.index("Unit")
                x_unit = row_hdr[i_unit][0]
                x_price = row_hdr[i_unit + 1][0] if names[i_unit + 1] == "Unit" else row_hdr[names.index("Pr.")][0] - 16
                x_amt = row_hdr[names.index("Amt.")][0]
                x_hsn = row_hdr[names.index("HSN/SAC")][0]
            except (ValueError, IndexError):
                continue
            edges = [("sno", -1, x_desc - 3), ("desc", x_desc - 3, x_deliv - 3), ("deliv", x_deliv - 3, x_qty - 6),
                     ("qty", x_qty - 6, x_unit - 4), ("unit", x_unit - 4, x_price - 5),
                     ("price", x_price - 5, x_amt - 14), ("amt", x_amt - 14, x_hsn - 2)]

            def col(w):
                c = _center(w)
                return next((name for name, lo, hi in edges if lo <= c < hi), None)

            body = sorted((w for w in ws if w[1] > hy + 5), key=lambda w: (round(w[1]), w[0]))
            starts = []
            for w in body:
                if col(w) == "sno" and w[4].isdigit():
                    same = [x for x in body if abs(x[1] - w[1]) < 2.5]
                    if any(col(x) == "deliv" and _DATE.match(x[4]) for x in same):
                        starts.append((w[1], int(w[4]), same))
            stop_y = min((w[1] for w in body if w[4] in _HEADER_STOP and w[1] > hy), default=10_000)
            for k, (y, sno, same) in enumerate(starts):
                y_next = starts[k + 1][0] if k + 1 < len(starts) else stop_y
                desc_words = sorted((w for w in body if col(w) == "desc" and y - 2 <= w[1] < y_next - 2),
                                    key=lambda w: (round(w[1]), w[0]))
                get = lambda name: " ".join(x[4] for x in sorted(same, key=lambda x: x[0]) if col(x) == name)
                qty, unit, price, amt = dec(get("qty")), get("unit") or None, dec(get("price")), dec(get("amt"))
                if qty is None or price is None:
                    continue
                lines.append(POLine(sno=sno, description=" ".join(w[4] for w in desc_words), unit=unit, qty=qty,
                                    unit_price=price, amount=amt if amt is not None else round2(qty * price),
                                    delivery_date=parse_date(get("deliv"))))
        if not lines:
            return None
        lines.sort(key=lambda l: l.sno)
        uniq: dict[int, POLine] = {}
        for l in lines:
            uniq.setdefault(l.sno, l)
        return ExtractedPO(po_number="", lines=list(uniq.values()), extractor_version=self.version)

    def _header(self, po: ExtractedPO, text: str) -> None:
        def grab(rx, flags=0):
            m = re.search(rx, text, flags)
            return m.group(1).strip() if m else None
        po.po_number = grab(r"\b(PPO\d{8}-\d+)\b") or grab(r"Number\s+(\S+)") or ""
        rev = po.po_number.rpartition("-")[2]
        po.revision = int(rev) if rev.isdigit() else 1
        po.po_date = parse_date(grab(r"\bDate\s+(\d{2}-\d{2}-\d{4})"))
        po.payment_terms = grab(r"Terms of payment\s+(\S+)")
        po.requisition_no = grab(r"Purchase requisition\s+(PPR\d+)")
        rn = re.search(r"Purchase requisition name\s+(.+?)\n\s*(.+?)\n", text)
        if rn:
            tail = rn.group(2).strip()
            po.requisition_name = rn.group(1).strip() + (" " + tail if len(tail) < 60 and not tail.startswith("S.No") else "")
        m = re.search(r"\bSN\s*(\d{3,5})\b", po.requisition_name or "") or re.search(r"\bSN\s*(\d{3,5})\b", text)
        po.store_sn = m.group(1) if m else None
        po.store_name = re.sub(r"\s+(New\s+FSC|New\s+HP|Ren|PO\s+SN).*$", "", po.requisition_name or "").strip() or None
        gst = re.findall(r"\b(\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z])\b", text)
        vendor_gstin = grab(r"GSTIN:\s*(\w{15})")
        po.vendor = Party(name=(grab(r"^\s*(.+?)\s{2,}Purchase order", re.M) or "").strip(), gstin=vendor_gstin,
                          account=grab(r"Vendor account:\s*(V\d+)"))
        po.buyer_gstin = next((g for g in gst if g != vendor_gstin), None)
        m = re.search(r"\bINR\s+([\d,]+\.\d{2})\s+([\d,]+\.\d{2})\s+([\d,]+\.\d{2})\s+([\d,]+\.\d{2})\s+"
                      r"([\d,]+\.\d{2})\s+([\d,]+\.\d{2})", text)
        if m:
            po.subtotal, po.tax, po.total = dec(m.group(1)), dec(m.group(4)), dec(m.group(6))
        dd = [l.delivery_date for l in po.lines if l.delivery_date]
        po.delivery_date = max(dd) if dd else None

    @staticmethod
    def _penalties(po: ExtractedPO, terms: str) -> None:
        """'first 7 days: … 10% …; Second 7 days: … 20% …; thereafter: 10% for every day'."""
        t = re.sub(r"\s+", " ", terms or "")
        if "late delivery penalty" not in t.lower():
            return
        m1 = re.search(r"first (\d+) days?: late delivery penalty amounting to (\d+)%", t, re.I)
        m2 = re.search(r"second (\d+) days?: late delivery penalty amounting to (\d+)%", t, re.I)
        m3 = re.search(r"thereafter: (\d+)% for every day", t, re.I)
        a = int(m1.group(1)) if m1 else 7
        if m1:
            po.penalties.append(PenaltyTerm(days_from=1, days_to=a, pct=Decimal(m1.group(2))))
        b = a + (int(m2.group(1)) if m2 else 7)
        if m2:
            po.penalties.append(PenaltyTerm(days_from=a + 1, days_to=b, pct=Decimal(m2.group(2))))
        if m3:
            po.penalties.append(PenaltyTerm(days_from=b + 1, days_to=None, pct=Decimal(m3.group(1)), per_day=True))

    @staticmethod
    def _check(po: ExtractedPO) -> None:
        s = sum((l.amount for l in po.lines), Decimal(0))
        if po.subtotal is not None and abs(s - po.subtotal) > 1:
            po.warnings.append(f"po_footing: lines add up to {s}, PO sub total {po.subtotal}")
        for l in po.lines:
            if abs(round2(l.qty * l.unit_price) - l.amount) > 1:
                po.warnings.append(f"po_line_arithmetic: line {l.sno} {l.qty} × {l.unit_price} ≠ {l.amount}")

    # ── fallback ───────────────────────────────────────────────────────────────
    async def _llm(self, seg, ctx: ExtractContext) -> ExtractedPO:
        if ctx.llm is None:
            raise RuntimeError("PO layout not recognised and no LLM configured")
        if ctx.all_text_layer(seg.pages):
            r = await ctx.llm.json("po", PO_PROMPT, text=ctx.text(seg.pages))
        else:
            r = await ctx.vision("po", PO_PROMPT, seg.pages)
        lines = []
        for i, l in enumerate(r.get("lines") or [], 1):
            q, p = dec(l.get("qty")), dec(l.get("unit_price"))
            if q is None or p is None:
                continue
            a = dec(l.get("amount"))
            lines.append(POLine(sno=int(l.get("sno") or i), description=str(l.get("description") or ""),
                                unit=l.get("unit"), qty=q, unit_price=p, amount=a if a is not None else round2(q * p),
                                delivery_date=parse_date(l.get("delivery_date"))))
        from .base import party
        po = ExtractedPO(po_number=str(r.get("po_number") or ""), po_date=parse_date(r.get("po_date")),
                         vendor=party(r.get("vendor")), buyer_gstin=r.get("buyer_gstin"),
                         payment_terms=r.get("payment_terms"), requisition_no=r.get("requisition_no"),
                         requisition_name=r.get("requisition_name"), lines=lines, subtotal=dec(r.get("subtotal")),
                         tax=dec(r.get("tax")), total=dec(r.get("total")), extractor_version=self.version + "-llm")
        m = re.search(r"\bSN\s*(\d{3,5})\b", po.requisition_name or "")
        po.store_sn = m.group(1) if m else seg.store_sn
        self._check(po)
        return po
