#!/usr/bin/env python3
"""Set up the synthetic Cash Flow Forecast demo for one tenant.

    python3.12 scripts/seed_cash_forecast_demo.py --tenant <tenant-uuid>

Then start the API with CASH_FORECAST_FIXTURE_TENANTS=<tenant-uuid> so that
tenant's books come from docs/cashflow-forecast/dummy-data/seed while its
editable inputs live in the cf_* tables. Also enables the cash_forecast
entitlement for the tenant. Use a demo or dev tenant: this replaces the
tenant's existing cash-forecast inputs, scenarios and plans.
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from psycopg2.extras import RealDictCursor  # noqa: E402

from backend_ocr.app.cashflow.demo import seed_inputs  # noqa: E402
from backend_ocr.app.cashflow.schema import DDL  # noqa: E402
from backend_ocr.app.config import get_conn, put_conn  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tenant", required=True, help="tenant UUID to seed (a demo/dev tenant)")
    ap.add_argument("--no-entitlement", action="store_true", help="don't enable the cash_forecast service")
    args = ap.parse_args()
    conn = get_conn()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            for stmt in DDL:
                cur.execute(stmt)
            seed_inputs(cur, args.tenant)
            if not args.no_entitlement:
                cur.execute("SAVEPOINT ent")
                try:
                    cur.execute("""INSERT INTO tenant_service (tenant_id, service_key, enabled, enabled_at, notes)
                                   VALUES (%s, 'cash_forecast', true, now(), 'cash forecast demo seed')
                                   ON CONFLICT (tenant_id, service_key)
                                   DO UPDATE SET enabled = true, enabled_at = now(), updated_at = now()""", (args.tenant,))
                except Exception as exc:  # schema differs per environment; enable from the admin panel instead
                    cur.execute("ROLLBACK TO SAVEPOINT ent")
                    print(f"Could not enable cash_forecast automatically ({type(exc).__name__}); enable it in Admin → Services.")
        conn.commit()
    finally:
        put_conn(conn)
    print(f"Seeded cash forecast inputs for {args.tenant}.")
    print(f"Start the API with CASH_FORECAST_FIXTURE_TENANTS={args.tenant} to use the synthetic books.")


if __name__ == "__main__":
    main()
