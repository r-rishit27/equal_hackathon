"""Line matching: PO lines ↔ invoice lines, and PO lines ↔ evidence rows
(03_LLD_BACKEND.md §12).

1. Overrides (a human said so) are applied first and leave the matrix.
2. Every remaining pair is scored on rate, name, variant tokens, unit, the
   evidence row's own PO-qty column, and position.
3. A one-to-one assignment (Hungarian) picks the best global pairing.
4. Pairs ≥ MATCH_ACCEPT are taken. Pairs in [LLM_FLOOR, ACCEPT) are taken
   without an LLM only when the rate is exact and no other open PO line shares
   it; otherwise they go to `adjudicate`, whose answer must pass a numeric
   guardrail. Everything else stays unmatched — never guessed.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Callable, Iterable

from rapidfuzz import fuzz

from . import config as C
from .normalize import norm, same_unit, variant_conflicts, variant_tokens
from .num import close
from .types import EvidenceRow, InvoiceLine, MatchMethod, MatchPair, PairScore, POLine, sval

W_RATE, W_NAME, W_VARIANT, W_UNIT, W_QTY, W_POS = 0.35, 0.30, 0.12, 0.08, 0.10, 0.05


@dataclass
class Cand:
    """Anything matchable against a PO line."""
    key: str
    text: str
    unit: str | None
    rate: Decimal | None
    alt_rate: Decimal | None = None
    po_qty: Decimal | None = None
    pos: float = 0.0


def cands_from_invoice(lines: Iterable[InvoiceLine]) -> list[Cand]:
    # A section heading is not an item, so it is never offered a PO line. Left
    # in, it competes for one and then sits unmatched for good, because no
    # purchase order has a line called "Supply Installation of HVAC Work".
    out = [Cand(key=l.key, text=l.description, unit=l.unit, rate=sval(l.rate))
           for l in lines if not l.is_rollup]
    return _positions(out)


def cands_from_evidence(rows: Iterable[EvidenceRow]) -> list[Cand]:
    out = [Cand(key=r.key, text=r.item, unit=r.unit, rate=r.rate_after_discount or r.rate,
                alt_rate=r.rate if r.rate_after_discount else None, po_qty=r.po_qty)
           for r in rows if r.row_type != "additional"]
    return _positions(out)


def _positions(cands: list[Cand]) -> list[Cand]:
    n = max(len(cands) - 1, 1)
    for i, c in enumerate(cands):
        c.pos = i / n
    return cands


def _rate_score(p: POLine, c: Cand) -> float:
    rates = [r for r in (c.rate, c.alt_rate) if r is not None]
    if not rates:
        return 0.5
    if any(close(p.unit_price, r) for r in rates):
        return 1.0
    if any(close(p.unit_price, r, Decimal("0"), Decimal("0.05")) for r in rates):
        return 0.6
    return 0.0


def _name(text: str, nc: str) -> float:
    nt = norm(text)
    s = fuzz.token_set_ratio(nt, nc) / 100.0
    # A PO line truncated to nothing ("Supply & Installation") carries no name signal.
    if len(nt.split()) <= 2 and nt != nc and not set(nt.split()) - {"supply", "installation", "fixing"}:
        s = min(s, 0.3)
    return s


def score(p: POLine, c: Cand, p_pos: float, alt_texts: Iterable[str] = ()) -> PairScore:
    """`alt_texts`: other wordings already known for this PO line (e.g. the
    invoice line it matched), so a report row can match through them."""
    nc = norm(c.text)
    texts = [p.description, *alt_texts]
    named = [(_name(t, nc), t) for t in texts]
    name, best_text = max(named, key=lambda x: x[0])
    np = norm(p.description)
    va, vb = variant_tokens(best_text), variant_tokens(c.text)
    conflicts = variant_conflicts(va, vb)
    variant = 0.2 if conflicts else (1.0 if (va and vb) or (not va and not vb) else 0.7)
    su = same_unit(p.unit, c.unit)
    unit = 0.5 if su is None else (1.0 if su else 0.0)
    if c.po_qty is None:
        qty = 0.5
    else:
        qty = 1.0 if close(p.qty, c.po_qty, Decimal("0.01"), Decimal("0")) else 0.3
    position = 1.0 if abs(p_pos - c.pos) <= 0.1 else 0.5
    rate = _rate_score(p, c)
    total = W_RATE * rate + W_NAME * name + W_VARIANT * variant + W_UNIT * unit + W_QTY * qty + W_POS * position
    if np == nc:
        total = max(total, 0.99 if not conflicts else total)
    return PairScore(rate=rate, unit=unit, name=name, variant=variant, qty=qty, position=position,
                     total=round(total, 4), conflicts=conflicts)


def hungarian(cost: list[list[float]]) -> list[tuple[int, int]]:
    """Min-cost assignment for an n×m matrix (n ≤ m handled by transposing).

    Pure Python O(n²m); fine for a few hundred lines. Returns (row, col) pairs.
    """
    if not cost or not cost[0]:
        return []
    n, m = len(cost), len(cost[0])
    if n > m:
        t = [[cost[i][j] for i in range(n)] for j in range(m)]
        return [(i, j) for j, i in hungarian(t)]
    INF = float("inf")
    u = [0.0] * (n + 1)
    v = [0.0] * (m + 1)
    p = [0] * (m + 1)
    way = [0] * (m + 1)
    for i in range(1, n + 1):
        p[0] = i
        j0 = 0
        minv = [INF] * (m + 1)
        used = [False] * (m + 1)
        while True:
            used[j0] = True
            i0, delta, j1 = p[j0], INF, 0
            for j in range(1, m + 1):
                if not used[j]:
                    cur = cost[i0 - 1][j - 1] - u[i0] - v[j]
                    if cur < minv[j]:
                        minv[j], way[j] = cur, j0
                    if minv[j] < delta:
                        delta, j1 = minv[j], j
            for j in range(m + 1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    minv[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while True:
            j1 = way[j0]
            p[j0] = p[j1]
            j0 = j1
            if j0 == 0:
                break
    return [(p[j] - 1, j - 1) for j in range(1, m + 1) if p[j] != 0]


# adjudicate(cand, [(po_line, PairScore), …]) -> (po_key | None, confidence, reason)
Adjudicator = Callable[[Cand, list[tuple[POLine, PairScore]]], tuple[str | None, float, str]]


class LineMatcher:
    def __init__(self, accept: float = C.MATCH_ACCEPT, llm_floor: float = C.MATCH_LLM_FLOOR,
                 adjudicate: Adjudicator | None = None) -> None:
        self.accept = accept
        self.llm_floor = llm_floor
        self.adjudicate = adjudicate

    def match(self, po_lines: list[POLine], cands: list[Cand],
              aliases: dict[str, str] | None = None,
              overrides: dict[str, str | None] | None = None,
              po_alt_text: dict[str, list[str]] | None = None) -> list[MatchPair]:
        """Return one MatchPair per candidate that matched (or was overridden)."""
        po_alt_text = po_alt_text or {}
        aliases = aliases or {}
        overrides = overrides or {}
        result: list[MatchPair] = []
        po_by_key = {p.key: p for p in po_lines}
        taken_po: set[str] = set()

        for c in cands:
            if c.key in overrides:
                po_key = overrides[c.key]
                if po_key is not None and po_key not in po_by_key:
                    continue        # stale override (PO revised) — fall back to scoring
                result.append(MatchPair(po_key=po_key, other_key=c.key, score=1.0, method=MatchMethod.HUMAN,
                                        conflicts=self._conflicts(po_by_key.get(po_key), c)))
                if po_key:
                    taken_po.add(po_key)
        done = {r.other_key for r in result}
        open_po = [p for p in po_lines if p.key not in taken_po]
        open_c = [c for c in cands if c.key not in done]
        if not open_po or not open_c:
            return result

        n_po = max(len(po_lines) - 1, 1)
        pos_of = {p.key: i / n_po for i, p in enumerate(po_lines)}
        norm_po = {p.key: norm(p.description) for p in open_po}
        scores: dict[tuple[int, int], PairScore] = {}
        method: dict[tuple[int, int], MatchMethod] = {}
        for i, p in enumerate(open_po):
            for j, c in enumerate(open_c):
                s = score(p, c, pos_of[p.key], po_alt_text.get(p.key, ()))
                exact = norm(c.text) in {norm_po[p.key], *(norm(t) for t in po_alt_text.get(p.key, ()))}
                m = MatchMethod.EXACT if exact and not s.conflicts else MatchMethod.SCORE
                alias_target = aliases.get(norm(c.text))
                if alias_target and alias_target == norm_po[p.key]:
                    s.total = max(s.total, 0.95)
                    m = MatchMethod.ALIAS
                scores[(i, j)] = s
                method[(i, j)] = m

        cost = [[1.0 - scores[(i, j)].total for j in range(len(open_c))] for i in range(len(open_po))]
        pending: list[tuple[int, int]] = []
        assigned_c: set[int] = set()
        assigned_p: set[int] = set()
        for i, j in hungarian(cost):
            s = scores[(i, j)]
            if s.total >= self.accept:
                result.append(MatchPair(po_key=open_po[i].key, other_key=open_c[j].key, score=s.total,
                                        method=method[(i, j)], conflicts=s.conflicts))
                assigned_c.add(j)
                assigned_p.add(i)
            elif s.total >= self.llm_floor:
                pending.append((i, j))

        # Mid-band pairs: exact unique rate rescues them; otherwise ask the adjudicator.
        for i, j in pending:
            p, c, s = open_po[i], open_c[j], scores[(i, j)]
            same_rate_open = [k for k, q in enumerate(open_po)
                              if k not in assigned_p and close(q.unit_price, c.rate or c.alt_rate)]
            if s.rate == 1.0 and same_rate_open == [i] and (s.unit != 0.0 or s.name >= 0.6):
                result.append(MatchPair(po_key=p.key, other_key=c.key, score=s.total, method=MatchMethod.SCORE,
                                        conflicts=s.conflicts, reason="only open PO line at this rate"))
                assigned_c.add(j)
                assigned_p.add(i)

        if self.adjudicate:
            for j, c in enumerate(open_c):
                if j in assigned_c:
                    continue
                ranked = sorted(((open_po[i], scores[(i, j)]) for i in range(len(open_po)) if i not in assigned_p),
                                key=lambda t: -t[1].total)[:5]
                ranked = [t for t in ranked if t[1].total >= self.llm_floor]
                if not ranked:
                    continue
                po_key, conf, reason = self.adjudicate(c, ranked)
                pick = next(((p, s) for p, s in ranked if p.key == po_key), None)
                if pick is None or conf < 0.6 or not self._guardrail(pick[0], c, pick[1], reason):
                    continue
                i = open_po.index(pick[0])
                result.append(MatchPair(po_key=pick[0].key, other_key=c.key, score=pick[1].total,
                                        method=MatchMethod.LLM, conflicts=pick[1].conflicts, reason=reason))
                assigned_c.add(j)
                assigned_p.add(i)
        return result

    @staticmethod
    def _guardrail(p: POLine, c: Cand, s: PairScore, reason: str) -> bool:
        """The LLM may propose; arithmetic decides (§12.4)."""
        rate_ok = s.rate >= 0.6
        unit_ok = s.unit == 1.0
        if not (rate_ok or unit_ok):
            return False
        if s.conflicts and not any(t.split("≠")[0] in (reason or "").lower() for t in s.conflicts):
            return False
        return True

    @staticmethod
    def _conflicts(p: POLine | None, c: Cand) -> list[str]:
        if p is None:
            return []
        return variant_conflicts(variant_tokens(p.description), variant_tokens(c.text))
