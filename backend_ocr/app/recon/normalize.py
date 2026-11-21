"""Line-item text normalisation (03_LLD_BACKEND.md §12.1).

The same item reads differently on a Bata PO, a vendor invoice and an auditor's
sheet: action prefixes come and go ("Supply & Installation of"), brand tails
are dropped ("Make Asian Jindal sail"), both sides misspell ("Sienems",
"Acousting"), and narrow PO columns break words ("PROGRAMMI NG"). `norm()`
removes that noise; `variant_tokens()` keeps what distinguishes one item from
its sibling (600 vs 1200, Type D vs Type E, SPN vs TPN) so a match can carry
a conflict instead of hiding it.
"""
from __future__ import annotations

import re
from functools import lru_cache

PREFIXES = [
    "supply & installation of", "supply and installation of", "supply & installation",
    "supply and installation", "supply installation of", "suply and installation of",
    "providing and fixing of", "providing and fixing and", "providing and fixing",
    "providing & fixing of", "providing & fixing", "supply of", "installation of", "fixing of",
]

SPELLING = {
    "sienems": "siemens", "seimens": "siemens", "stainner": "strainer", "interartion": "integration",
    "progamming": "programming", "acousting": "acoustic", "accousting": "acoustic",
    "scafolding": "scaffolding", "dismenlitng": "dismantling", "dismentling": "dismantling",
    "isolater": "isolator", "thermostate": "thermostat", "panal": "panel", "guage": "gauge",
    "addresabl": "addressable", "nitrial": "nitrile", "nitril": "nitrile", "presure": "pressure",
    "flaxible": "flexible", "impuls": "impulse", "promot": "promo", "puch": "punch",
    "tempreture": "temperature", "insulatio": "insulation", "integratio": "integration",
    "transportatio": "transportation", "measurment": "measurement", "cassetle": "cassette",
    "faca": "facade", "façade": "facade", "laminat": "laminate", "rel": "relay",
}

# Words that broke across a narrow PO column: rejoin "PROGRAMMI" + "NG".
_WRAP_JOIN = re.compile(r"\b([a-z]{4,})\s([a-z]{1,2})\b")
_KNOWN_TAILS = {"ng", "n", "on", "e", "al", "ed", "er", "es", "s"}
_NO_JOIN_HEADS = {"type", "class", "grade", "size", "make", "with", "plus", "only", "item", "code"}
_DIGIT_WRAP = re.compile(r"(x\d+)\s(\d+\s*mm)\b")

_MAKE_TAIL = re.compile(r"\bmake\b.*$")
_NUMWORDS = [(re.compile(r"(\d+)\s*point\s*(\d+)"), r"\1.\2")]
_PUNCT = re.compile(r"[^a-z0-9.]+")
_DIM = re.compile(r"\b(\d+(?:\.\d+)?)\s*x\s*(\d+(?:\.\d+)?)(?:\s*x\s*(\d+(?:\.\d+)?))?(?![\d.])")
_BARE = re.compile(r"(?<![\w.])(\d+)(?![\w.])")
_SIZE = re.compile(r"\b(\d+(?:\.\d+)?)\s*(mm|inch|inches|in|ft|fit|feet|tr|sqmm|sq\s*mm|a|amp|w|watt|gauge|g|kg|v|vdc|m)\b")
_TYPE = re.compile(r"\btype\s+([a-z])\b")
_POLES = re.compile(r"\b(spn|tpn|dp|sp|tp)\b")
_STOP = {"of", "and", "the", "with", "for", "in", "on", "to", "as", "per", "&", "a", "an", "nos", "no"}


def _base(desc: str) -> str:
    s = (desc or "").lower().replace("&", " & ")
    s = re.sub(r"\s+", " ", s).strip()
    for pat, rep in _NUMWORDS:
        s = pat.sub(rep, s)
    return s


def _spell(s: str) -> str:
    return " ".join(SPELLING.get(w, w) for w in s.split())


def _dewrap(s: str) -> str:
    def j(m: re.Match) -> str:
        head, tail = m.group(1), m.group(2)
        if tail in _KNOWN_TAILS and head not in _NO_JOIN_HEADS:
            return head + tail
        return m.group(0)
    return _DIGIT_WRAP.sub(r"\1\2", _WRAP_JOIN.sub(j, s))


@lru_cache(maxsize=8192)
def norm(desc: str) -> str:
    """Comparable form of a line description. Never empty if the input wasn't."""
    s = _dewrap(_base(desc))
    for p in PREFIXES:
        if s.startswith(p + " ") or s == p:
            s = s[len(p):].strip()
            break
    s = _MAKE_TAIL.sub("", s).strip()
    s = _PUNCT.sub(" ", s)
    s = _spell(re.sub(r"\s+", " ", s).strip())
    s = re.sub(r"(?<![0-9])\.|\.(?![0-9])", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s or _PUNCT.sub(" ", _base(desc)).strip()


def tokens(desc: str) -> set[str]:
    return {t for t in norm(desc).split() if t not in _STOP}


_UNIT_CANON = {"fit": "ft", "feet": "ft", "inches": "inch", "in": "inch", "amp": "a", "watt": "w",
               "g": "gauge", "vdc": "v", "sq mm": "sqmm"}


def _num(s: str) -> str:
    return str(float(s)).rstrip("0").rstrip(".") if "." in s else str(int(s))


def variant_tokens(desc: str) -> set[str]:
    """Distinguishing tokens: sizes, dimensions, type letters, pole counts."""
    return set(_variant_tokens(desc or ""))


@lru_cache(maxsize=8192)
def _variant_tokens(desc: str) -> frozenset[str]:
    s = _spell(_dewrap(_base(desc)))
    s = s.replace("’", "'")
    out: set[str] = set()
    for m in _DIM.finditer(s):
        parts = [p for p in m.groups() if p]
        out.add("x".join(_num(p) for p in parts))
    for m in _SIZE.finditer(s):
        unit = _UNIT_CANON.get(m.group(2).replace(" ", ""), m.group(2).replace(" ", ""))
        if unit == "m":          # bare metres are a length, not a size class
            continue
        out.add(f"{_num(m.group(1))}{unit}")
    rest = _SIZE.sub(" ", _DIM.sub(" ", s))
    for m in _BARE.finditer(rest):
        out.add(f"{int(m.group(1))}#")
    for m in _TYPE.finditer(s):
        out.add(f"type-{m.group(1)}")
    for m in _POLES.finditer(s):
        out.add(f"pole-{m.group(1)}")
    return frozenset(out)


def variant_conflicts(a: set[str], b: set[str]) -> list[str]:
    """Pairs of tokens of the same kind that disagree, e.g. ['600mm≠1200mm', 'type-d≠type-e']."""
    def kind(t: str) -> str:
        if t.startswith(("type-", "pole-")):
            return t.split("-")[0]
        if t.endswith("#"):
            return "num"
        if "x" in t and t[0].isdigit():
            return "dim"
        return re.sub(r"^[\d.]+", "", t)       # unit suffix: mm, ft, tr…
    ka: dict[str, set[str]] = {}
    kb: dict[str, set[str]] = {}
    for t in a:
        ka.setdefault(kind(t), set()).add(t)
    for t in b:
        kb.setdefault(kind(t), set()).add(t)
    out = []
    for k in sorted(set(ka) & set(kb)):
        if ka[k] & kb[k]:
            continue
        # A dimension cut off by a narrow column ("1200x450x10" for "…x100") is not a different size.
        if k == "dim" and any(x.startswith(y) or y.startswith(x) for x in ka[k] for y in kb[k]):
            continue
        if True:
            out.append(f"{'/'.join(sorted(ka[k]))}≠{'/'.join(sorted(kb[k]))}")
    return out


# ── Units ──────────────────────────────────────────────────────────────────────

_UNIT_ALIASES = {
    "nos": ["no", "nos", "no.", "nos.", "number", "each", "ea", "pcs", "pc", "set", "sets", "unit", "units"],
    "sqm": ["sm", "sqm", "sqmt", "sq mtrs", "sq mtr", "sq m", "sq. m", "sqmtr", "sq.mtr", "m2"],
    "sqft": ["sf", "sft", "sqft", "sq ft", "sq. ft", "sq.ft"],
    "rft": ["rft", "running ft", "r ft", "rft."],
    "m": ["m", "rmt", "mtr", "mtrs", "meter", "metre", "meters", "metres", "rm"],
    "ls": ["ls", "lot", "job", "lumpsum", "lump sum"],
}
_UNIT_LOOKUP = {alias: canon for canon, aliases in _UNIT_ALIASES.items() for alias in aliases}


def canon_unit(unit: str | None) -> str | None:
    if not unit:
        return None
    u = re.sub(r"\s+", " ", unit.strip().lower())
    if u in ("na", "n/a", "-", ""):
        return None
    return _UNIT_LOOKUP.get(u, _UNIT_LOOKUP.get(u.rstrip("."), u))


def same_unit(a: str | None, b: str | None) -> bool | None:
    """True/False when both are known, None when either is missing."""
    ca, cb = canon_unit(a), canon_unit(b)
    if ca is None or cb is None:
        return None
    return ca == cb
