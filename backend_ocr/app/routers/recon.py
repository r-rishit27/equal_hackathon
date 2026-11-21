"""Recon API — Vendor card → Documents → Recon (docs/bata-recon/03_LLD_BACKEND.md §4).

Every route resolves the tenant from the JWT and checks the supplier / case /
segment belongs to it; anything from another tenant is a 404 (E-SC-01).
Files are never served publicly: evidence crops come back as image bytes on
this authenticated route, rendered on demand and not cached by the browser.
"""
from __future__ import annotations

import hashlib
import io
import json
import mimetypes
import uuid
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel

from ..recon import config as C
from ..recon.repo import ReconRepository, load_extracted
from ..recon.types import SegmentKind
from ..security.auth import current_role, current_username, require_tenant

router = APIRouter()


async def _repo() -> ReconRepository:
    from db import get_pool
    return ReconRepository(await get_pool())


def _j(v):
    """JSON-safe: Decimal → str, dates → ISO, UUID → str."""
    if isinstance(v, dict):
        return {k: _j(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_j(x) for x in v]
    if isinstance(v, Decimal):
        return str(v)
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    if isinstance(v, uuid.UUID):
        return str(v)
    return v


async def _supplier(repo: ReconRepository, tenant: str, supplier_id: str) -> None:
    try:
        uuid.UUID(supplier_id)
    except ValueError:
        raise HTTPException(404, "Vendor not found")
    async with repo.pool.acquire() as c:
        ok = await c.fetchval("SELECT 1 FROM dim_suppliers WHERE supplier_id = $1::uuid AND tenant_id = $2::uuid",
                              supplier_id, tenant)
    if not ok:
        raise HTTPException(404, "Vendor not found")


async def _case(repo: ReconRepository, tenant: str, case_id: str) -> dict:
    try:
        uuid.UUID(case_id)
    except ValueError:
        raise HTTPException(404, "Case not found")
    row = await repo.case_row(tenant, case_id)
    if not row:
        raise HTTPException(404, "Case not found")
    return row


async def _segment(repo: ReconRepository, tenant: str, seg_id: str) -> dict:
    try:
        uuid.UUID(seg_id)
    except ValueError:
        raise HTTPException(404, "Document section not found")
    s = await repo.segment(tenant, seg_id)
    if not s:
        raise HTTPException(404, "Document section not found")
    return s


def _actor() -> str:
    return current_username() or "user"


async def _recompute(repo: ReconRepository, tenant: str, case_id: str) -> None:
    from ..recon.pipeline import ReconPipeline
    await ReconPipeline(repo).recompute(tenant, case_id, actor=_actor())


# ── documents ─────────────────────────────────────────────────────────────────

@router.post("/api/vendors/{supplier_id}/recon/documents")
async def upload_recon_documents(supplier_id: str, request: Request, brand_id: str | None = None):
    tenant = require_tenant()
    repo = await _repo()
    await _supplier(repo, tenant, supplier_id)
    from ..core import object_store
    out = []
    async with request.form() as form:
        files = form.getlist("file")
        if not files:
            raise HTTPException(422, "Attach at least one file")
        force = str(form.get("force") or "").lower() in ("1", "true", "yes")
        for f in files:
            name = f.filename or "document"
            ext = Path(name).suffix.lower()
            if ext not in C.ALLOWED_EXT:
                out.append({"file_name": name, "error": "This file type can't be read here (use PDF, image, XLSX or CSV)"})
                continue
            data = await f.read()
            if len(data) > C.MAX_UPLOAD_MB * 1024 * 1024:
                out.append({"file_name": name, "error": f"Larger than {C.MAX_UPLOAD_MB} MB"})
                continue
            sha = hashlib.sha256(data).hexdigest()
            dup = await repo.find_duplicate(tenant, supplier_id, sha)
            if dup and not force:
                out.append({"file_name": name, "duplicate_of": _j(dup), "error": None, "id": None})
                continue
            doc_id = str(uuid.uuid4())
            try:
                ref = object_store.save(object_store.key("vendor-docs", tenant, supplier_id, doc_id), data,
                                        mimetypes.guess_type(name)[0])
            except object_store.LocalRefOnSharedDatabase as e:
                # Say it here, where the mistake is, rather than letting it
                # surface later as an unreadable document.
                out.append({"file_name": name, "error": str(e)})
                continue
            async with repo.pool.acquire() as c:
                await c.execute(
                    """INSERT INTO vendor_documents (id, supplier_id, tenant_id, brand_id, file_name, file_path, file_size,
                              uploaded_by, doc_type, doc_label, claims_status, recon_status, content_sha256)
                       VALUES ($1::uuid, $2::uuid, $3::uuid,
                               COALESCE($4::uuid, (SELECT brand_id FROM dim_suppliers WHERE supplier_id = $2::uuid)),
                               $5, $6, $7, $8, 'recon', 'Recon', 'SKIPPED', 'PENDING', $9)""",
                    doc_id, supplier_id, tenant, brand_id, name, ref, len(data), _actor(), sha)
            await repo.log_event(tenant, "uploaded", {"file_name": name, "bytes": len(data)}, actor=_actor(), doc_id=doc_id)
            out.append({"id": doc_id, "file_name": name, "recon_status": "PENDING",
                        "duplicate_of": _j(dup) if dup else None})
    await repo.notify("recon_docs", json.dumps({"kind": "doc"}))
    return out


@router.get("/api/vendors/{supplier_id}/recon/documents")
async def list_recon_documents(supplier_id: str, brand_id: str | None = None):
    tenant = require_tenant()
    repo = await _repo()
    await _supplier(repo, tenant, supplier_id)
    docs = await repo.list_docs(tenant, supplier_id, brand_id)
    out = []
    for d in docs:
        segs = await repo.segments_for_doc(str(d["id"]))
        out.append(_j({
            "id": d["id"], "file_name": d["file_name"], "recon_status": d["recon_status"], "recon_stage": d["recon_stage"],
            "progress": json.loads(d["recon_progress"]) if isinstance(d["recon_progress"], str) else d["recon_progress"],
            "error": d["recon_error"], "uploaded_at": d["uploaded_at"], "uploaded_by": d["uploaded_by"],
            "segments": [_seg_view(s) for s in segs],
        }))
    return out


def _seg_view(s: dict) -> dict:
    ex = s.get("extracted_json") or {}
    rows = ex.get("rows") or []
    return _j({
        "id": s["id"], "kind": s["kind"], "llm_label": s.get("llm_label") or ex.get("llm_label"), "pages": s["pages"],
        "status": s["status"], "section_title": s.get("section_title"), "vendor_name": s.get("vendor_name"),
        "store_sn": s.get("store_sn"), "confidence": float(s["confidence"]) if s.get("confidence") is not None else None,
        "case_id": s.get("case_id"), "candidates": s.get("link_candidates") or [],
        "needs_review_cells": sum(1 for r in rows if r.get("needs_review")), "warnings": s.get("warnings") or [],
        "summary": _seg_summary(s["kind"], ex),
    })


def _seg_summary(kind: str, ex: dict) -> str | None:
    if not ex:
        return None
    if kind == SegmentKind.PURCHASE_ORDER.value:
        return f"PO {ex.get('po_number')} · {len(ex.get('lines') or [])} lines"
    if kind == SegmentKind.TAX_INVOICE.value:
        return f"Invoice {ex.get('invoice_no')}"
    if kind == SegmentKind.PV_SECTION.value:
        return f"{ex.get('section_title') or 'Audit section'} · {len(ex.get('rows') or [])} rows"
    if kind == SegmentKind.POD.value:
        return f"Delivery proof {ex.get('waybill_no') or ''}".strip()
    if kind == SegmentKind.APPROVAL_MEMO.value:
        return f"Memo {ex.get('memo_ref') or ''}".strip()
    return ex.get("summary") or ex.get("llm_label")


class KindBody(BaseModel):
    kind: SegmentKind


@router.patch("/api/recon/segments/{segment_id}")
async def set_segment_kind(segment_id: str, body: KindBody):
    tenant = require_tenant()
    repo = await _repo()
    s = await _segment(repo, tenant, segment_id)
    await repo.set_segment(segment_id, kind=body.kind.value, status="PENDING", overridden_by=_actor())
    await repo.log_event(tenant, "kind_changed", {"from": s["kind"], "to": body.kind.value}, actor=_actor(),
                         doc_id=str(s["doc_id"]))
    from ..recon.pipeline import ReconPipeline
    from ..recon.llm import ReconLLM
    await ReconPipeline(repo, llm=ReconLLM()).reextract_segment(tenant, segment_id)
    return {"queued": False}


class LinkBody(BaseModel):
    case_id: str | None = None
    bill_id: str | None = None
    po_id: str | None = None


_ROLE = {"PURCHASE_ORDER": "po", "TAX_INVOICE": "invoice", "PV_SECTION": "evidence", "POD": "pod",
         "APPROVAL_MEMO": "memo", "OTHER": "other"}


@router.get("/api/recon/cases/{case_id}/path")
async def case_evidence_path(case_id: str, key: str, depth: int = 4):
    """What one line connects to, and the path that reaches it.

    `key` is a line key (`rl:…`, `pol:…`, `ev:…`) — passed as a query parameter
    because it contains a colon. A recursive CTE over `recon_edges`, not a graph
    database (plan §3.1).
    """
    tenant = require_tenant()
    repo = await _repo()
    return {"start": key,
            "reachable": await repo.evidence_path(tenant, case_id, key, max_depth=min(depth, 6))}


@router.get("/api/recon/cases/{case_id}/graph")
async def case_graph(case_id: str):
    """How this reconciliation is held together, for the diagram on the case.

    The documents on the case and the links between them, with the strength of
    those links — what the activity log could never show. A log says a
    recompute happened; this says what it concluded.
    """
    tenant = require_tenant()
    repo = await _repo()
    row = await repo.case_row(tenant, case_id)
    if row is None:
        raise HTTPException(404, "Case not found")
    segs = await repo.case_segments(case_id)
    roles = [s["role"] for s in segs]
    s = row.get("summary_json") or {}
    return _j({
        **(await repo.edge_shape(tenant, case_id)),
        "documents": [
            {"role": "po", "label": "Purchase order", "present": "po" in roles,
             "detail": row.get("po_number")},
            {"role": "invoice", "label": "Invoice", "present": "invoice" in roles or bool(row.get("bill_id")),
             "detail": row.get("invoice_no")},
            {"role": "evidence", "label": "Audit report", "present": "evidence" in roles,
             "detail": f"{roles.count('evidence')} section(s)" if "evidence" in roles else None},
            {"role": "pod", "label": "Delivery proof", "present": "pod" in roles, "detail": None},
            {"role": "payment", "label": "Payment", "present": "payment" in roles, "detail": None},
        ],
        "cover": s.get("leg_cover") or {},
    })


@router.get("/api/recon/cases/{case_id}/fourway")
async def case_fourway(case_id: str):
    """The invoice against each supporting document: PO, audit, GRN, payment.

    Four panels, always in the same order and always present — a panel that
    cannot be filled says why, because a missing screen reads as a forgotten one.
    """
    from ..recon import fourway
    from ..recon.case import CaseBuilder
    from ..recon.types import LineResult, from_json
    tenant = require_tenant()
    repo = await _repo()
    inp, _case = await CaseBuilder(repo).load_input(tenant, case_id)
    lines, _header = await repo.results(case_id)
    # repo.results() already unwraps each row's JSON into the line dict.
    results = [from_json(LineResult, l) for l in lines]
    panels = fourway.build(results, receipt_lines=inp.receipt_lines, payment=inp.payment, pods=inp.pods,
                           invoice=inp.invoice, qty_tol=inp.config.qty_tol,
                           money_tol=inp.config.money_tol)
    return [{
        "pair": p.pair, "title": p.title, "ask": p.ask, "available": p.available,
        "absent_reason": p.absent_reason, "note": p.note, "confirm": p.confirm, "counts": p.counts,
        "lines": [{"description": l.description, "key": l.key, "state": l.state,
                   "match_method": l.match_method, "match_score": l.match_score,
                   "checks": [{"field": c.field, "state": c.state,
                               "invoice": c.invoice, "other": c.other} for c in l.checks]}
                  for l in p.lines],
    } for p in panels]


@router.post("/api/recon/grn/upload")
async def upload_grn_extract(request: Request):
    """Load a goods-receipt extract from Microsoft Dynamics (plan §7).

    Not a document: no OCR, no parser. Columns are mapped from the tenant's
    declared `grn_column_map`, falling back to inference.

    The response is the load report rather than a count, because a partial load
    must never read as a clean one — it names the sheet used, the sheets
    rejected, the columns left unmapped and every row skipped.
    """
    tenant = require_tenant()
    repo = await _repo()
    from ..recon.pipeline import ReconPipeline
    out = []
    async with request.form() as form:
        files = form.getlist("file")
        if not files:
            raise HTTPException(422, "Attach at least one file")
        for f in files:
            name = f.filename or "extract.xlsx"
            if Path(name).suffix.lower() not in (".xlsx", ".xlsm", ".csv"):
                out.append({"file_name": name, "error": "A GRN extract must be .xlsx, .xlsm or .csv"})
                continue
            data = await f.read()
            if len(data) > C.MAX_UPLOAD_MB * 1024 * 1024:
                out.append({"file_name": name, "error": f"Larger than {C.MAX_UPLOAD_MB} MB"})
                continue
            r = await ReconPipeline(repo).ingest_grn_extract(tenant, name, data, actor=_actor())
            out.append({
                "file_name": name, "ok": r.ok, "sheet": r.sheet, "mapping": r.mapping_source,
                "saved": len(r.lines), "rows_read": r.rows_read,
                "mapped_columns": r.mapped, "unmapped_columns": r.unmapped_columns,
                "declared_but_absent": r.declared_but_absent,
                "skipped_rows": r.problems, "rejected_sheets": r.rejected_sheets,
                "error": None if r.lines else (r.problems[0] if r.problems else "nothing loaded"),
            })
    await repo.notify("recon_docs", json.dumps({"kind": "grn"}))
    return out


@router.get("/api/recon/grn/mapping")
async def get_grn_mapping():
    """The tenant's declared column mapping, and the fields the loader needs.

    Returned together so whoever configures a new client can see which canonical
    fields exist without reading the source.
    """
    from ..recon import grn
    tenant = require_tenant()
    repo = await _repo()
    return {"declared": await repo.tenant_grn_mapping(tenant) or {},
            "fields": {f: a[:4] for f, a in grn.ALIASES.items()},
            "required": list(grn.REQUIRED)}


@router.post("/api/recon/segments/{segment_id}/link")
async def link_segment(segment_id: str, body: LinkBody):
    tenant = require_tenant()
    repo = await _repo()
    s = await _segment(repo, tenant, segment_id)
    supplier = str(s["supplier_id"])
    if body.case_id:
        case_id = str((await _case(repo, tenant, body.case_id))["id"])
    elif body.bill_id:
        b = await repo.bill(tenant, body.bill_id)
        if not b or str(b["supplier_id"]) != supplier:
            raise HTTPException(404, "Bill not found for this vendor")
        case_id = await repo.case_for_bill(tenant, body.bill_id) or await repo.ensure_case(
            tenant, supplier, bill_id=body.bill_id, invoice_no=b["invoice_number"])
    elif body.po_id:
        po = await repo.load_po(tenant, body.po_id)
        if not po:
            raise HTTPException(404, "PO not found")
        case_id = await repo.awaiting_case_for_po(tenant, body.po_id) or await repo.ensure_case(
            tenant, supplier, po_id=body.po_id, store_sn=po.store_sn)
    else:
        raise HTTPException(422, "Pick an invoice, a case or a PO")
    role = _ROLE.get(s["kind"], "other")
    if role == "invoice":
        await repo.set_case(case_id, invoice_segment_id=segment_id)
    if role == "po":
        po_id = await repo.find_po(tenant, ((s.get("extracted_json") or {}).get("po_number") or "").partition("-")[0])
        if po_id:
            await repo.set_case(case_id, po_id=po_id)
    await repo.attach(tenant, case_id, segment_id, role, "user", None, _actor())
    await repo.log_event(tenant, "linked", {"segment_id": segment_id, "role": role}, actor=_actor(), case_id=case_id)
    await _recompute(repo, tenant, case_id)
    return {"case_id": case_id}


class IgnoreBody(BaseModel):
    reason: str = ""


@router.post("/api/recon/segments/{segment_id}/ignore")
async def ignore_segment(segment_id: str, body: IgnoreBody):
    tenant = require_tenant()
    repo = await _repo()
    s = await _segment(repo, tenant, segment_id)
    for case_id in await repo.cases_using_segment(segment_id):
        await repo.detach(tenant, case_id, segment_id)
        await _recompute(repo, tenant, case_id)
    await repo.set_segment(segment_id, status="IGNORED")
    await repo.log_event(tenant, "ignored", {"segment_id": segment_id, "reason": body.reason}, actor=_actor(),
                         doc_id=str(s["doc_id"]))
    return {}


# ── cases ─────────────────────────────────────────────────────────────────────

def case_ref(n) -> str | None:
    """The readable case number: 12 → "RC-0012"."""
    return f"RC-{int(n):04d}" if n else None


def _case_summary(c: dict) -> dict:
    s = c.get("summary_json") or {}
    docs = c.get("docs") or []
    kinds = [d.get("role") for d in docs]
    return _j({
        "id": c["id"], "ref": case_ref(c.get("ref_no")), "supplier_id": c.get("supplier_id"), "vendor_name": c.get("vendor_name"),
        "bill_id": c.get("bill_id"), "invoice_no": c.get("invoice_no"), "po_number": c.get("po_number"),
        "store_sn": c.get("store_sn"), "status": c["status"],
        "docs": {"po": "po" in kinds, "invoice": "invoice" in kinds or bool(c.get("bill_id")),
                 "evidence": kinds.count("evidence"), "pod": "pod" in kinds, "memo": "memo" in kinds},
        "po_total": s.get("po_total"), "billed_total": s.get("billed_total"), "expected_total": s.get("expected_total"),
        "money_at_risk": c.get("money_at_risk"), "under_billed": c.get("under_billed"),
        "counts": c.get("counts") or {"BLOCKER": 0, "REVIEW": 0, "INFO": 0}, "computed_at": c.get("computed_at"),
        # How much of the billed value rests on a pairing we are sure of, and
        # which lines are dragging it down.
        "confidence": s.get("confidence"), "confidence_weakest": s.get("confidence_weakest") or [],
        # Section headings left out of the billing, and what they said.
        "rollup_lines": s.get("rollup_lines") or [],
        # How much of the bill each supporting document accounts for.
        "leg_cover": s.get("leg_cover") or {},
        # The bill behind this case was deleted. The reconciliation and its
        # documents are untouched; it is simply not something to pay.
        "bill_deleted": bool(c.get("bill_deleted")),
        "acknowledged_by": c.get("acknowledged_by"), "acknowledged_at": c.get("acknowledged_at"),
    })


@router.get("/api/vendors/{supplier_id}/recon/cases")
async def list_recon_cases(supplier_id: str):
    tenant = require_tenant()
    repo = await _repo()
    await _supplier(repo, tenant, supplier_id)
    return [_case_summary(c) for c in await repo.cases_for_supplier(tenant, supplier_id)]


@router.get("/api/recon/cases/{case_id}")
async def get_recon_case(case_id: str):
    tenant = require_tenant()
    repo = await _repo()
    row = await _case(repo, tenant, case_id)
    segs = await repo.case_segments(case_id)
    row["docs"] = [{"role": s["role"], "kind": s["kind"]} for s in segs]
    async with repo.pool.acquire() as c:
        row["vendor_name"] = await c.fetchval("SELECT COALESCE(NULLIF(name, ''), legal_name) FROM dim_suppliers WHERE supplier_id = $1", row["supplier_id"])
    lines, header = await repo.results(case_id)
    await _attach_crops(repo, lines)
    approvals = []
    for s in segs:
        if s["role"] == "memo":
            m = load_extracted(s["kind"], s.get("extracted_json"))
            if m:
                approvals += [{"memo_ref": m.memo_ref, "approver": a.approver, "status": a.status,
                               "date": a.date, "remark": a.remark} for a in m.approvals]
    return _j({
        "summary": _case_summary(row), "header": header, "lines": lines,
        "attached": [{**_seg_view(s), "role": s["role"], "file_name": s.get("file_name"),
                      "doc_id": s["doc_id"], "link_method": s.get("link_method")} for s in segs],
        "approvals": approvals, "events": await repo.events(tenant, case_id),
        "ack_note": row.get("ack_note"),
    })


async def _attach_crops(repo: ReconRepository, lines: list[dict]) -> None:
    """Each line's evidence cell location (page + bbox) for the review crop."""
    ids = [l["evidence_key"][3:] for l in lines if (l.get("evidence_key") or "").startswith("ev:")]
    found = {}
    if ids:
        async with repo.pool.acquire() as c:
            for r in await c.fetch("SELECT id, segment_id, page, bbox FROM recon_evidence_rows WHERE id = ANY($1::uuid[])", ids):
                bbox = json.loads(r["bbox"]) if isinstance(r["bbox"], str) else r["bbox"]
                if r["page"] and bbox:
                    found[str(r["id"])] = {"segment_id": str(r["segment_id"]), "page": r["page"], "bbox": bbox}
    for l in lines:
        k = l.get("evidence_key") or ""
        l["evidence_crop"] = found.get(k[3:]) if k.startswith("ev:") else None


class DetachBody(BaseModel):
    segment_id: str


@router.post("/api/recon/cases/{case_id}/detach")
async def detach_segment(case_id: str, body: DetachBody):
    tenant = require_tenant()
    repo = await _repo()
    await _case(repo, tenant, case_id)
    s = await _segment(repo, tenant, body.segment_id)
    await repo.detach(tenant, case_id, body.segment_id)
    if s["kind"] == "PURCHASE_ORDER":
        await repo.set_case(case_id, po_id=None)
    await repo.log_event(tenant, "unlinked", {"segment_id": body.segment_id}, actor=_actor(), case_id=case_id)
    await _recompute(repo, tenant, case_id)
    return await get_recon_case(case_id)


class MatchBody(BaseModel):
    other_key: str
    po_line_key: str | None = None


@router.post("/api/recon/cases/{case_id}/lines/match")
async def override_match(case_id: str, body: MatchBody):
    tenant = require_tenant()
    repo = await _repo()
    case = await _case(repo, tenant, case_id)
    from ..recon.case import CaseBuilder
    inp, _ = await CaseBuilder(repo).load_input(tenant, case_id)
    po_by = {l.key: l for l in (inp.po.lines if inp.po else [])}
    if body.po_line_key and body.po_line_key not in po_by:
        raise HTTPException(422, "That PO line isn't on this case's PO")
    texts = {l.key: l.description for l in (inp.invoice.lines if inp.invoice else [])}
    texts |= {r.key: r.item for sec in inp.evidence for r in sec.rows}
    if body.other_key not in texts:
        raise HTTPException(422, "That line isn't on this case")
    await repo.set_override(tenant, case_id, body.other_key, body.po_line_key, _actor())
    await repo.save_alias(tenant, str(case["supplier_id"]), texts[body.other_key],
                          po_by[body.po_line_key].description if body.po_line_key else None, _actor())
    await repo.log_event(tenant, "match_override", body.model_dump(), actor=_actor(), case_id=case_id)
    await _recompute(repo, tenant, case_id)
    return await get_recon_case(case_id)


class ReviewBody(BaseModel):
    note: str = ""


class ConfirmBody(BaseModel):
    """A person's answer to a check the engine could not settle on its own."""
    code: str
    shown: str
    note: str = ""
    withdraw: bool = False


@router.post("/api/recon/cases/{case_id}/confirm")
async def confirm_check(case_id: str, body: ConfirmBody):
    """Answer a check that asked for a human judgement, and recompute.

    `shown` is what the reviewer was looking at. It is stored with the answer
    and compared on every later run, so re-reading the document — which can
    change the reference — asks again rather than coasting on a yes given about
    other words.

    Only checks that declared themselves confirmable can be answered, because a
    screen that lets a reviewer tick away an arithmetic failure is not a review.
    """
    tenant = require_tenant()
    repo = await _repo()
    try:
        uuid.UUID(case_id)
    except ValueError:
        raise HTTPException(404, "Case not found")
    _lines, header = await repo.results(case_id)
    want = next((h for h in header if h.get("code") == body.code), None)
    if want is None:
        raise HTTPException(404, "No such check on this case")
    confirmable = (want.get("evidence") or {}).get("confirmable")
    if not confirmable:
        raise HTTPException(400, "This check is not one a person can confirm")
    if confirmable != body.shown:
        # The document has been read again since the screen was drawn.
        raise HTTPException(409, "The document has changed since this was shown — reload the case")
    await repo.confirm_check(tenant, case_id, code=body.code, shown=body.shown,
                             actor=_actor(), note=body.note or None, withdraw=body.withdraw)
    await repo.log_event(tenant, "check_withdrawn" if body.withdraw else "check_confirmed",
                         {"code": body.code, "shown": body.shown, "note": body.note},
                         actor=_actor(), case_id=case_id)
    from ..recon.pipeline import ReconPipeline
    await ReconPipeline(repo).recompute(tenant, case_id, actor=_actor())
    return {}


@router.post("/api/recon/lines/{result_id}/review")
async def review_line(result_id: str, body: ReviewBody):
    tenant = require_tenant()
    repo = await _repo()
    try:
        uuid.UUID(result_id)
    except ValueError:
        raise HTTPException(404, "Line not found")
    case_id = await repo.review_line(tenant, result_id, _actor(), body.note)
    if not case_id:
        raise HTTPException(404, "Line not found")
    await repo.log_event(tenant, "line_reviewed", {"result_id": result_id, "note": body.note}, actor=_actor(),
                         case_id=case_id)
    return {}


class CorrectBody(BaseModel):
    audit_qty: str | None = None
    vendor_qty: str | None = None
    verdict: str | None = None
    remark: str | None = None


@router.post("/api/recon/evidence/{row_id}/correct")
async def correct_evidence(row_id: str, body: CorrectBody):
    tenant = require_tenant()
    repo = await _repo()
    patch = body.model_dump(exclude_unset=True)
    if "verdict" in patch and patch["verdict"] not in (None, "VERIFIED", "NOT_DONE", "NOT_COUNTABLE", "NOT_COVERED"):
        raise HTTPException(422, "Unknown verdict")
    for k in ("audit_qty", "vendor_qty"):
        if k in patch and patch[k] not in (None, ""):
            from ..recon.num import parse_inr
            v = parse_inr(patch[k])
            if v is None or v < 0:
                raise HTTPException(422, f"{k.replace('_', ' ')} must be a number")
            patch[k] = v
    try:
        uuid.UUID(row_id)
    except ValueError:
        raise HTTPException(404, "Row not found")
    seg_id = await repo.correct_evidence(tenant, row_id, patch, _actor())
    if not seg_id:
        raise HTTPException(404, "Row not found")
    cases = await repo.cases_using_segment(seg_id)
    for case_id in cases:
        await repo.log_event(tenant, "cell_corrected", {"row_id": row_id, **{k: str(v) for k, v in patch.items()}},
                             actor=_actor(), case_id=case_id)
        await _recompute(repo, tenant, case_id)
    return await get_recon_case(cases[0]) if cases else {}


class AckBody(BaseModel):
    note: str = ""
    force: bool = False


@router.post("/api/recon/cases/{case_id}/ack")
async def acknowledge_case(case_id: str, body: AckBody):
    tenant = require_tenant()
    repo = await _repo()
    await _case(repo, tenant, case_id)
    open_ = await repo.unreviewed_blockers(case_id)
    if open_ and not body.force:
        raise HTTPException(409, f"{open_} blocker line(s) or handwritten reading(s) still need a look")
    if open_ and (current_role() or "").lower() not in ("admin", "approver", "owner", "superadmin"):
        raise HTTPException(403, "Only an admin or approver can acknowledge with open blockers")
    if open_ and not body.note.strip():
        raise HTTPException(422, "Add a note saying why it is acknowledged with open blockers")
    await repo.acknowledge(tenant, case_id, _actor(), body.note)
    await repo.log_event(tenant, "acknowledged", {"note": body.note, "forced": bool(open_)}, actor=_actor(),
                         case_id=case_id)
    await repo.notify("review_adapters", "recon")
    return {}


@router.post("/api/recon/cases/{case_id}/rerun")
async def rerun_case(case_id: str):
    tenant = require_tenant()
    repo = await _repo()
    await _case(repo, tenant, case_id)
    await _recompute(repo, tenant, case_id)
    return await get_recon_case(case_id)


@router.get("/api/recon/cases/{case_id}/export")
async def export_case(case_id: str):
    tenant = require_tenant()
    repo = await _repo()
    await _case(repo, tenant, case_id)
    from ..recon.export import case_workbook
    data = case_workbook(await get_recon_case(case_id))
    row = await repo.case_row(tenant, case_id)
    name = f"recon-{(row.get('invoice_no') or case_id[:8]).replace('/', '-')}.xlsx"
    return Response(data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{name}"', "Cache-Control": "no-store"})


@router.get("/api/recon/cases/{case_id}/documents")
async def case_documents(case_id: str):
    """Every document on the case with what was read from it — the step before reconciling."""
    tenant = require_tenant()
    repo = await _repo()
    await _case(repo, tenant, case_id)
    from ..recon.views import DocumentsView
    return _j(await DocumentsView(repo).for_case(tenant, case_id))


@router.get("/api/recon/documents/{doc_id}/view")
async def document_view(doc_id: str):
    """One uploaded file opened: each part as read, with its comparison against the invoice's other documents."""
    tenant = require_tenant()
    repo = await _repo()
    try:
        uuid.UUID(doc_id)
    except ValueError:
        raise HTTPException(404, "Document not found")
    doc = await repo.get_doc(tenant, doc_id)
    if not doc:
        raise HTTPException(404, "Document not found")
    from ..recon.views import DocumentsView
    return _j(await DocumentsView(repo).for_file(tenant, doc))


async def _doc_or_404(repo: ReconRepository, tenant: str, doc_id: str) -> dict:
    try:
        uuid.UUID(doc_id)
    except ValueError:
        raise HTTPException(404, "Document not found")
    doc = await repo.get_doc(tenant, doc_id)
    if not doc:
        raise HTTPException(404, "Document not found")
    return doc


async def _settle(repo: ReconRepository, tenant: str, cases: set[str]) -> None:
    """After a file's parts leave its cases: drop cases left empty, re-check the rest."""
    for cid in cases:
        if not await repo.drop_if_empty(tenant, cid):
            await _recompute(repo, tenant, cid)


@router.delete("/api/recon/documents/{doc_id}")
async def delete_recon_document(doc_id: str):
    """Remove an uploaded file from Recon. Its parts leave every invoice they were on, POs read
    from it are retired, and those invoices are checked again without it. The same file can then
    be uploaded again (the duplicate check skips deleted files)."""
    tenant = require_tenant()
    repo = await _repo()
    doc = await _doc_or_404(repo, tenant, doc_id)
    cases = await repo.remove_doc_parts(tenant, doc_id)
    await repo.delete_doc(tenant, doc_id, _actor())
    await repo.log_event(tenant, "deleted", {"file_name": doc["file_name"], "cases": sorted(cases)}, actor=_actor(), doc_id=doc_id)
    await _settle(repo, tenant, cases)
    return {"deleted": doc_id, "cases": sorted(cases)}


@router.post("/api/recon/documents/{doc_id}/reread")
async def reread_recon_document(doc_id: str):
    """Read a file again from scratch — after a failure, or once the reader has improved."""
    tenant = require_tenant()
    repo = await _repo()
    doc = await _doc_or_404(repo, tenant, doc_id)
    if doc["recon_status"] in ("PENDING", "RUNNING"):
        raise HTTPException(409, "This file is already being read")
    cases = await repo.remove_doc_parts(tenant, doc_id)
    await _settle(repo, tenant, cases)
    await repo.set_doc(doc_id, status="PENDING", stage="reading", error=None, progress={})
    await repo.log_event(tenant, "reread", {"file_name": doc["file_name"]}, actor=_actor(), doc_id=doc_id)
    await repo.notify("recon_docs", json.dumps({"kind": "doc"}))
    return {"id": doc_id, "recon_status": "PENDING"}


@router.get("/api/recon/segments/{segment_id}/page")
async def segment_page(segment_id: str, page: int):
    """One page of an uploaded document as an image, for checking values against the original.

    Tenant-checked and streamed through this authenticated route — never a public link.
    """
    tenant = require_tenant()
    repo = await _repo()
    s = await _segment(repo, tenant, segment_id)
    if page < 1:
        raise HTTPException(404, "Page not found")
    doc = await repo.get_doc(tenant, str(s["doc_id"]))
    if not doc:
        raise HTTPException(404, "Document not found")
    from ..recon.pipeline import ReconPipeline
    from ..recon.pages import PageReader
    data = await ReconPipeline(repo)._bytes(tenant, doc["file_path"])
    if not data:
        raise HTTPException(404, "Document not found")
    reader = PageReader()
    pdf = reader.open(data, doc["file_name"])
    if page > len(pdf):
        raise HTTPException(404, "Page not found")
    png = reader.render(pdf, page, dpi=110)
    return Response(png, media_type="image/png", headers={"Cache-Control": "private, no-store"})


@router.get("/api/recon/segments/{segment_id}/crop")
async def evidence_crop(segment_id: str, page: int, bbox: str):
    """A rendered crop of the page region a number was read from (for the reviewer)."""
    tenant = require_tenant()
    repo = await _repo()
    s = await _segment(repo, tenant, segment_id)
    if page < 1:
        raise HTTPException(404, "Page not found")
    try:
        box = [float(x) for x in bbox.split(",")][:4]
        assert len(box) == 4
    except Exception:
        raise HTTPException(422, "bbox must be x0,y0,x1,y1")
    doc = await repo.get_doc(tenant, str(s["doc_id"]))
    if not doc:
        raise HTTPException(404, "Document not found")
    from ..recon.pipeline import ReconPipeline
    from ..recon.pages import PageReader
    data = await ReconPipeline(repo)._bytes(tenant, doc["file_path"])
    if not data:
        raise HTTPException(404, "Document not found")
    reader = PageReader()
    pdf = reader.open(data, doc["file_name"])
    if page > len(pdf):
        raise HTTPException(404, "Page not found")
    png = reader.crop(pdf, page, box)
    return Response(png, media_type="image/png", headers={"Cache-Control": "private, no-store"})


# ── bills ─────────────────────────────────────────────────────────────────────

@router.get("/api/bills/{invoice_id}/recon")
async def bill_recon(invoice_id: str):
    tenant = require_tenant()
    repo = await _repo()
    try:
        uuid.UUID(invoice_id)
    except ValueError:
        raise HTTPException(404, "Bill not found")
    case_id = await repo.case_for_bill(tenant, invoice_id)
    if not case_id:
        return None
    rows = [c for c in await repo.cases_for_supplier(tenant, str((await repo.case_row(tenant, case_id))["supplier_id"]))
            if str(c["id"]) == case_id]
    return _case_summary(rows[0]) if rows else None


@router.post("/api/bills/{invoice_id}/recon/start")
async def start_bill_recon(invoice_id: str):
    """Read this bill's own invoice file through recon (finds its PO reference and detail page)."""
    tenant = require_tenant()
    repo = await _repo()
    try:
        uuid.UUID(invoice_id)
    except ValueError:
        raise HTTPException(404, "Bill not found")
    doc_id = await repo.adopt_bill(tenant, invoice_id, _actor())
    if not doc_id:
        raise HTTPException(404, "This bill has no stored invoice file")
    await repo.notify("recon_docs", json.dumps({"kind": "doc"}))
    return {"doc_id": doc_id}
