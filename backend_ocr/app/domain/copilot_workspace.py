"""Tenant- and license-scoped relational projections for the application Copilot.

Only the static source catalog below can supply SQL fragments. Retrieved entities
carry their source, relationship, authorization boundary and navigation target.
"""
from dataclasses import dataclass
from functools import lru_cache
import json
import time

from psycopg2.extras import RealDictCursor
from ..config import get_conn, put_conn
from ..routers.copilot import verify_actor, retrieve, grounded_answer


@dataclass(frozen=True)
class Source:
    service: str
    path: str
    sql: str
    roles: tuple = ("admin", "accountant", "finance_controller", "auditor")


ADMIN = ("admin",)
FINANCE = ("admin", "finance_controller")
SOURCES = {
    "vendors": Source("vendors", "/vendors", "SELECT supplier_id id,name title,status,payment_terms_days FROM dim_suppliers WHERE tenant_id=%s"),
    "receivables": Source("receivables", "/receivables/invoices", """SELECT a.id,a.invoice_number title,a.status,a.currency,a.outstanding,a.due_date,c.name customer
        FROM ar_invoices a LEFT JOIN ar_customers c ON (c.tenant_id,c.id)=(a.tenant_id,a.customer_id) WHERE a.tenant_id=%s"""),
    "cash_application": Source("receivables","/receivables/cash-application","SELECT id,coalesce(reference,id::text) title,status,currency,amount,applied_amount,received_on FROM ar_payments WHERE tenant_id=%s"),
    "cash_forecast": Source("reports","/reports","SELECT cashflow_id id,cashflow_date::text title,currency_code,opening_balance,closing_balance,inflows_forecast,outflows_forecast FROM fact_cashflow_daily WHERE tenant_id=%s"),
    "inventory": Source("reports","/finance-desk/inventory","""SELECT l.line_item_id id,l.product_name title,l.unit,l.quantity,l.unit_price,b.currency_code,b.bill_number,b.bill_date
        FROM stg_bill_line_items l JOIN stg_bills b USING (tenant_id,stg_bill_id) WHERE l.tenant_id=%s AND l.quantity>0 AND l.unit_price>0"""),
    "reconciliation": Source("recon","/bills","""SELECT r.id,r.invoice_no title,r.status,r.money_at_risk,r.computed_at,p.po_number purchase_order
        FROM recon_cases r LEFT JOIN purchase_orders p ON (p.tenant_id,p.id)=(r.tenant_id,r.po_id) WHERE r.tenant_id=%s""", ("admin","finance_controller","accountant")),
    "purchases": Source("recon","/bills","SELECT id,po_number title,po_date,delivery_date,total,payment_terms FROM purchase_orders WHERE tenant_id=%s AND deleted_at IS NULL AND superseded_by IS NULL", ("admin","finance_controller","accountant")),
    "payments": Source("disbursement","/payments","SELECT disbursement_id id,disbursement_id::text title,status,amount,created_at FROM fact_disbursements WHERE tenant_id=%s", FINANCE),
    "ledger": Source("ledger","/reports","SELECT account_id id,account_name title,account_type,account_code FROM dim_ledger_accounts WHERE tenant_id=%s AND is_active"),
    "tax": Source("tds","/settings","SELECT ledger_id id,tds_section_code title,fiscal_year,ytd_base_amount,ytd_tds_deducted,threshold_crossed FROM fact_tds_ledger WHERE tenant_id=%s", FINANCE),
    "fx": Source("fx","/reports","SELECT payment_id id,payment_date::text title,currency_code,foreign_amount,actual_inr,effective_rate FROM fx_bill_payments WHERE tenant_id=%s", FINANCE),
    "nova": Source("nova_billing","/nova","SELECT run_id id,vendor_name title,billing_month,status,total_invoice_amount,variance_amount FROM billing_reconciliation_runs WHERE tenant_id=%s", FINANCE),
    "brands": Source("brands","/settings","SELECT id,name title,is_default FROM brands WHERE tenant_id=%s", ADMIN),
    "integrations": Source("accounting_api_sync","/integrations","SELECT connection_id id,source::text title,status,last_sync_at FROM int_connections WHERE tenant_id=%s AND source::text ILIKE '%%apideck%%'", ADMIN),
    "review": Source("review_hub","/review","SELECT finding_id id,title,severity,status,subject_type,verification,money_at_risk,money_currency FROM rh_findings WHERE tenant_id=%s", ("admin","finance_controller","auditor")),
    "uploads": Source("upload_ocr","/upload","SELECT upload_id id,file_name title,file_type,status,created_at FROM raw_invoice_uploads WHERE tenant_id=%s", ("admin","finance_controller","accountant")),
    "vendor_verification": Source("kyc_verification","/vendors","SELECT supplier_id id,name title,bank_verified,status FROM dim_suppliers WHERE tenant_id=%s", FINANCE),
    "sap_catalog": Source("sap_matching","/vendors","SELECT catalog_id id,material_desc title,item_code,hsn_code FROM sap_item_catalog WHERE tenant_id=%s AND is_active", FINANCE),
    "tally": Source("tally_connector","/integrations","SELECT connection_id id,source::text title,status,last_sync_at FROM int_connections WHERE tenant_id=%s AND source::text ILIKE '%%tally%%'", ADMIN),
    "approval_configuration": Source("settings","/settings","SELECT id,label title,step_order,role,department FROM tenant_chain_config WHERE tenant_id=%s AND is_snapshot=false", ADMIN),
    "automation": Source("agent_hub","/agent-hub","SELECT tenant_id id,'Agent settings' title,enabled,updated_at FROM agent_settings WHERE tenant_id=%s", ADMIN),
    "team": Source("users","/settings","SELECT id,username title,role,department FROM users WHERE company_id=%s", ADMIN),
}
MODEL = "gpt-6-luna"


def access(cur, identity):
    verify_actor(cur, *identity, services=("fact_graph",))
    cur.execute("""SELECT c.service_key FROM service_catalog c LEFT JOIN tenant_service t
        ON t.service_key=c.service_key AND t.tenant_id=%s WHERE c.retired_at IS NULL
        AND coalesce(t.enabled,c.default_enabled)""", (identity[0],))
    enabled = {r["service_key"] for r in cur.fetchall()}
    return sorted([k for k,s in SOURCES.items() if identity[2] in s.roles and s.service in enabled]
                  + (["bills","approvals"] if {"bills","approvals"} <= enabled else []))


@lru_cache(maxsize=128)
def serialize_projection(identity, revision_window, encoded):
    # Keyed by actor and exact reauthorized source values; no prompts or uploads.
    rows = json.loads(encoded)
    return json.dumps(rows, ensure_ascii=False, separators=(",", ":"))


def workspace(identity, domains=(), search="", overview=False):
    conn = get_conn()
    evidence = []
    try:
        with conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            cur.execute("SET LOCAL statement_timeout='5s'")
            allowed = access(cur, identity)
            chosen = allowed if overview else [k for k in domains if k in allowed]
            modules = [(k,SOURCES[k]) for k in chosen if k in SOURCES]
            if overview and modules:
                sql = " UNION ALL ".join("SELECT %s AS domain,count(*) AS records FROM ("+s.sql+") q" for k,s in modules)
                params = [value for k,s in modules for value in (k,identity[0])]
                cur.execute(sql,params)
                for row in cur.fetchall():
                    k=row["domain"]
                    evidence.append(dict(domain=k,title=k.replace("_"," "),path=SOURCES[k].path,records=row["records"]))
            elif modules:
                for key,source in modules:
                    totals = {
                        "receivables": ",sum(outstanding) OVER(PARTITION BY currency) AS matched_outstanding_in_currency",
                        "cash_application": ",sum(amount) OVER(PARTITION BY currency) AS matched_receipts_in_currency",
                    }.get(key, "")
                    cur.execute("SELECT q.*,count(*) OVER() AS matching_records"+totals+" FROM ("+source.sql+
                                ") q WHERE %s='' OR strpos(lower(to_jsonb(q)::text),lower(%s))>0 ORDER BY id LIMIT 8",
                                (identity[0],search,search))
                    rows = cur.fetchall()
                    for r in rows:
                        rid = str(r.pop("id"))
                        path = source.path + "/" + rid if key in {"vendors","receivables"} else source.path
                        evidence.append(dict(domain=key,path=path,**r))
                    if not rows:
                        evidence.append(dict(domain=key,title=key.replace("_"," "),path=source.path,matching_records=0))
    finally:
        put_conn(conn)
    for key in chosen:
        if key in {"bills","approvals"}:
            intent = "queue" if key=="approvals" else "records"
            rows = retrieve(identity,intent,search=search)
            for row in grounded_answer(identity,intent,None,rows)["evidence"][:8]:
                evidence.append(dict(domain=key,title=row["invoice_number"] or row["id"],path=row["path"],
                    supplier=row["supplier"], supplier_graph_link=row["graph_link"],stage=row["stage"],
                    amount=row["total_amount"],currency=row["currency_code"],due=row["due_date"],last_action=row["latest_action"]))
            if not rows:
                evidence.append(dict(domain=key,title=key,path="/bills",matching_records=0))
    for record in evidence:
        edges = []
        for field,relation in (("supplier","issued_by"),("customer","billed_to"),("purchase_order","matches_order"),
                               ("bill_number","from_invoice"),("stage","at_approval_step")):
            if record.get(field):
                edges.append({"relation":relation,"target":record[field]})
        if edges:
            record["relationships"]=edges
    encoded = json.dumps(evidence,default=str,sort_keys=True,ensure_ascii=False)
    return allowed, json.loads(serialize_projection(identity,int(time.monotonic()//90),encoded))
