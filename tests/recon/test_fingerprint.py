"""Decision-aware input fingerprint (RECON_IMPLEMENTATION_PLAN.md §8).

Acceptance test 6: "re-running after a decision produces a fresh result, not the
cached one". That only holds if a decision changes the fingerprint, so these
tests pin exactly that.
"""
from backend_ocr.app.recon.repo import input_fingerprint


def _fp(**kw):
    base = dict(segment_versions=[("seg-1", "x1"), ("seg-2", "x1")],
                engine_version="e1", rule_version="r1", decision_hwm=10, vocab_version="v1")
    base.update(kw)
    return input_fingerprint(**base)


# ── stability ─────────────────────────────────────────────────────────────────

def test_same_inputs_same_fingerprint():
    assert _fp() == _fp()


def test_segment_order_does_not_matter():
    a = _fp(segment_versions=[("seg-1", "x1"), ("seg-2", "x1")])
    b = _fp(segment_versions=[("seg-2", "x1"), ("seg-1", "x1")])
    assert a == b, "the same case assembled in a different order is the same case"


def test_it_is_a_sha256_hex_digest():
    fp = _fp()
    assert len(fp) == 64 and int(fp, 16) >= 0


# ── what must change it ───────────────────────────────────────────────────────

def test_a_new_decision_changes_the_fingerprint():
    """The whole reason this function exists.

    Without the decision high-water mark, a reviewer's correction would leave
    the fingerprint untouched and the engine would hand back the old verdict.
    """
    assert _fp(decision_hwm=10) != _fp(decision_hwm=11)


def test_a_parser_fix_changes_the_fingerprint():
    """Same document, new extractor version ⇒ the extraction may differ."""
    assert _fp(segment_versions=[("seg-1", "x1"), ("seg-2", "x1")]) != \
           _fp(segment_versions=[("seg-1", "x2"), ("seg-2", "x1")])


def test_a_new_document_on_the_case_changes_the_fingerprint():
    assert _fp() != _fp(segment_versions=[("seg-1", "x1"), ("seg-2", "x1"), ("seg-3", "x1")])


def test_an_engine_change_changes_the_fingerprint():
    assert _fp(engine_version="e1") != _fp(engine_version="e2")


def test_a_rule_version_change_changes_the_fingerprint():
    """Tolerances and thresholds are versioned, so a verdict stays replayable."""
    assert _fp(rule_version="r1") != _fp(rule_version="r2")


def test_a_vocabulary_release_changes_the_fingerprint():
    assert _fp(vocab_version="v1") != _fp(vocab_version="v2")


# ── edges ─────────────────────────────────────────────────────────────────────

def test_no_decisions_yet_is_stable():
    assert _fp(decision_hwm=None) == _fp(decision_hwm=0)


def test_missing_extractor_version_is_handled():
    assert len(_fp(segment_versions=[("seg-1", None)])) == 64


def test_a_case_with_no_segments_still_fingerprints():
    assert len(_fp(segment_versions=[])) == 64


def test_fields_do_not_bleed_into_each_other():
    """A value moving between fields must not collide.

    Naive concatenation would make engine='e1', rules='r1' hash the same as
    engine='e1r1', rules=''.
    """
    assert _fp(engine_version="e1", rule_version="r1") != _fp(engine_version="e1r1", rule_version="")
