"""The vendor playground: saving a flow, and running it.

The canvas used to live only in the browser's localStorage, which meant a flow
was lost on a different machine and could never be run anywhere but the tab
that drew it. It is stored per vendor here instead, and `run` works it
server-side so the things it produces — a filed report, an amended rate card,
an email — happen where the data and the credentials already are.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from ..config import get_conn, put_conn
from ..domain.playground import checks
from ..domain.playground.engine import RunError
from ..domain.playground.runner import run_flow
from ..security.auth import current_username, require_tenant

log = logging.getLogger(__name__)
router = APIRouter()


class TermDecision(BaseModel):
    choice: str                      # 'contract' | 'keep'
    finding_id: Optional[str] = None  # sent by Review Hub; not needed here


class FlowBody(BaseModel):
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    name: Optional[str] = None


def _vendor(cur, tenant: str, supplier_id: str) -> dict:
    cur.execute(
        "SELECT name, brand_id FROM dim_suppliers WHERE supplier_id=%s AND tenant_id=%s",
        (supplier_id, tenant),
    )
    r = cur.fetchone()
    if not r:
        raise HTTPException(status_code=404, detail="Vendor not found")
    return {"name": r[0], "brand_id": str(r[1]) if r[1] else None}


@router.get("/api/vendors/{supplier_id}/flow")
def get_flow(supplier_id: str, company_id: str = Query(default=None)):
    tenant = require_tenant()
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT flow_id, graph, name, updated_at, updated_by
                     FROM vendor_flows WHERE tenant_id=%s AND supplier_id=%s""",
                (tenant, supplier_id),
            )
            r = cur.fetchone()
        if not r:
            return {"flow_id": None, "nodes": [], "edges": [], "name": None}
        graph = r[1] or {}
        return {"flow_id": str(r[0]), "nodes": graph.get("nodes") or [],
                "edges": graph.get("edges") or [], "name": r[2],
                "updated_at": r[3].isoformat() if r[3] else None, "updated_by": r[4]}
    finally:
        put_conn(conn)


@router.put("/api/vendors/{supplier_id}/flow")
def put_flow(supplier_id: str, body: FlowBody, company_id: str = Query(default=None)):
    tenant = require_tenant()
    graph = {"nodes": body.nodes, "edges": body.edges}
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            _vendor(cur, tenant, supplier_id)
            cur.execute(
                """INSERT INTO vendor_flows (tenant_id, supplier_id, name, graph, updated_by)
                   VALUES (%s,%s,%s,%s,%s)
                   ON CONFLICT (tenant_id, supplier_id) DO UPDATE
                      SET graph = EXCLUDED.graph, name = EXCLUDED.name,
                          updated_by = EXCLUDED.updated_by, updated_at = now()
                   RETURNING flow_id""",
                (tenant, supplier_id, body.name, json.dumps(graph), current_username()),
            )
            flow_id = str(cur.fetchone()[0])
        conn.commit()
        return {"flow_id": flow_id, "saved": True}
    finally:
        put_conn(conn)


@router.post("/api/vendors/{supplier_id}/flow/run")
def run(supplier_id: str, body: FlowBody, company_id: str = Query(default=None)):
    """Work the flow now and report what each node did.

    Synchronous on purpose: a run reaches a model and a mail server, so it is
    slow, but it is also started by someone watching who needs to see whether
    their formula was right. A background job would hand them a job id and a
    page to go and check.
    """
    tenant = require_tenant()
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            v = _vendor(cur, tenant, supplier_id)
            cur.execute("SELECT flow_id FROM vendor_flows WHERE tenant_id=%s AND supplier_id=%s",
                        (tenant, supplier_id))
            row = cur.fetchone()
            flow_id = str(row[0]) if row else None
    finally:
        put_conn(conn)

    if not body.nodes:
        raise HTTPException(status_code=400, detail="There is nothing on the canvas to run.")
    try:
        return run_flow(tenant=tenant, supplier=supplier_id, vendor_name=v["name"],
                        brand_id=v["brand_id"], graph={"nodes": body.nodes, "edges": body.edges},
                        actor=current_username(), flow_id=flow_id)
    except RunError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:                                   # noqa: BLE001
        log.exception("[playground] run failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/vendors/{supplier_id}/flow/runs")
def list_runs(supplier_id: str, company_id: str = Query(default=None), limit: int = Query(10, le=50)):
    tenant = require_tenant()
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT run_id, status, steps, outputs, run_by, started_at
                     FROM vendor_flow_runs WHERE tenant_id=%s AND supplier_id=%s
                    ORDER BY started_at DESC LIMIT %s""",
                (tenant, supplier_id, limit),
            )
            return {"runs": [{"run_id": str(r[0]), "status": r[1], "steps": r[2] or [],
                              "outputs": r[3] or [], "run_by": r[4],
                              "started_at": r[5].isoformat() if r[5] else None}
                             for r in cur.fetchall()]}
    finally:
        put_conn(conn)


@router.post("/api/vendors/{supplier_id}/flow/terms/{field}/decide")
def decide_term(supplier_id: str, field: str, body: TermDecision, company_id: str = Query(default=None)):
    """Answer "the new contract changes this term — which do we use?".

    Called from the Review Hub finding the `playground_checks` adapter raises.
    The next run calculates with the answer; the finding closes as soon as the
    adapters rescan, since the question it asserted is no longer open.
    """
    tenant = require_tenant()
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT flow_id FROM vendor_flows WHERE tenant_id=%s AND supplier_id=%s FOR UPDATE",
                        (tenant, supplier_id))
            r = cur.fetchone()
            if not r:
                raise HTTPException(status_code=404, detail="This vendor has no saved flow")
            flow_id = str(r[0])
            terms = checks.load_terms(cur, flow_id)
            try:
                held = checks.decide_term(terms, field, body.choice, current_username())
            except LookupError as e:
                raise HTTPException(status_code=409, detail=str(e))
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e))
            checks.save_terms(cur, flow_id, terms)
            cur.execute("SELECT pg_notify('ch_review_adapters', '')")
        conn.commit()
        used = f"{held['value']}" + (f" ({held['unit']})" if held.get("unit") else "")
        return {"status": "ok", "field": field, "value": held["value"],
                "message": f"The next run calculates {field.replace('_', ' ')} with {used}."}
    finally:
        put_conn(conn)


@router.get("/api/bills/{invoice_id}/playground-check")
def bill_check(invoice_id: str, company_id: str = Query(default=None)):
    """The latest playground run reconciled against this bill, for its page.

    `check` is null when no run has been compared with this bill — the
    ordinary case for most vendors, which the page shows as nothing at all.
    """
    tenant = require_tenant()
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT r.run_id, r.started_at, r.run_by, r.checks, r.supplier_id, f.terms
                     FROM vendor_flow_runs r
                     LEFT JOIN vendor_flows f ON f.flow_id = r.flow_id
                    WHERE r.tenant_id=%s AND r.invoice_id=%s
                    ORDER BY r.started_at DESC LIMIT 1""",
                (tenant, invoice_id),
            )
            r = cur.fetchone()
        conn.commit()
    finally:
        put_conn(conn)
    if not r:
        return {"check": None}
    chk = r[3] or {}
    pending = [{"field": k, "value": v.get("value"), "unit": v.get("unit"),
                "file_name": v.get("file_name"),
                "contract_value": v["pending"].get("value"),
                "contract_file": v["pending"].get("file_name")}
               for k, v in (r[5] or {}).items() if isinstance(v, dict) and v.get("pending")]
    return {"check": {"run_id": str(r[0]), "run_at": r[1].isoformat() if r[1] else None,
                      "run_by": r[2], "supplier_id": str(r[4]),
                      "recon": chk.get("recon"), "terms": chk.get("terms") or [],
                      "pending_terms": pending}}
