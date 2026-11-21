"""Remittance advice → structured lines (which invoices a payment covers).

Remittance arrives separately from the money and in every shape: an email body
("Please find payment of ₹1,18,000 against inv 1045 and 1046 less TDS"), a PDF
payment advice from the customer's ERP, a scan of a cheque stub. All of them go
through the same reader the payable side uses — the PDF text layer when there is
one, vision transcription when it is a scan — and then one structuring call.

What comes back is unverified: the matcher only *uses* remittance lines as a
clue, and a person confirms anything that isn't an exact match.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime

from ..integrations.ocr import _pdf_to_text, _text_layer_ok   # noqa: F401 — also puts utils/ on sys.path
from utils import ocr_engine  # noqa: E402
import config  # noqa: E402  (the pipeline-level config the OCR engine reads)

log = logging.getLogger(__name__)

PROMPT = """You read REMITTANCE ADVICE: a customer telling us (the seller) which of our
invoices their payment covers. Input is an email body or the text of a payment-advice
document. Return ONLY a JSON object:

{
  "payer_name": "",            // the customer who paid
  "payment_reference": "",     // UTR / transaction ref / cheque number, verbatim
  "payment_date": "",          // DD-MM-YYYY
  "payment_method": "",        // NEFT | RTGS | IMPS | UPI | CHEQUE | other | ""
  "total_amount": null,        // net amount actually paid
  "currency": "INR",
  "lines": [
    {
      "invoice_number": "",    // OUR invoice number as the customer quotes it, verbatim
      "invoice_date": "",
      "invoice_amount": null,  // gross invoice value if stated
      "amount_paid": null,     // what was paid against this invoice
      "deduction_amount": null,// what was held back against it (TDS, discount, short supply...)
      "deduction_reason": ""   // "TDS", "TDS 194C", "discount", "rate difference", "damaged goods"...
    }
  ]
}

Rules:
- Numbers: plain numbers, no commas or currency symbols. Indian grouping 1,18,000 = 118000.
- One line per invoice. A debit note or credit note the customer set off goes in as its
  own line with a NEGATIVE amount_paid and its number in invoice_number.
- If only gross and net are given for a line, deduction_amount = gross − net.
- Do not invent invoices: if the text names none, return an empty lines array.
- Dates: copy only what is written. If a date has no year ("27/10"), take the year from a
  full date elsewhere in the same text (an invoice date, the email's date); if there is none,
  return "" — never guess a year.
- Missing values: null for numbers, "" for strings.
"""


def _num(v):
    if v is None or v == "":
        return None
    try:
        return float(str(v).replace(",", ""))
    except ValueError:
        return None


def _date(v):
    s = str(v or "").strip()
    for fmt in ("%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d", "%d %b %Y", "%d-%b-%Y", "%d.%m.%Y", "%d/%m/%y", "%d-%m-%y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _plausible_payment_date(paid, lines: list[dict]):
    """Drop a payment date that can't be right: before the invoices it pays, years in the
    past, or in the future. A wrong date is worse than none — linking a remittance to its
    payment looks within days of it (a guessed year once hid a real match)."""
    if not paid:
        return None
    from datetime import date as _d, timedelta
    today = _d.today()
    if paid > today + timedelta(days=31) or paid < today - timedelta(days=550):
        return None
    inv_dates = [d for d in (_date(ln.get("invoice_date")) for ln in lines) if d]
    if inv_dates and paid < min(inv_dates):
        return None
    return paid


def clean(data: dict) -> dict:
    lines = []
    for ln in data.get("lines") or []:
        num = str(ln.get("invoice_number") or "").strip()
        paid = _num(ln.get("amount_paid"))
        if not num or paid is None:
            continue
        lines.append({
            "invoice_number": num,
            "invoice_date": str(ln.get("invoice_date") or "") or None,
            "invoice_amount": _num(ln.get("invoice_amount")),
            "amount_paid": paid,
            "deduction_amount": _num(ln.get("deduction_amount")) or 0,
            "deduction_reason": (str(ln.get("deduction_reason") or "").strip() or None),
        })
    return {
        "payer_name": (str(data.get("payer_name") or "").strip() or None),
        "payment_reference": (re.sub(r"\s+", "", str(data.get("payment_reference") or "")) or None),
        "payment_date": _plausible_payment_date(_date(data.get("payment_date")), lines),
        "payment_method": (str(data.get("payment_method") or "").strip().upper() or None),
        "total_amount": _num(data.get("total_amount")),
        "lines": lines,
    }


async def _structure(text: str) -> dict:
    resp = await ocr_engine._get_client().chat.completions.create(
        model=config.OPENAI_OCR_MODEL,
        messages=[{"role": "system", "content": PROMPT},
                  {"role": "user", "content": text[:30000]}],
        temperature=0,
        response_format={"type": "json_object"},
        max_tokens=4096,
    )
    return clean(json.loads(ocr_engine._content_or_raise(resp, "remittance extraction")))


async def read_text(text: str) -> dict:
    """An email body or pasted advice."""
    return await _structure(text)


async def read_pdf(pdf_path: str) -> tuple[dict, str]:
    """A remittance PDF (or a photo already turned into one). Returns (data, text read)."""
    import asyncio
    loop = asyncio.get_running_loop()
    try:
        pages = await loop.run_in_executor(None, lambda: _pdf_to_text(pdf_path))
    except Exception:
        pages = []
    if not _text_layer_ok(pages):
        pages, _ = await ocr_engine.transcribe_scanned_pdf(pdf_path, max_pages=5)
    text = "\n\n".join(f"--- Page {i} ---\n{t}" for i, t in enumerate(pages, 1))
    return await _structure(text), text
