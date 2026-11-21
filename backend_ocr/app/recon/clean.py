"""Cleaning a model's answers before they are trusted or stored.

A leaf module (imports nothing from the package) so the classifier, the
extractors and the repository can all use it without import cycles.
"""
from __future__ import annotations

import re

_NULLISH = {"", "null", "none", "n/a", "na", "nil", "-", "—", "not stated", "not available", "unknown"}


def text(v) -> str | None:
    """A model's string answer, with its stand-ins for "nothing" removed.

    Prompts describe optional fields as `"...|null"`, and models sometimes echo
    that literally ("null", "AMP/26-27/000|null") instead of returning JSON null.
    """
    if v is None:
        return None
    s = re.sub(r"\s*\|\s*null\s*$", "", str(v).strip(), flags=re.I).strip()
    return None if s.lower() in _NULLISH else s



_GSTIN_CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def gstin_valid(g: str | None) -> bool:
    """GSTIN check digit (mod-36) — a misread GSTIN fails this (E-EX-18)."""
    if not g or len(g) != 15:
        return False
    g = g.upper()
    total = 0
    for i, ch in enumerate(g[:14]):
        if ch not in _GSTIN_CHARS:
            return False
        v = _GSTIN_CHARS.index(ch) * (2 if i % 2 else 1)
        total += v // 36 + v % 36
    return _GSTIN_CHARS[(36 - total % 36) % 36] == g[14]


def _gstin(g) -> str | None:
    if not g:
        return None
    g = str(g).strip().upper().replace(" ", "")
    return g if gstin_valid(g) else None


def gstin(v) -> str | None:
    """A GSTIN only when its check digit holds: "29AABCB1043Q1ZI|null" → the GSTIN, a misread one → None."""
    return _gstin(text(v))


def fit(v, n: int) -> str | None:
    """A value cut to a column's width, so one odd reading can't fail a whole file."""
    t = text(v)
    return None if t is None else t[:n]


_STORE_NO = re.compile(r"(?<!\d)(\d{3,5})(?!\d)")


def store_no(v) -> str | None:
    """A store number on its own: "Shop No 1859", "SN 1859", "(1859)" → "1859"; leading zeros dropped.

    Sheets print the label with the number ("Shop No 1859"); compared raw, the
    same store reads as two (the Yelanka report scored store 0 against its own PO).
    """
    t = text(v)
    if t is None:
        return None
    m = _STORE_NO.search(t)
    return (m.group(1).lstrip("0") or "0") if m else None


def doc_number_ok(no, store_sn=None) -> bool:
    """A PO or invoice number worth filing: at least five characters with digits, and not the store number.

    An auditor's sheet prints the store ("1859") where a PO prints its number; a
    misread sheet once filed "1859" as a PO and took over a real invoice's case.
    """
    t = re.sub(r"-\d{1,2}$", "", text(no) or "")          # a revision suffix: "PPO00024378-1", "1859-1"
    t = re.sub(r"[^A-Za-z0-9]", "", t)
    if len(t) < 5 or not re.search(r"\d", t):
        return False
    s = store_no(store_sn)
    return not (s and t.lstrip("0") == s)
