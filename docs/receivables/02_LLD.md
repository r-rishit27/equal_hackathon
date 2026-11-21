# Cash Application Agent — Low-Level Design

Companion to [01_HLD.md](01_HLD.md). Code: `backend_ocr/app/receivables/`,
`backend_ocr/app/routers/receivables.py`, `frontend/src/pages/receivables/`.

---

## 1. Package layout

```
backend_ocr/app/receivables/
  schema.py          DDL (idempotent), applied by migrations._ensure_receivables_tables
  types.py           enums: PaymentStatus, InvoiceStatus, ReasonCode, JobReason, Method
  matching.py        PURE engine: identify customer → candidates → score → MatchResult
  policy.py          PURE: Policy (from ar_settings) → Decision(AUTO | REVIEW | UNMATCHED)
  detectors.py       PURE: non-receipt classifimonk forcast cashflow in cash application

campfire do -> churn rate analysis
Track expansion, contraction, and churn as it happens.


﻿﻿Invoice: The document sent to customers detailing products or services provided and payment terms. It's the foundation for matching payments in accounts receivable.
﻿﻿Payment: Funds received from customers through various methods, including checks processed through lockbox services, ACH transfers, wire transfers for larger amounts, and credit card payments processed through payment gateways
﻿﻿Remittance advice: A notification or document from the customer that confirms payment and includes details such as invoice numbers, amounts paid, and any adjustments. It shows up in email bodies and attachments, EDI files, bank file references, customer AP portals, or paper check stubs, and it often arrives separately from the money.
remittance data collection , payment capture and matching with remittance data

Applied Cash % = Applied Cash / Total Receipts × 100

Common Matching Clues
﻿﻿Invoice number
﻿﻿Customer account
﻿﻿Payment amount
﻿Purchase order
﻿﻿Bank reference


common issues:
Missing or incomplete remittance information
Multiple payment formats
Data capture issues  Payment data often comes from scattered sources (emails, bank files, vendor portals)

Partial payments and deductions

ERP inefficiencies: Entering payment data into outdated or disconnected systems slows reconciliation. Inefficiencies in an ERP system make it harder to track receivables and resolve payment remittances promptly.


Track cash application KPIs

Cash application KPIs are the metrics that show how efficiently and accurately your team applies payments. Monitor these key performance indicators to measure your process:

Match rate: The percentage of payments automatically matched on the first pass
Exception rate: The percentage of payments requiring manual intervention
Time to apply: The average time from payment receipt to posting (in hours or days)
Unapplied cash aging: A report showing how long payments have been sitting unmatched, usually grouped in buckets such as 0–30, 31–60, and 61+ days


AI-powered matching: The system should use artificial intelligence to learn your customer payment patterns over time, improving match rates continuously.
Multi-format remittance capture: Look for a solution that can automatically read and extract data from all remittance formats, including check stubs, EDI files, email bodies and attachments, and web portals.
Exception management: The software should provide a dedicated workflow to queue, route, and manage unmatched payments, giving your staff the context to resolve them quickly.
Reporting and analytics: Dashboards and reports are essential for tracking match rates, processing time, exception trends, and other key metrics.er, duplicate-payment, clue-conflict detectors
  bank_statement.py  PURE: statement → rows; narration → (rail, UTR, payer)
  remittance.py      remittance text/PDF → structured lines (LLM, via shared OCR engine)
  repo.py            CashAppRepository (asyncpg): all SQL, candidate retrieval, locking
  service.py         CashApplicationService: capture, match, apply, unapply, learn, audit
  worker.py          CashAppWorker(BaseWorker): drains ar_match_jobs
routers/receivables.py  /api/ar/* — thin: auth, validation, calls service
```

Pure modules have no I/O, so the whole decision surface is unit-tested without a DB.

## 2. Class diagram — backend

```mermaid
classDiagram
  direction LR

  class CashApplicationService {
    +repo: CashAppRepository
    +capture_statement(tenant, file, actor) ImportResult
    +capture_manual(tenant, PaymentIn, actor) Payment
    +add_remittance(tenant, text|file, actor) Remittance
    +ingest_invoice(tenant, ocr_payload, file, actor) Invoice
    +run_match(tenant, payment_id) MatchOutcome
    +apply(tenant, payment_id, allocations, method, version, actor)
    +unapply(tenant, payment_id, actor, reason)
    +mark_exception(tenant, payment_id, ReasonCode, note, actor)
    +mark_not_receipt(tenant, payment_id, actor)
    +reverse_bounced(tenant, payment_id, actor)
    -learn(tenant, payment, allocations)
  }

  class CashAppRepository {
    +pool: asyncpg.Pool
    +settings(tenant) Policy
    +insert_payments(tenant, rows) list~id~
    +enqueue(tenant, payment_ids, JobReason)
    +claim_jobs(limit) list~Job~
    +customers_for_payment(tenant, payer_norm, tokens) list~Customer~
    +invoices_by_tokens(tenant, tokens) list~OpenInvoice~
    +open_invoices(tenant, customer_id, limit) list~OpenInvoice~
    +invoices_near_amount(tenant, amount, tol) list~OpenInvoice~
    +paid_invoices_like(tenant, customer_id, amount) list~OpenInvoice~
    +remittance_for(tenant, payment) Remittance?
    +lock_payment(conn, tenant, id, version) Payment
    +lock_invoices(conn, tenant, ids) list~Invoice~
    +event(conn, tenant, entity, id, action, actor, payload)
  }

  class CashAppWorker {
    name = "cash_app"
    notify_channel = "ar_match"
    +process_batch() int
  }
  BaseWorker <|-- CashAppWorker
  CashAppWorker --> CashApplicationService

  class MatchingEngine {
    <<module matching.py>>
    +match_payment(Payment, customers, invoices, remittance, policy) MatchResult
    +identify_customer(...) (id, how, confidence)
    +invoice_referenced(number, text) bool
    +token_windows(text) set~str~
  }

  class Policy {
    +auto_apply_enabled: bool
    +auto_apply_threshold: Decimal
    +amount_tolerance: Decimal
    +writeoff_tolerance: Decimal
    +tds_rates: list~Decimal~
    +trust_learned_tds: bool
    +decide(MatchResult, flags) Decision
  }

  class Detectors {
    <<module detectors.py>>
    +classify_non_receipt(narration) str?
    +possible_duplicate(payment, paid_invoices, recent_payments) str?
    +clue_conflict(MatchResult) str?
    +is_bounce(narration) bool
  }

  class StatementParser {
    <<module bank_statement.py>>
    +parse_statement(bytes, filename) list~row~
    +parse_narration(text) (method, utr, payer)
    +fingerprint(row, occurrence) str
  }

  class RemittanceReader {
    <<module remittance.py>>
    +read_text(text) RemittanceData
    +read_pdf(path) RemittanceData
  }

  CashApplicationService --> CashAppRepository
  CashApplicationService --> MatchingEngine
  CashApplicationService --> Policy
  CashApplicationService --> Detectors
  CashApplicationService --> StatementParser
  CashApplicationService --> RemittanceReader
  RemittanceReader --> OcrEngine : text layer / vision
  class OcrEngine {
    <<utils/ocr_engine.py, shared with payables>>
    +process_pdf_async(path, ledger)
    +system_prompt(ledger, text_layer)
    +transcribe_scanned_pdf(path)
  }
```

### Matching value objects

```mermaid
classDiagram
  class Payment {
    +Decimal amount
    +date received_on
    +str payer_name
    +str narration
    +str reference
    +str customer_id
  }
  class Customer {
    +str id
    +str name
    +list aliases
    +Decimal tds_rate_hint
  }
  class OpenInvoice {
    +str id
    +str number
    +str customer_id
    +Decimal outstanding
    +Decimal total
    +Decimal taxable
    +date due_date
    +str po_number
    +bool untouched
  }
  class RemittanceLine {
    +str invoice_number
    +Decimal amount_paid
    +Decimal deduction_amount
    +str deduction_reason
  }
  class Allocation {
    +str invoice_id
    +Decimal amount_applied
    +Decimal tds_amount
    +Decimal deduction_amount
    +str reason_code
  }
  class Suggestion {
    +str kind
    +Decimal confidence
    +str customer_id
    +list clues
    +Decimal unapplied
  }
  class MatchResult {
    +str customer_id
    +str customer_how
    +Suggestion best
    +list alternatives
    +list flags
  }
  class Decision {
    +str action
    +str reason
  }
  Suggestion "1" o-- "*" Allocation
  MatchResult "1" o-- "0..4" Suggestion
```

## 3. Data model

```mermaid
erDiagram
  ar_settings ||--|| tenant : configures
  ar_customers ||--o{ ar_payer_aliases : "is paid under"
  ar_customers ||--o{ ar_invoices : owes
  ar_customers ||--o{ ar_payments : "identified as payer"
  ar_payments ||--o{ ar_applications : "is split into"
  ar_invoices ||--o{ ar_applications : "is settled by"
  ar_payments ||--o{ ar_remittances : "explained by"
  ar_payments ||--o{ ar_match_jobs : "queued as"
  ar_payments ||--o{ ar_events : audited
  ar_invoices ||--o{ ar_events : audited

  ar_customers {
    uuid id PK
    uuid tenant_id
    text name
    text name_norm "trigram-indexed"
    varchar gstin "unique per tenant"
    varchar pan "group key: same PAN = same group"
    int payment_terms_days
    numeric tds_rate_hint
  }
  ar_payer_aliases {
    uuid id PK
    uuid tenant_id
    text alias_norm "unique with customer_id"
    uuid customer_id FK
    varchar source "learned|manual|invoice"
    int confirmations
  }
  ar_invoices {
    uuid id PK
    uuid customer_id FK
    text invoice_number
    text number_norm "GENERATED, indexed"
    date invoice_date
    date due_date
    text po_number
    numeric taxable_amount
    numeric total_amount
    numeric amount_received
    numeric tds_amount
    numeric deduction_amount
    numeric outstanding "GENERATED"
    varchar status "open|partially_paid|paid|disputed|written_off|void"
    text storage_ref "object store, signed links only"
  }
  ar_payments {
    uuid id PK
    date received_on
    numeric amount
    varchar method "NEFT|RTGS|IMPS|UPI|CHQ|..."
    text utr
    text payer_name
    text narration
    varchar source "statement|manual|api"
    uuid customer_id FK
    varchar status
    numeric applied_amount
    jsonb suggestion
    numeric match_confidence
    bool auto_applied
    varchar reason_code
    int version "optimistic lock"
    text fingerprint "unique per tenant"
  }
  ar_applications {
    uuid id PK
    uuid payment_id FK
    uuid invoice_id FK
    numeric amount_applied
    numeric tds_amount
    numeric deduction_amount
    varchar reason_code "TDS|DISCOUNT|BANK_CHARGES|ROUNDING|..."
    varchar method "auto|accepted|manual"
    timestamptz reversed_at "append-only; reversal never deletes"
  }
  ar_remittances {
    uuid id PK
    uuid payment_id FK "null until linked"
    text payment_reference
    numeric total_amount
    jsonb lines
    varchar status "unlinked|linked|conflict"
  }
  ar_match_jobs {
    uuid id PK
    uuid payment_id FK
    varchar reason "new_payment|remittance|new_invoice|alias_learned|manual|sweep"
    varchar status "PENDING|RUNNING|DONE|FAILED"
    int attempts
    timestamptz run_after
  }
  ar_events {
    uuid id PK
    varchar entity
    uuid entity_id
    varchar action
    text actor "user or 'agent'"
    jsonb payload
  }
```

Key indexes:

| Index | Serves |
|---|---|
| `ar_invoices (tenant_id, number_norm)` | invoice-number token lookup |
| `ar_invoices (tenant_id, customer_id, due_date) WHERE status IN ('open','partially_paid')` | oldest-first candidates |
| `ar_invoices (tenant_id, outstanding) WHERE status IN ('open','partially_paid')` | amount-near lookup when payer unknown |
| `ar_payer_aliases (tenant_id, alias_norm)` | exact payer → customer |
| `ar_customers USING gin (name_norm gin_trgm_ops)` | fuzzy payer → customer (top 5) |
| `ar_payments (tenant_id, fingerprint) UNIQUE` | idempotent import |
| `ar_payments (tenant_id, utr)` | cross-source dedupe, remittance linking |
| `ar_match_jobs (status, run_after) WHERE status='PENDING'` | job claim |
| `ar_match_jobs (payment_id) UNIQUE WHERE status IN ('PENDING','RUNNING')` | job coalescing |

## 4. State machines

### Payment

```mermaid
stateDiagram-v2
  [*] --> unmatched : captured (job enqueued)
  unmatched --> applied : agent — exact match (auto)
  unmatched --> needs_review : agent — plausible suggestion
  unmatched --> unmatched : agent — nothing fits (waits for remittance / invoice)
  unmatched --> not_receipt : agent — interest, refund, own transfer (reversible)
  needs_review --> applied : human accepts / edits (fully allocated)
  needs_review --> partially_applied : human applies part, rest on account
  unmatched --> partially_applied : human applies part
  partially_applied --> applied : later remittance / invoice → human or exact agent match of remainder
  applied --> unmatched : human unapplies (re-match queued)
  partially_applied --> unmatched : human unapplies
  needs_review --> exception : human flags (dispute, duplicate, FX, ...)
  unmatched --> exception : human flags
  exception --> unmatched : human resolves → re-match
  applied --> reversed : bounce / recall (human confirms)
  not_receipt --> unmatched : human restores
  reversed --> [*]
```

### Invoice

```mermaid
stateDiagram-v2
  [*] --> open : ingested
  open --> partially_paid : part applied
  open --> paid : outstanding ≤ 0
  partially_paid --> paid
  partially_paid --> open : application reversed
  paid --> partially_paid : application reversed
  open --> disputed : human puts on hold (excluded from auto)
  disputed --> open : resolved
  partially_paid --> written_off : human writes off residual
  open --> void : cancelled / replaced by revised invoice
```

### Match job

```mermaid
stateDiagram-v2
  [*] --> PENDING
  PENDING --> RUNNING : claimed (SKIP LOCKED)
  RUNNING --> DONE
  RUNNING --> PENDING : error, attempts < 5 (backoff run_after)
  RUNNING --> FAILED : attempts ≥ 5
  RUNNING --> PENDING : process died (stale sweep on start)
```

## 5. Sequences

### 5.1 Statement import → auto-apply

```mermaid
sequenceDiagram
  actor U as Finance user
  participant API as /api/ar/payments/import
  participant SP as StatementParser
  participant R as Repository
  participant W as CashAppWorker
  participant E as MatchingEngine
  participant P as Policy
  participant S as Service.apply

  U->>API: upload statement.xlsx
  API->>SP: parse_statement(bytes)
  SP-->>API: credits[] (+ rail, UTR, payer, fingerprint)
  API->>R: insert_payments ON CONFLICT (fingerprint) DO NOTHING
  API->>R: enqueue(new ids, new_payment) + NOTIFY ar_match
  API-->>U: 200 {imported, duplicates_skipped, not_receipts}
  W->>R: claim_jobs(50) FOR UPDATE SKIP LOCKED
  loop each job
    W->>R: candidates (aliases, token invoices, customer's open, near-amount, remittance)
    W->>E: match_payment(...)
    E-->>W: MatchResult(best, alternatives, flags)
    W->>P: decide(result)
    alt AUTO
      W->>S: apply(method=auto, actor=agent)
    else REVIEW / UNMATCHED
      W->>R: save suggestion, status
    end
  end
```

### 5.2 Human accepts a suggestion

```mermaid
sequenceDiagram
  actor U
  participant API as POST /api/ar/payments/{id}/apply
  participant S as Service
  participant DB as Postgres
  U->>API: allocations[], version
  API->>S: apply(...)
  S->>DB: BEGIN; SELECT payment FOR UPDATE (version check → 409)
  S->>DB: SELECT invoices FOR UPDATE ORDER BY id
  S->>S: validate Σ applied ≤ unapplied; per invoice applied+tds+deduction ≤ outstanding + tol
  S->>DB: INSERT ar_applications; UPDATE invoices; UPDATE payment (status, version+1)
  S->>DB: learn: upsert alias, tds_rate_hint; INSERT ar_events
  S->>DB: COMMIT
  API-->>U: payment + applications
```

### 5.3 Late remittance re-splits an on-account payment

```mermaid
sequenceDiagram
  participant API as POST /api/ar/remittances
  participant RR as RemittanceReader
  participant R as Repository
  participant W as Worker
  API->>RR: read_text / read_pdf
  RR-->>API: lines[], reference, total
  API->>R: find payment: UTR = reference → else amount±tol & date±10d & unique
  alt linked
    API->>R: remittance.payment_id = p; enqueue(p, remittance)
    W->>W: re-match: if payment untouched by a human → normal policy
    W->>W: if a human already applied differently → status needs_review, flag REMITTANCE_DISAGREES
  else not linked
    API->>R: status unlinked — linked automatically when the payment is imported
  end
```

## 6. Algorithms

### 6.1 Customer identification (strongest first)

| # | Signal | Confidence |
|---|---|---|
| 1 | User chose the customer | 1.00 |
| 2 | Normalised payer name = a confirmed alias of exactly one customer | 1.00 |
| 2a | Alias maps to several customers (group company / shared payer) | → flag `AMBIGUOUS_PAYER`, review |
| 3 | Invoice number(s) quoted in narration all belong to one customer | 1.00 |
| 4 | Remittance names invoices of one customer | 1.00 |
| 5 | Trigram top-5 → rapidfuzz `token_set_ratio` ≥ 90 | 0.90 |
| 6 | Same, 80–89 | 0.75 |
| 7 | None | — (amount-only search across tenant, never auto) |

Name normalisation drops `M/S, PVT, PRIVATE, LTD, LIMITED, LLP, INDIA, THE, CO…`,
punctuation and case: `M/s. Acme Trading Pvt. Ltd.` → `ACME TRADING`.

### 6.2 Invoice reference detection (`token_windows`)

Narrations break numbers apart (`INV 24-25 0045`). The text is split on non-alphanumerics
and every window of 1–4 adjacent tokens is concatenated and normalised; the set is looked
up by equality on `number_norm` — one indexed query, no `LIKE '%…%'`. Short all-digit
numbers (< 6 digits) must stand alone in the raw text so `1045` never matches inside a UTR.

### 6.3 Candidate generation and base confidence

Final confidence = base × customer confidence (for customer-scoped candidates).

| Kind | Rule | Base |
|---|---|---|
| `remittance` | every remittance line resolves and Σ paid = amount (±tol) | 1.00 |
| `remittance_partial` | some lines unresolved or Σ ≠ amount | 0.80 |
| `reference_exact` | quoted invoices' outstanding Σ = amount | 1.00 |
| `reference_tds` | quoted invoices Σ(outstanding − r·taxable) = amount for one rate r | 0.92 |
| `reference_partial` | amount < quoted Σ → fill oldest first, rest open | 0.75 |
| `reference_overpaid` | amount > quoted Σ → rest on account | 0.80 |
| `amount_exact` | exactly one of the customer's open invoices = amount | 0.97 |
| `amount_exact_ambiguous` | several equal invoices → oldest | 0.70 |
| `amount_tds` | exactly one invoice net of TDS at r (customer's usual r first) | 0.85 (0.90 at learned rate) |
| `oldest_first` | prefix of oldest invoices sums to amount | 0.88 |
| `combination` | unique 2–4-invoice subset (gross or net of one TDS rate) | 0.82 |
| `combination_ambiguous` | several subsets | 0.60 |
| `oldest_partial` | amount < oldest invoice | 0.50 |
| `overpaid` | amount > everything owed | 0.60 |
| `amount_only` | payer unknown; one invoice tenant-wide equals amount | 0.60 |

TDS is computed on the **taxable value** (pre-GST); if the invoice has no taxable value the
total is used and the suggestion says so. TDS is only considered on an **untouched**
invoice (nothing yet received).

### 6.4 Flags (always force review, regardless of confidence)

| Flag | Raised when |
|---|---|
| `CLUE_CONFLICT` | quoted invoice ≠ the invoice the amount matches |
| `POSSIBLE_DUPLICATE` | amount equals an invoice of this customer that is already **paid**, or a payment with same amount/payer within 7 days already applied to it |
| `AMBIGUOUS_PAYER` | alias maps to more than one customer |
| `CROSS_CUSTOMER` | allocations span customers (group payment) |
| `ADVANCE` | payment date before the invoice date |
| `FOREIGN_CURRENCY` | invoice currency ≠ INR |
| `REMITTANCE_DISAGREES` | late remittance contradicts a human's application |
| `DISPUTED_INVOICE` | candidate invoice is on hold |

### 6.5 Decision policy

```
if payment is not_receipt/reversed/exception           → no action
if flags                                               → REVIEW
if best is None                                        → UNMATCHED
if best.kind in AUTO_KINDS and conf ≥ threshold
   and auto_apply_enabled and no deduction other than rounding   → AUTO
if best.kind == amount_tds/reference_tds and trust_learned_tds
   and rate == customer.tds_rate_hint and conf ≥ threshold      → AUTO
else                                                   → REVIEW
AUTO_KINDS = {remittance, reference_exact, amount_exact}
```

Residual within `writeoff_tolerance` (default 0 = off) is written off as `ROUNDING`/
`BANK_CHARGES` only when the tenant enabled it.

### 6.6 Application invariants (enforced in `apply`, in one transaction)

1. `Σ amount_applied ≤ payment.amount − payment.applied_amount` (+ ₹0.01)
2. per invoice: `amount_applied + tds + deduction ≤ outstanding + tolerance`
3. invoice must be `open | partially_paid` (not disputed/void/written-off) unless the
   caller is a human who explicitly overrides
4. `version` matches, else 409 (somebody — or the agent — changed it)
5. negative application only via `unapply` (reversal), never edits

### 6.7 Learning

On every human-confirmed application:
- upsert `(alias_norm(payer_name) → customer)` with `confirmations += 1`;
- if a TDS line was confirmed: `tds_rate_hint = round(tds / taxable × 100, 3)`;
- enqueue `alias_learned` jobs for that customer's other `unmatched` payments.

## 7. Job queue

```sql
-- claim
UPDATE ar_match_jobs SET status='RUNNING', locked_at=now(), attempts=attempts+1
 WHERE id IN (SELECT id FROM ar_match_jobs
               WHERE status='PENDING' AND run_after <= now()
               ORDER BY run_after LIMIT $1 FOR UPDATE SKIP LOCKED)
RETURNING id, tenant_id, payment_id, reason;
-- enqueue (coalesces: one live job per payment)
INSERT INTO ar_match_jobs (tenant_id, payment_id, reason) VALUES (...)
ON CONFLICT (payment_id) WHERE status IN ('PENDING','RUNNING') DO NOTHING;
SELECT pg_notify('ar_match', '');
```

Triggers for enqueue: new payment (statement import / manual entry), remittance added
(its linked payment, or — when it can't be linked on arrival — the waiting payments of about
its amount, each of which links it only by UTR or by amount + date + a fitting payer name),
invoice ingested (the customer's waiting payments and payer-unknown ones), alias learned or
added, unapply (re-matched, never auto-applied), exception resolved / receipt restored,
and a sweep of `unmatched` payments older than a day.

**Every upload is matched straight away.** The repository records the payments a request
queues; the route hands them to `CashApplicationService.drain` as a background task that
runs right after the response, claiming only those payments' jobs (`FOR UPDATE SKIP
LOCKED`). So a statement, remittance, invoice or alias is acted on within seconds whether or
not `CashAppWorker` runs; the worker remains the safety net for retries, overflow (> 500
payments in one upload) and the sweep. The Cash Application page polls every 3 s for 30 s
after any upload so the results appear.

## 8. API contract (`/api/ar`, service `receivables`)

| Method | Path | Body / query | Returns |
|---|---|---|---|
| GET | `/summary` | `days=30` | KPIs, aging, AR totals |
| GET | `/settings` · PUT `/settings` | Policy fields | Policy |
| POST | `/invoices/ingest` | `{payload}` (OCR result, `_ledger=receivable`) | invoice |
| GET | `/invoices` | `status, customer_id, q, limit, offset` | page |
| GET | `/invoices/{id}` | | invoice + applications |
| PATCH | `/invoices/{id}` | `status: disputed|open|void`, fields | invoice |
| GET | `/invoices/{id}/document` | `signed=1` | PDF / signed link |
| GET | `/customers` · POST `/customers` | | list / customer |
| GET | `/customers/{id}` · PATCH | aliases, terms, contacts | customer + invoices + payments |
| GET | `/payments` | `status, customer_id, q, limit, offset` | page |
| POST | `/payments` | manual payment | payment (job queued) |
| POST | `/payments/import` | multipart `file`, `bank_account` | `{imported, duplicates, not_receipts}` |
| GET | `/payments/{id}` | | payment + suggestion + alternatives + candidate invoices + applications + remittances + events |
| POST | `/payments/{id}/match` | | re-runs synchronously, returns suggestion |
| POST | `/payments/{id}/apply` | `{allocations[], customer_id?, version, method}` | payment |
| POST | `/payments/{id}/unapply` | `{reason}` | payment |
| POST | `/payments/{id}/exception` | `{reason_code, note}` | payment |
| POST | `/payments/{id}/resolve` | | payment (re-match queued) |
| POST | `/payments/{id}/not-receipt` · `/restore` | | payment |
| POST | `/remittances` | multipart `file` or `text` | remittance + linked payment |
| GET | `/remittances` | `status` | list |

Money is serialised as strings. All writes record an `ar_events` row.

## 9. Frontend

```mermaid
classDiagram
  class Sidebar { ledger: payable|receivable; LedgerSwitch }
  class UploadPage { ledger prop → ocrInvoice(file, ledger) }
  class ArInvoiceReviewPage { pdf + editable fields → ingest }
  class CashApplicationPage { KpiStrip; tabs: review|unmatched|applied|all|remittances }
  class PaymentWorkbench { suggestion + clues; AllocationEditor; actions }
  class AllocationEditor { rows: invoice, applied, TDS, deduction, reason; totals }
  class ArInvoicesPage { DataTable; status tabs; detail drawer }
  class ArCustomersPage { DataTable; detail: aliases, invoices, payments }
  class ImportStatementModal
  class RemittanceModal
  class RecordPaymentModal
  CashApplicationPage --> PaymentWorkbench
  PaymentWorkbench --> AllocationEditor
  CashApplicationPage --> ImportStatementModal
  CashApplicationPage --> RemittanceModal
  CashApplicationPage --> RecordPaymentModal
  UploadPage --> ArInvoiceReviewPage : ledger=receivable
```

Routes: `/receivables/cash-application`, `/receivables/invoices`,
`/receivables/upload` (+ `/review`), `/receivables/customers[/:id]`. The sidebar's ledger
switch is derived from the path (`/receivables/*` → receivable) and remembered for
neutral pages.
