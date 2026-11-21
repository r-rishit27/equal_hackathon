"""Recon thresholds, model names and limits (03_LLD_BACKEND.md §3)."""
from __future__ import annotations

import os

ENGINE_VERSION = "e1"
EXTRACTOR_VERSION = "x1"

MAX_PAGES = int(os.getenv("RECON_MAX_PAGES", "60"))
# Full pages go to the vision model as JPEG at this resolution: plenty for print and handwriting,
# and light enough for the 1 GB backend box (a scan at 200 dpi PNG froze it, 2026-11-13).
DPI = int(os.getenv("RECON_DPI", "150"))
PAGE_MAX_SIDE = int(os.getenv("RECON_PAGE_MAX_SIDE", "1800"))
JPEG_QUALITY = int(os.getenv("RECON_JPEG_QUALITY", "78"))
# At most this many page images in one model request; longer documents are read in batches.
MAX_IMAGES_PER_CALL = int(os.getenv("RECON_MAX_IMAGES_PER_CALL", "4"))
# Below this much free memory the worker waits instead of reading (see memory.py).
MIN_FREE_MB = int(os.getenv("RECON_MIN_FREE_MB", "250"))
CROP_DPI = 300
MAX_UPLOAD_MB = 25

# Page images (scanned POs, invoices, memos, PODs, field sheets): gpt-5.4 with reasoning off. In the parser
# evaluation (docs/reconciliation/RECON_PARSER_EVAL.md) gpt-4o scored 82.1 and invented 23 money rows; gpt-5.4 scored 93.0
# with none, at about the same price per page.
VISION_MODEL = os.getenv("RECON_VISION_MODEL", "gpt-5.4")
FAST_MODEL = os.getenv("RECON_FAST_MODEL", "gpt-4o-mini")
SECOND_READ_MODEL = os.getenv("RECON_SECOND_READ_MODEL", VISION_MODEL)
# Auditors' scanned sheets (dense tables, handwritten quantities): read whole rows by one model and
# again, independently, by a second. gpt-4o lost and shifted rows on these (Yelanka, 2026-11-14);
# gpt-5.4 with reasoning off read every row of the same page in ~35 s.
SHEET_MODEL = os.getenv("RECON_SHEET_MODEL", "gpt-5.4")
SHEET_CHECK_MODEL = os.getenv("RECON_SHEET_CHECK_MODEL", "gpt-5.4-mini")
REASONING_EFFORT = os.getenv("RECON_REASONING_EFFORT", "none")
# Handwritten field sheets (Mounted / Unmounted / Damaged / Total) are read twice like auditor sheets:
# where two readers agree the value was right every time in the evaluation.
FIELD_CHECK_MODEL = os.getenv("RECON_FIELD_CHECK_MODEL", SHEET_CHECK_MODEL)

# Off by default: local and dev share the dev DB, and the first worker to start
# would claim dev's uploads (see the review-workers-lock incident).
WORKER_ENABLED = os.getenv("RECON_WORKER_ENABLED", "false").lower() in ("1", "true", "yes")

LINK_AUTO_SCORE = 0.85
LINK_AUTO_MARGIN = 0.15
LOOKBACK_DAYS = 365

MATCH_ACCEPT = 0.72
MATCH_LLM_FLOOR = 0.35

CELL_ACCEPT_CONF = 0.90

ALLOWED_EXT = {".pdf", ".png", ".jpg", ".jpeg", ".heic", ".webp", ".tif", ".tiff", ".xlsx", ".xlsm", ".csv"}
