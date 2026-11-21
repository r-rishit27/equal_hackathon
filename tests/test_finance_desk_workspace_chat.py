from datetime import date
from unittest.mock import AsyncMock
import asyncio
import json

import pytest
from fastapi import HTTPException, Response
from backend_ocr.app.domain.copilot_documents import inspect_document
from backend_ocr.app.routers import copilot_chat as chat


def test_document_math_exact_rounding_and_mismatches():
    result=inspect_document("lines.csv",b"quantity,unit_price,line_total\n1.5,2.01,3.02\n2,5,12\n")
    assert result["checked_rows"]==2 and result["mismatch_count"]==1
    assert result["examples"]==[dict(row=3,expected="10.00",difference="2.00")]


@pytest.mark.parametrize("name,data", [("bad.pdf",b"garbage"),("a.exe",b"x"),("lines.csv",b"quantity,unit_price,line_total\nNaN,3,9"),
                                        ("x.txt",b"x"*(2*1024*1024+1)),("a.txt",b"")])
def test_document_validation(name,data):
    with pytest.raises(HTTPException):inspect_document(name,data)


def test_record_comparison_scoped_and_currency_checked(monkeypatch):
    claims=inspect_document("x.csv",b"invoice_number,invoice_total,currency\nINV1,100.05,INR")["invoice_claims"]
    actor=("test","user","admin")
    def lookup(identity,intent,search,exact):
        assert identity==actor and intent=="records" and exact and search=="INV1"
        return [dict(id="bill",currency_code="INR",total_amount="100.01")]
    monkeypatch.setattr(chat,"retrieve",lookup)
    assert chat.reconcile_claims(actor,claims)[0]["difference"]=="0.04"
    monkeypatch.setattr(chat,"retrieve",lambda *a,**k: [])
    assert chat.reconcile_claims(actor,claims)[0]["status"]=="no visible match"


def test_conflicting_invoice_total_rejected():
    with pytest.raises(HTTPException):
        inspect_document("x.csv",b"invoice_number,invoice_total,currency\nA,10,INR\nA,12,INR")


def test_model_cannot_choose_unlicensed_tool_or_citation(monkeypatch):
    calls=[]
    monkeypatch.setattr(chat,"require_tenant",lambda:"t")
    monkeypatch.setattr(chat,"actor",lambda tenant:("tenant","user","auditor"))
    def read(identity,domains=(),search="",overview=False):
        calls.extend(domains)
        return ["vendors"], [dict(title="A",path="/vendors",domain="vendors")] if domains else []
    monkeypatch.setattr(chat,"workspace",read)
    model=AsyncMock(side_effect=[chat.Tools(domains=["vendors","payments"]), chat.Answer(message="See [S8]",citations=["S8"])])
    monkeypatch.setattr(chat,"completion",model)
    reply=asyncio.run(chat.chat(Response(),json.dumps(dict(question="Suppliers?")),None))
    assert set(calls)=={"vendors"} and reply["mode"]=="evidence"
    assert reply["sources"][0]["id"]=="S1"


def test_access_revoked_during_model_call(monkeypatch):
    monkeypatch.setattr(chat,"require_tenant",lambda:"t")
    monkeypatch.setattr(chat,"actor",lambda tenant:("t","u","admin"))
    snapshots=iter([(["vendors"],[]),(["vendors"],[dict(title="A",domain="vendors",path="/vendors")]),([],[])])
    monkeypatch.setattr(chat,"workspace",lambda *a:next(snapshots))
    monkeypatch.setattr(chat,"completion",AsyncMock(side_effect=[
        chat.Tools(domains=["vendors"]),chat.Answer(message="A [S1]",citations=["S1"])]))
    with pytest.raises(HTTPException) as err:
        asyncio.run(chat.chat(Response(),'{"question":"vendors"}',None))
    assert err.value.status_code==409


def test_followup_context_is_scoped_to_identity_and_expiry(monkeypatch):
    ident=("t","u","admin")
    token=chat.remember_plan(ident,{"domains":["vendors"],"search":"test","overview":False})
    assert chat.context_plan(ident,token)["domains"]==["vendors"]
    assert chat.context_plan(("other","u","admin"),token) is None
    assert chat.context_plan(("t","u","auditor"),token) is None
    monkeypatch.setattr(chat,"monotonic",lambda:float("inf"))
    assert chat.context_plan(ident,token) is None
