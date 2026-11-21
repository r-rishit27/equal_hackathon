"""docread — the shared document reader for every module except bill OCR.

Bills keep their own path (utils/ocr_engine.py, OCR_TO_USE) and must not import this.
Recon, contracts and insertion orders read through here.

How a page is read (docs/RECON_PARSER_EVAL.md, decisions D1–D7):
  1. PDF text layer, when the page has one: free and exact.
  2. Otherwise OpenAI vision (DOCREAD_VISION_MODEL, gpt-5.4 by default, reasoning off): the most
     accurate parser in the evaluation (93.0 quality, 84.0 on handwriting).
  3. If OpenAI fails (quota, outage, refusal, timeouts), Sarvam Document AI reads the page instead,
     and sarvam-105b can turn text into JSON. Sarvam is the slower path, so it is only a fallback.

Which prompt structures the text is the caller's choice: each document type has its own prompt
(recon/extract/prompts.py for POs, invoices, audit sheets, field sheets and memos;
review/comm_extract.py for contracts, insertion orders and vendor POs).
"""
from .checks import find_gstins, gstin_valid
from .reader import DocRead, PageRead, read_document

__all__ = ["DocRead", "PageRead", "read_document", "gstin_valid", "find_gstins"]
