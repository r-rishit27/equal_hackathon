"""Where the forecast's rows come from.

Two parts, kept separate on purpose:

* **Books** — what Reckon.ai already records: bank accounts and statement
  balances, AP bills, payment schedules, payouts, AR invoices, payment history,
  unapplied receipts. Read live from PostgreSQL (`load_books_live`) or, for the
  synthetic demo tenant and tests, from the seed JSON (`load_books_fixture`).
* **Inputs** — what the business tells the forecast: settings, holidays,
  account choices, manual balances, recurring items, adjustments, payment
  windows, promises, approved planned dates. Always the cf_* tables
  (`load_inputs`), or the seed JSON in pure tests (`load_inputs_fixture`).

Every query filters on the authenticated tenant and uses bound parameters.
"""

from __future__ import annotations

import json
import os
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from .rules import Settings, SourceData
from .types import to_paise

SEED_DIR = Path(__file__).resolve().parents[3] / "docs" / "cashflow-forecast" / "dummy-data" / "seed"
FIXTURE_ENV = "CASH_FORECAST_FIXTURE_TENANTS"


def fixture_tenants() -> set[str]:
    return {t.strip() for t in os.getenv(FIXTURE_ENV, "").split(",") if t.strip()}


# Tenants whose *live* forecast also gets the seed's synthetic receivables, so a
# demo workspace with real bills but no sales ledger still shows collections and
# the collection model's predicted payment dates. Never set for a real customer.
DEMO_COLLECTIONS_ENV = "CASH_FORECAST_DEMO_COLLECTIONS_TENANTS"


def demo_collection_tenants() -> set[str]:
    return {t.strip() for t in os.getenv(DEMO_COLLECTIONS_ENV, "").split(",") if t.strip()}


def add_demo_collections(data: SourceData, today: date, seed_dir=SEED_DIR) -> None:
    """Give a demo workspace believable money coming in, on top of its real books.

    Three parts, all labelled "(demo)" and all in memory only — nothing is
    written to the database, so switching the tenant off removes every trace:

    1. **Receipts clearing on the first banking day**, sized to the bills
       already overdue (the forecast pays those on day one) less the opening
       cash, plus about today's cash again — so day one does not start in a hole.
    2. **The seed's customers' invoices**, dates moved by (today − the seed's own
       today) so each keeps its place relative to now, amounts scaled to the
       workspace; their paid history teaches the collection model each
       customer's habits, which is what dates the expected/downside receipts.
    3. **The seed's recurring costs** (payroll, GST, rent, …) at the same scale,
       so the line dips and recovers rather than only climbing.
    """
    shift = today - fixture_today(seed_dir)
    start = today + timedelta(days=1)
    customers = {c["id"]: c for c in _seed("customers.json", seed_dir)}
    ar = _seed("ar_invoices.json", seed_dir)
    open_ar = [i for i in ar if i["status"] in ("open", "partially_paid", "disputed")]
    seed_open = sum(int(i["outstanding_paise"]) for i in open_ar) or 1

    live_bills = [b for b in data.bills
                  if b.get("payment_status") != "paid" and b.get("soft_status", "active") == "active"
                  and b.get("status") not in ("DRAFT", "REJECTED", "VOID", "CANCELLED")
                  and b.get("validation_flag") != "DUPLICATE" and (b.get("currency") or "INR") == "INR"]
    payables = sum(max(0, int(b.get("outstanding_paise") or 0)) for b in live_bills)
    overdue = sum(max(0, int(b.get("outstanding_paise") or 0)) for b in live_bills
                  if b.get("due_date") is not None and b["due_date"] < start)
    inflight = sum(int(d.get("amount_paise") or 0) for d in data.disbursements
                   if d.get("status") in ("PENDING", "PENDING_OTP", "PROCESSING", "INITIATED"))
    included = {str(a["bank_account_id"]) for a in data.accounts if a.get("include")}
    opening = sum(int(b["balance_paise"]) for b in data.balances if str(b["bank_account_id"]) in included)

    # Receivables sized to the workspace: the bills not already covered by (1),
    # and never smaller than the seed itself.
    scale = max(1.0, (payables - overdue) * 1.5 / seed_open, opening * 0.5 / seed_open)

    def amt(p):
        return int(int(p or 0) * scale) // 100 * 100   # whole rupees

    # (1) as a receivable from a customer who always pays on the due date, so
    # the collection model lands it on day one in the expected and downside
    # views while "no new collections" stays the honest stress case it is.
    cushion = max(50_00_000_00, opening)                 # start the month near today's cash
    clearing = (max(0, overdue + inflight - opening) + cushion) // 100 * 100
    payer = "00000000-0000-4000-8000-00000000d3e1"
    data.ar_open.append(dict(
        id="00000000-0000-4000-8000-00000000d3e0", customer_id=payer, customer_name="Receipts clearing (demo)",
        invoice_number="DEMO-CLEARING", due_date=start, status="open", currency="INR",
        taxable_paise=0, tds_paise=0, outstanding_paise=clearing, tds_rate_hint=None))
    data.ar_history.extend((payer, start - timedelta(days=30 * k), start - timedelta(days=30 * k)) for k in range(1, 13))

    for i in open_ar:
        data.ar_open.append(dict(
            id=i["id"], customer_id=i["customer_id"], customer_name=f"{i['customer_name']} (demo)",
            invoice_number=i["invoice_number"], due_date=_d(i["due_date"]) + shift, status=i["status"],
            currency=i["currency"], taxable_paise=amt(i["taxable_amount_paise"]), tds_paise=amt(i["tds_amount_paise"]),
            outstanding_paise=amt(i["outstanding_paise"]), tds_rate_hint=customers[i["customer_id"]]["tds_rate_hint"]))
    data.ar_history.extend((i["customer_id"], _d(i["due_date"]) + shift, _d(i["paid_at"]) + shift)
                           for i in ar if i["status"] == "paid" and i["paid_at"])

    have = {str(r.get("id")) for r in data.recurring}
    for r in _seed("recurring_items.json", seed_dir):
        if str(r["id"]) in have:
            continue
        data.recurring.append(dict(r, name=f"{r['name']} (demo)", amount_paise=amt(r["amount_paise"]),
                                   start_date=_d(r["start_date"]), end_date=_d(r["end_date"]), active=True))


def uses_fixture(tenant_id: str) -> bool:
    """Synthetic-demo tenants read their *books* from the seed files (inputs stay in cf_*)."""
    return str(tenant_id) in fixture_tenants() and SEED_DIR.exists()


def _d(v):
    return v if isinstance(v, date) or v is None else date.fromisoformat(str(v)[:10])


def _ts(v):
    return v if isinstance(v, datetime) else datetime.fromisoformat(str(v))


# ── Fixture (seed JSON) ─────────────────────────────────────────────────────
def _seed(name, seed_dir=SEED_DIR):
    return json.loads((Path(seed_dir) / name).read_text())


def fixture_today(seed_dir=SEED_DIR) -> date:
    """The synthetic tenant is always viewed on the morning after its balance."""
    return _ts(_seed("bank_balances.json", seed_dir)[0]["as_of"]).date() + timedelta(days=1)


def load_books_fixture(seed_dir=SEED_DIR) -> SourceData:
    customers = {c["id"]: c for c in _seed("customers.json", seed_dir)}
    ar = _seed("ar_invoices.json", seed_dir)
    data = SourceData()
    data.accounts = [dict(bank_account_id=a["bank_account_id"], account_name=a["account_name"],
                          account_mask=a["account_mask"], account_type=a["account_type"],
                          include=a["include_in_forecast"], od_limit_paise=a["od_limit_paise"])
                     for a in _seed("bank_accounts.json", seed_dir)]
    data.balances = [dict(bank_account_id=b["bank_account_id"], balance_paise=b["balance_paise"],
                          as_of=_ts(b["as_of"]), source="statement")
                     for b in _seed("bank_balances.json", seed_dir)]
    data.bills = [dict(invoice_id=b["invoice_id"], stg_bill_id=b["stg_bill_id"], supplier_id=b["supplier_id"],
                       supplier_name=b["supplier_name"], bill_number=b["bill_number"], due_date=_d(b["due_date"]),
                       status=b["status"], payment_status=b["payment_status"], validation_flag=b["validation_flag"],
                       soft_status=b["soft_status"], currency=b["currency_code"],
                       outstanding_paise=b["outstanding_amount_paise"], amount_paid_paise=b["amount_paid_paise"],
                       tds_paise=b["tds_amount_paise"], net_payable_paise=b["net_payable_paise"])
                  for b in _seed("ap_bills.json", seed_dir)]
    data.schedules = [dict(schedule_id=s["schedule_id"], stg_bill_id=s["stg_bill_id"], due_date=_d(s["due_date"]),
                           scheduled_paise=s["scheduled_amount_paise"], paid_paise=s["paid_amount_paise"], status=s["status"])
                      for s in _seed("payment_schedules.json", seed_dir)]
    data.disbursements = [dict(disbursement_id=d["disbursement_id"], invoice_id=d["invoice_id"],
                               amount_paise=d["amount_paise"], status=d["status"])
                          for d in _seed("disbursements.json", seed_dir)]
    data.ar_open = [dict(id=i["id"], customer_id=i["customer_id"], customer_name=i["customer_name"],
                         invoice_number=i["invoice_number"], due_date=_d(i["due_date"]), status=i["status"],
                         currency=i["currency"], taxable_paise=i["taxable_amount_paise"], tds_paise=i["tds_amount_paise"],
                         outstanding_paise=i["outstanding_paise"], tds_rate_hint=customers[i["customer_id"]]["tds_rate_hint"])
                    for i in ar if i["status"] in ("open", "partially_paid", "disputed")]
    data.ar_history = [(i["customer_id"], _d(i["due_date"]), _d(i["paid_at"]))
                       for i in ar if i["status"] == "paid" and i["paid_at"]]
    data.unapplied = {p["suggestion"]["invoice_id"]: dict(id=p["id"], received_on=_d(p["received_on"]))
                      for p in _seed("ar_payments.json", seed_dir)
                      if p["status"] in ("unmatched", "needs_review") and p.get("suggestion")
                      and p["suggestion"]["confidence"] >= 0.90}
    return data


def load_inputs_fixture(data: SourceData, seed_dir=SEED_DIR) -> Settings:
    """Pure-test path: inputs straight from the seed (no database)."""
    s = _seed("settings.json", seed_dir)
    settings = Settings.from_row({k: v for k, v in s.items() if k != "holiday_calendar"},
                                 {_d(h["date"]): h["name"] for h in s["holiday_calendar"]})
    data.windows = {w["invoice_id"]: dict(earliest=_d(w["earliest_date"]), latest=_d(w["latest_date"]),
                                          agreed_with=w["agreed_with"], evidence=w["evidence"])
                    for w in _seed("payment_windows.json", seed_dir)}
    data.promises = {p["invoice_id"]: dict(promised_date=_d(p["promised_date"]), promised_amount_paise=p["promised_amount_paise"])
                     for p in _seed("collection_promises.json", seed_dir)}
    data.recurring = [dict(r, start_date=_d(r["start_date"]), end_date=_d(r["end_date"]))
                      for r in _seed("recurring_items.json", seed_dir)]
    data.adjustments = [dict(a, on_date=_d(a["date"]), active=True) for a in _seed("adjustments.json", seed_dir)]
    return settings


# ── Live books (PostgreSQL) ─────────────────────────────────────────────────
def load_books_live(cur, tenant_id: str, tz_name: str = "Asia/Kolkata") -> SourceData:
    """Read Reckon.ai's own records. `cur` is a RealDictCursor in a read-only txn."""
    tz = ZoneInfo(tz_name)
    data = SourceData()

    def guarded(name, fn):
        try:
            cur.execute("SAVEPOINT cf_src")
            fn()
            cur.execute("RELEASE SAVEPOINT cf_src")
        except Exception:
            cur.execute("ROLLBACK TO SAVEPOINT cf_src")
            data.failed_sources.append(name)

    def accounts():
        cur.execute("""
            SELECT bank_account_id::text, account_name, source_account_id, account_type::text AS account_type
            FROM dim_bank_accounts
            WHERE tenant_id = %s AND is_active AND currency_code = 'INR'
            ORDER BY is_primary DESC, account_name""", (tenant_id,))
        for r in cur.fetchall():
            tail = "".join(ch for ch in (r["source_account_id"] or "") if ch.isdigit())[-4:]
            data.accounts.append(dict(bank_account_id=r["bank_account_id"], account_name=r["account_name"],
                                      account_mask=f"XX{tail}" if tail else None, account_type=r["account_type"],
                                      include=r["account_type"] in ("CURRENT", "SAVINGS"), od_limit_paise=0))
        cur.execute("""
            SELECT DISTINCT ON (s.bank_account_id) s.bank_account_id::text, s.running_balance, s.transaction_date
            FROM stg_bank_statements s
            WHERE s.tenant_id = %s AND s.bank_account_id IS NOT NULL AND s.running_balance IS NOT NULL
            ORDER BY s.bank_account_id, s.transaction_date DESC, s.source_updated_at DESC""", (tenant_id,))
        for r in cur.fetchall():
            as_of = datetime.combine(r["transaction_date"], time(23, 59, 59), tz)
            data.balances.append(dict(bank_account_id=r["bank_account_id"], balance_paise=to_paise(r["running_balance"]),
                                      as_of=as_of, source="statement"))

    def payment_hub_accounts():
        # The accounts Payment Hub pays from (one per bank, with the balance each
        # payment draws down). Without them a tenant with no imported bank master
        # has nothing to forecast from, and the two pages disagree about cash.
        known = {a["account_mask"] for a in data.accounts if a.get("account_mask")}
        cur.execute("""
            SELECT id::text, bank_name, bank_provider, account_number, balance
            FROM remitter_accounts WHERE tenant_id = %s ORDER BY created_at""", (tenant_id,))
        now = datetime.now(tz)
        for r in cur.fetchall():
            tail = "".join(ch for ch in (r["account_number"] or "") if ch.isdigit())[-4:]
            mask = f"XX{tail}" if tail else None
            if mask and mask in known:
                continue  # same account already comes from the bank master
            data.accounts.append(dict(bank_account_id=r["id"], account_name=r["bank_name"], account_mask=mask,
                                      account_type="CURRENT", include=True, od_limit_paise=0))
            data.balances.append(dict(bank_account_id=r["id"], balance_paise=to_paise(r["balance"]),
                                      as_of=now, source="payment_hub"))

    def payables():
        cur.execute("""
            SELECT fi.invoice_id::text, fi.stg_bill_id::text, fi.supplier_id::text, coalesce(s.name, 'Supplier') AS supplier_name,
                   fi.invoice_number AS bill_number, fi.due_date, fi.status::text AS status,
                   coalesce(fi.payment_status, 'unpaid') AS payment_status, fi.soft_status, fi.currency_code,
                   fi.total_amount, fi.amount_paid, coalesce(fi.outstanding_amount, fi.total_amount - fi.amount_paid) AS outstanding,
                   coalesce(sb.validation_flag::text, 'OK') AS validation_flag, coalesce(sb.tds_amount, 0) AS tds_amount,
                   sb.net_payable
            FROM fact_invoices fi
            LEFT JOIN stg_bills sb    ON sb.tenant_id = fi.tenant_id AND sb.stg_bill_id = fi.stg_bill_id
            LEFT JOIN dim_suppliers s ON s.tenant_id = fi.tenant_id AND s.supplier_id = fi.supplier_id
            WHERE fi.tenant_id = %s AND fi.invoice_type = 'AP' AND fi.soft_status = 'active'
              AND coalesce(fi.payment_status, 'unpaid') <> 'paid'""", (tenant_id,))
        for r in cur.fetchall():
            outstanding = to_paise(r["outstanding"])
            tds = to_paise(r["tds_amount"])
            net = to_paise(r["net_payable"]) if r["net_payable"] is not None else to_paise(r["total_amount"]) - tds
            data.bills.append(dict(invoice_id=r["invoice_id"], stg_bill_id=r["stg_bill_id"], supplier_id=r["supplier_id"],
                                   supplier_name=r["supplier_name"], bill_number=r["bill_number"], due_date=r["due_date"],
                                   status=r["status"], payment_status=r["payment_status"], validation_flag=r["validation_flag"],
                                   soft_status=r["soft_status"], currency=(r["currency_code"] or "INR").strip(),
                                   outstanding_paise=outstanding, amount_paid_paise=to_paise(r["amount_paid"]),
                                   tds_paise=tds, net_payable_paise=net))
        cur.execute("""
            SELECT schedule_id::text, stg_bill_id::text, due_date, scheduled_amount, paid_amount, status::text AS status
            FROM payment_schedules
            WHERE tenant_id = %s AND cycle_type = 'PAYABLE' AND stg_bill_id IS NOT NULL
              AND status IN ('PENDING', 'PARTIAL', 'OVERDUE')""", (tenant_id,))
        for r in cur.fetchall():
            data.schedules.append(dict(schedule_id=r["schedule_id"], stg_bill_id=r["stg_bill_id"], due_date=r["due_date"],
                                       scheduled_paise=to_paise(r["scheduled_amount"]), paid_paise=to_paise(r["paid_amount"]),
                                       status=r["status"]))

    def disbursements():
        cur.execute("""
            SELECT disbursement_id::text, invoice_id::text, amount, status
            FROM fact_disbursements
            WHERE tenant_id = %s
              AND (status IN ('PENDING', 'PENDING_OTP', 'PROCESSING', 'INITIATED')
                   OR (status = 'SUCCESS' AND updated_at > now() - interval '10 days'))""", (tenant_id,))
        for r in cur.fetchall():
            data.disbursements.append(dict(disbursement_id=r["disbursement_id"], invoice_id=r["invoice_id"],
                                           amount_paise=to_paise(r["amount"]), status=r["status"]))

    def receivables():
        cur.execute("""
            SELECT i.id::text, i.customer_id::text, c.name AS customer_name, i.invoice_number, i.due_date, i.status,
                   i.currency, i.taxable_amount, i.tds_amount, i.outstanding, c.tds_rate_hint
            FROM ar_invoices i JOIN ar_customers c ON c.id = i.customer_id AND c.tenant_id = i.tenant_id
            WHERE i.tenant_id = %s AND i.status IN ('open', 'partially_paid', 'disputed') AND i.outstanding > 0""",
                    (tenant_id,))
        for r in cur.fetchall():
            data.ar_open.append(dict(id=r["id"], customer_id=r["customer_id"], customer_name=r["customer_name"],
                                     invoice_number=r["invoice_number"], due_date=r["due_date"], status=r["status"],
                                     currency=(r["currency"] or "INR").strip(), taxable_paise=to_paise(r["taxable_amount"]),
                                     tds_paise=to_paise(r["tds_amount"]), outstanding_paise=to_paise(r["outstanding"]),
                                     tds_rate_hint=r["tds_rate_hint"]))
        cur.execute("""
            SELECT customer_id::text, due_date, (paid_at AT TIME ZONE %s)::date AS paid_on
            FROM ar_invoices
            WHERE tenant_id = %s AND status = 'paid' AND paid_at IS NOT NULL AND due_date IS NOT NULL
              AND paid_at >= now() - interval '12 months'""", (tz_name, tenant_id))
        data.ar_history = [(r["customer_id"], r["due_date"], r["paid_on"]) for r in cur.fetchall()]
        cur.execute("""
            SELECT id::text, received_on, suggestion->>'invoice_id' AS invoice_id
            FROM ar_payments
            WHERE tenant_id = %s AND status IN ('unmatched', 'needs_review')
              AND suggestion ? 'invoice_id' AND (suggestion->>'confidence')::numeric >= 0.90""", (tenant_id,))
        data.unapplied = {r["invoice_id"]: dict(id=r["id"], received_on=r["received_on"]) for r in cur.fetchall()}

    guarded("bank", accounts)
    guarded("payment_hub", payment_hub_accounts)
    guarded("payables", payables)
    guarded("disbursements", disbursements)
    guarded("receivables", receivables)
    return data


# ── Inputs (cf_* tables) ────────────────────────────────────────────────────
def load_inputs(cur, tenant_id: str, data: SourceData) -> Settings:
    cur.execute("SELECT * FROM cf_settings WHERE tenant_id = %s", (tenant_id,))
    row = cur.fetchone()
    cur.execute("SELECT holiday_date, name FROM cf_holidays WHERE tenant_id = %s", (tenant_id,))
    settings = Settings.from_row(dict(row) if row else None, {r["holiday_date"]: r["name"] for r in cur.fetchall()})

    cur.execute("SELECT bank_account_id::text, include_in_forecast, od_limit_paise FROM cf_account_settings WHERE tenant_id = %s",
                (tenant_id,))
    prefs = {r["bank_account_id"]: r for r in cur.fetchall()}
    for a in data.accounts:
        p = prefs.get(str(a["bank_account_id"]))
        if p:
            a["include"], a["od_limit_paise"] = p["include_in_forecast"], int(p["od_limit_paise"])

    cur.execute("""
        SELECT DISTINCT ON (bank_account_id) bank_account_id::text, balance_paise, as_of, source
        FROM cf_bank_balances WHERE tenant_id = %s ORDER BY bank_account_id, as_of DESC""", (tenant_id,))
    latest = {str(b["bank_account_id"]): b for b in data.balances}
    for r in cur.fetchall():
        cur_b = latest.get(r["bank_account_id"])
        if cur_b is None or r["as_of"] > cur_b["as_of"]:
            latest[r["bank_account_id"]] = dict(bank_account_id=r["bank_account_id"], balance_paise=int(r["balance_paise"]),
                                                as_of=r["as_of"], source=r["source"])
    data.balances = list(latest.values())

    cur.execute("""SELECT invoice_id::text, earliest_date, latest_date, agreed_with, evidence
                   FROM cf_payment_windows WHERE tenant_id = %s AND active""", (tenant_id,))
    data.windows = {r["invoice_id"]: dict(earliest=r["earliest_date"], latest=r["latest_date"],
                                          agreed_with=r["agreed_with"], evidence=r["evidence"]) for r in cur.fetchall()}
    cur.execute("""SELECT invoice_id::text, promised_date, promised_amount_paise
                   FROM cf_collection_promises WHERE tenant_id = %s AND active""", (tenant_id,))
    data.promises = {r["invoice_id"]: dict(r) for r in cur.fetchall()}
    cur.execute("SELECT source_type, source_id, planned_date FROM cf_planned_dates WHERE tenant_id = %s AND active",
                (tenant_id,))
    data.planned = {(r["source_type"], r["source_id"]): r["planned_date"] for r in cur.fetchall()}
    cur.execute("""SELECT id::text, name, category, direction, amount_paise, frequency, anchor, quarter_months,
                          business_day_rule, confidence, statutory, start_date, end_date, active
                   FROM cf_recurring_items WHERE tenant_id = %s AND active""", (tenant_id,))
    data.recurring = [dict(r) for r in cur.fetchall()]
    cur.execute("""SELECT id::text, name, category, direction, amount_paise, on_date, confidence, active
                   FROM cf_adjustments WHERE tenant_id = %s AND active""", (tenant_id,))
    data.adjustments = [dict(r) for r in cur.fetchall()]
    if str(tenant_id) in demo_collection_tenants() and SEED_DIR.exists():
        add_demo_collections(data, datetime.now(ZoneInfo(settings.timezone)).date())
    return settings
