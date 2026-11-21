"""The decisions layer, which must never be able to break a reconciliation.

Most of these tests are about what happens when it goes wrong, because that is
the whole risk of the thing: a pipeline that reconciles today must not start
failing because an HTTP endpoint is slow, and a probability must never settle
something a person should.
"""
from __future__ import annotations

import pytest

from backend_ocr.app.recon import decisions as D


@pytest.fixture(autouse=True)
def _on(monkeypatch):
    monkeypatch.setattr(D, "ENABLED", True)
    monkeypatch.setattr(D, "OPENAI_API_KEY", "test-key", raising=False)


def reply(answers):
    async def _post(_body):
        return {"answers": answers}
    return _post


def raises(exc):
    async def _post(_body):
        raise exc
    return _post


# ── predicates ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_confident_yes_is_an_answer(monkeypatch):
    monkeypatch.setattr(D, "_post", reply([
        {"type": "predicate", "name": "same_line_item", "probability": 0.97}]))
    v = await D.same_line_item("ACP cladding", "A.C.P. Cladding work")
    assert v.decided and v.value is True
    assert v.as_evidence()["by"] == "openai_decisions"


@pytest.mark.asyncio
async def test_a_confident_no_is_also_an_answer(monkeypatch):
    """0.02 is a confident NO, not a failure to answer.

    Worth having: it tells the caller these two lines are not a pair, which is
    as useful as being told they are.
    """
    monkeypatch.setattr(D, "_post", reply([
        {"type": "predicate", "name": "same_line_item", "probability": 0.02}]))
    v = await D.same_line_item("25 mm piping", "Shoe display rack")
    assert v.decided and v.value is False and v.confidence == pytest.approx(0.98)


@pytest.mark.asyncio
async def test_the_middle_is_an_abstention(monkeypatch):
    """A coin toss with a decimal point on it is not a judgement.

    Shown one, a reviewer either trusts it or learns to ignore the lot.
    """
    monkeypatch.setattr(D, "_post", reply([
        {"type": "predicate", "name": "same_line_item", "probability": 0.6}]))
    v = await D.same_line_item("a", "b")
    assert not v.decided and "not clear enough" in v.why


# ── choices ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_document_kind_needs_its_confidence_not_just_a_winner(monkeypatch):
    """`choice` always returns something. Returning something is not knowing."""
    monkeypatch.setattr(D, "_post", reply([
        {"type": "choice", "name": "document_kind", "choice": "PURCHASE_ORDER",
         "confidence": 0.41}]))
    v = await D.which_document("some text", [("PURCHASE_ORDER", "an order"), ("OTHER", "anything else")])
    assert not v.decided


@pytest.mark.asyncio
async def test_a_confident_document_kind_comes_through(monkeypatch):
    monkeypatch.setattr(D, "_post", reply([
        {"type": "choice", "name": "document_kind", "choice": "PV_SHEET_SCANNED",
         "confidence": 0.94, "probabilities": [{"value": "PV_SHEET_SCANNED", "probability": 0.94}]}]))
    v = await D.which_document("audit qty  vendor qty", [("PV_SHEET_SCANNED", "a site report")])
    assert v.decided and v.value == "PV_SHEET_SCANNED"
    assert v.as_evidence()["confidence"] == 0.94


# ── every way it can go wrong ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_refusal_is_reported_as_itself(monkeypatch):
    """The model declined to judge, so a person does. That is not an error."""
    monkeypatch.setattr(D, "_post", reply([{"type": "refusal", "name": "same_line_item"}]))
    v = await D.same_line_item("a", "b")
    assert not v.decided and "declined" in v.why


@pytest.mark.asyncio
async def test_an_unreachable_endpoint_abstains_rather_than_raising(monkeypatch):
    async def _post(_b):
        return None
    monkeypatch.setattr(D, "_post", _post)
    v = await D.same_line_item("a", "b")
    assert not v.decided and "could not be reached" in v.why


@pytest.mark.asyncio
async def test_an_answer_for_a_different_question_is_not_used(monkeypatch):
    """Answers are matched by name. Taking the first one in the array would
    silently attribute one question's answer to another."""
    monkeypatch.setattr(D, "_post", reply([
        {"type": "predicate", "name": "something_else", "probability": 0.99}]))
    v = await D.same_line_item("a", "b")
    assert not v.decided and "no answer" in v.why


@pytest.mark.asyncio
async def test_an_unknown_answer_type_abstains(monkeypatch):
    monkeypatch.setattr(D, "_post", reply([{"type": "sentiment", "name": "same_line_item"}]))
    assert not (await D.same_line_item("a", "b")).decided


@pytest.mark.asyncio
async def test_a_malformed_body_abstains(monkeypatch):
    monkeypatch.setattr(D, "_post", reply(None))
    assert not (await D.same_line_item("a", "b")).decided


@pytest.mark.asyncio
async def test_with_no_api_key_it_does_not_call_out_at_all(monkeypatch):
    called = False

    async def _post(_b):
        nonlocal called
        called = True
        return {}
    monkeypatch.setattr(D, "OPENAI_API_KEY", "", raising=False)
    monkeypatch.setattr(D, "_post", _post)
    v = await D.same_line_item("a", "b")
    assert not v.decided and not called


@pytest.mark.asyncio
async def test_it_can_be_switched_off_without_touching_callers(monkeypatch):
    monkeypatch.setattr(D, "ENABLED", False)
    v = await D.same_line_item("a", "b")
    assert not v.decided and "switched off" in v.why


@pytest.mark.asyncio
async def test_the_caller_can_demand_more_certainty(monkeypatch):
    """A threshold belongs to the question, not to the module.

    Matching a line is cheap to undo; naming a document decides how it is
    parsed. The caller is the one that knows which it is.
    """
    monkeypatch.setattr(D, "_post", reply([
        {"type": "predicate", "name": "same_line_item", "probability": 0.9}]))
    assert (await D.same_line_item("a", "b", threshold=0.85)).decided
    assert not (await D.same_line_item("a", "b", threshold=0.95)).decided


# ── adjudicating the leftovers ─────────────────────────────────────────────

class _PO:
    def __init__(self, key, description="x", unit_price=None):
        self.key, self.description, self.unit_price = key, description, unit_price


class _Cand:
    def __init__(self, key):
        self.key = key


@pytest.mark.asyncio
async def test_many_pairs_are_asked_in_one_call(monkeypatch):
    """Independent questions share a request. One call per line would make
    adjudication cost more than the reconciliation it is helping."""
    calls = []

    async def _post(body):
        calls.append(body)
        return {"answers": [{"type": "predicate", "name": q["name"], "probability": 0.95}
                            for q in body["questions"]]}
    monkeypatch.setattr(D, "_post", _post)
    judged = await D.judge_pairs([("p1|c1", "A", "B"), ("p2|c2", "C", "D")])
    assert len(calls) == 1 and len(calls[0]["questions"]) == 2
    assert all(v.decided and v.value is True for v in judged.values())


@pytest.mark.asyncio
async def test_more_than_four_hundred_pairs_are_batched_not_dropped(monkeypatch):
    calls = []

    async def _post(body):
        calls.append(len(body["questions"]))
        return {"answers": []}
    monkeypatch.setattr(D, "_post", _post)
    judged = await D.judge_pairs([(f"p{i}|c{i}", "A", "B") for i in range(450)])
    assert calls == [400, 50]
    assert len(judged) == 450


@pytest.mark.asyncio
async def test_a_failed_batch_leaves_its_pairs_unjudged(monkeypatch):
    async def _post(_b):
        return None
    monkeypatch.setattr(D, "_post", _post)
    judged = await D.judge_pairs([("p1|c1", "A", "B")])
    assert not judged["p1|c1"].decided


@pytest.mark.asyncio
async def test_nothing_to_judge_makes_no_call(monkeypatch):
    async def _post(_b):
        raise AssertionError("should not be called")
    monkeypatch.setattr(D, "_post", _post)
    assert await D.judge_pairs([]) == {}


def test_the_matcher_is_only_offered_pairs_the_model_accepted():
    """An abstention and a NO are both "say nothing", so the line falls through
    to a person — which is what happens today without any of this."""
    judged = {
        "po:1|c:1": D.Answer(True, 0.96, "po:1|c:1"),
        "po:2|c:2": D.Answer(False, 0.97, "po:2|c:2"),
        "po:3|c:3": D.Abstain("not clear enough", "po:3|c:3"),
    }
    adj = D.lookup_adjudicator(judged)
    assert adj(_Cand("c:1"), [(_PO("po:1"), None)])[0] == "po:1"
    assert adj(_Cand("c:2"), [(_PO("po:2"), None)])[0] is None
    assert adj(_Cand("c:3"), [(_PO("po:3"), None)])[0] is None
    assert adj(_Cand("c:9"), [(_PO("po:9"), None)])[0] is None


def test_the_adjudicator_takes_the_best_ranked_accepted_pair():
    """`ranked` arrives best-first, so the first acceptance is the right one."""
    judged = {"po:2|c:1": D.Answer(True, 0.9, "po:2|c:1"),
              "po:3|c:1": D.Answer(True, 0.99, "po:3|c:1")}
    adj = D.lookup_adjudicator(judged)
    key, conf, reason = adj(_Cand("c:1"), [(_PO("po:1"), None), (_PO("po:2"), None), (_PO("po:3"), None)])
    assert key == "po:2" and conf == 0.9 and "decisions" in reason


# ── the glossary: what the confident edges teach about the uncertain ones ──

@pytest.mark.asyncio
async def test_the_shared_input_carries_what_is_already_confirmed(monkeypatch):
    """These two documents translate between each other in a particular way,
    and the only honest source for that is the pairs that matched cleanly."""
    sent = {}

    async def _post(body):
        sent.update(body)
        return {"answers": []}
    monkeypatch.setattr(D, "_post", _post)
    await D.judge_pairs([("p|c", "A", "B")],
                        glossary=[("Gypsum False Ceiling India Gypsum", "False ceiling - gypsum")])
    assert "False ceiling - gypsum" in sent["input"]
    assert "already" in sent["input"] and "confirmed" in sent["input"]


@pytest.mark.asyncio
async def test_no_glossary_sends_no_empty_heading(monkeypatch):
    sent = {}

    async def _post(body):
        sent.update(body)
        return {"answers": []}
    monkeypatch.setattr(D, "_post", _post)
    await D.judge_pairs([("p|c", "A", "B")])
    assert "confirmed as the same item" not in sent["input"]


@pytest.mark.asyncio
async def test_the_glossary_is_capped(monkeypatch):
    """The point is to show how the documents talk, not to resend the invoice."""
    sent = {}

    async def _post(body):
        sent.update(body)
        return {"answers": []}
    monkeypatch.setattr(D, "_post", _post)
    await D.judge_pairs([("p|c", "A", "B")],
                        glossary=[(f"po line {i}", f"billed {i}") for i in range(200)])
    assert sent["input"].count("  PO: ") == 40


@pytest.mark.asyncio
async def test_the_case_keys_the_cache_so_a_rerun_reuses_the_prefix(monkeypatch):
    sent = {}

    async def _post(body):
        sent.update(body)
        return {"answers": []}
    monkeypatch.setattr(D, "_post", _post)
    await D.judge_pairs([("p|c", "A", "B")], cache_key="case-42")
    assert sent["prompt_cache_key"] == "case-42"


def test_only_pairings_that_teach_something_go_in_the_glossary():
    """A glossary entry is a pairing we are sure of whose wordings DIFFER.

    EXACT is excluded although it is certain: it is exact because the words
    already match, so it has nothing to teach. Measured on the real case,
    including it produced an empty glossary and excluding it produced 21
    entries like "Anchor/Roma /Crabtree/" ↔ the invoice dropping the make.

    A scored match needs its RATE to agree as well. The money corroborating
    the text is what separates this from teaching one guess with another.
    """
    from backend_ocr.app.recon.pipeline import _glossary
    from backend_ocr.app.recon.types import CaseStatus, LineResult, MatchMethod, ReconResult, ReconSummary
    from decimal import Decimal as Dc

    def line(method, desc, billed, score=1.0, po_rate=None, billed_rate=None):
        return LineResult(ord=1, kind="po", description=desc, po_key="pol:1", invoice_key="rl:1",
                          invoice_text=billed, match_method=MatchMethod(method),
                          match_score=score, po_rate=po_rate, billed_rate=billed_rate)

    res = ReconResult(
        header=[], engine_version="t",
        lines=[
            line("HUMAN", "Vinyl pasting", "Vinyl paste work"),
            line("ALIAS", "Shoe rack 4 tier", "4-tier display rack"),
            line("SCORE", "Socket Anchor/Roma", "Socket", 0.95, Dc("10"), Dc("10")),
            # High text score, but the money disagrees: not sure enough to teach.
            line("SCORE", "Cable 2x4", "Cable four core", 0.95, Dc("10"), Dc("99")),
            # Certain, but the words are the same — it teaches nothing.
            line("EXACT", "Canvas Connection", "Canvas Connection"),
            # Below the bar on text however well the rate agrees.
            line("SCORE", "Guessed line", "Guessed billing", 0.73, Dc("10"), Dc("10")),
        ],
        summary=ReconSummary(po_total=None, expected_goods=Dc(0), expected_total=Dc(0),
                             billed_goods=Dc(0), billed_total=Dc(0),
                             money_at_risk=Dc(0), under_billed=Dc(0),
                             counts={}, status=CaseStatus.NEEDS_REVIEW))
    got = dict(_glossary(res))
    assert got == {"Vinyl pasting": "Vinyl paste work",
                   "Shoe rack 4 tier": "4-tier display rack",
                   "Socket Anchor/Roma": "Socket"}
