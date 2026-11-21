"""PageReader — one page at a time, text layer first (03_LLD_BACKEND.md §7).

Pages are opened and rendered one by one and the pixmap is dropped right away:
the backend box is small, and rendering a whole long PDF up front is what took
it down in October (88-page OCR incident).
"""
from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from pathlib import Path

from . import config as C

_DIGIT = re.compile(r"\d")
_WORD = re.compile(r"[A-Za-z]{3,}")
_IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".heic"}


@dataclass
class PageInfo:
    index: int                      # 1-based
    text: str = ""
    has_text_layer: bool = False
    source: str = "text"            # text | vision | sheet
    ocr_confidence: float | None = None
    size: tuple[float, float] = (0.0, 0.0)
    blank: bool = False             # set by PageReader.mark_blank (scans with no ink)
    words: list[tuple] = field(default_factory=list, repr=False)   # pymupdf words, text-layer pages only

    def to_row(self) -> dict:
        return {"index": self.index, "text": self.text, "source": self.source,
                "ocr_confidence": self.ocr_confidence}


def text_layer_usable(text: str) -> bool:
    """≥80 non-space chars, some digits, and mostly real words (E-IN-10: a scan
    with a junk embedded OCR layer reads as garbage, so treat it as no layer)."""
    t = text or ""
    if len(re.sub(r"\s", "", t)) < 80 or not _DIGIT.search(t):
        return False
    tokens = t.split()
    wordy = sum(1 for w in tokens if _WORD.search(w))
    return wordy / max(len(tokens), 1) >= 0.3


class PageReader:
    def __init__(self, max_pages: int = C.MAX_PAGES, dpi: int = C.DPI) -> None:
        self.max_pages = max_pages
        self.dpi = dpi
        self.warnings: list[str] = []

    @staticmethod
    def is_image(name: str) -> bool:
        return Path(name).suffix.lower() in _IMAGE_EXT

    def open(self, data: bytes, name: str):
        import fitz
        if self.is_image(name):
            data = self._normalise_image(data, name)
            img = fitz.open(stream=data, filetype="png")      # _normalise_image always yields PNG
            return fitz.open("pdf", img.convert_to_pdf())
        try:
            doc = fitz.open(stream=data, filetype="pdf")
        except Exception as exc:                                   # E-IN-03
            raise ValueError("Can't open this PDF (it may be damaged)") from exc
        if doc.needs_pass:
            raise ValueError("Can't open this PDF (it is password-protected)")
        return doc

    @staticmethod
    def _normalise_image(data: bytes, name: str) -> bytes:
        """EXIF-rotate and convert HEIC/TIFF to PNG so pymupdf can read it (E-IN-06, E-IN-12)."""
        from PIL import Image, ImageOps
        if name.lower().endswith(".heic"):
            try:
                import pillow_heif  # type: ignore
                pillow_heif.register_heif_opener()
            except ImportError as exc:
                raise ValueError("HEIC photos aren't supported here — export as JPG") from exc
        img = ImageOps.exif_transpose(Image.open(io.BytesIO(data)))
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        out = io.BytesIO()
        img.save(out, format="PNG")
        return out.getvalue()

    def read_text(self, doc) -> list[PageInfo]:
        """Text-layer probe for every page (cheap, no rendering)."""
        n = len(doc)
        if n > self.max_pages:
            self.warnings.append(f"Only {self.max_pages} of {n} pages read — split the file to read the rest")
        out = []
        for i in range(min(n, self.max_pages)):
            page = doc[i]
            if page.rotation:
                page.set_rotation(0)
            text = page.get_text("text", sort=True)
            usable = text_layer_usable(text)
            out.append(PageInfo(index=i + 1, text=text if usable else "", has_text_layer=usable,
                                source="text" if usable else "vision",
                                size=(page.rect.width, page.rect.height),
                                words=page.get_text("words") if usable else []))
        return out

    def mark_blank(self, doc, pages: list[PageInfo], ink: float = 0.004) -> None:
        """Flag scanned pages with almost no ink (blank backs of printouts) using a tiny render."""
        import fitz
        for p in pages:
            if p.has_text_layer:
                continue
            pix = doc[p.index - 1].get_pixmap(matrix=fitz.Matrix(0.25, 0.25), colorspace=fitz.csGRAY)
            data = pix.samples
            dark = sum(1 for b in data if b < 200)
            p.blank = dark / max(len(data), 1) < ink
            del pix

    def render(self, doc, index: int, dpi: int | None = None, clip=None, max_side: int = C.PAGE_MAX_SIDE,
               fmt: str = "jpeg") -> bytes:
        """One page (1-based) as an image, optionally clipped; never kept in memory after return.

        JPEG for the model (a scanned page is ~0.3 MB instead of 5–8 MB as PNG, and far cheaper to
        encode on a 1-vCPU box); PNG only for the crops people look at. Checks free memory first.
        """
        import fitz
        from .memory import ensure_headroom
        ensure_headroom()
        page = doc[index - 1]
        d = dpi or self.dpi
        rect = clip or page.rect
        scale = min(d / 72, max_side / max(rect.width, rect.height))
        pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), clip=clip, alpha=False)
        try:
            return pix.tobytes("png") if fmt == "png" else pix.tobytes("jpeg", jpg_quality=C.JPEG_QUALITY)
        finally:
            del pix

    def crop(self, doc, index: int, bbox: list[float], dpi: int = C.CROP_DPI, pad: float = 6) -> bytes:
        """A cell/row crop for the review UI; bbox in PDF points, clamped to the page (E-SC-02)."""
        import fitz
        page = doc[index - 1]
        r = fitz.Rect(bbox[0] - pad, bbox[1] - pad, bbox[2] + pad, bbox[3] + pad) & page.rect
        if r.is_empty:
            r = page.rect
        return self.render(doc, index, dpi=dpi, clip=r, max_side=2000, fmt="png")
