"""Recon API against a throwaway Postgres (RECON_TEST_DB_URL).

Mounts only the recon router on a bare FastAPI app; the tenant/user context
and storage are patched, everything else (SQL, engine) is real.
"""
from __future__ import annotations

import os
import uuid

import pytest

asyncpg = pytest.importorskip("asyncpg")
httpx = pytest.importorskip("httpx")

from fastapi import FastAPI

from backend_ocr.app.recon.pipeline import ReconPipeline
from backend_ocr.app.recon.repo import ReconRepository
from backend_ocr.app.recon.schema import DDL

from .vocab_db import apply_vocab
from backend_ocr.app.routers import recon as R

from .test_pipeline_db import EXTRA
from .test_repo_db import STUBS, SUPPLIER, TENANT, _load_case

DB_URL = os.getenv("RECON_TEST_DB_URL")
pytestmark = pytest.mark.skipif(not DB_URL, reason="RECON_TEST_DB_URL not set")


@pytest.fixture
async def env(monkeypatch, tmp_path):
    pool = await asyncpg.create_pool(DB_URL, min_size=1, max_size=4)
    async with pool.acquire() as c:
        await c.execute(STUBS)
        await c.execute(EXTRA)
        for stmt in DDL:
            await c.execute(stmt)
        apply_vocab(DB_URL)                      # vocabulary codes, generated columns, FKs
        await c.execute("INSERT INTO dim_suppliers VALUES ($1::uuid, $2::uuid, 'INNERSPACE', '29AKRPP8699K1ZO', NULL)",
                        SUPPLIER, TENANT)
    repo = ReconRepository(pool)
    who = {"tenant": TENANT, "role": "finance"}

    async def _repo():
        return repo
    monkeypatch.setattr(R, "_repo", _repo)
    monkeypatch.setattr(R, "require_tenant", lambda: who["tenant"])
    monkeypatch.setattr(R, "current_username", lambda: "tester")
    monkeypatch.setattr(R, "current_role", lambda: who["role"])
    from backend_ocr.app.core import object_store

    def save(key, data, content_type=None):
        p = tmp_path / key.replace("/", "_")
        p.write_bytes(data)
        return str(p)
    monkeypatch.setattr(object_store, "save", save)
    app = FastAPI()
    app.include_router(R.router)
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")
    yield client, repo, who
    await client.aclose()
    await pool.close()


async def test_case_endpoints(env):
    client, repo, who = env
    _, case_id, _ = await _load_case(repo.pool, "innerspace_red")
    await ReconPipeline(repo).recompute(TENANT, case_id)

    r = await client.get(f"/api/vendors/{SUPPLIER}/recon/cases")
    assert r.status_code == 200 and len(r.json()) == 1
    assert r.json()[0]["money_at_risk"] == "31350.00"

    r = await client.get(f"/api/recon/cases/{case_id}")
    case = r.json()
    assert r.status_code == 200 and case["summary"]["status"] == "NEEDS_REVIEW"
    assert {a["role"] for a in case["attached"]} == {"po", "invoice", "evidence"}
    assert any(not h["passed"] for h in case["header"])

    # Acknowledge is refused while a blocker is open, and needs a note + approver role to force.
    r = await client.post(f"/api/recon/cases/{case_id}/ack", json={"note": ""})
    assert r.status_code == 409
    r = await client.post(f"/api/recon/cases/{case_id}/ack", json={"note": "x", "force": True})
    assert r.status_code == 403
    who["role"] = "approver"
    r = await client.post(f"/api/recon/cases/{case_id}/ack", json={"note": "Transport billed per site manager mail",
                                                                    "force": True})
    assert r.status_code == 200
    who["role"] = "finance"

    # Correcting the transport reading reopens the case and clears the blocker.
    transport = next(l for l in case["lines"] if l["description"].startswith("Transportatio"))
    row_id = transport["evidence_key"].split(":", 1)[1]
    r = await client.post(f"/api/recon/evidence/{row_id}/correct", json={"verdict": "NOT_COVERED"})
    assert r.status_code == 200
    assert r.json()["summary"]["money_at_risk"] == "0.00"
    assert r.json()["summary"]["status"] == "NEEDS_REVIEW"          # changed after acknowledgement

    # Override a match and confirm it sticks.
    ten = next(l for l in r.json()["lines"] if (l.get("invoice_text") or "").startswith("See Through channel 10"))
    po_line = next(l for l in r.json()["lines"] if l["description"] == "See Through channel 8 Fit")
    r = await client.post(f"/api/recon/cases/{case_id}/lines/match",
                          json={"other_key": ten["invoice_key"], "po_line_key": po_line["po_key"]})
    assert r.status_code == 200
    moved = next(l for l in r.json()["lines"] if l["po_key"] == po_line["po_key"])
    assert moved["invoice_key"] == ten["invoice_key"] and moved["match_method"] == "HUMAN"

    r = await client.get(f"/api/recon/cases/{case_id}/export")
    assert r.status_code == 200 and r.content[:2] == b"PK"

    # Another tenant sees nothing.
    who["tenant"] = str(uuid.uuid4())
    assert (await client.get(f"/api/recon/cases/{case_id}")).status_code == 404
    assert (await client.get(f"/api/vendors/{SUPPLIER}/recon/cases")).status_code == 404


async def test_upload_and_duplicates(env):
    client, repo, _ = env
    files = [("file", ("po.pdf", b"%PDF-1.4 tiny", "application/pdf")), ("file", ("notes.docx", b"x", "application/msword"))]
    r = await client.post(f"/api/vendors/{SUPPLIER}/recon/documents", files=files)
    assert r.status_code == 200
    body = r.json()
    assert body[0]["recon_status"] == "PENDING"
    assert body[1]["error"]
    r = await client.post(f"/api/vendors/{SUPPLIER}/recon/documents",
                          files=[("file", ("po-again.pdf", b"%PDF-1.4 tiny", "application/pdf"))])
    assert r.json()[0]["duplicate_of"] and r.json()[0]["id"] is None
    docs = (await client.get(f"/api/vendors/{SUPPLIER}/recon/documents")).json()
    assert len(docs) == 1 and docs[0]["recon_status"] == "PENDING"
    assert (await client.get(f"/api/vendors/{uuid.uuid4()}/recon/documents")).status_code == 404


async def test_case_documents_show_what_was_read(env):
    """Step 1 of the case screen: each document with its fields and lines, as the engine reads them."""
    client, repo, who = env
    _, case_id, _ = await _load_case(repo.pool, "innerspace_red")
    await ReconPipeline(repo).recompute(TENANT, case_id)

    r = await client.get(f"/api/recon/cases/{case_id}/documents")
    assert r.status_code == 200
    docs = r.json()
    assert [d["role"] for d in docs][:2] == ["po", "invoice"] and "evidence" in {d["role"] for d in docs}

    po = docs[0]
    labels = {f["label"]: f for f in po["fields"]}
    assert "PO number" in labels and labels["PO total"]["fmt"] == "money"
    assert po["tables"][0]["title"] == "PO lines" and len(po["tables"][0]["rows"]) > 5
    assert {c["key"] for c in po["tables"][0]["columns"]} >= {"description", "qty", "rate", "amount"}

    inv = docs[1]
    assert any(f["label"] == "Invoice number" for f in inv["fields"])
    assert any("Transportatio" in (row["description"] or "") for t in inv["tables"] for row in t["rows"])

    ev = next(d for d in docs if d["role"] == "evidence")
    rows = ev["tables"][0]["rows"]
    transport = next(row for row in rows if (row["item"] or "").startswith("Transportatio"))
    assert transport["audit_qty"] in ("0", "0.000", "0.00") and transport["id"]

    # A correction made on step 2 shows on step 1 too — one reading, not two.
    await client.post(f"/api/recon/evidence/{transport['id']}/correct", json={"audit_qty": "1", "verdict": "VERIFIED"})
    rows = next(d for d in (await client.get(f"/api/recon/cases/{case_id}/documents")).json() if d["role"] == "evidence")["tables"][0]["rows"]
    assert next(row for row in rows if row["id"] == transport["id"])["verdict"] == "Counted"

    who["tenant"] = str(uuid.uuid4())
    assert (await client.get(f"/api/recon/cases/{case_id}/documents")).status_code == 404
    assert (await client.get(f"/api/recon/segments/{ev['id']}/page", params={"page": 1})).status_code == 404


async def test_file_view_compares_each_line_against_the_other_documents(env):
    """Opening an uploaded file: every part as read, each row with its comparison and the case's coverage."""
    client, repo, who = env
    _, case_id, _ = await _load_case(repo.pool, "innerspace_red")
    await ReconPipeline(repo).recompute(TENANT, case_id)
    segs = await repo.case_segments(case_id)
    inv = next(s for s in segs if s["role"] == "invoice")

    r = await client.get(f"/api/recon/documents/{inv['doc_id']}/view")
    assert r.status_code == 200
    v = r.json()
    part = next(p for p in v["parts"] if p["id"] == inv["id"])
    assert part["case"]["ways"] == 3 and part["case"]["coverage"] == {"po": True, "invoice": True, "evidence": True, "pod": False}
    assert part["case"]["totals"]["money_at_risk"] == "31350.00"
    rows = part["tables"][0]["rows"]
    transport = next(x for x in rows if x["description"].startswith("Transportatio"))
    assert transport["_cmp"]["severity"] == "BLOCKER" and transport["_cmp"]["verified_qty"] in ("0", "0.000")
    assert sum(1 for x in rows if x.get("_cmp")) >= len(rows) - 1

    # The PO's rows carry the comparison too, from the other side.
    po = next(s for s in segs if s["role"] == "po")
    pv = (await client.get(f"/api/recon/documents/{po['doc_id']}/view")).json()
    assert any(x.get("_cmp") for p in pv["parts"] for t in p["tables"] for x in t["rows"])

    who["tenant"] = str(uuid.uuid4())
    assert (await client.get(f"/api/recon/documents/{inv['doc_id']}/view")).status_code == 404


async def test_po_links_to_an_invoice_that_does_not_print_its_number(env):
    """Inner Space prints its own reference ("P00004731 dt. 16.Sep.26"), not Bata's PO number:
    the PO still finds its invoice by lines, store and dates (05_USER_FLOWS.md F8)."""
    import json as _json
    client, repo, who = env
    _, case_id, inp = await _load_case(repo.pool, "innerspace_red")
    segs = await repo.case_segments(case_id)
    po_seg = next(s for s in segs if s["role"] == "po")
    inv_seg = next(s for s in segs if s["role"] == "invoice")
    async with repo.pool.acquire() as c:
        ex = _json.loads(await c.fetchval("SELECT extracted_json FROM recon_doc_segments WHERE id = $1::uuid", inv_seg["id"]))
        ex["po_ref"] = "P00004731 dt. 16.Sep.26"
        await c.execute("UPDATE recon_doc_segments SET extracted_json = $2::jsonb, store_sn = $3 WHERE id = $1::uuid",
                        inv_seg["id"], _json.dumps(ex), inp.po.store_sn)
    await repo.detach(TENANT, case_id, po_seg["id"])
    await repo.set_case(case_id, po_id=None)
    po_id = await repo.find_po(TENANT, inp.po.po_number.partition("-")[0])

    linked = await ReconPipeline(repo)._link_po_by_content(TENANT, SUPPLIER, po_seg["id"], po_id, inp.po)
    assert linked == case_id
    row = await repo.case_row(TENANT, case_id)
    assert str(row["po_id"]) == po_id
    assert any(s["id"] == po_seg["id"] for s in await repo.case_segments(case_id))


async def test_delete_and_read_again(env):
    client, repo, who = env
    _, case_id, inp = await _load_case(repo.pool, "innerspace_red")
    await ReconPipeline(repo).recompute(TENANT, case_id)
    doc_id = str((await repo.case_segments(case_id))[0]["doc_id"])

    # Read again: the file's parts leave the case (rebuilt when the worker reads it), status back to PENDING.
    r = await client.post(f"/api/recon/documents/{doc_id}/reread")
    assert r.status_code == 200 and r.json()["recon_status"] == "PENDING"
    assert await repo.case_segments(case_id) == []
    row = await repo.case_row(TENANT, case_id)
    assert row is not None and row["po_id"] is None                  # kept: it has a bill; PO retired with its file
    assert (await client.post(f"/api/recon/documents/{doc_id}/reread")).status_code == 409   # already queued

    # Delete: gone from the list, and the same bytes can be uploaded again.
    files = [("file", ("po.pdf", b"%PDF-1.4 delete-me", "application/pdf"))]
    up = (await client.post(f"/api/vendors/{SUPPLIER}/recon/documents", files=files)).json()[0]
    async with repo.pool.acquire() as c:
        await c.execute("UPDATE vendor_documents SET recon_status = 'FAILED', recon_error = 'value too long' WHERE id = $1::uuid", up["id"])
    r = await client.delete(f"/api/recon/documents/{up['id']}")
    assert r.status_code == 200
    names = [d["file_name"] for d in (await client.get(f"/api/vendors/{SUPPLIER}/recon/documents")).json()]
    assert "po.pdf" not in names
    again = (await client.post(f"/api/vendors/{SUPPLIER}/recon/documents", files=files)).json()[0]
    assert again["id"] and not again.get("duplicate_of")

    who["tenant"] = str(uuid.uuid4())
    assert (await client.delete(f"/api/recon/documents/{again['id']}")).status_code == 404
    assert (await client.post(f"/api/recon/documents/{again['id']}/reread")).status_code == 404
