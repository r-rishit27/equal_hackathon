"""Keep the recon tests off the network.

`ReconPipeline.recompute` consults the OpenAI Decisions API about lines the
matcher could not place. That is right in production and wrong in a test: it
makes a paid call, it needs a key, and it makes the result depend on something
outside the inputs.

It was not a theory. The first full run of the database suite took **3h19m**
and `test_db_recompute_equals_in_memory` failed, because the test compares
`recompute` (adjudicated, over the network) against `reconcile` (deterministic)
and the two are no longer the same function.

Disabling it here rather than in the product keeps the default honest — the
feature is on where it should be — and keeps every test hermetic. A test that
wants the layer can set `decisions.ENABLED` itself; the ones that do already
patch `_post`, so nothing reaches the network either way.
"""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _no_outbound_decisions(monkeypatch):
    from backend_ocr.app.recon import decisions

    monkeypatch.setattr(decisions, "ENABLED", False, raising=False)
