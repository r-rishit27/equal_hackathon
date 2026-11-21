"""docread settings. Every value can be changed with an environment variable."""
from __future__ import annotations

import os

# Primary reader for pages with no text layer. Best on scans and handwriting in the evaluation.
VISION_MODEL = os.getenv("DOCREAD_VISION_MODEL", "gpt-5.4")
# Second, independent reader where a value is cross-checked (handwritten counts).
CHECK_MODEL = os.getenv("DOCREAD_CHECK_MODEL", "gpt-5.4-mini")
REASONING_EFFORT = os.getenv("DOCREAD_REASONING_EFFORT", "none")

# A page counts as having a text layer when it carries at least this many words.
MIN_TEXT_WORDS = int(os.getenv("DOCREAD_MIN_TEXT_WORDS", "20"))

# Rendering for vision: 150 dpi JPEG, capped on the long side. Plenty for print and handwriting,
# light enough for the 1 GB backend box (a 200 dpi PNG scan froze it, 2026-11-13).
DPI = int(os.getenv("DOCREAD_DPI", "150"))
MAX_SIDE = int(os.getenv("DOCREAD_MAX_SIDE", "1800"))
JPEG_QUALITY = int(os.getenv("DOCREAD_JPEG_QUALITY", "78"))
MAX_PAGES = int(os.getenv("DOCREAD_MAX_PAGES", "60"))
# Pages read at the same time. One rendered page is ~0.3 MB; 2 keeps memory flat on a small box.
CONCURRENCY = int(os.getenv("DOCREAD_CONCURRENCY", "2"))
OPENAI_TIMEOUT_S = float(os.getenv("DOCREAD_OPENAI_TIMEOUT_S", "180"))

# Sarvam fallback: on unless switched off; needs SARVAM_API_KEY.
SARVAM_FALLBACK = os.getenv("DOCREAD_SARVAM_FALLBACK", "true").lower() in ("1", "true", "yes")
SARVAM_BASE = os.getenv("SARVAM_BASE_URL", "https://api.sarvam.ai")
SARVAM_CHAT_MODEL = os.getenv("DOCREAD_SARVAM_CHAT_MODEL", "sarvam-105b")
SARVAM_JOB_TIMEOUT_S = float(os.getenv("DOCREAD_SARVAM_JOB_TIMEOUT_S", "600"))

# USD per 1M tokens (in, out), for the cost log only. Check the provider's price page before quoting.
PRICES = {"gpt-5.4": (2.50, 15.00), "gpt-5.4-mini": (0.75, 4.50),
          "gpt-4o": (2.50, 10.00), "gpt-4o-mini": (0.15, 0.60)}
SARVAM_PAGE_USD = 0.50 / 88.0          # ₹0.50 a page


def openai_key() -> str | None:
    from ..config import OPENAI_API_KEY
    return OPENAI_API_KEY or None


def sarvam_key() -> str | None:
    return os.getenv("SARVAM_API_KEY") or None


def sampling(model: str, max_tokens: int) -> dict:
    """gpt-5 family: no temperature, a completion budget, reasoning off (35 s a page vs 11 min on "low")."""
    if model.startswith(("gpt-5", "o3", "o4")):
        out = {"max_completion_tokens": max_tokens}
        if REASONING_EFFORT:
            out["reasoning_effort"] = REASONING_EFFORT
        return out
    return {"temperature": 0, "max_tokens": max_tokens}


def cost(model: str, tokens_in: int, tokens_out: int) -> float:
    pin, pout = PRICES.get(model, PRICES["gpt-5.4"])
    return (tokens_in * pin + tokens_out * pout) / 1_000_000
