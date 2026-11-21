"""The match surface as a rebuildable projection (plan §3, acceptance test 7).

The property that matters: edges hold no authored state, so wiping and
rebuilding them must produce an identical set and lose nothing a human decided.
"""
from decimal import Decimal as D

from backend_ocr.app.recon import edges as E
from backend_ocr.app.recon.types import LineResult, MatchMethod


def _lr(ord_, *, po=None, inv=None, ev=None, method=MatchMethod.EXACT, score=1.0):
    return LineResult(ord=ord_, kind="po", description="x", po_key=po, invoice_key=inv,
                      evidence_key=ev, match_method=method, match_score=score)


LINES = [
    _lr(1, po="pol:1", inv="rl:1", ev="ev:1"),
    _lr(2, po="pol:2", inv="rl:2"),
    _lr(3, po="pol:3", ev="ev:3"),
    _lr(4, inv="rl:4"),                      # not in PO — no edge to draw
]


# ── what gets derived ─────────────────────────────────────────────────────────

def test_an_invoice_line_bills_against_its_po_line():
    out = E.derive(LINES)
    assert E.Edge(kind=E.BILLS_AGAINST, src_key="rl:1", dst_key="pol:1",
                  method="EXACT", score=1.0) in out


def test_an_evidence_row_certifies_its_po_line():
    out = E.derive(LINES)
    assert any(e.kind == E.CERTIFIES and e.src_key == "ev:1" and e.dst_key == "pol:1" for e in out)


def test_a_line_with_no_po_draws_no_edge():
    out = E.derive([_lr(4, inv="rl:4")])
    assert out == [], "an out-of-PO line has nothing to point at"


def test_edge_count_matches_the_alignments():
    out = E.derive(LINES)
    assert len(out) == 4, "two BILLS_AGAINST + two CERTIFIES"


def test_payment_edges_come_from_the_payment_leg():
    out = E.derive([], payment_refs=[("rl:1", "pay:1")])
    assert out == [E.Edge(kind=E.PAID_BY, src_key="rl:1", dst_key="pay:1",
                          method="REFERENCE", score=1.0)]


# ── acceptance test 7: rebuild is identical, nothing lost ────────────────────

def test_rebuilding_produces_an_identical_set():
    first = E.derive(LINES)
    again = E.derive(LINES)
    assert first == again
    assert E.diff(first, again) == ([], [])


def test_rebuild_is_order_independent():
    """Rows come back from Postgres in whatever order; the projection must not care."""
    assert E.derive(LINES) == E.derive(list(reversed(LINES)))


def test_duplicate_alignments_collapse():
    assert E.derive(LINES + LINES) == E.derive(LINES)


def test_a_confirmation_is_stamped_on_but_not_stored_only_here():
    """The confirmation lives in recon_decisions; the edge only reflects it.

    So a rebuild that is handed the confirmations reproduces them exactly — and
    one that is handed none still builds every edge, just unconfirmed. This is
    the Plan B failure (0 of 23 confirmations survived a rebuild) made impossible.
    """
    with_conf = E.derive(LINES, confirmed_keys={"rl:1"})
    without = E.derive(LINES)
    assert any(e.confirmed for e in with_conf)
    assert not any(e.confirmed for e in without)
    assert {e.identity() for e in with_conf} == {e.identity() for e in without}, \
        "confirmation changes an attribute, never which edges exist"


def test_diff_reports_both_directions():
    a = E.derive(LINES)
    b = E.derive(LINES[:2])
    only_a, only_b = E.diff(a, b)
    assert only_a and not only_b


# ── determinism ───────────────────────────────────────────────────────────────

def test_edges_are_sorted_so_the_projection_is_byte_stable():
    out = E.derive(LINES)
    assert out == sorted(out)


def test_every_kind_used_is_declared():
    for e in E.derive(LINES, payment_refs=[("rl:1", "pay:1")]):
        assert e.kind in E.KINDS
