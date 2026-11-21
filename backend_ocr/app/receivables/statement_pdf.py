"""PDF bank statement → raw lines, for bank_statement.finalize.

Indian banks mostly hand out statements as PDF. They are read with the same OCR
machinery as invoices: the text layer when the PDF has one (character-exact),
vision transcription when it is a scan. A model then structures each page's text
into transactions; it only lays out what the page says. Narrations, UTRs and payer
names are still parsed by bank_statement.parse_narration, exactly as for CSV/XLSX,
so a PDF and a spreadsheet of the same statement import to the same payments.

Pages are structured independently (a page holds whole rows), at most 3 at a time,
which keeps memory flat on the 1 GB box and lets a long statement finish in
roughly the time of its slowest page.
"""
from __future__ import annotations

import asyncio
import json
import logging

from ..integrations.ocr import _pdf_to_text, _text_layer_ok   # noqa: F401 — also puts utils/ on sys.path
from utils import ocr_engine  # noqa: E402
import config  # noqa: E402

from .bank_statement import StatementError, parse_amount, parse_date

log = logging.getLogger(__name__)

MAX_PAGES = 30

PROMPT = """You read ONE PAGE of an Indian bank account statement and list its transactions.
Return ONLY a JSON object:

{
  "account_number": "",       // as printed (may be masked), "" if not on this page
  "transactions": [
    {"date": "DD-MM-YYYY", "narration": "", "reference": "", "debit": null, "credit": null}
  ]
}

Rules:
- One entry per transaction row, top to bottom, exactly as printed. Skip opening/closing
  balance lines, totals, headers and page footers.
- A narration that wraps onto following lines belongs to the row above it — join it with a space.
- "reference" is the Chq./Ref. No. column (UTR, cheque number) if the statement has one, else "".
- Withdrawal / Debit / Dr amounts go in "debit"; Deposit / Credit / Cr amounts in "credit". Exactly
  one of them is set per row. Plain numbers: no commas, no currency symbol. Indian grouping
  1,18,000.00 = 118000.00. Never put the running balance in either field.
- Use the transaction date (not value date) when both are printed.
- Copy narrations and references character for character — they are matched against invoices.
"""


async def _structure(page_text: str, page_no: int, total: int) -> dict:
    resp = await ocr_engine._get_client().chat.completions.create(
        model=config.OPENAI_OCR_MODEL,
        messages=[{"role": "system", "content": PROMPT},
                  {"role": "user", "content": f"Page {page_no} of {total}:\n\n{page_text[:24000]}"}],
        temperature=0,
        response_format={"type": "json_object"},
        max_tokens=8000,
    )
    return json.loads(ocr_engine._content_or_raise(resp, f"statement page {page_no}"))


def _record(t: dict) -> dict | None:
    d = parse_date(str(t.get("date") or "").strip())
    if not d:
        return None
    credit = parse_amount(t.get("credit")) if t.get("credit") not in (None, "", 0) else None
    debit = parse_amount(t.get("debit")) if t.get("debit") not in (None, "", 0) else None
    if not credit and not debit:
        return None
    return {"date": d, "narration": (str(t.get("narration") or "").strip() or None),
            "reference": (str(t.get("reference") or "").strip() or None),
            "credit": credit, "debit": debit}


async def pdf_records(pdf_path: str) -> tuple[list[dict], str | None]:
    """(raw lines in statement order, account number if printed)."""
    loop = asyncio.get_running_loop()
    try:
        pages = await loop.run_in_executor(None, lambda: _pdf_to_text(pdf_path))
    except Exception as e:
        raise StatementError(f"Couldn't open the PDF ({type(e).__name__}) — if it's password-protected, "
                             "save an unlocked copy first")
    if len(pages) > MAX_PAGES:
        raise StatementError(f"Statement has {len(pages)} pages — import up to {MAX_PAGES} at a time")
    if not _text_layer_ok(pages):
        pages, _ = await ocr_engine.transcribe_scanned_pdf(pdf_path, max_pages=MAX_PAGES)
    sem = asyncio.Semaphore(3)

    async def one(i: int, text: str) -> dict:
        if not text.strip():
            return {"transactions": []}
        async with sem:
            return await _structure(text, i + 1, len(pages))

    results = await asyncio.gather(*(one(i, t) for i, t in enumerate(pages)))
    records: list[dict] = []
    account = None
    for r in results:
        account = account or (str(r.get("account_number") or "").strip() or None)
        for t in r.get("transactions") or []:
            rec = _record(t)
            if rec:
                records.append(rec)
    if not records:
        raise StatementError("No transactions could be read from this PDF")
    return records, account
