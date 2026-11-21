"""Checks on values read from a page. No parser in the evaluation read every GSTIN exactly, so a GSTIN
taken from a scan is only trusted when its check character is right."""
from __future__ import annotations

import re

_CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
_GSTIN_SHAPE = re.compile(r"(?<![0-9A-Z])\d{2}[A-Z]{5}\d{4}[A-Z][0-9A-Z]Z[0-9A-Z](?![0-9A-Z])")


def gstin_valid(g: str | None) -> bool:
    """True when `g` is a GSTIN whose 15th character matches its mod-36 check digit."""
    if not g:
        return False
    g = re.sub(r"\s+", "", str(g)).upper()
    if len(g) != 15 or not _GSTIN_SHAPE.fullmatch(g):
        return False
    total = 0
    for i, ch in enumerate(g[:14]):
        v = _CHARS.index(ch) * (2 if i % 2 else 1)
        total += v // 36 + v % 36
    return _CHARS[(36 - total % 36) % 36] == g[14]


def find_gstins(text: str) -> list[tuple[str, bool]]:
    """Every GSTIN-shaped string in `text`, in order, de-duplicated, with whether its check digit holds."""
    seen: dict[str, bool] = {}
    for m in _GSTIN_SHAPE.finditer((text or "").upper()):
        seen.setdefault(m.group(0), gstin_valid(m.group(0)))
    return list(seen.items())
