"""Cash forecast against a real PostgreSQL: live SQL sources, persistence, plans.

Runs only when CF_TEST_DB_URL points at a THROWAWAY database (its public schema
is dropped and recreated):

    createdb cf_test
    CF_TEST_DB_URL=postgresql://localhost/cf_test python3.12 -m pytest tests/test_cash_forecast_db.py

The synthetic books from docs/cashflow-forecast/dummy-data/seed are loaded into
minimal copies of the real source tables, so the live adapters must reproduce
the same golden forecast as the fixture path.
"""

import json
import os
from datetime import date

import psycopg2
import pytest
from psycopg2.extras import Json, RealDictCursor

DB_URL = os.getenv("CF_TEST_DB_URL")
pytestmark = pytest.mark.skipif(not DB_URL, reason="CF_TEST_DB_URL not set")

from backend_ocr.app.cashflow import scenario as sc  # noqa: E402
from backend_ocr.app.cashflow import service as svc  # noqa: E402
from backend_ocr.app.cashflow.demo import seed_inputs  # noqa: E402
from backend_ocr.app.cashflow.schema import DDL, PUBLISH_INDEX  # noqa: E402
from backend_ocr.app.cashflow.sources import SEED_DIR  # noqa: E402

GOLDEN = json.loads((SEED_DIR / "expected_forecast.json").read_text())
TENANT = GOLDEN["tenant_id"]
OTHER = "00000000-0000-4000-8000-000000000999"
TODAY = date(2026, 11, 21)

SOURCE_DDL = """
CREATE TABLE dim_bank_accounts (bank_account_id uuid PRIMARY KEY, tenant_id uuid, account_name text, source_account_id text,
    account_type text, currency_code char(3), is_primary bool, is_active bool);
CREATE TABLE stg_bank_statements (tenant_id uuid, bank_account_id uuid, transaction_date date, running_balance numeric(18,4),
    source_updated_at timestamptz DEFAULT now());
CREATE TABLE dim_suppliers (tenant_id uuid, supplier_id uuid, name text);
CREATE TABLE stg_bills (tenant_id uuid, stg_bill_id uuid, validation_flag text, tds_amount numeric(14,2), net_payable numeric(14,2));
CREATE TABLE fact_invoices (invoice_id uuid PRIMARY KEY, tenant_id uuid, stg_bill_id uuid, supplier_id uuid, invoice_number text,
    due_date date, status text, payment_status text, soft_status text, currency_code char(3), total_amount numeric(18,4),
    amount_paid numeric(18,4), outstanding_amount numeric(18,4), invoice_type text);
CREATE TABLE payment_schedules (schedule_id uuid, tenant_id uuid, cycle_type text, stg_bill_id uuid, due_date date,
    scheduled_amount numeric(18,4), paid_amount numeric(18,4), status text);
CREATE TABLE fact_disbursements (disbursement_id uuid, tenant_id uuid, invoice_id uuid, amount numeric, status text,
    updated_at timestamptz);
CREATE TABLE ar_customers (id uuid PRIMARY KEY, tenant_id uuid, name text, tds_rate_hint numeric(6,3));
CREATE TABLE ar_invoices (id uuid PRIMARY KEY, tenant_id uuid, customer_id uuid, invoice_number text, due_date date,
    currency char(3), taxable_amount numeric(18,2), total_amount numeric(18,2), amount_received numeric(18,2),
    tds_amount numeric(18,2), deduction_amount numeric(18,2),
    outstanding numeric(18,2) GENERATED ALWAYS AS (total_amount - amount_received - tds_amount - deduction_amount) STORED,
    status text, paid_at timestamptz);
CREATE TABLE ar_payments (id uuid, tenant_id uuid, received_on date, status text, suggestion jsonb);
CREATE TABLE fact_cashflow_daily (cashflow_id uuid, tenant_id uuid, cashflow_date date, currency_code char(3),
    inflows_actual numeric(18,4), outflows_actual numeric(18,4), inflows_forecast numeric(18,4), outflows_forecast numeric(18,4),
    opening_balance numeric(18,4), closing_balance numeric(18,4), ar_outstanding numeric(18,4), ap_outstanding numeric(18,4),
    updated_at timestamptz);
"""


def seed(name):
    return json.loads((SEED_DIR / name).read_text())


def rupees(p):
    return None if p is None else p / 100


def load_books(cur):
    for a in seed("bank_accounts.json"):
        cur.execute("INSERT INTO dim_bank_accounts VALUES (%s, %s, %s, %s, %s, 'INR', %s, true)",
                    (a["bank_account_id"], TENANT, a["account_name"], a["account_mask"], a["account_type"], a["is_primary"]))
    for b in seed("bank_balances.json"):
        cur.execute("INSERT INTO stg_bank_statements VALUES (%s, %s, '2026-11-20', %s)",
                    (TENANT, b["bank_account_id"], rupees(b["balance_paise"])))
    for s in seed("suppliers.json"):
        cur.execute("INSERT INTO dim_suppliers VALUES (%s, %s, %s)", (TENANT, s["supplier_id"], s["name"]))
    for b in seed("ap_bills.json"):
        cur.execute("INSERT INTO stg_bills VALUES (%s, %s, %s, %s, %s)",
                    (TENANT, b["stg_bill_id"], b["validation_flag"], rupees(b["tds_amount_paise"]), rupees(b["net_payable_paise"])))
        cur.execute("INSERT INTO fact_invoices VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'AP')",
                    (b["invoice_id"], TENANT, b["stg_bill_id"], b["supplier_id"], b["bill_number"], b["due_date"], b["status"],
                     b["payment_status"], b["soft_status"], b["currency_code"], rupees(b["total_amount_paise"]),
                     rupees(b["amount_paid_paise"]), rupees(b["outstanding_amount_paise"])))
    for s in seed("payment_schedules.json"):
        cur.execute("INSERT INTO payment_schedules VALUES (%s, %s, 'PAYABLE', %s, %s, %s, %s, %s)",
                    (s["schedule_id"], TENANT, s["stg_bill_id"], s["due_date"], rupees(s["scheduled_amount_paise"]),
                     rupees(s["paid_amount_paise"]), s["status"]))
    for d in seed("disbursements.json"):
        cur.execute("INSERT INTO fact_disbursements VALUES (%s, %s, %s, %s, %s, now() - interval '2 days')",
                    (d["disbursement_id"], TENANT, d["invoice_id"], rupees(d["amount_paise"]), d["status"]))
    for c in seed("customers.json"):
        cur.execute("INSERT INTO ar_customers VALUES (%s, %s, %s, %s)", (c["id"], TENANT, c["name"], c["tds_rate_hint"]))
    for i in seed("ar_invoices.json"):
        # paid_at at midday IST so the local paid date is the seed's date.
        cur.execute("INSERT INTO ar_invoices (id, tenant_id, customer_id, invoice_number, due_date, currency, taxable_amount, "
                    "total_amount, amount_received, tds_amount, deduction_amount, status, paid_at) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (i["id"], TENANT, i["customer_id"], i["invoice_number"], i["due_date"], i["currency"],
                     rupees(i["taxable_amount_paise"]), rupees(i["total_amount_paise"]), rupees(i["amount_received_paise"]),
                     rupees(i["tds_amount_paise"]), rupees(i["deduction_amount_paise"]), i["status"], i["paid_at"]))
    for p in seed("ar_payments.json"):
        cur.execute("INSERT INTO ar_payments VALUES (%s, %s, %s, %s, %s)",
                    (p["id"], TENANT, p["received_on"], p["status"], Json(p.get("suggestion"))))


@pytest.fixture(scope="module")
def db():
    conn = psycopg2.connect(DB_URL)
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
        cur.execute(SOURCE_DDL)
        for stmt in DDL:
            cur.execute(stmt)
        cur.execute(PUBLISH_INDEX)
        load_books(cur)
        seed_inputs(cur, TENANT)
    conn.commit()
    conn.close()
    return DB_URL


@pytest.fixture(autouse=True)
def wire(db, monkeypatch):
    monkeypatch.setattr(svc, "get_conn", lambda: psycopg2.connect(db))
    monkeypatch.setattr(svc, "put_conn", lambda conn, close=False: conn.close())
    monkeypatch.setattr(svc, "today_for", lambda tenant, settings: TODAY)
    monkeypatch.delenv("CASH_FORECAST_FIXTURE_TENANTS", raising=False)
    svc.repo._CACHE.clear()


def sql(q, params=()):
    with psycopg2.connect(DB_URL) as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(q, params)
        return cur.fetchall() if cur.description else None


def metrics_of(result):
    m = result["metrics"]
    return m["minimum_closing_paise"], m["minimum_date"], m["first_reserve_breach_date"]


PLAN_SHIFTS = GOLDEN["scenarios"]["defer_windowed_bills"]["overrides"]


def shifts(mapping=PLAN_SHIFTS):
    return [sc.ShiftEvent(op="shift_event", event_key=k, to_date=date.fromisoformat(v)) for k, v in mapping.items()]


def test_01_live_sources_reproduce_golden():
    snap, changed = svc.build(TENANT, "acct")
    assert changed and snap.revision == 1
    assert snap.coverage["state"] == "complete"
    for view in ("expected", "downside", "no_collections"):
        out = svc.forecast(TENANT, snap.snapshot_id, view)
        g = GOLDEN["views"][view]
        assert [d["closing_paise"] for d in out["days"]] == [d["closing_paise"] for d in g["days"]]
        assert out["metrics"]["minimum_closing_paise"] == g["minimum_closing_paise"]
        assert out["category_totals"] == GOLDEN["category_totals"][view]
    assert sorted(x["reason"] for x in svc.exclusions(TENANT, snap.snapshot_id)) == \
        sorted(x["reason"] for x in GOLDEN["exclusions"])


def test_02_refresh_without_changes_is_a_noop_and_published():
    snap, changed = svc.build(TENANT, "acct")
    assert (changed, snap.revision) == (False, 1)
    rows = sql("SELECT count(*) n, min(closing_balance) lo FROM fact_cashflow_daily WHERE tenant_id = %s", (TENANT,))
    assert rows[0]["n"] == 30 and float(rows[0]["lo"]) == GOLDEN["views"]["expected"]["minimum_closing_paise"] / 100


def test_03_other_tenant_sees_nothing():
    with pytest.raises(svc.CFError) as e:
        svc.snapshot(OTHER, svc.latest(TENANT, "acct").snapshot_id)
    assert e.value.status == 404


def test_04_preview_and_refusal():
    snap = svc.latest(TENANT, "acct")
    out = svc.preview(TENANT, snap.snapshot_id, snap.revision, "expected", shifts())
    assert metrics_of(out["scenario"]) == (191370024, "2026-11-23", None)
    raigad = [k for k, v in PLAN_SHIFTS.items() if v == "2026-12-02"][0]
    with pytest.raises(svc.CFError) as e:
        svc.preview(TENANT, snap.snapshot_id, snap.revision, "expected", shifts({raigad: "2026-12-03"}))
    assert e.value.code == "OVERRIDE_REFUSED"
    assert e.value.details["refusals"][0]["code"] == "OUTSIDE_PAYMENT_WINDOW"
    payroll = next(e.event_key for e in snap.events if e.category == "payroll")
    with pytest.raises(svc.CFError) as e:
        svc.preview(TENANT, snap.snapshot_id, snap.revision, "expected", shifts({payroll: "2026-12-01"}))
    assert e.value.details["refusals"][0]["code"] == "FIXED_OBLIGATION"


def make_plan(name="Defer three windowed supplier payments", actor="acct"):
    snap = svc.latest(TENANT, actor)
    scen = svc.save_scenario(TENANT, actor, {"name": name, "description": None, "snapshot_id": snap.snapshot_id,
                                             "view": "expected", "overrides": shifts()})
    return svc.create_plan(TENANT, actor, scen["id"], "Suppliers agreed in writing.", True)


def test_05_self_approval_refused_and_idempotent_approval():
    plan = make_plan()
    assert plan["state"] == "submitted" and plan["metrics"]["minimum_closing_paise"] == 191370024
    with pytest.raises(svc.CFError) as e:
        svc.decide(TENANT, "acct", plan["id"], "approve", 1, None, "key-self-0001")
    assert e.value.code == "SELF_APPROVAL"
    first = svc.decide(TENANT, "owner", plan["id"], "approve", 1, "Go ahead", "key-approve-0001")
    again = svc.decide(TENANT, "owner", plan["id"], "approve", 1, "Go ahead", "key-approve-0001")
    assert first == again and first["plan"]["state"] == "approved"
    with pytest.raises(svc.CFError) as e:
        svc.decide(TENANT, "owner", plan["id"], "return", 1, "changed my mind", "key-approve-0001")
    assert e.value.code == "IDEMPOTENCY_CONFLICT"
    assert sql("SELECT count(*) n FROM cf_plan_decisions WHERE plan_id = %s", (plan["id"],))[0]["n"] == 1


def test_06_approved_decisions_become_planned_dates():
    snap, changed = svc.build(TENANT, "acct")
    assert changed and snap.revision == 2
    for key, day in PLAN_SHIFTS.items():
        e = snap.event(key)
        assert e.dates.expected.isoformat() == day and e.date_basis["expected"].startswith("Approved plan: pay")
    out = svc.forecast(TENANT, snap.snapshot_id, "expected")
    assert metrics_of(out) == (191370024, "2026-11-23", None)


def test_07_stale_plan_is_refused_but_irrelevant_changes_revalidate():
    plan = make_plan("Second plan")
    # A change that only touches an excluded record: new revision, same metrics → approved on the new revision.
    sql("UPDATE stg_bills SET net_payable = net_payable + 1 WHERE validation_flag = 'DUPLICATE'")
    ok = svc.decide(TENANT, "owner", plan["id"], "approve", 1, None, "key-approve-0002")
    assert ok["plan"]["state"] == "approved" and ok["validated_on_revision"] > plan["revision"]
    assert sql("SELECT state FROM cf_plans WHERE state = 'superseded'")[0]["state"] == "superseded"

    plan3 = make_plan("Third plan")
    # A change the plan's numbers depend on: ₹1,000 more payroll moves the closing balance.
    sql("UPDATE cf_recurring_items SET amount_paise = amount_paise + 100000 WHERE category = 'payroll'")
    with pytest.raises(svc.CFError) as e:
        svc.decide(TENANT, "owner", plan3["id"], "approve", 1, None, "key-approve-0003")
    assert e.value.code == "PLAN_STALE"
    assert e.value.details["submitted"]["closing_paise"] - e.value.details["now"]["closing_paise"] == 100000


def test_08_return_needs_a_note():
    plan = make_plan("Fourth plan")
    with pytest.raises(svc.CFError) as e:
        svc.decide(TENANT, "owner", plan["id"], "return", 1, "  ", "key-return-0001")
    assert e.value.code == "VALIDATION_ERROR"
    out = svc.decide(TENANT, "owner", plan["id"], "return", 1, "Ask Indus for a later date too", "key-return-0002")
    assert out["plan"]["state"] == "returned"
    detail = svc.get_plan(TENANT, plan["id"])
    assert [h["action"] for h in detail["history"]] == ["submit", "returned"]


def test_09_day_detail_sums_to_the_row():
    snap = svc.latest(TENANT, "acct")
    d = svc.day_detail(TENANT, snap.snapshot_id, "expected", date(2026, 11, 30))
    assert sum(e["amount_paise"] for e in d["inflows"]) == d["day"]["inflow_paise"]
    assert sum(e["amount_paise"] for e in d["outflows"]) == d["day"]["outflow_paise"]
