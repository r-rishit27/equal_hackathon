"""InvoiceExtractor — tax invoice header + detail annexure (03_LLD_BACKEND.md §10.2).

Text layer → the text goes to the model (digits are exact); scan → page images.
The model only transcribes. Everything checkable is checked here and in the
engine: line arithmetic, the annexure sub total, charges billed as a % of goods.
"""
from __future__ import annotations

import re
from decimal import Decimal

from ..num import ZERO, round2
from ..types import Correction, DocClass, ExtractedInvoice, InvoiceLine, TaxBlock, TaxRegime
from . import prompts as P
from .base import ExtractContext, Extractor, dec, parse_date, party, src, text

_CHARGE = re.compile(r"packing|forwarding|freight|transport|loading|insurance|installation charges|fixing charges", re.I)
_PCTS = (Decimal(2), Decimal(3), Decimal(5), Decimal(10))


class InvoiceExtractor(Extractor):
    version = "inv1"

    async def extract(self, seg, ctx: ExtractContext) -> ExtractedInvoice:
        if ctx.llm is None:
            raise RuntimeError("invoice extraction needs the LLM")
        header_pages = [p for p, c in zip(seg.pages, seg.classes) if c == DocClass.TAX_INVOICE] or seg.pages[:1]
        annex_pages = [p for p, c in zip(seg.pages, seg.classes) if c == DocClass.INVOICE_ANNEXURE]
        h = await self._read(ctx, "invoice_header", P.INVOICE_HEADER, header_pages)
        inv = ExtractedInvoice(
            invoice_no=text(h.get("invoice_no")) or "", invoice_date=parse_date(text(h.get("invoice_date"))),
            irn=text(h.get("irn")), vendor=party(h.get("vendor")), buyer_gstin=text(h.get("buyer_gstin")),
            place_of_supply=text(h.get("place_of_supply")), po_ref=text(h.get("po_ref")),
            payment_terms=text(h.get("payment_terms")),
            header_lines=self._lines(h.get("header_lines"), "h", header_pages[0]),
            taxable=dec(h.get("taxable")), round_off=dec(h.get("round_off")) or ZERO, total=dec(h.get("total")),
            corrections=[Correction(field=c.get("field", "other"), printed=str(c.get("printed", "")),
                                    handwritten=str(c.get("handwritten", "")), page=header_pages[0])
                         for c in h.get("corrections") or [] if text(c.get("printed")) or text(c.get("handwritten"))],
            extractor_version=self.version)
        cg, sg, ig = dec(h.get("cgst")) or ZERO, dec(h.get("sgst")) or ZERO, dec(h.get("igst")) or ZERO
        inv.tax = TaxBlock(regime=TaxRegime.IGST if ig else (TaxRegime.CGST_SGST if cg else TaxRegime.NONE),
                           cgst=cg, sgst=sg, igst=ig, rate=dec(h.get("tax_rate")))
        if annex_pages:
            a = await self._read(ctx, "invoice_annexure", P.INVOICE_ANNEXURE, annex_pages, po_prior=True)
            inv.annexure_lines = self._lines(a.get("lines"), "a", annex_pages[0])
            inv.printed_subtotal = dec(a.get("printed_subtotal"))
            inv.po_ref = inv.po_ref or text(a.get("po_ref"))
            for c in a.get("corrections") or []:
                if text(c.get("printed")) or text(c.get("handwritten")):
                    inv.corrections.append(Correction(field=c.get("field", "other"), printed=str(c.get("printed", "")),
                                                      handwritten=str(c.get("handwritten", "")), page=annex_pages[0]))
            a_no = text(a.get("invoice_no"))
            if a_no and inv.invoice_no and _norm_no(a_no) != _norm_no(inv.invoice_no):
                inv.warnings.append(f"detail page number {a_no} differs from invoice {inv.invoice_no}")
        self._charges(inv)
        self._check(inv)
        return inv

    async def _read(self, ctx: ExtractContext, purpose: str, prompt: str, pages: list[int], po_prior: bool = False) -> dict:
        prior = ""
        if po_prior and ctx.po_hint and ctx.po_hint.lines:
            items = "\n".join(f"- {l.description} ({l.unit}, rate {l.unit_price})" for l in ctx.po_hint.lines[:120])
            prior = ("\n\nFor reference, the purchase order this invoice is against lists these items (wording may "
                     "differ on the invoice; do NOT copy values from this list):\n" + items)
        if ctx.all_text_layer(pages):
            return await ctx.llm.json(purpose, prompt + prior, text=ctx.text(pages))
        return await ctx.vision(purpose, prompt + prior, pages)

    @staticmethod
    def _lines(raw, prefix: str, page: int) -> list[InvoiceLine]:
        out = []
        for i, l in enumerate(raw or [], 1):
            desc = text(l.get("description")) or ""
            if not desc:
                continue
            after = bool(l.get("after_subtotal"))
            out.append(InvoiceLine(
                key=f"{prefix}:{i}", sno=_int(l.get("sno")), description=desc, hsn=text(l.get("hsn")), unit=text(l.get("unit")),
                qty=src(l.get("qty"), page=page, raw=l.get("qty")), rate=src(l.get("rate"), page=page),
                amount=src(l.get("amount"), page=page), is_charge=after))
        return out

    @staticmethod
    def _charges(inv: ExtractedInvoice) -> None:
        """Rows after the sub total are charges; a charge equal to N% of the sub total records N (E-RL-05)."""
        base = inv.printed_subtotal
        if base is None:
            goods = [l for l in inv.annexure_lines if not l.is_charge and l.amount]
            base = sum((l.amount.value for l in goods), ZERO) if goods else None
        for l in inv.annexure_lines:
            if not l.is_charge or not l.amount or base is None:
                continue
            for pct in _PCTS:
                if abs(round2(base * pct / 100) - l.amount.value) <= 1:
                    l.charge_pct = pct
                    break

    @staticmethod
    def _check(inv: ExtractedInvoice) -> None:
        for l in inv.lines:
            q, r, a = (x.value if x else None for x in (l.qty, l.rate, l.amount))
            if q is not None and r is not None and a is not None and l.charge_pct is None and abs(round2(q * r) - a) > 1:
                inv.warnings.append(f"line {l.sno}: {q} × {r} ≠ printed {a}")
        if inv.taxable is None and inv.header_lines:
            inv.taxable = sum((l.amount.value for l in inv.header_lines if l.amount), ZERO) or None


def _int(v) -> int | None:
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return None


def _norm_no(s: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", s.upper())
