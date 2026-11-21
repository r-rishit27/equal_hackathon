"""Match a case's documents, then run the engine — the one path both the
worker (pipeline.recompute) and the golden tests go through.
"""
from __future__ import annotations

from dataclasses import replace

from .engine import ReconEngine
from .match import Adjudicator, LineMatcher, cands_from_evidence, cands_from_invoice
from .types import MatchPair, ReconInput, ReconResult


def match_case(inp: ReconInput, aliases: dict[str, str] | None = None,
               overrides: dict[str, str | None] | None = None,
               adjudicate: Adjudicator | None = None) -> tuple[list[MatchPair], list[MatchPair]]:
    """PO ↔ invoice first; then PO ↔ evidence, letting each PO line also be
    known by the invoice wording it matched (a truncated PO line like
    "Supply & Installation" is found in the report via "15 MM Air Punch Valve")."""
    if inp.po is None:
        return [], []
    matcher = LineMatcher(adjudicate=adjudicate)
    inv_lines = inp.invoice.lines if inp.invoice else []
    inv_matches = matcher.match(inp.po.lines, cands_from_invoice(inv_lines), aliases, overrides)
    by_key = {l.key: l for l in inv_lines}
    alt = {m.po_key: [by_key[m.other_key].description] for m in inv_matches
           if m.po_key and m.other_key in by_key}
    rows = [r for sec in inp.evidence for r in sec.rows]
    ev_matches = matcher.match(inp.po.lines, cands_from_evidence(rows), aliases, overrides, po_alt_text=alt)
    return inv_matches, ev_matches


def reconcile(inp: ReconInput, aliases: dict[str, str] | None = None,
              overrides: dict[str, str | None] | None = None,
              adjudicate: Adjudicator | None = None) -> ReconResult:
    inv_m, ev_m = match_case(inp, aliases, overrides, adjudicate)
    return ReconEngine().run(replace(inp, invoice_matches=inv_m, evidence_matches=ev_m))
