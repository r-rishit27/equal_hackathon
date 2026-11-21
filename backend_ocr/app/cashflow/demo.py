"""Load the synthetic tenant's forecast *inputs* into cf_* tables.

With the tenant listed in CASH_FORECAST_FIXTURE_TENANTS, its books (bills,
receivables, payouts, balances) are read from the seed files while everything
a user can edit — reserve, recurring items, adjustments, payment windows,
promises — lives in the database, so the demo is fully interactive.
"""

from __future__ import annotations

import json
from pathlib import Path

from .sources import SEED_DIR

DEMO_TABLES = ("cf_plan_decisions", "cf_plans", "cf_scenarios", "cf_snapshot_events", "cf_snapshot_exclusions",
               "cf_snapshot_balances", "cf_snapshots", "cf_planned_dates", "cf_collection_promises", "cf_payment_windows",
               "cf_adjustments", "cf_recurring_items", "cf_bank_balances", "cf_account_settings", "cf_holidays",
               "cf_settings", "cf_alerts", "cf_audit_log")


def _seed(name, seed_dir):
    return json.loads((Path(seed_dir) / name).read_text())


def seed_inputs(cur, tenant_id: str, actor: str = "demo-seed", seed_dir=SEED_DIR, reset: bool = True):
    if reset:
        for t in DEMO_TABLES:
            cur.execute(f"DELETE FROM {t} WHERE tenant_id = %s", (tenant_id,))
    s = _seed("settings.json", seed_dir)
    cur.execute("""INSERT INTO cf_settings (tenant_id, reserve_paise, horizon_days, timezone, default_view,
                       include_pending_approval_ap, overdue_fallback_days, downside_exclude_overdue_after_days,
                       min_customer_history, updated_by)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT (tenant_id) DO NOTHING""",
                (tenant_id, s["reserve_paise"], s["horizon_days"], s["timezone"], s["default_view"],
                 s["include_pending_approval_ap"], s["overdue_fallback_days"], s["downside_exclude_overdue_after_days"],
                 s["min_customer_history"], actor))
    for h in s["holiday_calendar"]:
        cur.execute("INSERT INTO cf_holidays (tenant_id, holiday_date, name) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                    (tenant_id, h["date"], h["name"]))
    for a in _seed("bank_accounts.json", seed_dir):
        cur.execute("""INSERT INTO cf_account_settings (tenant_id, bank_account_id, include_in_forecast, od_limit_paise)
                       VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING""",
                    (tenant_id, a["bank_account_id"], a["include_in_forecast"], a["od_limit_paise"]))
    for r in _seed("recurring_items.json", seed_dir):
        cur.execute("""INSERT INTO cf_recurring_items (id, tenant_id, name, category, direction, amount_paise, frequency, anchor,
                           quarter_months, business_day_rule, confidence, statutory, start_date, end_date, created_by)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING""",
                    (r["id"], tenant_id, r["name"], r["category"], r["direction"], r["amount_paise"], r["frequency"],
                     str(r["anchor"]), r["quarter_months"], r["business_day_rule"], r["confidence"], r["statutory"],
                     r["start_date"], r["end_date"], actor))
    for a in _seed("adjustments.json", seed_dir):
        cur.execute("""INSERT INTO cf_adjustments (id, tenant_id, name, category, direction, amount_paise, on_date, confidence,
                           note, created_by) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING""",
                    (a["id"], tenant_id, a["name"], a["category"], a["direction"], a["amount_paise"], a["date"],
                     a["confidence"], a["note"], actor))
    for w in _seed("payment_windows.json", seed_dir):
        cur.execute("""INSERT INTO cf_payment_windows (id, tenant_id, invoice_id, earliest_date, latest_date, agreed_with,
                           evidence, recorded_by) VALUES (%s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING""",
                    (w["id"], tenant_id, w["invoice_id"], w["earliest_date"], w["latest_date"], w["agreed_with"],
                     w["evidence"], actor))
    for p in _seed("collection_promises.json", seed_dir):
        cur.execute("""INSERT INTO cf_collection_promises (id, tenant_id, invoice_id, promised_date, promised_amount_paise,
                           source, note, recorded_by) VALUES (%s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING""",
                    (p["id"], tenant_id, p["invoice_id"], p["promised_date"], p["promised_amount_paise"], p["source"],
                     p["note"], actor))
