"""ExtractorRegistry — which extractor reads which segment."""
from __future__ import annotations

from ..segment import Segment
from ..types import DocClass, SegmentKind
from .base import ExtractContext, Extractor
from .invoice import InvoiceExtractor
from .misc import FieldSheetExtractor, GenericExtractor, MemoExtractor, PODExtractor
from .po import POExtractor
from .pv_jpc import JpcAnnexureExtractor
from .pv_sheet import ScannedSheetExtractor


def for_segment(seg: Segment) -> Extractor:
    if seg.kind == SegmentKind.PURCHASE_ORDER:
        return POExtractor()
    if seg.kind == SegmentKind.TAX_INVOICE:
        return InvoiceExtractor()
    if seg.kind == SegmentKind.PV_SECTION:
        if DocClass.PV_ANNEXURE_TYPED in seg.classes:
            return JpcAnnexureExtractor()
        return ScannedSheetExtractor()
    if seg.kind == SegmentKind.POD:
        return PODExtractor()
    if seg.kind == SegmentKind.APPROVAL_MEMO:
        return MemoExtractor()
    return GenericExtractor()


__all__ = ["ExtractContext", "Extractor", "FieldSheetExtractor", "for_segment"]
