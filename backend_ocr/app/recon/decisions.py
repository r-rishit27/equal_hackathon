"""Typed judgements from the OpenAI Decisions API, used only where we are stuck.

The reconciliation is deterministic and must stay that way. Rates, quantities
and totals come off documents and are compared by arithmetic; nothing in this
module touches that. What it is for is the handful of places where the rules
genuinely run out:

  - a page the rule classifier cannot name and the extractor would file as OTHER
  - two lines whose natural key scores below `keys.TRUST_FLOOR`, where position
    is the only thing left and position alone must never decide (plan §3)

In both the current answer is "give up and ask a person". That is the right
default and it stays the fallback — this only tries to answer first.

**Three rules hold this to advisory.**

*It abstains by default.* Every call returns `Abstain` unless the answer clears
a threshold the caller sets. An abstention is not an error and not a "no": it
means the question was not settled, and the caller does exactly what it did
before this module existed.

*It never overrules evidence.* Callers ask it to choose between readings the
documents support, never to supply a number. A probability of 0.99 that two
lines are the same item is still not a measurement, and no money moves on one.

*It cannot break the pipeline.* Every failure — no key, no network, a timeout,
a malformed body, a refusal, a budget stop — comes back as an abstention with a
reason. A reconciliation that works today must not start failing because an
HTTP endpoint is slow.

What it decides is recorded like any other decision (`repo.record_decision`,
`actor_kind="machine"`), with the probability and the model that produced it,
so a reviewer can see why a line was matched and an as-of replay can reproduce
it.
"""
from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field
from typing import Any

from ..config import OPENAI_API_KEY

log = logging.getLogger(__name__)

URL = os.getenv("OPENAI_DECISIONS_URL", "https://api.openai.com/v1/decisions")
MODEL = os.getenv("OPENAI_DECISION_MODEL", "gpt-6-luna")
TIMEOUT_S = float(os.getenv("OPENAI_DECISION_TIMEOUT_S", "15"))
ENABLED = os.getenv("RECON_DECISIONS_ENABLED", "true").strip().lower() not in ("0", "false", "no")

#: Below this, a judgement is not worth having. A reviewer who is shown a
#: machine's 0.6 "probably the same item" has been given a coin toss with a
#: decimal point on it, and will either trust it or learn to ignore the lot.
DEFAULT_THRESHOLD = 0.85

#: One retry, for the transient cases only. These calls sit in a document
#: pipeline that already takes seconds per page; a long retry ladder here buys
#: nothing and delays the fallback the caller is going to use anyway.
_RETRYABLE = ("timeout", "connection", "429", "500", "502", "503", "overloaded")


@dataclass(frozen=True)
class Answer:
    """A judgement that cleared its threshold."""
    value: Any                      # True/False for a predicate, the chosen value, or the score
    confidence: float
    name: str
    model: str = MODEL
    probabilities: list[dict] = field(default_factory=list)

    decided = True

    def as_evidence(self) -> dict:
        """What to store on the decision log, so the answer can be audited."""
        return {"value": self.value, "confidence": round(self.confidence, 4),
                "model": self.model, "question": self.name, "by": "openai_decisions"}


@dataclass(frozen=True)
class Abstain:
    """No judgement. The caller does whatever it would have done anyway."""
    why: str
    name: str = ""
    confidence: float = 0.0

    decided = False

    def as_evidence(self) -> dict:
        return {"abstained": self.why, "question": self.name}


Verdict = Answer | Abstain


def _retryable(exc: Exception) -> bool:
    text = f"{type(exc).__name__} {exc}".lower()
    return any(tag in text for tag in _RETRYABLE)


async def _post(body: dict) -> dict | None:
    """One call. Returns the parsed body, or None when it could not be had.

    Never raises: the caller is a document pipeline, and an endpoint being slow
    is not a reason for a reconciliation to fail.
    """
    import httpx

    headers = {"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"}
    for attempt in (1, 2):
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT_S) as http:
                r = await http.post(URL, json=body, headers=headers)
            if r.status_code == 200:
                return r.json()
            if r.status_code in (429, 500, 502, 503) and attempt == 1:
                await asyncio.sleep(0.5)
                continue
            # The body can carry the provider's own explanation; the key never
            # appears in it, and it is logged at warning rather than raised.
            log.warning("[decisions] %s returned %s: %s", URL, r.status_code, r.text[:200])
            return None
        except Exception as exc:                                   # noqa: BLE001
            if attempt == 1 and _retryable(exc):
                await asyncio.sleep(0.5)
                continue
            log.warning("[decisions] call failed: %s: %s", type(exc).__name__, exc)
            return None
    return None


def _answer_for(body: dict, name: str) -> dict | None:
    for a in (body or {}).get("answers") or []:
        if a.get("name") == name:
            return a
    return None


async def ask(question: dict, evidence: Any, *, threshold: float = DEFAULT_THRESHOLD) -> Verdict:
    """Put one question to the Decisions API and return a verdict or an abstention.

    `evidence` is the shared input: a string, or the message array the API
    takes when there are images or JSON to pass.
    """
    name = question.get("name") or "question"
    if not ENABLED:
        return Abstain("decisions are switched off", name)
    if not OPENAI_API_KEY:
        return Abstain("no API key configured", name)

    body = {"model": MODEL,
            "input": evidence,
            "questions": [question]}
    raw = await _post(body)
    if raw is None:
        return Abstain("the decisions endpoint could not be reached", name)

    a = _answer_for(raw, name)
    if a is None:
        return Abstain("no answer came back for this question", name)
    kind = a.get("type")

    # A refusal is a real outcome and is reported as itself, not as a failure:
    # the model declined to judge, so a person does.
    if kind == "refusal":
        return Abstain("the model declined to answer", name)

    if kind == "predicate":
        p = float(a.get("probability") or 0.0)
        # Both ends are informative. A probability of 0.02 that two lines are
        # the same item is a confident NO, and the caller can use it.
        if p >= threshold:
            return Answer(True, p, name)
        if p <= 1 - threshold:
            return Answer(False, 1 - p, name)
        return Abstain(f"not clear enough (p={p:.2f})", name, p)

    if kind == "choice":
        conf = float(a.get("confidence") or 0.0)
        if conf < threshold:
            return Abstain(f"not clear enough (confidence {conf:.2f})", name, conf)
        return Answer(a.get("choice"), conf, name, probabilities=a.get("probabilities") or [])

    if kind == "score":
        conf = float(a.get("confidence") or 0.0)
        if conf < threshold:
            return Abstain(f"not clear enough (confidence {conf:.2f})", name, conf)
        return Answer(float(a.get("score") or 0.0), conf, name,
                      probabilities=a.get("probabilities") or [])

    return Abstain(f"unexpected answer type {kind!r}", name)


# ── the questions this codebase asks ───────────────────────────────────────

async def which_document(text: str, choices: list[tuple[str, str]], *,
                         threshold: float = DEFAULT_THRESHOLD) -> Verdict:
    """What kind of document is this page, when the rules could not tell?

    Only ever called for a page the rule classifier left unnamed. A confident
    answer saves a page from being filed as OTHER and ignored; anything less
    and it is filed as OTHER exactly as before.
    """
    return await ask({
        "type": "choice",
        "name": "document_kind",
        "instructions": ("Which kind of document is this page from? Judge by its headings, "
                         "columns and totals, not by a single word appearing somewhere."),
        "choices": [{"value": v, "description": d} for v, d in choices],
    }, (text or "")[:4000], threshold=threshold)


async def same_line_item(a: str, b: str, *, context: str = "",
                         threshold: float = DEFAULT_THRESHOLD) -> Verdict:
    """Are these two descriptions the same item on the same job?

    Asked only where `keys` scored below its trust floor and the alternative is
    matching on position, which the plan forbids as a decision. The documents
    describe one item three ways — a PO, a vendor's bill and an auditor's
    shorthand — so the judgement is about wording, never about amounts.
    """
    return await ask({
        "type": "predicate",
        "name": "same_line_item",
        "instructions": ("Do these two lines describe the SAME item of work or material? "
                         "They come from different documents about one purchase — a purchase "
                         "order, a vendor's invoice and an auditor's site report — so wording, "
                         "spelling and abbreviations differ. Different sizes, ratings, "
                         "locations or materials mean they are NOT the same item."),
    }, f"Line A: {a}\nLine B: {b}" + (f"\n\nOther lines on the same documents:\n{context}" if context else ""),
       threshold=threshold)


# ── adjudicating the lines the scorer could not place ──────────────────────

async def judge_pairs(pairs: list[tuple[str, str, str]], *,
                      glossary: list[tuple[str, str]] | None = None,
                      cache_key: str | None = None,
                      threshold: float = DEFAULT_THRESHOLD) -> dict[str, Verdict]:
    """Ask about many candidate pairings in one request.

    The API takes up to 400 questions against one shared input, and these
    questions are independent of each other — whether line 7 is the same item
    as PO line 3 does not depend on what we concluded about line 8. So the
    whole leftover set costs one call rather than one call per line.

    `pairs` is (id, line A, line B). The returned map is keyed by id and holds
    a verdict per pair; a pair the API said nothing useful about is an
    abstention, exactly as if it had been asked alone.

    `glossary` is the pairings on these same documents that we are already sure
    of — the confident edges of the match graph. It is the most useful thing we
    can offer: these two documents translate between each other in a particular
    way ("Gypsum False Ceiling India Gypsum" is billed as "False ceiling -
    gypsum"), and that vocabulary is learned from the lines that matched
    cleanly. It is evidence about **wording**, deliberately not about position:
    where a line sits in a table may not decide a match (plan §3), and feeding
    neighbours in document order would smuggle that back in through the model.

    It goes in the shared `input`, which is also the cacheable prefix, so the
    same glossary is paid for once across every question and every re-run of
    the case.
    """
    out: dict[str, Verdict] = {p[0]: Abstain("not asked", p[0]) for p in pairs}
    if not pairs:
        return out
    if not ENABLED:
        return {k: Abstain("decisions are switched off", k) for k in out}
    if not OPENAI_API_KEY:
        return {k: Abstain("no API key configured", k) for k in out}

    # The API caps questions per request; beyond that, ask in batches rather
    # than silently dropping the tail.
    for batch in (pairs[i:i + 400] for i in range(0, len(pairs), 400)):
        questions = [{
            "type": "predicate",
            "name": pid,
            "instructions": [
                {"type": "input_text",
                 "text": ("Do these two lines describe the SAME item of work or material?\n"
                          f"Line A (purchase order): {a}\n"
                          f"Line B (the other document): {b}\n"
                          "They come from different documents about one purchase, so wording, "
                          "spelling and abbreviations differ. Different sizes, ratings, "
                          "locations or materials mean they are NOT the same item.")},
            ],
        } for pid, a, b in batch]
        body = {"model": MODEL, "input": _shared_input(glossary), "questions": questions}
        if cache_key:
            body["prompt_cache_key"] = cache_key
        raw = await _post(body)
        if raw is None:
            for pid, _a, _b in batch:
                out[pid] = Abstain("the decisions endpoint could not be reached", pid)
            continue
        for pid, _a, _b in batch:
            a = _answer_for(raw, pid)
            if a is None:
                out[pid] = Abstain("no answer came back for this question", pid)
            elif a.get("type") == "refusal":
                out[pid] = Abstain("the model declined to answer", pid)
            elif a.get("type") == "predicate":
                p = float(a.get("probability") or 0.0)
                out[pid] = (Answer(True, p, pid) if p >= threshold
                            else Answer(False, 1 - p, pid) if p <= 1 - threshold
                            else Abstain(f"not clear enough (p={p:.2f})", pid, p))
            else:
                out[pid] = Abstain(f"unexpected answer type {a.get('type')!r}", pid)
    return out


def _shared_input(glossary: list[tuple[str, str]] | None) -> str:
    """The evidence every question in the request shares."""
    head = ("You are checking whether lines from a purchase order, a vendor's invoice and "
            "an auditor's site report refer to the same item. Judge wording only; amounts "
            "are checked elsewhere.")
    if not glossary:
        return head
    # Capped: the point is to show how these documents talk, not to re-send the
    # whole invoice. Longest wordings first — they carry the most vocabulary.
    pairs = sorted(glossary, key=lambda t: -(len(t[0]) + len(t[1])))[:40]
    lines = "\n".join(f"  PO: {a}\n  billed as: {b}" for a, b in pairs)
    return (head + "\n\nOn these same two documents the following pairs are already "
            "confirmed as the same item. They show how this vendor words things; use them "
            "to judge the wording of the pairs you are asked about, and nothing more.\n"
            + lines)


def lookup_adjudicator(judged: dict[str, Verdict]):
    """Turn pre-computed judgements into the matcher's synchronous hook.

    `LineMatcher` is pure and synchronous, and should stay that way: it is the
    piece whose output a reviewer has to be able to reproduce. So the asking
    happens before it runs, and what it sees is a lookup.

    A pair the model rejected, or abstained on, is simply not offered — the
    matcher then leaves the line for a person, which is what it does today.
    """
    def adjudicate(cand, ranked):
        for po_line, _score in ranked:
            v = judged.get(f"{po_line.key}|{cand.key}")
            if v is not None and v.decided and v.value is True:
                return po_line.key, v.confidence, f"same item (decisions, p={v.confidence:.2f})"
        return None, 0.0, ""
    return adjudicate


class Collector:
    """An adjudicator that answers nothing and remembers what it was asked.

    `LineMatcher` already works out, for each line it could not place, which PO
    lines are plausible — that is what it hands its adjudicator. Rather than
    reaching into the matcher to recompute it, we run the match once with this,
    judge what it collected, and run it again with the answers. The matcher
    stays pure and unchanged, and the first pass is a pure function of its
    input, so running it twice costs only CPU.
    """

    def __init__(self) -> None:
        self.pairs: list[tuple[str, str, str]] = []

    def __call__(self, cand, ranked):
        for po_line, _score in ranked:
            self.pairs.append((f"{po_line.key}|{cand.key}", po_line.description, cand.text))
        return None, 0.0, ""
