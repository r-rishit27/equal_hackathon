"""Read-only, evidence-grounded answers over the current approval chain and Fact Graph."""
import asyncio
import hashlib
import json
import time
from collections import OrderedDict, defaultdict
from threading import Lock
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Response
from fastapi.encoders import jsonable_encoder
from psycopg2.extras import Json, RealDictCursor
from pydantic import BaseModel, ConfigDict, Field

from ..ai.llm import complete_json, LLMError, LLMRefused
from ..config import get_conn, put_conn
from ..core.approval_chain import _step_idx_to_status
from ..domain.tenant_defaults import DEFAULT_APPROVAL_CHAIN
from ..security.auth import current_actor, current_role, current_username, is_impersonating, require_tenant

router = APIRouter(prefix="/api/finance-desk/assistant", tags=["Finance Desk"])
ROLES = {"admin", "finance_controller", "accountant", "approver", "auditor"}
QUESTIONS = {
    "Which bills are in my approval queue?": "queue",
    "Which pending bills are overdue?": "overdue",
    "Show supplier relationships for pending bills.": "relationships",
}
LIMIT = 12


class Query(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    question: str = Field(min_length=1, max_length=2000)
    bill_id: UUID | None = None


class Intent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    intent: Literal["queue", "overdue", "relationships", "unsupported"]
    citation: int = Field(default=0, ge=0, le=LIMIT)
    focus: Literal["stage", "supplier", "last_action"] = "stage"


def actor():
    tenant = require_tenant()
    role, username = current_role(), current_username()
    if current_actor() or is_impersonating() or role not in ROLES or not username:
        raise HTTPException(403, "Copilot is unavailable for this session.")
    return tenant, username, role


def verify_actor(cur, tenant, username, role):
    # Fail closed on revoked roles and entitlements, including a still-valid old JWT.
    cur.execute("""
        SELECT u.name,
               (SELECT count(*) FROM users n WHERE n.company_id=u.company_id
                AND trim(n.name)=trim(u.name)) = 1 AS unique_name
        FROM users u WHERE u.company_id=%s AND u.username=%s AND u.role=%s
          AND (SELECT count(*) FROM service_catalog c LEFT JOIN tenant_service ts
                ON ts.tenant_id=u.company_id AND ts.service_key=c.service_key
               WHERE c.service_key IN ('bills','approvals','fact_graph') AND c.retired_at IS NULL
                 AND coalesce(ts.enabled,c.default_enabled))=3
    """, (tenant, username, role))
    row = cur.fetchone()
    if not row:
        raise HTTPException(403, "Copilot access is unavailable.")
    return (row["name"] or "").strip() if row["unique_name"] else None


def stage_scope(config, role, name):
    by_department = defaultdict(list)
    for step in config:
        by_department[step["department"]].append(step)
    by_department.setdefault(None, DEFAULT_APPROVAL_CHAIN)
    rules = []
    for department, chain in by_department.items():
        for index, step in enumerate(s for s in chain if not s.get("locked")):
            names = step.get("assignees")
            assigned = not names or (name and name in [n.strip() for n in names if isinstance(n, str)])
            if role == "admin" or (role == step["role"] and assigned):
                rules.append(dict(dept=department, status=_step_idx_to_status(index),
                                  label=step["label"], step_role=step["role"]))
    return rules, [d for d in by_department if d is not None]


EVIDENCE_SQL = """
    WITH stages AS (SELECT * FROM jsonb_to_recordset(%(rules)s::jsonb)
        AS r(dept text,status text,label text,step_role text)),
    visible AS (
        SELECT fi.invoice_id, fi.tenant_id, fi.supplier_id, fi.invoice_number, fi.due_date,
               fi.status, r.label AS stage, r.step_role
        FROM fact_invoices fi JOIN stages r ON r.status=fi.status::text
         AND r.dept IS NOT DISTINCT FROM
             (CASE WHEN fi.department=ANY(%(departments)s::text[]) THEN fi.department END)
        WHERE fi.tenant_id=%(tenant)s AND coalesce(fi.soft_status,'active')='active'
          AND (%(bill)s::uuid IS NULL OR fi.invoice_id=%(bill)s::uuid)
          AND (NOT %(overdue)s OR fi.due_date < (now() AT TIME ZONE 'Asia/Kolkata')::date)
        ORDER BY fi.due_date NULLS LAST, fi.invoice_id LIMIT %(limit)s
    )
    SELECT v.invoice_id::text AS id, v.invoice_number, v.due_date, v.stage, v.step_role,
           s.name AS supplier, history.action AS latest_action, history.created_at AS action_at,
           EXISTS(SELECT FROM fact_graph_nodes b JOIN fact_graph_edges e
                    ON e.tenant_id=b.tenant_id AND e.dst_node_id=b.node_id AND e.relation='has_bill'
                  JOIN fact_graph_nodes n ON n.tenant_id=e.tenant_id AND n.node_id=e.src_node_id
                  WHERE b.tenant_id=v.tenant_id AND b.node_type='bill' AND b.ref_id=v.invoice_id
                    AND n.node_type='vendor' AND n.ref_id=s.supplier_id) AS graph_link
    FROM visible v LEFT JOIN dim_suppliers s ON s.tenant_id=v.tenant_id AND s.supplier_id=v.supplier_id
    LEFT JOIN LATERAL (SELECT a.action, a.created_at FROM bill_approval_chain a
        WHERE a.tenant_id=v.tenant_id AND a.invoice_id=v.invoice_id AND a.step<>99
        ORDER BY a.created_at DESC NULLS LAST, a.id DESC LIMIT 1) history ON true
    ORDER BY v.due_date NULLS LAST, v.invoice_id
"""


def retrieve(identity, intent, bill_id=None):
    tenant, username, role = identity
    conn = get_conn()
    try:
        with conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            cur.execute("SET LOCAL statement_timeout='4s'")
            name = verify_actor(cur, tenant, username, role)
            cur.execute("""SELECT department,label,role,locked,assignees FROM tenant_chain_config
                           WHERE tenant_id=%s AND is_snapshot=false ORDER BY department,step_order,id""", (tenant,))
            rules, departments = stage_scope(cur.fetchall(), role, name)
            cur.execute(EVIDENCE_SQL, dict(rules=Json(rules), departments=departments, tenant=tenant,
                        bill=str(bill_id) if bill_id else None, overdue=intent=="overdue", limit=LIMIT+1))
            return jsonable_encoder(cur.fetchall())
    finally:
        put_conn(conn)


_cache = OrderedDict()
_lock = Lock()


def grounded_answer(identity, intent, bill_id, rows, selection=None):
    # Cache the derived answer only. Every replay first obtains a fresh authorized projection.
    digest = hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()
    key = (*identity, intent, str(bill_id or ""), digest, selection)
    now = time.monotonic()
    with _lock:
        hit = _cache.get(key)
        if hit and now < hit[0]:
            _cache.move_to_end(key)
            return hit[1]
    evidence = [dict(row, citation=f"B{i}", path=f"/bills/{row['id']}") for i, row in enumerate(rows[:LIMIT], 1)]
    more = len(rows) > LIMIT
    if not evidence:
        summary = "No matching pending bills are visible in your approval scope."
    else:
        count = f"At least {LIMIT+1}" if more else str(len(evidence))
        noun = "bill" if len(evidence) == 1 else "bills"
        topic = ("overdue pending " if intent == "overdue" else "pending ") + noun
        summary = f"{count} {topic} in your approval scope. Earliest due dates are shown first."
        if intent=="relationships":
            linked = sum(bool(r["graph_link"]) for r in evidence)
            summary += f" The PostgreSQL Fact Graph confirms supplier links for {linked} of the {len(evidence)} bills shown."
        else:
            first = evidence[0]
            summary += f" [{first['citation']}] is at the {first['stage']} step."
    if selection:
        source_id, focus = selection
        cited = next((r for r in evidence if r["id"] == source_id), None)
        if cited:
            field, label = {"supplier": ("supplier", "Supplier on the bill"),
                            "last_action": ("latest_action", "Latest recorded action"),
                            "stage": ("stage", "Current approval step")}[focus]
            if cited[field]:
                summary += f" [{cited['citation']}] {label}: {cited[field]}."
    answer = dict(answer=summary, intent=intent, evidence=evidence, partial=more)
    with _lock:
        _cache[key] = (now+90, answer)
        _cache.move_to_end(key)
        while len(_cache)>128:
            _cache.popitem(last=False)
    return answer


@router.post("/query")
async def query_copilot(body: Query, response: Response):
    response.headers["Cache-Control"] = "private, no-store"
    identity = actor()
    intent = QUESTIONS.get(body.question)
    selection = None
    if intent is None:
        context = await asyncio.to_thread(retrieve, identity, "queue", body.bill_id)
        # Capture only relationships reachable from these authorized bill roots.
        hints = []
        for index, record in enumerate(context[:LIMIT], 1):
            edges = [["bill", "awaits", "approval_step"], ["approval_step", "assigned_role", record["step_role"]]]
            if record["graph_link"]:
                edges.append(["supplier", "has_bill", "bill"])
            if record["latest_action"]:
                edges.append(["bill", "has_history", "approval_event"])
            hints.append({"citation": index, "relationships": edges})
        try:
            route = await asyncio.wait_for(complete_json(
                tenant_id=identity[0], purpose="finance_copilot_intent",
                system="Classify the question. Return JSON with intent queue, overdue, relationships or unsupported. "
                       "Only general pending approval queue, overdue pending bills, or supplier links of pending bills "
                       "are supported. Specific invoice references without an attached bill, amounts, time ranges, "
                       "actions and unrelated questions are unsupported. Choose an optional citation index and focus "
                       "(stage, supplier or last_action) from the authorized graph context. Never invent a citation.",
                user=json.dumps({"question": body.question, "graph_context": hints, "attached_bill": bool(body.bill_id)}), schema=Intent.model_json_schema(), max_tokens=40), timeout=12)
            routed = Intent.model_validate(route.content)
            intent = routed.intent
            if 1 <= routed.citation <= len(hints):
                selection = (context[routed.citation-1]["id"], routed.focus)
        except (LLMError, LLMRefused, ValueError, TimeoutError):
            intent = "unsupported"
    if intent=="unsupported":
        return dict(answer="Choose an approval queue, overdue bills, or supplier relationships question below.",
                    intent=intent, evidence=[], partial=False)
    rows = await asyncio.to_thread(retrieve, identity, intent, body.bill_id)
    return grounded_answer(identity, intent, body.bill_id, rows, selection)
