"""ScannedSheetExtractor — auditor sheets with handwritten quantities (03_LLD_BACKEND.md §10.4).

The riskiest numbers in the system, so every page is read twice, independently:
  read A — SHEET_MODEL reads the table row by row, every cell of a row together
           (printed item, PO qty, rates; handwritten Vendor Qty / Audit Qty; remark);
  read B — SHEET_CHECK_MODEL, a different model, does the same from the same image.
Read A gives the rows; read B is lined up with them by item. Where both read the
same Vendor Qty and Audit Qty the value is accepted (confidence 0.97). Where they
don't, or a cell is arithmetic / struck through / illegible, the row is marked
needs_review and both readings are kept for the reviewer.

Why whole rows: reading the printed rows first and the handwritten cells in a
second pass let the two drift apart — on the Yelanka Interior sheet, gpt-4o
returned 16 of 32 rows and gave Wall Mirror the tiles' quantities.
"""
from __future__ import annotations

import asyncio
import re

from rapidfuzz import fuzz

from .. import config as C
from ..num import parse_inr
from ..types import EvidenceRow, Party, PVSection, Sourced
from . import prompts as P
from .base import ExtractContext, Extractor, dec, parse_date, party, text


class ScannedSheetExtractor(Extractor):
    version = "sheet3"

    async def extract(self, seg, ctx: ExtractContext) -> PVSection:
        if ctx.llm is None:
            raise RuntimeError("scanned sheets need the LLM")
        rows: list[EvidenceRow] = []
        head: dict = {}
        for page in seg.pages:
            img = ctx.png(page)
            a, b = await asyncio.gather(
                ctx.llm.json("sheet_rows", P.SHEET_ROWS, images=[img], model=C.SHEET_MODEL, max_tokens=16000),
                ctx.llm.json("sheet_rows_check", P.SHEET_ROWS, images=[img], model=C.SHEET_CHECK_MODEL,
                             max_tokens=16000),
                return_exceptions=True)
            del img
            if isinstance(a, BaseException):
                if isinstance(b, BaseException):
                    raise a
                a, b = b, {}                       # one reader failed: keep the other, every row to check
            if isinstance(b, BaseException):
                b = {}
            if not head:
                head = a
            ra = _rows(a)
            rb = _align(ra, _rows(b)) if b else [{} for _ in ra]
            for i, (x, y) in enumerate(zip(ra, rb), 1):
                rows.append(self._row(page, i, x, y, checked=bool(b)))
        sec = PVSection(
            auditor=_auditor(ctx.narrative_text), store_sn=text(head.get("store_sn")) or seg.store_sn,
            verification_date=parse_date(text(head.get("verification_date"))), vendor=party(head.get("vendor")),
            section_title=text(head.get("section_title")) or seg.section_title, layout="matolia_scan", rows=rows,
            extractor_version=self.version)
        if not sec.vendor.gstin and seg.vendor_gstin:
            sec.vendor = Party(name=sec.vendor.name or (seg.vendor_name or ""), gstin=seg.vendor_gstin)
        n = sum(1 for r in rows if r.needs_review)
        if n:
            sec.warnings.append(f"{n} handwritten value(s) to check")
        return sec

    @staticmethod
    def _row(page: int, i: int, a: dict, b: dict, checked: bool = True) -> EvidenceRow:
        va, vb = _qty(a.get("audit_qty")), _qty(b.get("audit_qty"))
        raw = str(a.get("audit_qty_raw") or a.get("audit_qty") or "").strip()
        agree = checked and va == vb
        odd = bool(re.search(r"[+=~]|struck", raw)) or a.get("legible") is False or b.get("legible") is False
        conf = 0.97 if agree and not odd else 0.5
        alts = [] if agree or not checked else [str(x) for x in (va, vb)]
        audit = Sourced(value=va if va is not None else vb, confidence=conf, page=page, raw=raw or None,
                        alternatives=alts) if (va is not None or vb is not None) else None
        vqa, vqb = _qty(a.get("vendor_qty")), _qty(b.get("vendor_qty"))
        v_agree = checked and vqa == vqb
        vendor = Sourced(value=vqa if vqa is not None else vqb, confidence=0.97 if v_agree else 0.5, page=page,
                         alternatives=[] if v_agree or not checked else [str(x) for x in (vqa, vqb)]
                         ) if (vqa is not None or vqb is not None) else None
        remark = text(a.get("remark")) or text(b.get("remark"))
        needs_review = (not agree) or odd
        return EvidenceRow(
            key=f"tmp:{page}:{i}", sno=i, asset_code=text(a.get("asset_code")), item=str(a["item"]).strip(),
            unit=text(a.get("unit")), po_qty=dec(a.get("po_qty")), vendor_qty=vendor, audit_qty=audit,
            audit_qty_raw=raw or None, remark=remark, rate=dec(a.get("rate")),
            rate_after_discount=dec(a.get("rate_after_discount")),
            amount=dec(a.get("amount")),
            row_type="additional" if a.get("in_additional_block") else "po", needs_review=needs_review)


def _rows(r: dict) -> list[dict]:
    return [x for x in (r or {}).get("rows") or [] if isinstance(x, dict) and str(x.get("item") or "").strip()]


def _align(a: list[dict], b: list[dict]) -> list[dict]:
    """Read B's row for each of read A's rows, by item text, in order (a missing row → {}).

    Same count and the same items in the same places is the usual case; otherwise
    each A row takes the best still-unused B row nearby whose item reads alike.
    """
    def key(x: dict) -> str:
        return re.sub(r"[^a-z0-9]+", " ", str(x.get("item") or "").lower()).strip()

    if len(a) == len(b) and all(fuzz.token_set_ratio(key(x), key(y)) >= 70 for x, y in zip(a, b)):
        return list(b)
    out: list[dict] = []
    used: set[int] = set()
    for i, x in enumerate(a):
        best, best_j = 0.0, None
        for j in range(max(0, i - 6), min(len(b), i + 7)):
            if j in used:
                continue
            s = fuzz.token_set_ratio(key(x), key(b[j])) - abs(i - j)
            if s > best:
                best, best_j = s, j
        if best_j is not None and best >= 75:
            used.add(best_j)
            out.append(b[best_j])
        else:
            out.append({})
    return out


def _qty(v):
    return parse_inr(v)


def _auditor(narrative: str) -> str | None:
    t = (narrative or "").lower()
    if "matolia" in t:
        return "Matolia Rai & Associates"
    if "chawla" in t:
        return "J P Chawla & Co. LLP"
    return None
