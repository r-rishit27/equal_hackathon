# Cash Flow Forecast — Product Requirements Document

| | |
|---|---|
| **Product** | Reckon.ai · Finance Desk · Cash Flow Forecast |
| **Status** | Draft for build · v1.0 · 21 Nov 2026 |
| **Route** | `/finance-desk/cash-forecast` (sidebar: **Insights → Cash flow forecast**) |
| **API prefix** | `/api/finance-desk/cash-forecast` |
| **Entitlement** | New service key `cash_forecast` (falls back to `reports` until the catalog entry ships) |
| **Scope source** | Narrows [`docs/finance-desk`](../finance-desk/README.md) to the cash-forecasting slice. Inventory, vendor-offer comparison and the general assistant are out of scope here. |
| **Companion docs** | [Technical design](02_TECHNICAL_DESIGN.md) · [HLD](03_HLD.md) · [LLD](04_LLD.md) · [User flows](05_USER_FLOWS.md) · [UI spec](06_UI_SPEC.md) · [Dummy data](dummy-data/README.md) |

---

## 1. Summary

Reckon.ai already holds most of the data an Indian MSME needs to see its cash position: approved supplier bills with TDS and net payable, payment schedules, payouts in flight, customer invoices with their payment history, unapplied bank receipts, and bank statements. What it lacks is a single screen that turns those records into a **dated, explainable forecast of bank cash**, plus a safe way to decide what to do about a shortfall.

**Cash Flow Forecast** gives the accountant and the owner:

1. A **daily cash projection for the next 30 days**, with a 13-week weekly rollup in P1. It starts from a dated bank balance and is built only from records Reckon.ai already has, plus a small set of recurring obligations the business enters once (payroll, GST, TDS, EMI and rent).
2. **Three views on the same snapshot.** *Expected* is the default. *Downside* is a stress view. *No new collections* is a liquidity floor.
3. **Explainability at every number.** Each day's balance opens the exact bills, invoices, payouts and recurring items behind it. Anything left out appears with a reason.
4. **What-if scenarios** that respect real constraints. A supplier payment can move only inside a window the supplier agreed to. Payroll and statutory dues cannot move. Customer-delay assumptions are labelled as assumptions.
5. **A cash plan with approval.** The accountant submits a versioned plan and the owner approves or returns it. An approved plan records *decisions* (for example, “pay Ankur on 4 Dec”) that later forecasts honour. It never moves money.

## 2. Problem

### 2.1 Customer

The first customer is an **Indian B2B distributor or trader** with ₹10–100 Cr turnover. It has one legal entity, 2–4 bank accounts (often a cash-credit line among them), 50–500 active customers on 15–60 day terms, and 20–200 suppliers. The finance team is one accountant, sometimes with a junior, plus an external CA. The **owner** decides which payments go out each week.

The synthetic tenant in [dummy-data](dummy-data/README.md) is **Kaveri Packaging & Distribution Pvt Ltd**. It has a ₹24 Cr turnover, 46 staff, 18 customers and 14 suppliers. Its accounts are HDFC and SBI current accounts and a ₹40 L SBI cash-credit line.

### 2.2 Today's workflow (observed pattern)

| Step | How it is done today | Pain |
|---|---|---|
| Find today's cash | Log in to 2–3 net-banking portals and note balances | 15–20 min. Balances go stale by noon. |
| List what must go out | Export approved bills, add payroll, GST, TDS, EMI and rent from memory or a calendar | Statutory dates get missed. TDS is double-counted, because bills are listed gross but paid net. |
| Guess what comes in | Sort the receivables ageing by due date and apply gut feel per customer | Customers who always pay 3 weeks late are forecast on the due date. |
| Spot the crunch | Build an Excel running balance | Formula errors. Nobody notices a payroll-day breach until the day before. |
| Decide | Message the owner on WhatsApp: “Can we pay Ankur next week instead?” | No record of what was agreed, or why. |
| Re-do tomorrow | Start again | 1–2 hours a day, every day |

### 2.3 Why now

- Receivables now records customer **payment behaviour** (applied receipts, TDS deducted, payment dates). That is the input a realistic collection forecast needs.
- AP already tracks **net payable after TDS**, payment schedules and payouts in flight, so outflows can be dated and sized correctly.
- Copilot already reads `fact_cashflow_daily`, but nothing populates it with a trustworthy forecast. This module becomes its source.

### 2.4 Job to be done

> “Every morning, tell me how much cash I will have each day for the next month. Warn me before I drop below my safety reserve, show me exactly which payments and collections cause it, and let me agree a fix with my accountant without losing track of what we decided.”

## 3. Goals and non-goals

### 3.1 Goals

| # | Goal | Measured by |
|---|---|---|
| G1 | A trustworthy daily forecast with no manual spreadsheet | ≥ 80% of pilot tenants open the forecast ≥ 4 days/week by week 4 |
| G2 | Earlier warning of shortfalls | Reserve breaches flagged ≥ 5 banking days in advance in ≥ 80% of cases (backtest) |
| G3 | Accuracy that earns trust | 7-day-ahead closing-balance WAPE ≤ 15%, and ≤ 25% at 30 days, after 8 weeks of pilot data |
| G4 | Faster cash meetings | Daily cash-prep time drops from ~60 min to ≤ 15 min (self-reported, plus time-on-page) |
| G5 | Decisions are recorded | ≥ 70% of reserve breaches get a submitted plan within 2 banking days |

### 3.2 Non-goals (this release)

- **Moving money.** No payouts, sweeps, CC drawdowns or collection emails. Payment Hub keeps its existing OTP and approval controls.
- **Inventory, purchasing and vendor-offer optimisation.** These stay in the Finance Desk inventory planner.
- **Multi-currency forecasting.** The release is INR only. Foreign-currency bills appear as an excluded item (`NON_INR`) with their INR estimate shown for information.
- **Multi-entity consolidation.**
- **ML-trained forecasting models.** The collection model is a transparent statistical rule (§7.3). ML is a later option once backtests exist.
- **Live bank feeds (account aggregator / bank APIs).** P0 uses statement imports and manual balance entry.

## 4. Personas and permissions

| Persona | Reckon.ai role | Can do | Cannot do |
|---|---|---|---|
| **Owner** (approver of cash decisions) | `finance_controller` (or `admin`) | Everything the accountant can, plus approve or return plans and edit the reserve | Approve a plan they submitted, unless `allow_self_approval` is on |
| **Accountant** (preparer) | `accountant` | View forecast, add balances, recurring items, adjustments, payment windows and promises, build scenarios, submit plans | Approve plans, change the reserve |
| **CA / auditor** | `auditor` | View the forecast, plans and decision history, and export | Any change |
| **Admin** | `admin` | Everything, including settings | — |
| Approver (bills), member | `approver`, `member` | No access. Cash position is sensitive, so access is denied by default. | — |

Permissions are enforced on the server for every endpoint (§9 of the [LLD](04_LLD.md)). Impersonated platform sessions get read-only access.

## 5. User stories

Priority: **P0** is required for first release. **P1** follows in the next iteration. **P2** is later.

### 5.1 See the position

| ID | Pri | Story | Acceptance criteria |
|---|---|---|---|
| US-01 | P0 | As an accountant, I see today's opening cash across included bank accounts, with each balance's date and source. | Each account shows its balance, as-of timestamp, source (statement or manual) and freshness badge. The total matches the sum of included accounts. On the fixture: **₹48,70,432** (HDFC ₹43,51,483 + SBI ₹5,18,949), as of 20 Nov 2026 18:30 IST. |
| US-02 | P0 | As an accountant, I see a 30-day daily projection of closing cash with my reserve drawn on it. | 30 consecutive local dates. Every day shows opening, inflow, outflow and closing. Non-banking days are visually muted and carry no flows. The reserve line shows **₹15,00,000**. |
| US-03 | P0 | As an owner, I see the lowest balance, the first reserve breach and how far below the reserve it goes, in words as well as on the chart. | Fixture, expected view: “Lowest balance **₹9,99,874** on **Mon 30 Nov**, ₹5,00,126 below your ₹15,00,000 reserve.” |
| US-04 | P0 | As an owner, I switch between *Expected*, *Downside* and *No new collections* without losing my place. | Switching changes only which events count. All three views use the same snapshot revision, which is shown. Fixture minimums: expected ₹9,99,874 (30 Nov), downside −₹32,44,064 (30 Nov), no-collections −₹1,36,51,289 (19 Dec). |
| US-05 | P0 | As an owner, I see what drives the month in a few lines. | A drivers panel shows totals by category (collections, suppliers, payroll, statutory, rent, debt, other) for the horizon. Fixture, expected view: collections ₹2,21,14,651, suppliers ₹1,29,69,886, payroll ₹21,80,000, statutory ₹21,33,550. |
| US-06 | P1 | As an owner, I see my undrawn cash-credit headroom next to the forecast. | Headroom = limit − drawn. Fixture: ₹40,00,000. It is never added to the forecast balance; it is shown as available liquidity. |
| US-07 | P1 | As an owner, I see a 13-week weekly rollup. | Week buckets Monday to Sunday. Same events and same rules. Daily detail available on drill-in. |

### 5.2 Understand a number

| ID | Pri | Story | Acceptance criteria |
|---|---|---|---|
| US-10 | P0 | As an accountant, I click any day and see every inflow and outflow on it. | The drawer lists source type, counterparty, document number, amount, confidence, *date basis* (for example “due + 21d median, customer, n=10”) and a link to the source record. Rows sum exactly to the day's inflow and outflow. |
| US-11 | P0 | As an accountant, I see what was left out of the forecast and why. | An Exclusions panel lists every source record not scheduled, with a reason code. Fixture: 7 exclusions. They are an in-flight payout counted once, a disbursement already in the balance, a suspected duplicate, a rejected bill, a receipt awaiting cash application, a disputed invoice, and an invoice aged over 60 days (downside view only). |
| US-12 | P0 | As an accountant, I see how a customer's expected payment date was derived. | The date basis shows the method (median delay, conditional remaining delay, promise to pay, or fallback), the sample size and whether the customer's own history or the tenant's history was used. |
| US-13 | P0 | As an owner, I am warned when the forecast's inputs are stale or incomplete. | A balance older than 1 banking day shows a warning. Older than 3 banking days blocks plan submission. A missing balance blocks the forecast with an “add a balance” action. |

### 5.3 Maintain inputs that are not in the books

| ID | Pri | Story | Acceptance criteria |
|---|---|---|---|
| US-20 | P0 | As an accountant, I enter a bank balance manually when no statement is imported. | The balance is saved with an as-of timestamp, the user and the source `manual`. The latest one by as-of wins over an older statement balance. |
| US-21 | P0 | As an accountant, I set up recurring obligations: payroll, PF/ESI, TDS deposit, GST, EMI, rent, utilities and advance tax. | Frequency can be monthly, weekly or quarterly. The anchor day can be a date or *last banking day*. The business-day rule rolls payments to the previous or next banking day. Confidence is committed or estimated. Fixture: 10 items. |
| US-22 | P0 | As an accountant, I add a one-off adjustment: capex, insurance, a refund or a loan disbursal. | Dated, signed, with confidence, a note and an author. Fixture: insurance ₹6,85,000 on 30 Nov, forklift down payment ₹4,50,000 on 9 Dec, GST refund ₹1,42,000 on 16 Dec (estimated). |
| US-23 | P0 | As an accountant, I record that a supplier agreed to a later payment date. | The payment window has earliest date, latest date, who agreed and evidence text or an attachment. Only windowed bills can be rescheduled later than their due date in scenarios. |
| US-24 | P0 | As an accountant, I record a customer's promise to pay. | The promise overrides the model date in the expected view and is labelled “promise to pay”. The downside view keeps the model's p80 date, because promises slip. Fixture: Malabar ₹7,31,600 promised for 26 Nov. |
| US-25 | P1 | As an owner, I set the reserve, the horizon and the business calendar. | The reserve is only editable by `finance_controller` or `admin`. Changes are audited. |

### 5.4 Explore and decide

| ID | Pri | Story | Acceptance criteria |
|---|---|---|---|
| US-30 | P0 | As an accountant, I move a payment or a collection to another date and see the effect instantly. | Recalculates in < 300 ms p95 on the fixture. Shows a baseline line and a scenario line, plus the delta in minimum balance and in first breach. |
| US-31 | P0 | As an accountant, I am stopped from making an impossible change. | Moving a statutory or payroll item, or moving a bill outside its agreed window, is refused with a readable reason. Fixture: moving Raigad RAI/2610/203 to 3 Dec is refused because its window ends 2 Dec. |
| US-32 | P0 | As an accountant, I can model customer slippage. | “Delay all of {customer} by N days”, “Exclude invoice”, and “Collect only X% of {customer}”. These are always labelled *assumption*. |
| US-33 | P0 | As an accountant, I save a scenario, name it and come back to it. | Scenarios persist per tenant and are pinned to the snapshot revision they were built on. On a newer revision they show “rebased” or “needs review”. |
| US-34 | P0 | As an accountant, I submit a scenario as a cash plan with a note. | The server recomputes the metrics. The plan freezes at version N. The owner is notified in-app (email in P1). |
| US-35 | P0 | As an owner, I approve or return a plan with a note. | Approval is refused if the plan is stale, meaning the inputs changed and the recomputed metrics differ. It is refused if I submitted it, unless `allow_self_approval` is on. A repeated click creates one decision (idempotency key). |
| US-36 | P0 | As an owner, approved payment-date decisions are honoured by tomorrow's forecast. | Approved `shift_event` decisions on bills become *planned payment dates* (basis `approved_plan`). Assumptions are not carried into the baseline. |
| US-37 | P1 | As an owner, I export the forecast and the plan as CSV or PDF for my CA or bank. | The export includes the snapshot revision, the view, assumptions and exclusions. |

### 5.5 Stay ahead

| ID | Pri | Story | Acceptance criteria |
|---|---|---|---|
| US-40 | P1 | As an owner, I get an alert when the expected view first breaches the reserve within the next 7 days. | A daily 07:00 IST job sends one alert per new breach date (deduplicated). It is in-app first; email goes out through the existing user-email connection. |
| US-41 | P1 | As an owner, I see how accurate past forecasts were. | Accuracy panel: WAPE and bias for 1–7, 8–14 and 15–30 days ahead, computed against actual bank closing balances. |
| US-42 | P1 | As an accountant, I ask Copilot “when do we drop below reserve?” and get the same numbers as the screen. | The Copilot `cash_forecast` tool reads this module's service, not raw tables. |
| US-43 | P2 | As an owner, I see probabilistic bands (P10–P90) once 8 weeks of backtest data exist. | — |

## 6. Experience overview

The page has one main screen and three supporting drawers. Wireframes are in the [UI spec](06_UI_SPEC.md) and journeys in [user flows](05_USER_FLOWS.md).

```
┌ Header: Cash flow forecast · view switch · snapshot rev · Refresh · Export ┐
├ Freshness strip: account balances and their age · data coverage            ┤
├ KPI strip: Cash today · Lowest balance · First breach · Runway w/o         ┤
│            collections · 30-day net flow · CC headroom                     │
├ Chart: daily closing (baseline + scenario), reserve line, breach markers   ┤
├ Two columns:  Drivers (by category)  │  Scenario builder / plan panel      ┤
├ Table: day-by-day ledger (accessible equivalent of the chart)              ┤
└ Drawers: Day detail · Exclusions · Inputs (recurring, adjustments, ...)    ┘
```

## 7. Functional specification

### 7.1 Sources and what they contribute

| Source (existing table) | Becomes | Amount used | Date used |
|---|---|---|---|
| `stg_bank_statements.running_balance`, or a manual balance in `cf_bank_balances` | Opening cash per included account | Latest balance at or before the as-of time | Balance timestamp |
| `fact_invoices` (`invoice_type='AP'`) joined to `stg_bills` | Supplier outflows | Outstanding **net of TDS** (TDS is withheld at first payment) | Payment-schedule instalment, then planned date (approved plan), then due date. Overdue bills go to the first banking day. |
| `payment_schedules` (`PAYABLE`) | Instalment outflows | `scheduled − paid` | Instalment due date |
| `fact_disbursements` | In-flight payouts (`PENDING`, `PENDING_OTP`, `PROCESSING`) count as confirmed outflows. `SUCCESS` after the balance time counts as already paid. | Payout amount | First banking day |
| `ar_invoices` (`open`, `partially_paid`) | Customer inflows | Outstanding **minus expected TDS** (customer's `tds_rate_hint` × taxable, if not yet deducted) | Collection model (§7.3), or promise to pay |
| `ar_payments` (`unmatched`, `needs_review` with suggestion ≥ 0.90) | Dedupe signal: the money is already in the bank | — | — |
| `cf_recurring_items` (new) | Payroll, statutory, rent, EMI, utilities | Item amount | Expanded by frequency, then rolled by business-day rule |
| `cf_adjustments` (new) | One-off items | As entered | As entered, rolled to a banking day |
| `cf_payment_windows`, `cf_collection_promises`, `cf_planned_dates` (new) | Scheduling constraints and decisions | — | — |

### 7.2 Status and eligibility rules

| Record state | Expected | Downside | No new collections | Exclusion reason if not scheduled |
|---|:-:|:-:|:-:|---|
| AP `APPROVED`, unpaid or partial, validation `OK` | ✓ | ✓ | ✓ | — |
| AP in approval (`PENDING_APPROVER`, `PENDING_ACCOUNTANT`, `PENDING_FC`, `PENDING`) | ✓ (confidence *pipeline*) | ✓ | ✗ | — |
| AP `REJECTED`, `VOID`, `CANCELLED`, soft-deleted | ✗ | ✗ | ✗ | `REJECTED` / `VOID` |
| AP `validation_flag = DUPLICATE` | ✗ | ✗ | ✗ | `SUSPECTED_DUPLICATE` |
| AP with a `SUCCESS` disbursement but still `unpaid` | ✗ | ✗ | ✗ | `PAID_VIA_DISBURSEMENT` |
| AP with an in-flight disbursement | Counted once, as the payout | | | `PAYOUT_IN_FLIGHT` (on the bill row) |
| AP non-INR | ✗ | ✗ | ✗ | `NON_INR` |
| AR `open` / `partially_paid` | ✓ | ✓ unless > 60 days overdue | ✗ | `AGED_OVER_60_DAYS_DOWNSIDE` |
| AR `disputed` | ✗ | ✗ | ✗ | `DISPUTED` |
| AR with an unapplied receipt suggestion ≥ 0.90 | ✗ | ✗ | ✗ | `SETTLED_PENDING_APPLICATION` |
| Recurring / adjustment, committed | ✓ | ✓ | ✓ | — |
| Recurring / adjustment, estimated outflow | ✓ | ✓ | ✓ | — |
| Adjustment, estimated inflow | ✓ | ✗ | ✗ | — |

### 7.3 Collection model (customer receipts)

The model is deliberately transparent, so an accountant can check any date by hand.

1. **History.** For each customer, take every invoice paid in the last 12 months and compute `delay = paid_date − due_date` in days, which can be negative.
2. **Profile.** With at least `min_customer_history` (default 3) samples, the customer's own **median** and **p80** apply (nearest-rank). Otherwise the tenant-wide distribution applies. Fixture tenant profile: median 10 days, p80 24 days, n = 215.
3. **Not yet overdue** (due ≥ start): the expected date is `due + median` and the downside date is `due + p80`.
4. **Already overdue by *o* days**: use the **conditional remaining delay**. Take the delays greater than *o*, subtract *o*, and use their median for expected and p80 for downside, counted from the start date. Use the customer's history if it has ≥ 3 such samples, otherwise the tenant's. With no comparable history, use start + `overdue_fallback_days` (5 banking days) for expected and 14 more days for downside.
5. **Promise to pay** overrides the expected date only.
6. **Roll forward** to the next banking day.
7. **Amount**: outstanding minus expected TDS deduction.

Fixture example: Sahyadri Agro Foods (median 21, p80 26, n = 10) has invoice ₹14,50,000 net due 28 Nov. Its expected date is **19 Dec** and its downside date is **24 Dec**, which falls outside the horizon.

### 7.4 Business calendar

- Non-banking days are Sundays, the 2nd and 4th Saturdays, and tenant-configured holidays (seeded per state; the fixture uses a synthetic list including 24 Nov Guru Nanak Jayanti).
- **Vendor payments, EMI, rent and receipts** roll to the **next** banking day.
- **Statutory dues and payroll** roll to the **previous** banking day, to avoid late-payment interest. Fixture: GSTR-3B due Sun 20 Dec is paid **Sat 19 Dec**.

### 7.5 Views

| View | Purpose | Inflows | Outflows |
|---|---|---|---|
| **Expected** (default) | Best single estimate | AR at median / conditional median, promises, estimated inflows | All committed, pipeline and estimated outflows |
| **Downside** | “What if collections are slow?” | AR at p80; excludes > 60 days overdue and estimated inflows | Same as expected |
| **No new collections** | Liquidity floor and runway | None | Committed outflows only, excluding pipeline AP |

### 7.6 Scenario operations

| Operation | Targets | Rule | Kind |
|---|---|---|---|
| `shift_event` | Supplier bill or instalment | Earlier: any banking day ≥ start. Later: only up to the payment window's `latest_date`. | **Decision** |
| `shift_event` | AR invoice | Any date ≥ start | Assumption |
| `shift_event` | Recurring item that is not statutory and not payroll; adjustment | Within ±15 days | Decision |
| `shift_event` | Statutory, payroll, debt, in-flight payout | **Refused** (`FIXED_OBLIGATION`) | — |
| `delay_customer` | All open invoices of one customer | 1–90 days | Assumption |
| `haircut_customer` | One customer or all | 0–100% of the amount | Assumption |
| `exclude_event` | Inflows only | — | Assumption |
| `add_item` | New hypothetical inflow or outflow | Dated, labelled. A financing inflow (CC drawdown) must not exceed headroom. | Decision if `committed`, else assumption |

### 7.7 Cash plan lifecycle

`draft → submitted → approved | returned`. A returned plan is edited and resubmitted as version N+1. An approved plan becomes `superseded` when a newer plan is approved. At approval the server rebuilds the plan on the **current** snapshot. If the revision changed **and** the recomputed metrics differ, the approval is refused as `PLAN_STALE`, and the response shows what changed.

### 7.8 Demo walkthrough (fixture, ≤ 3 minutes)

1. Open the forecast. The expected view shows **₹48.7 L today** and a dip to **₹9.99 L on Mon 30 Nov**. The red marker reads “₹5.0 L below reserve”.
2. Click **30 Nov**. Payroll ₹21.8 L, insurance renewal ₹6.85 L and six supplier bills (₹22.7 L) outweigh ₹18.9 L of expected collections.
3. Open **Exclusions**. The ₹2.36 L Polyshield duplicate is held, and Kalinga's ₹2.84 L is already in the bank awaiting cash application, so neither is double-counted.
4. Switch to **Downside**. Cash goes negative from 30 Nov, with a low of −₹32.4 L. The CC headroom chip shows ₹40 L available.
5. Build the scenario **“Defer three windowed supplier payments”**: Ankur to 4 Dec, Indus to 3 Dec, Raigad to 2 Dec, all inside agreed windows. The expected minimum rises to **₹19,13,700** and there is **no breach**. Try moving Raigad to 3 Dec: refused, because the window ends 2 Dec.
6. Submit as a plan. Switch user to owner and approve.
7. Refresh. The three bills now show the date basis *approved plan*.

## 8. Non-functional requirements

| Area | Requirement |
|---|---|
| Correctness | Integer paise end to end. Daily rows sum exactly to the events. Golden fixture parity: the engine matches `expected_forecast.json` exactly. |
| Performance | Snapshot build p95 < 1.5 s for 5,000 open documents. Scenario preview p95 < 300 ms (pure function, no DB). Page first render < 2 s on a 4G profile. |
| Freshness | Daily automatic snapshot at 07:00 IST. Manual refresh at any time. A refresh is a no-op when inputs are unchanged (same content hash, so no new revision). |
| Security | Tenant from the verified token only. Role checks on every route. Snapshots and plans are tenant-scoped by composite keys. No bank account numbers in responses beyond masks. |
| Audit | Every settings, input and plan change is written to `cf_audit_log` with actor, before/after and request ID. |
| Accessibility | WCAG 2.1 AA. The chart has a table equivalent. Status is never conveyed by colour alone. Fully keyboard-operable. |
| Availability | The forecast is read-only and degrades gracefully. If a source fails, coverage shows “partial” with the failing source named, and approval is blocked. |
| Observability | Metrics for build time, event counts per source, exclusions per reason, preview latency and plan transitions. Logs carry no customer or supplier names. |

## 9. Success metrics and instrumentation

| Metric | Definition | Target (pilot, week 8) |
|---|---|---|
| Weekly active forecasters | Tenants with ≥ 4 forecast views per week | ≥ 80% of pilot tenants |
| Breach lead time | Median banking days between the first forecast of a breach and the breach date | ≥ 5 |
| WAPE 1–7 days | Σ\|forecast − actual closing\| ÷ Σ actual, for 1–7 days ahead | ≤ 15% |
| Bias | Mean (forecast − actual) ÷ mean actual | Within ±5% |
| Plan adoption | Share of breaches with an approved plan before the breach date | ≥ 60% |
| Input hygiene | Share of forecasts with a balance ≤ 1 banking day old | ≥ 90% |

Events to log (no PII): `cf_viewed{view}`, `cf_day_opened`, `cf_exclusions_opened`, `cf_scenario_op{op,kind}`, `cf_scenario_refused{code}`, `cf_plan_submitted`, `cf_plan_decided{decision}`, `cf_refresh{changed}`, `cf_alert_sent`.

## 10. Release plan

| Phase | Content | Exit gate |
|---|---|---|
| **M0 · Foundations** (week 1) | Schema, fixture adapter, engine and golden tests | Engine matches `expected_forecast.json` exactly |
| **M1 · Read-only forecast** (weeks 2–3) | Live adapters, snapshot API, page with KPIs, chart, day drawer, exclusions, inputs drawer | Two internal tenants reconcile opening and AP/AR totals with the source screens |
| **M2 · Scenarios and plans** (weeks 4–5) | Preview, validation, scenarios, plan submit/approve, planned dates | Stale, self-approval and idempotency tests pass |
| **M3 · Pilot** (weeks 6–8) | Daily job, alerts, `fact_cashflow_daily` publish, Copilot tool, accuracy panel | Pilot metrics instrumented. No P0/P1 defects open for 5 days. |

Feature flag: `cash_forecast` entitlement per tenant. Default off.

## 11. Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Bank balance is stale or missing | The whole forecast is wrong | Freshness badges, block approval beyond 3 days, one-click manual balance entry |
| AP payment status lags payouts | Double-counted outflows | Disbursement dedupe (`PAID_VIA_DISBURSEMENT`, `PAYOUT_IN_FLIGHT`) |
| Unapplied receipts | Double-counted inflows | Dedupe using cash-application suggestions ≥ 0.90 |
| Recurring items not set up | Payroll and GST missing, so the forecast is far too rosy | First-run checklist that seeds templates for payroll, GST, TDS and PF. The coverage indicator flags “no payroll configured”. |
| Customers' behaviour changes | Dates drift | The 12-month window favours recency. The accuracy panel exposes drift. Promises to pay give manual control. |
| Users treat the plan as payment authority | Control failure | Copy and API make the separation explicit. No payment action exists on this page. |

## 12. Open questions

1. Should the reserve be a single number or a schedule (for example, higher in the payroll week)? Proposed: single number in P0, schedule in P2.
2. Should approved plans write the planned date back to Payment Hub's queue ordering? Proposed: show it read-only in Payment Hub in P1.
3. Which holiday calendar source is authoritative per state? Proposed: ship the RBI list per state as data and let the admin edit it.
4. Is `finance_controller` the right mapping for “owner” at every tenant, or do we need a dedicated `cash_approver` capability? Proposed: a capability flag in P1.

## 13. Glossary

| Term | Meaning |
|---|---|
| Snapshot | An immutable, revisioned set of dated cash events and exclusions built from sources at a point in time |
| View | A rule for which snapshot events count (expected, downside or no-collections) |
| Scenario | An ordered list of overrides applied to a snapshot. It never mutates sources. |
| Plan | A submitted scenario with a recorded owner decision |
| Decision vs assumption | A decision is something the business controls (paying later inside a window). An assumption is something it predicts (a customer paying late). |
| Reserve | The minimum closing balance the owner wants to keep |
| Date basis | A human-readable explanation of why an event sits on its date |
| WAPE | Weighted absolute percentage error |
