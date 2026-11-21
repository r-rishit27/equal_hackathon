"""POD, memo, field-sheet and unknown-document extractors (03_LLD_BACKEND.md §10.5–10.8)."""
from __future__ import annotations

import re

from ..num import parse_inr
from ..types import Approval, EvidenceRow, ExtractedMemo, ExtractedOther, ExtractedPOD, PVSection, Receipt, Sourced
from . import prompts as P
from .base import ExtractContext, Extractor, dec, parse_date


class PODExtractor(Extractor):
    version = "pod1"

    async def extract(self, seg, ctx: ExtractContext) -> ExtractedPOD:
        if ctx.llm is None:
            raise RuntimeError("POD extraction needs the LLM")
        r = await ctx.vision("pod", P.POD, seg.pages)
        rc = r.get("receipt") or {}
        nos = [str(x).strip() for x in (r.get("invoice_nos") or []) if str(x).strip()]
        pod = ExtractedPOD(
            waybill_no=_s(r.get("waybill_no")), carrier=_s(r.get("carrier")), invoice_nos=nos,
            total_invoice_value=dec(r.get("total_invoice_value")), packages=_int(r.get("packages")),
            weight=dec(r.get("weight")), ship_date=parse_date(r.get("ship_date")),
            receipt=Receipt(stamp_text=_s(rc.get("stamp_text")), receiver=_s(rc.get("receiver")),
                            date=parse_date(rc.get("date"))), extractor_version=self.version)
        if rc.get("date") and pod.receipt.date is None:
            pod.warnings.append(f"receipt date '{rc['date']}' could not be read as a date")
        return pod


class MemoExtractor(Extractor):
    """Text layer (Bata's web memo print) is parsed directly; scans go to the model."""
    version = "memo1"
    _ROW = re.compile(r"^\s*([A-Z][A-Za-z .]+?)\s{2,}(Approved|Rejected|Pending|Returned)\s+(\d{2}-\d{2}-\d{4})\s*(.*)$",
                      re.M)

    async def extract(self, seg, ctx: ExtractContext) -> ExtractedMemo:
        text = ctx.text(seg.pages) if ctx.all_text_layer(seg.pages) else ""
        if text and "Approver" in text:
            return self.from_text(text)
        if ctx.llm is None:
            raise RuntimeError("scanned memo needs the LLM")
        r = await ctx.llm.json("memo", P.MEMO, images=[ctx.png(i) for i in seg.pages[:1]])
        m = ExtractedMemo(memo_ref=_s(r.get("memo_ref")), subject=_s(r.get("subject")),
                          vendor_name=_s(r.get("vendor_name")), body=_s(r.get("body")),
                          approvals=[Approval(approver=str(a.get("approver") or "").strip(),
                                              status=str(a.get("status") or "").strip(),
                                              date=parse_date(a.get("date")), remark=_s(a.get("remark")))
                                     for a in r.get("approvals") or [] if a.get("approver")],
                          extractor_version=self.version + "-llm")
        m.store_sn = _store(m.subject)
        return m

    def from_text(self, text: str) -> ExtractedMemo:
        g = lambda rx: (re.search(rx, text, re.M) or [None, None])[1]
        subject = (g(r"Subject:\s*(.+)$") or "").strip() or None
        approvals = [Approval(approver=m.group(1).strip(), status=m.group(2), date=parse_date(m.group(3)),
                              remark=_remark(m.group(4))) for m in self._ROW.finditer(text)]
        return ExtractedMemo(memo_ref=(g(r"Memo Ref\.?\s*:\s*(\S+)") or None), subject=subject,
                             store_sn=_store(subject), approvals=approvals,
                             body=(g(r"(Please .+)$") or None), extractor_version=self.version)


class FieldSheetExtractor:
    """Signed site sheets (Mounted / Unmounted / Damaged) — corroboration merged into a section's rows."""
    version = "field2"
    _BOXES = ("mounted", "unmounted", "damaged", "total")

    async def merge(self, section: PVSection, pages: list[int], ctx: ExtractContext) -> None:
        """Every page is read twice, by two models, from the same image. A row whose handwritten boxes the
        two readers read differently is sent to review with both readings in its remark."""
        import asyncio

        from .. import config as C
        if ctx.llm is None or not pages:
            return
        by_sno = {r.sno: r for r in section.rows if r.sno is not None}
        for page in pages:
            img = ctx.png(page)
            r, chk = await asyncio.gather(
                ctx.llm.json("field_sheet", P.FIELD_SHEET, images=[img]),
                ctx.llm.json("field_sheet_check", P.FIELD_SHEET, images=[img], model=C.FIELD_CHECK_MODEL),
                return_exceptions=True)
            del img
            if isinstance(r, BaseException):
                if isinstance(chk, BaseException):
                    raise r
                r, chk = chk, None                    # one reader failed: use the other, unchecked
            if isinstance(chk, BaseException) or chk is None:
                chk = None
                section.warnings.append(f"field sheet p{page}: read once — the check read failed")
            check = {_int(x.get("sno")): x for x in (chk or {}).get("rows") or [] if isinstance(x, dict)}
            vendor = (r.get("vendor") or "").lower()
            if vendor and section.vendor.name and section.vendor.name.lower()[:8] not in vendor:
                continue
            for x in r.get("rows") or []:
                sno = _int(x.get("sno"))
                row = by_sno.get(sno)
                if row is None:
                    continue
                row.mounted, row.unmounted, row.damaged = (_int0(x.get(k)) for k in ("mounted", "unmounted", "damaged"))
                if chk is not None:
                    y = check.get(sno)
                    differ = [k for k in self._BOXES if y is None or _box(x.get(k)) != _box(y.get(k))]
                    if differ:
                        row.needs_review = True
                        seen = ", ".join(f"{k} {_box(x.get(k))} or {_box((y or {}).get(k))}" for k in differ)
                        note = f"field sheet read two ways: {seen}"
                        row.remark = f"{row.remark} · {note}" if row.remark else note
                total = parse_inr(x.get("total"))
                if x.get("note"):
                    row.remark = f"{row.remark} · site note: {x['note']}" if row.remark else f"site note: {x['note']}"
                a = row.audit_qty.value if row.audit_qty else None
                if total is not None and a is not None and total != a:
                    section.warnings.append(f"row {row.sno}: field sheet total {total} ≠ verified {a}")


class GenericExtractor(Extractor):
    version = "gen1"

    async def extract(self, seg, ctx: ExtractContext) -> ExtractedOther:
        if ctx.llm is None:
            return ExtractedOther(llm_label=seg.llm_label or "Document", summary=None, extractor_version=self.version)
        if ctx.all_text_layer(seg.pages):
            r = await ctx.llm.json("generic", P.GENERIC, text=ctx.text(seg.pages)[:20000])
        else:
            r = await ctx.vision("generic", P.GENERIC, seg.pages[:8])
        rows = []
        for i, x in enumerate(r.get("rows") or [], 1):
            q = parse_inr(x.get("qty"))
            if not x.get("item") or q is None:
                continue
            rows.append(EvidenceRow(key=f"tmp:g:{i}", sno=i, item=str(x["item"]), unit=x.get("unit"),
                                    audit_qty=Sourced(value=q, confidence=0.8), remark=_s(x.get("remark")),
                                    needs_review=True))
        return ExtractedOther(llm_label=_s(r.get("label")) or seg.llm_label, summary=_s(r.get("summary")),
                              key_values={str(k): str(v) for k, v in (r.get("key_values") or {}).items()},
                              rows=rows, extractor_version=self.version)


def _s(v) -> str | None:
    from .base import text
    return text(v)


def _int(v) -> int | None:
    try:
        return int(float(str(v).replace(",", "")))
    except (TypeError, ValueError):
        return None


def _box(v):
    """A field-sheet box as a comparable number ("-" and blank are 0)."""
    n = _int0(v)
    return 0 if n is None else n


def _int0(v) -> int | None:
    s = str(v or "").strip()
    if s in ("-", "–", "—", "~"):
        return 0
    return _int(s)


def _store(subject: str | None) -> str | None:
    m = re.search(r"(?<!\d)(\d{4})(?!\d)\s*$", subject or "") or re.search(r"(?<!\d)(\d{4})(?!\d)", subject or "")
    return m.group(1) if m else None


def _remark(s: str | None) -> str | None:
    s = (s or "").strip()
    return None if not s or "copyright" in s.lower() else s
