# Cash Flow Forecast

This is the design package for the cash-forecasting slice of Reckon.ai Finance Desk. It narrows the broader [Finance Desk proposal](../finance-desk/README.md) to one job: **show a dated, explainable bank-cash forecast for the next 30 days, warn before the reserve is breached, and let the accountant and owner agree a recorded plan.** Inventory, vendor-offer optimisation and the general assistant are out of scope.

**Status:** built (P0). Route `/finance-desk/cash-forecast`, API `/api/finance-desk/cash-forecast`, entitlement `cash_forecast` (off by default per tenant). P1 items not yet built: the 07:00 daily job and breach alerts, the accuracy panel, and the Copilot tool. A manual or plan-driven refresh already publishes to `fact_cashflow_daily`.

## Run it

```bash
# 1. Tables (also run by scripts/run_api_migrations.py)
python3.12 scripts/run_api_migrations.py
# 2. Demo tenant: inputs into cf_*, entitlement on
python3.12 scripts/seed_cash_forecast_demo.py --tenant <demo-tenant-uuid>
# 3. API with that tenant's books read from the synthetic seed
CASH_FORECAST_FIXTURE_TENANTS=<demo-tenant-uuid> uvicorn backend_ocr.app.main:app --port 8001
# Tests
python3.12 -m pytest tests/test_cash_forecast_engine.py tests/test_cash_forecast_rules.py
createdb cf_test && CF_TEST_DB_URL=postgresql:///cf_test python3.12 -m pytest tests/test_cash_forecast_db.py
```

Without `CASH_FORECAST_FIXTURE_TENANTS`, a tenant's forecast reads its real bills, payouts, receivables and statement balances.

## Read in this order

| # | Document | Use it for |
|---|---|---|
| 1 | [PRD](01_PRD.md) | Customer, problem, personas, user stories with acceptance criteria, rules, views, metrics, release plan |
| 2 | [Technical design](02_TECHNICAL_DESIGN.md) | Source SQL against existing tables, amount and date rules, snapshot build, engine, collection model, plans, jobs, security, testing, rollout |
| 3 | [HLD](03_HLD.md) | Context, container, component, data-flow, sequence, deployment and lifecycle diagrams, plus architecture decisions |
| 4 | [LLD](04_LLD.md) | Class diagrams (domain, overrides, sources, services, frontend), algorithms, ER diagram and full DDL, API contracts, state machines, auth matrix, error codes, test catalogue |
| 5 | [User flows](05_USER_FLOWS.md) | Eleven flows with diagrams: setup, morning check, investigation, inputs, scenarios, plan approval, stale plans, alerts, auditor, degraded states |
| 6 | [UI spec](06_UI_SPEC.md) | Screen inventory, wireframes with fixture numbers, component specs, chart, tokens, copy, interactions, accessibility |
| — | [Dummy data](dummy-data/README.md) | Synthetic distributor tenant, planted edge cases and the golden forecast the engine must match |

## The numbers in one place

All documents quote the synthetic tenant (as of 20 Nov 2026, horizon 21 Nov – 20 Dec):

- Opening cash **₹48,70,432** against a reserve of **₹15,00,000**.
- **Expected view:** cash falls to **₹9,99,874 on Mon 30 Nov** (payroll + insurance + six supplier bills), a breach.
- **Plan:** deferring three supplier bills inside their agreed windows gives a lowest balance of **₹19,13,700** and no breach.
- **Downside view:** cash goes negative from 30 Nov, with a lowest balance of −₹32,44,064. The ₹40 L cash-credit line covers it.

## Build order

1. Engine and golden tests against `dummy-data/seed/expected_forecast.json` ([LLD §5](04_LLD.md#5-algorithms), [§13](04_LLD.md#13-test-case-catalogue)).
2. DDL, live source adapters, snapshot API.
3. Page: KPIs, chart, ledger, drawers (buildable first on the fixture via `?fixture=1`).
4. Scenarios, plans and approvals.
5. Daily job, alerts, `fact_cashflow_daily` publish (Copilot and Reports pick it up), accuracy.
