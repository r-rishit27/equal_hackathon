# Cash Flow Forecast: synthetic dataset

This is a realistic, fully synthetic tenant for building and testing the forecast, and the **golden output** the production engine must reproduce.

```bash
python3 docs/cashflow-forecast/dummy-data/generate_dummy_data.py   # from repo root; deterministic
```

Rerunning the script produces byte-identical files (fixed seed, fixed as-of time). Every name, GSTIN, PAN, account number and UTR is invented. GSTINs and PANs are format-valid, and GSTINs carry a correct checksum, so validators accept them.

## The business

**Kaveri Packaging & Distribution Pvt Ltd (synthetic)** is a B2B packaging distributor in Maharashtra with a turnover of about ₹24 Cr and 46 staff.

| Item | Value |
|---|---|
| As of | 20 Nov 2026 18:30 IST (Friday close). Forecast runs from 21 Nov to 20 Dec 2026 (30 days). |
| Bank accounts | HDFC Current *Operations* ₹43,51,482.50 · SBI Current *Collections* ₹5,18,949.34 · SBI Cash Credit (₹40 L limit, ₹0 drawn, excluded from balance) |
| Opening cash | **₹48,70,431.84** |
| Reserve | ₹15,00,000 |
| Customers | 18, with four behaviour profiles: on-time, slightly late, slow and erratic. Terms are 15–60 days. |
| AR invoices | 302 in total: 215 paid (May–Nov history for the collection model), 86 open or partly paid (₹3.54 Cr outstanding) and 1 disputed |
| Suppliers | 14, covering raw material (194Q 0.1% TDS), freight and services (194C 1–2%), rent (194I 10%) and IT (194J 10%). Five are MSME-registered. |
| AP bills | 50: approved, partial with an instalment, in approval, rejected and a duplicate |
| Bank statements | 91 days for HDFC and SBI, plus the CC account. The CSV layout matches Indian net banking exports. Weekly sweeps from SBI to HDFC, Tue/Thu supplier payment runs sized from collections, and recurring debits are included. |
| Recurring items | Payroll ₹21.8 L (last banking day), GST ₹9.84 L (20th), advance tax ₹6.5 L (15 Dec), rent ₹3.15 L, PF/ESI ₹3.02 L, EMI ₹2.16 L, TDS deposit ₹1.97 L, electricity, internet, weekly diesel |
| Adjustments | Insurance ₹6.85 L (30 Nov), forklift down payment ₹4.5 L (9 Dec), GST refund ₹1.42 L (16 Dec, estimated) |

## Planted cases (each one tests a rule)

| Case | Record | Expected handling |
|---|---|---|
| Payout in flight | Ankur ANK/2610/248, disbursement `PENDING` | One ₹4,11,942.60 outflow on 21 Nov. Bill excluded `PAYOUT_IN_FLIGHT`. |
| Paid but not synced | Raigad RAI/2610/209, disbursement `SUCCESS` 19 Nov | Excluded `PAID_VIA_DISBURSEMENT`. Already in the balance. |
| Duplicate | Polyshield POL/2611/899, `validation_flag = DUPLICATE` | Excluded `SUSPECTED_DUPLICATE` |
| Rejected | Pune Hydraulics PUN/2611/330 | Excluded `REJECTED` |
| Partial with instalment | Sutlej, instalment 2 due 8 Dec | Only the remainder, on 8 Dec |
| Agreed payment windows | Ankur ANK/2610/234 (to 4 Dec), Indus IND/2610/884 (to 3 Dec), Raigad RAI/2610/203 (to 2 Dec) | Movable in scenarios up to the window end |
| In approval | 4 bills `PENDING_APPROVER` / `PENDING_FC` | Expected and downside views only, with confidence `pipeline` |
| Already received | Kalinga KPD/26-27/01479. A receipt of 20 Nov is `needs_review` with a 0.96 suggestion. | Excluded `SETTLED_PENDING_APPLICATION` |
| Disputed | Chambal KPD/26-27/01480 | Excluded `DISPUTED` |
| Very old | Thar KPD/26-27/01481, 74 days overdue | Expected view only. Downside view excludes it. |
| Promise to pay | Malabar KPD/26-27/01478, promised 26 Nov | Expected date = 26 Nov |
| Partly paid | Tapi KPD/26-27/01482 | Forecast only the outstanding remainder |
| Largest receivable | Sahyadri ₹14.5 L, due 28 Nov, customer median delay 21 days | Expected 19 Dec, downside 24 Dec (beyond horizon) |
| Calendar | 24 Nov holiday, 28 Nov and 12 Dec are 2nd/4th Saturdays, GST due Sun 20 Dec | Payroll on Mon 30 Nov, GST paid Sat 19 Dec, internet (12th) paid 14 Dec |

## Golden results (`seed/expected_forecast.json`)

| View / scenario | Lowest balance | On | First reserve breach | First negative | Closing 20 Dec |
|---|---:|---|---|---|---:|
| Expected | ₹9,99,874.24 | 30 Nov | 30 Nov | — | ₹78,96,847 |
| Downside | −₹32,44,064.26 | 30 Nov | 23 Nov | 30 Nov | ₹1,25,580 |
| No new collections | −₹1,36,51,288.76 | 19 Dec | 23 Nov | 26 Nov | −₹1,36,51,289 |
| Plan: defer 3 windowed bills (expected) | ₹19,13,700.24 | 23 Nov | none | — | ₹78,96,847 |
| Plan: defer 3 windowed bills (downside) | −₹17,66,767 | 2 Dec | 23 Nov | 30 Nov | ₹1,25,580 |
| Sahyadri pays 10 days later (expected) | ₹9,99,874.24 | 30 Nov | 30 Nov | — | ₹64,46,847 |

The demo story: the expected view breaches the reserve on payroll day. Deferring three bills inside their agreed windows fixes that. The downside view still needs collections or the CC line.

## Files (`seed/`)

| File | Maps to (production table) |
|---|---|
| `tenant.json` | `dim_tenants`, `users` (4 personas: owner = `finance_controller`, accountant, auditor, member) |
| `settings.json` | `cf_settings` + `cf_holidays` |
| `bank_accounts.json` | `dim_bank_accounts` + `cf_account_settings` |
| `bank_balances.json` | `cf_bank_balances` / latest `stg_bank_statements.running_balance` |
| `bank_statement_*.csv` | `stg_bank_statements` (import format) |
| `customers.json` | `ar_customers` |
| `ar_invoices.json`, `ar_payments.json`, `ar_applications.json` | `ar_invoices`, `ar_payments`, `ar_applications` |
| `collection_promises.json` | `cf_collection_promises` |
| `suppliers.json` | `dim_suppliers` |
| `ap_bills.json` | `fact_invoices` (`invoice_type='AP'`) + `stg_bills` (TDS, net payable, validation flag) |
| `payment_schedules.json` | `payment_schedules` |
| `payment_windows.json` | `cf_payment_windows` |
| `disbursements.json` | `fact_disbursements` |
| `recurring_items.json`, `adjustments.json` | `cf_recurring_items`, `cf_adjustments` |
| `scenarios.json` | `cf_scenarios` (baseline, plan, stress) |
| `expected_forecast.json` | Golden output: profiles, events, exclusions, 3 views, scenarios, category totals |

All money fields are integer paise (`*_paise`). The CSVs use rupees with two decimals, like real bank exports.

The second half of the generator is a **reference implementation** of [LLD §5](../04_LLD.md#5-algorithms). If a rule changes, change it there, regenerate, and update the docs' quoted numbers.
