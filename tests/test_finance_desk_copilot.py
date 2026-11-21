import asyncio
from uuid import uuid4
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException, Response
from pydantic import ValidationError
from backend_ocr.app.routers import copilot as cp


def row(stage="Approver", linked=True):
    return dict(id=str(uuid4()), invoice_number="INV-1", due_date="2026-11-20",
                stage=stage, step_role="approver", supplier="Vendor",
                graph_link=linked, latest_action="submit", action_at=None)


def test_assignment_and_department_override():
    config = [dict(department="Ops", role="approver", label="Finance check", locked=False,
                   assignees=[" Alice "])]
    rules, departments = cp.stage_scope(config, "approver", "Alice")
    assert departments == ["Ops"]
    assert {s["dept"] for s in rules} == {None, "Ops"}
    for name in ("Other", None):
        rules, departments = cp.stage_scope(config, "approver", name)
        assert departments == ["Ops"] and [s["dept"] for s in rules] == [None]
    assert cp.stage_scope(config, "member", "Alice")[0] == []


def test_cached_projection_is_bound_to_actor_scope_and_data():
    cp._cache.clear()
    first = ("tenant-a", "alice", "approver")
    records = [row()]
    answer = cp.grounded_answer(first, "queue", None, records)
    assert cp.grounded_answer(first, "queue", None, records) is answer
    for actor in [("tenant-b", "alice", "approver"), ("tenant-a","bob","approver"),
                  ("tenant-a","alice","accountant")]:
        assert cp.grounded_answer(actor,"queue",None,records) is not answer
    assert cp.grounded_answer(first,"queue",None,[])["evidence"] == []
    changed = [dict(records[0], supplier="New supplier")]
    assert cp.grounded_answer(first,"queue",None,changed)["evidence"][0]["supplier"] == "New supplier"


def test_expired_cache_and_bounded_citations(monkeypatch):
    clock = [100]
    monkeypatch.setattr(cp.time, "monotonic", lambda: clock[0])
    identity = ("a","b","admin")
    records = [row() for _ in range(cp.LIMIT+1)]
    answer = cp.grounded_answer(identity,"relationships",None,records)
    assert answer["partial"] and len(answer["evidence"]) == cp.LIMIT
    clock[0] += 91
    assert cp.grounded_answer(identity,"relationships",None,records) is not answer


def test_no_client_supplied_auth():
    with pytest.raises(ValidationError):
        cp.Query(question="queue", role="admin", tenant_id="other")


@pytest.mark.parametrize("role,impersonating", [("member",False),("admin",True),("unknown",False)])
def test_blocked_actor(monkeypatch, role, impersonating):
    for key,value in [('require_tenant','t'),('current_role',role),('current_username','u'),
                      ('current_actor',None),('is_impersonating',impersonating)]:
        monkeypatch.setattr(cp,key,lambda v=value:v)
    with pytest.raises(HTTPException) as exc:
        cp.actor()
    assert exc.value.status_code == 403


def test_permissions_rechecked_after_model(monkeypatch):
    identity = ("t","a","approver")
    evidence = row()
    monkeypatch.setattr(cp, "actor", lambda: identity)
    snapshots = iter([[evidence], []])
    monkeypatch.setattr(cp, "retrieve", lambda *args: next(snapshots))
    model = AsyncMock(return_value=SimpleNamespace(content=dict(intent="queue",citation=1,focus="supplier")))
    monkeypatch.setattr(cp,"complete_json", model)
    result = asyncio.run(cp.query_copilot(cp.Query(question="What is waiting on me?"), Response()))
    assert not result["evidence"] and evidence["supplier"] not in result["answer"]
    assert evidence["id"] not in model.call_args.kwargs["user"]


def test_model_unavailable_presets_still_work(monkeypatch):
    monkeypatch.setattr(cp,"actor",lambda: ("t","u","admin"))
    monkeypatch.setattr(cp,"retrieve",lambda *args: [row()])
    model = AsyncMock(side_effect=cp.LLMRefused("budget"))
    monkeypatch.setattr(cp,"complete_json",model)
    fallback = asyncio.run(cp.query_copilot(cp.Query(question="Free text"),Response()))
    assert fallback["intent"]=="unsupported"
    result = asyncio.run(cp.query_copilot(cp.Query(question=next(iter(cp.QUESTIONS))),Response()))
    assert result["evidence"][0]["citation"]=="B1"
    assert model.await_count==1
