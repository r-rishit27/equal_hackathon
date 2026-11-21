"""Extractor contract (02_CLASS_DIAGRAMS.md §3)."""
from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

from .. import config as C
from ..llm import LLM
from ..num import parse_inr
from ..pages import PageInfo, PageReader
from ..segment import Segment
from ..types import ExtractedDoc, ExtractedPO, Party, Sourced
from ..clean import _gstin, gstin_valid, text  # noqa: F401  (re-exported: extractors import them from here)


@dataclass
class ExtractContext:
    tenant_id: str
    supplier_id: str
    supplier_name: str | None = None
    supplier_gstin: str | None = None
    po_hint: ExtractedPO | None = None
    llm: LLM | None = None
    reader: PageReader | None = None
    doc: object | None = None                      # the open pymupdf document
    pages: dict[int, PageInfo] = field(default_factory=dict)
    narrative_text: str = ""                       # PV report narrative (auditor, store, date)

    def png(self, index: int, dpi: int | None = None) -> bytes:
        assert self.reader is not None and self.doc is not None
        return self.reader.render(self.doc, index, dpi=dpi)

    async def vision(self, purpose: str, prompt: str, pages: list[int], text: str | None = None) -> dict:
        """Read page images in batches of RECON_MAX_IMAGES_PER_CALL (4), merging the answers.

        Only one batch of images exists at a time, so an 11-page scan never sits in memory — or in
        one request — at once. Lists (lines, rows, approvals…) are concatenated in page order;
        single values are taken from the first batch that has them.
        """
        assert self.llm is not None
        n = max(1, C.MAX_IMAGES_PER_CALL)
        out: dict = {}
        for start in range(0, len(pages), n):
            batch = pages[start:start + n]
            note = (f"\n\n(These are pages {start + 1}–{start + len(batch)} of {len(pages)} of one document. Read only "
                    "what is on these pages; other pages are read separately.)") if len(pages) > n else ""
            r = await self.llm.json(purpose, prompt + note, text=text, images=[self.png(i) for i in batch])
            _merge(out, r or {})
        return out

    def text(self, seg_pages: list[int]) -> str:
        return "\n\n".join(f"--- Page {i} ---\n{self.pages[i].text}" for i in seg_pages if i in self.pages)

    def all_text_layer(self, seg_pages: list[int]) -> bool:
        return all(self.pages.get(i) and self.pages[i].has_text_layer for i in seg_pages)


def _merge(out: dict, r: dict) -> None:
    for k, v in r.items():
        if isinstance(v, list):
            out.setdefault(k, []).extend(v)
        elif isinstance(v, dict):
            if not out.get(k):
                out[k] = v
        elif out.get(k) in (None, "") and v not in (None, ""):
            out[k] = v


class Extractor(ABC):
    version = "x1"

    @abstractmethod
    async def extract(self, seg: Segment, ctx: ExtractContext) -> ExtractedDoc: ...


# ── helpers shared by extractors ───────────────────────────────────────────────

_DATE_FORMATS = ("%d-%m-%Y", "%d/%m/%Y", "%d.%m.%Y", "%Y-%m-%d", "%d-%b-%y", "%d-%b-%Y", "%d/%m/%y", "%d-%m-%y",
                 "%Y.%m.%d", "%d %b %Y", "%d %B %Y", "%b %d, %Y")


def parse_date(s) -> date | None:
    """dd-first dates in the formats these documents use (E-EX-19). Ambiguous junk → None."""
    if s is None:
        return None
    if isinstance(s, date):
        return s
    t = str(s).strip().replace("Sept", "Sep")
    for f in _DATE_FORMATS:
        try:
            return datetime.strptime(t, f).date()
        except ValueError:
            continue
    try:
        from dateutil import parser as dp
        return dp.parse(t, dayfirst=True).date()
    except Exception:
        return None


def src(v, confidence: float = 1.0, page: int | None = None, bbox=None, raw=None, alternatives=None) -> Sourced | None:
    d = parse_inr(v)
    if d is None:
        return None
    return Sourced(value=d, confidence=confidence, page=page, bbox=bbox, raw=None if raw is None else str(raw),
                   alternatives=alternatives or [])


def dec(v) -> Decimal | None:
    return parse_inr(v)


def party(d: dict | None) -> Party:
    d = d or {}
    return Party(name=text(d.get("name")) or "", gstin=_gstin(text(d.get("gstin"))), account=text(d.get("account")))
