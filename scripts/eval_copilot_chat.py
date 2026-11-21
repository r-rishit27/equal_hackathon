"""Evaluate local finance answers against independent SQL. Never send tenant records to a model."""
import argparse
import asyncio
import json
from pathlib import Path
import sys
from time import perf_counter
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend_ocr"))
from fastapi import Response
from app.config import get_conn, put_conn
from app.routers import copilot_chat
from app.security import auth


def query(sql, params):
    conn = get_conn()
    try:
        with conn, conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()
    finally:
        put_conn(conn)


async def evaluate(name):
    users = query("SELECT company_id,username,role FROM users WHERE name=%s", (name,))
    if len(users) != 1:
        raise SystemExit("Evaluation requires a unique workspace user.")
    tenant, username, role = users[0]
    auth._current_tenant.set(tenant)
    auth._current_role.set(role)
    auth._current_user.set(username)
    cases = [
        ("How many vendors are in my workspace?", "vendors", "SELECT count(*) FROM dim_suppliers WHERE tenant_id=%s"),
        ("How many priced inventory lines with positive quantity are there?", "inventory",
         "SELECT count(*) FROM stg_bill_line_items l JOIN stg_bills b USING(tenant_id,stg_bill_id) WHERE l.tenant_id=%s AND l.quantity>0 AND l.unit_price>0"),
        ("Which pending bills are overdue?", "approvals", None),
        ("Show supplier relationships for pending bills.", "approvals", None),
    ]
    passed = 0
    for question, domain, sql in cases:
        start = perf_counter()
        with patch.object(copilot_chat, "completion", AsyncMock(side_effect=copilot_chat.LLMRefused("local evaluation"))):
            response = Response()
            reply = await copilot_chat.chat(response, json.dumps({"question": question}), None)
        sources = reply["sources"]
        message = reply["message"]
        valid = bool(sources) and all(s["domain"] == domain for s in sources)
        if sql:
            expected = query(sql, (tenant,))[0][0]
            valid &= f"{expected} matching records" in message
            valid &= any(s["values"].get("matching_records") == expected for s in sources)
        else:
            for source in sources:
                if source["values"].get("matching_records") == 0:
                    valid = False  # No live row available to verify this case.
                    continue
                row = query("""SELECT fi.invoice_number, fi.due_date < (now() AT TIME ZONE 'Asia/Kolkata')::date,
                    EXISTS(SELECT FROM fact_graph_nodes v JOIN fact_graph_edges e ON e.tenant_id=v.tenant_id AND e.src_node_id=v.node_id
                    JOIN fact_graph_nodes b ON b.tenant_id=e.tenant_id AND b.node_id=e.dst_node_id
                    WHERE v.tenant_id=fi.tenant_id AND v.ref_id=fi.supplier_id AND v.node_type='vendor' AND b.node_type='bill'
                    AND b.ref_id=fi.invoice_id AND e.relation='has_bill')
                    FROM fact_invoices fi WHERE fi.tenant_id=%s AND fi.invoice_id=%s""", (tenant,source["path"].split("/")[-1]))
                valid &= bool(row) and row[0][0] in message
                if row:
                    valid &= bool(row[0][1]) if "overdue" in question else row[0][2] == source["values"]["supplier_graph_link"]
        valid &= all("[" + s["id"] + "]" in message for s in sources)
        passed += int(valid)
        print(f"{'PASS' if valid else 'FAIL'} | {question} | {len(sources)} sources | {perf_counter()-start:.1f}s including SQL audit | {response.headers.get('Server-Timing','')}", flush=True)
    print(f"Local answer checks: {passed}/{len(cases)}")
    return passed == len(cases)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--display-name", required=True)
    raise SystemExit(0 if asyncio.run(evaluate(parser.parse_args().display_name)) else 1)
