# Reckon.ai

> Finance operations for payables, receivables, and working capital.

Reckon.ai brings invoice capture, vendor reconciliation, tax review, approvals, payouts, cash application, and cash flow forecasting into one workspace. This README describes the code on `dev`, including the tenant-licensed workflows and deployment configurations checked into the repository.

---

## Table of Contents

1. [Product Overview](#1-product-overview)
2. [System Architecture](#2-system-architecture)
   - [Application architecture](#application-architecture)
   - [Components and integrations](#components-and-integrations)
   - [Payables flow](#payables-flow)
   - [Receivables flow](#receivables-flow)
   - [Deployment architecture](#deployment-architecture)
3. [Technology Stack](#3-technology-stack)
4. [Data Model & Table Taxonomy](#4-data-model--table-taxonomy)
5. [Pipeline Engine](#5-pipeline-engine)
   - 5.1 [Upload / OCR Worker](#51-upload--ocr-worker)
   - 5.2 [Staging Promotion Worker](#52-staging-promotion-worker)
   - 5.3 [Deduplication Worker](#53-deduplication-worker)
   - 5.4 [Approval Workflow Worker](#54-approval-workflow-worker)
   - 5.5 [API Sync Worker](#55-api-sync-worker)
   - 5.6 [Webhook Worker](#56-webhook-worker)
   - 5.7 [Tally Read Worker](#57-tally-read-worker)
   - 5.8 [GST Verification Worker](#58-gst-verification-worker)
   - 5.9 [Bank Verification Worker](#59-bank-verification-worker)
   - 5.10 [Category Enrichment Worker](#510-category-enrichment-worker)
   - 5.11 [Expense Report Generator](#511-expense-report-generator)
   - 5.12 [TDS Processing Worker](#512-tds-processing-worker)
   - 5.13 [Tally Sync Worker](#513-tally-sync-worker)
6. [Backend API Reference](#6-backend-api-reference)
7. [Configuration Reference](#7-configuration-reference)
8. [Enumerations](#8-enumerations)
9. [Indian Fiscal Calendar](#9-indian-fiscal-calendar)
10. [Testing](#10-testing)
11. [Running Locally](#11-running-locally)
12. [Repository Structure](#12-repository-structure)
13. [Audit Trail (`wf_audit_log`)](#13-audit-trail-wf_audit_log)
14. [Key Design Decisions](#14-key-design-decisions)

---

## 1. Product Overview

Reckon.ai helps finance teams manage accounts payable, accounts receivable, and working capital from a single workspace. Teams can capture bills, check them against supporting documents, route approvals, and track payment status. On the receivables side, they can import bank credits, match them to sales invoices, and review exceptions before applying cash.

| Workflow | What teams can do |
|---|---|
| **Bill capture and coding** | Upload invoices individually or in bulk, review AI-assisted document extraction, turn mailbox attachments into bill drafts, and suggest ledgers using chart-of-accounts rules. |
| **Vendor reconciliation** | Link bills to purchase orders, goods receipts, and delivery evidence. Compare quantities, rates, and line totals. Review discrepancies, correct evidence, and rerun cases. Vendor-specific checks can also compare bills with configured commercial terms. |
| **Approvals and payments** | Route bills through approval and exception queues. Eligible users can initiate single or bulk IMPS payouts, confirm by OTP, track gateway status, and issue receipts. Administrative beneficiary overrides are audited. |
| **Vendor records and tax** | Maintain GSTINs, bank accounts, contacts, and documents. Verify supported GSTIN, PAN, and bank details, and configure TDS sections, thresholds, rules, and vendor overrides. |
| **WhatsApp communication agent** | Connect a Twilio WhatsApp sender in Integrations. In Agent Hub, enable intake and watch vendor contacts. PDF invoices enter Bills → Drafts for review. Eligible text goes to the Communication Agent for terms extraction and Review Hub findings. Staff can reply within the vendor’s 24-hour window and track delivery. [Setup and rollout status](docs/whatsapp-agent/08-implementation-and-runbook.md) |
| **Cash flow forecast** | Project daily bank cash over 30 days. Compare expected, downside and no-collections views, inspect the events behind a reserve breach, and submit a scenario as a plan for approval. |
| **Receivables and cash application** | Capture sales invoices, import PDF/CSV/XLSX statements, add remittance advice, match credits to invoices, and apply or reverse allocations. The review board surfaces exceptions and cash-application KPIs. |
| **Reporting and review** | Inspect spend, outstanding balances, and approval activity. Export expense data in XLSX or CSV and review findings across bills, vendors, and related records. |
| **Review Hub and Agent Hub** | Triage findings, inspect evidence, and resolve or snooze exceptions in Review Hub. Agent Hub surfaces watched contacts, mailbox activity, and vendor invoice drafts for review. |
| **Vendor Playground** | Build and run a visual workflow from a licensed vendor card. Use document and data nodes to structure vendor-specific checks and inspect their results. |
| **Nova billing reconciliation** | Compare vendor invoices with Nova usage and certified rates. Review saved results by vendor and service month, or inspect the upstream billing response in the Raw Nova API view. |
| **Tenant and brand administration** | Switch brands in the workspace and manage roles, approval chains, mappings, and integrations. The separate operations console manages tenant service licensing. |

| Where to start | Paths |
|---|---|
| Payables | `/dashboard`, `/upload`, `/bills`, `/vendors`, `/payments` |
| Review and automation | `/review`, `/review/browse`, `/agent-hub`, `/nova` |
| Insights / Cash flow forecast | `/finance-desk/cash-forecast` (requires the `cash_forecast` tenant entitlement) |
| Receivables | `/receivables/cash-application`, `/receivables/invoices`, `/receivables/customers` |
| Reporting and setup | `/reports`, `/data-extraction`, `/integrations`, `/settings` |

Vendor reconciliation and its dashboard are available from the vendor card's **Documents** view. **Playground** has its own vendor-card tab. The tenant's service plan and the signed-in user's role determine which workflows are available. [Route map](frontend/src/routes/paths.ts) · [Service catalog](backend_ocr/app/security/services.py)

<details>
<summary><strong>Connector coverage and deployment requirements</strong></summary>

| Integration | Scope |
|---|---|
| **Tally Prime** | The Windows connector pulls XML ledgers and vouchers from Tally, then uploads them to Reckon.ai. Server-side Tally workers are available in the code and disabled in the default worker list. |
| **Apideck and SAP** | The ingestion pipeline normalizes Apideck accounting payloads. The SAP workflow supports item and vendor-code mapping. Connector direction and posting behavior depend on the integration. |
| **Banking** | The payout integration centers on IMPS and gateway status checks. Receivables has a separate bank-statement import and cash application flow. |
| **AI and vendor verification** | OCR, email processing, vendor verification, and bank calls depend on the configured provider, credentials, and tenant entitlements. |

[Tally connector](tally_agent/agent.py) · [Accounting ingestion](pipelines/api_sync.py) · [SAP mapping](backend_ocr/app/routers/item_mapping.py) · [Payment API](backend_ocr/app/routers/disbursement.py)

</details>

<details>
<summary><strong>Roles, controls, and audit</strong></summary>

- Authentication identifies the caller and tenant. Service licensing and capability checks govern access to gated workflows.
- Payables approval and payout confirmation are distinct steps. OTP, beneficiary checks, and audited administrative overrides apply to disbursement. Configured demo modes can simulate gateway activity.
- Review Hub records changes and selected before-and-after values. Workflow audit records, payment events, and receivables actions provide additional history. Selected stored credentials, including email OAuth tokens and Nova API keys, use Fernet encryption.
- Matching policies can auto-apply eligible incoming receipts. Ambiguous cases are routed for human review, and applied allocations can be reversed through the receivables workflow.

[Licensing and administration](docs/administration/LICENSING_AND_ADMIN.md) · [Payment guardrails](docs/payments_docs/PAYMENT_GUARDRAILS.md) · [Review audit](backend_ocr/app/review/audit.py) · [Cash application controls](docs/receivables/05_HUMAN_IN_THE_LOOP.md)

</details>

<details>
<summary><strong>Technical documentation by workflow</strong></summary>

| Topic | Reference |
|---|---|
| API composition and ownership | [Backend structure](docs/architecture/BACKEND_STRUCTURE.md) |
| Payables reconciliation and document evidence | [Reconciliation agent](docs/reconciliation/RECON_AGENT.md) |
| Receivables matching, settlement, and exception handling | [Cash application overview](docs/receivables/README.md) · [User flows](docs/receivables/03_USER_FLOWS.md) |
| Review Hub and communication agents | [Design and implementation](docs/review/HLD_LLD_COMM_COMPLIANCE_REVIEWHUB.md) |
| Tax, COA, and FX | [TDS configuration](docs/finance-operations/TDS_SETTINGS_IMPLEMENTATION_PLAN.md) · [COA rules and reports](docs/finance-operations/COA_RULES_AND_REPORTS.md) · [FX workflows](docs/finance-operations/FX_CURRENCY_STANDARDIZATION.md) |
| Nova billing reconciliation | [Standalone reconciliation service](docs/nova/README.md) |
| Cash flow forecast | [Setup and tests](docs/cashflow-forecast/README.md) · [Service architecture](docs/architecture/ARCHITECTURE.md#310-cash-flow-forecast) · [User flows](docs/cashflow-forecast/05_USER_FLOWS.md) |
| Finance Desk proposal | [PRD, requirements, architecture, and delivery plan](docs/finance-desk/README.md) |
| Deployment, database, and API migrations | [UAT2 deployment](docs/aws-deploy/DEV_ENVIRONMENT.md) · [Database schema reference](docs/architecture/full_database_schema.md) · [Migration runner](scripts/run_api_migrations.py) |

</details>

---

## 2. System Architecture

The React workspace calls FastAPI over REST and multipart uploads. FastAPI and a separate Python worker process coordinate through PostgreSQL. The API also hosts background agents and status sweepers. Tenant configuration and service flags control which integrations and optional workers are available.

### Application architecture

<img width="1582" height="886" alt="image" src="https://github.com/user-attachments/assets/e7248e67-6032-4908-9f07-9037ecfdbb72" />

[Open the interactive application diagram](docs/aws-deploy/system-architecture.html) to highlight a workflow, inspect its steps, or pause the animation.

<details>
<summary>Cash flow forecast and Twilio WhatsApp service diagrams</summary>

**Cash flow forecast**

![Bank and ledger inputs feed a daily cash forecast, scenario preview and plan decision](docs/aws-deploy/cash-flow-forecast.png)

**WhatsApp communication**

![Twilio inbound PDFs and text flow to bill review or terms extraction, with a separate reply and delivery path](docs/aws-deploy/whatsapp-communication.png)

[Diagram sources and service boundaries](docs/architecture/ARCHITECTURE.md#310-cash-flow-forecast)

</details>

### Finance automation workspace

| Screen | What the finance team can do |
|---|---|
| Agent Hub · `/agent-hub` | Open agent findings and evidence, inspect the Fact Graph, check a recent invoice, and enable or pause mailbox scanning. The Communication card stays live while its scanner is paused. |
| CFO Orchestrator · `/cfo-orchestrator` | Select an invoice, run the five-stage control review, and inspect the evidence behind each passed, review or blocked result. Available to admins and finance controllers with Agent Hub access. |
| Bills and Payment Hub · `/bills`, `/payments` | Switch brands to refresh approval badges, notifications, outstanding bills, payment history and bank-specific transaction totals. The Acme workspace switcher offers Acme group, Bata India Limited and Diensten Tech Limited. |

The CFO review reads the vendor master, reconciliation case, approval decision and payment records. Payment authorization stays in the payment workflow. See the [control sequence and API contract](docs/architecture/ARCHITECTURE.md#cfo-invoice-controls) and the [standalone agent commands](docs/agent-hub/agent-runtime.md).

### Components and integrations

```mermaid
flowchart LR
    People["Finance users"] --> Web["React · TypeScript · Vite"]
    Web -->|REST and multipart| API["FastAPI · Uvicorn"]
    Tally["Tally Prime · Windows connector"] -->|Voucher and ledger XML| API
    Sources["Accounting feeds · payment webhooks"] -->|Inbound payloads| DB[("PostgreSQL")]
    API -->|Tenant data and workflow state| DB
    API -->|Upload and retrieval| Files[("Document storage · local or S3")]
    API -->|Gated background tasks| Agents["Review · recon · cash application"]
    Agents -->|Jobs and findings| DB
    Twilio["Twilio WhatsApp"] -->|Signed inbound and delivery callbacks| API
    API --> WA["WhatsApp intake worker and reply outbox"]
    WA -->|PDF drafts and communication claims| DB
    WA -->|Authorized replies| Twilio
    API --> Forecast["Cash flow forecast module"]
    DB -->|Bank balances and AP/AR events| Forecast
    Forecast -->|Snapshots and plan decisions| DB
    DB <-->|Queries and LISTEN / NOTIFY| Workers["Python pipeline workers"]
    API --> Providers["OCR · email · KYB providers"]
    Workers --> Providers
    API -->|IMPS and status checks| Bank["Bank gateway"]
    Web -->|Nova dashboard and raw explorer| Nova["Nova reconciliation service"]
    Nova -->|Saved runs and tenant configuration| DB
    Nova -->|Vendor usage by month| NovaUpstream["Nova billing API"]

    classDef client fill:#dbeafe,stroke:#2563eb,color:#172554;
    classDef compute fill:#ede9fe,stroke:#7c3aed,color:#2e1065;
    classDef data fill:#ccfbf1,stroke:#0f766e,color:#042f2e;
    classDef external fill:#ffedd5,stroke:#c2410c,color:#431407;
    class People,Web client;
    class API,Agents,Workers,Nova,Forecast,WA compute;
    class DB,Files data;
    class Tally,Sources,Providers,Bank,NovaUpstream external;
```

<details>
<summary><strong>Read the architecture diagram as text</strong></summary>

1. Finance users work in the React UI. The API handles authentication, tenant-scoped HTTP requests, uploads, and service licensing.
2. PostgreSQL stores raw input, staged records, financial facts, workflow state, and reconciliation jobs. Documents use local storage or S3 depending on deployment.
3. The standalone pipeline processes source data, OCR jobs, staging, deduplication, tax, and approval follow-up using PostgreSQL notifications or polling. API-hosted tasks handle Review Hub, optional reconciliation and cash application, and payment status sweeps.
4. Provider boundaries include the Windows Tally connector, OCR/email/KYB integrations, the IMPS gateway, and a separate Nova reconciliation service.

[Application composition](backend_ocr/app/main.py) · [Pipeline process](main.py) · [Background scheduler](backend_ocr/app/review/scheduler.py) · [Document storage](backend_ocr/app/core/object_store.py)

</details>

### Payables flow

```mermaid
flowchart TD
    Intake["Upload · mailbox or WhatsApp draft · accounting feed"] --> Capture["Extract or normalize bill data"]
    Capture --> Stage["Validate · check duplicates · stage"]
    Stage -->|Eligible bill| Bill["Bill record"]
    Stage -->|Duplicate or anomaly| Review["Review evidence and exceptions"]
    Bill --> Evidence["Reconcile PO and receipt evidence · resolve coding and tax"]
    Evidence --> Approval{"Approval complete?"}
    Approval -->|Needs action| Review
    Review -->|Correct and resubmit| Evidence
    Approval -->|Approved| Pay["Payment request · beneficiary checks"]
    Pay --> OTP{"OTP confirmed?"}
    OTP -->|Yes| Gateway["Submit IMPS payout"]
    OTP -->|Pending or expired| Pay
    Gateway --> Settle["Track status · settle on confirmation · issue receipt"]

    classDef input fill:#dbeafe,stroke:#2563eb,color:#172554;
    classDef process fill:#ede9fe,stroke:#7c3aed,color:#2e1065;
    classDef review fill:#fef3c7,stroke:#b45309,color:#451a03;
    classDef outcome fill:#dcfce7,stroke:#15803d,color:#052e16;
    class Intake input;
    class Capture,Stage,Bill,Evidence,Pay,Gateway process;
    class Review,Approval,OTP review;
    class Settle outcome;
```

The diagram shows the end-to-end path when the relevant services are configured. Reconciliation and approvals can involve separate queues, and a confirmed payment can settle immediately or after a provider status check.

### Receivables flow

```mermaid
flowchart TD
    Invoices["Sales invoices and customer records"] --> Match["Identify payer · generate candidate allocations"]
    Credits["Statement import or manual credit"] --> Parse["Extract date · amount · payer · UTR"]
    Parse --> Match
    Advice["Remittance advice"] --> Match
    Match --> Policy{"Matches satisfy automation policy?"}
    Policy -->|Eligible| Apply["Apply cash to invoice balances"]
    Policy -->|Ambiguous or unmatched| Board["Cash application review board"]
    Board -->|Accept or allocate manually| Apply
    Board -->|Need more evidence| Advice
    Apply --> Metrics["Update balances · history · KPIs"]
    Apply -->|Reverse allocation| Board

    classDef input fill:#dbeafe,stroke:#2563eb,color:#172554;
    classDef process fill:#ede9fe,stroke:#7c3aed,color:#2e1065;
    classDef review fill:#fef3c7,stroke:#b45309,color:#451a03;
    classDef outcome fill:#dcfce7,stroke:#15803d,color:#052e16;
    class Invoices,Credits,Advice input;
    class Parse,Match process;
    class Policy,Board review;
    class Apply,Metrics outcome;
```

[Payables reconciliation lifecycle](docs/reconciliation/RECON_AGENT.md) · [Receivables user flows](docs/receivables/03_USER_FLOWS.md)

### Deployment architecture

The repository documents an AWS topology with Amplify serving the static frontend, an EC2 reverse proxy terminating HTTPS for the APIs, and PostgreSQL on RDS. Nova runs as a separate process. These are deployment configurations from the repository. The live host, branch mappings, and enabled services are set in the deployment environment.

```mermaid
flowchart LR
    Git["GitHub repository"] -->|"npm ci and npm run build"| Amplify["AWS Amplify<br/>Static frontend and prerendered pages"]
    User["Finance workspace"] -->|HTTPS| Amplify
    User -->|"API and Nova base URLs"| Proxy

    subgraph EC2["AWS EC2"]
        Proxy["Nginx<br/>HTTPS and route prefixes"]
        Prod["Production API<br/>FastAPI and Uvicorn"]
        Dev["Development API<br/>Separate systemd unit"]
        Pipeline["Pipeline worker process"]
        Nova["Nova reconciliation service<br/>Separate Uvicorn process"]
        Proxy -->|Production API| Prod
        Proxy -->|Development API| Dev
        Proxy -->|Configured Nova route| Nova
    end

    RDS[("Amazon RDS<br/>PostgreSQL")]
    S3[("Amazon S3<br/>Document objects")]
    CDN["CloudFront<br/>Optional signed document delivery"]
    Providers["OCR, email, verification,<br/>banking and Nova providers"]

    Prod --> RDS
    Dev --> RDS
    Pipeline <-->|Queries and notifications| RDS
    Nova --> RDS
    Prod -->|When configured| S3
    Dev -->|When configured| S3
    CDN --> S3
    User -.->|Signed download| CDN
    Prod --> Providers
    Pipeline --> Providers
    Nova --> Providers

    classDef entry fill:#dbeafe,stroke:#1d4ed8,color:#172554;
    classDef compute fill:#ede9fe,stroke:#6d28d9,color:#2e1065;
    classDef storage fill:#ccfbf1,stroke:#0f766e,color:#134e4a;
    classDef external fill:#ffedd5,stroke:#c2410c,color:#431407;
    class Git,User,Amplify,CDN entry;
    class Proxy,Prod,Dev,Pipeline,Nova compute;
    class RDS,S3 storage;
    class Providers external;

    click Amplify href "https://github.com/r-rishit27/equal_hackathon/blob/main/frontend/amplify.yml" "Open the Amplify build spec" _blank
    click Proxy href "https://github.com/r-rishit27/equal_hackathon/blob/dev/docs/aws-deploy/DEV_ENVIRONMENT.md" "Open the deployment routing notes" _blank
    click Nova href "https://github.com/r-rishit27/equal_hackathon/blob/dev/docs/nova/README.md" "Open Nova service setup" _blank
```

<details>
<summary>Deployment components and configuration</summary>

| Component | Configuration |
|---|---|
| Frontend | Amplify installs dependencies, runs `npm run build`, and serves `frontend/dist`. Configure `VITE_API_URL` and, for Nova, `VITE_NOVA_RECONCILIATION_API_URL` at build time. Apply the documented SPA rewrite for authenticated routes while allowing static and prerendered files through. |
| API and workers | Run the main FastAPI app on EC2 behind Nginx. The deployment notes show separate production and development API units on ports `8001` and `8002`. Run the ingestion pipeline separately with `python main.py`. |
| Nova | Run the independent Nova service with the intended database, frontend origin, and tenant credentials. The checked-in development unit binds to `127.0.0.1:8102`. Its local default is `8100`. |
| Database and files | APIs, workers, and Nova use PostgreSQL. Document storage can use S3 and signed delivery, with local storage available when S3 is unconfigured. Use the configured connection strings to identify the database for each environment. |

</details>

Use the diagram nodes to open configuration files in renderers that support Mermaid links. [Frontend build spec](frontend/amplify.yml) · [AWS deployment guide](docs/aws-deploy/README.md) · [Development routing](docs/aws-deploy/DEV_ENVIRONMENT.md) · [Nova service](docs/nova/README.md)

---

## 3. Technology Stack

| Layer | Technology |
|---|---|
| **Language** | Python 3.11.9 for the API runtime · Python 3.12 for development tests |
| **Async runtime** | asyncio (native) |
| **Database drivers** | psycopg2 and asyncpg 0.29 |
| **Database** | PostgreSQL 15 |
| **Backend framework** | FastAPI + Uvicorn |
| **Frontend** | React 18 + Vite + TypeScript, built on Node.js 20 |
| **OCR — primary** | OpenAI GPT-4o (vision) |
| **OCR — fallback** | Sarvam AI |
| **PDF to image** | Poppler (`pdftoppm`) |
| **XLSX parsing** | openpyxl |
| **Tally integration** | HTTP XML (custom client) |
| **Env management** | python-dotenv |
| **Testing** | pytest + pytest-asyncio · Vitest + Testing Library |

---

## 4. Data Model & Table Taxonomy

### Prefix convention

| Prefix | Layer | Purpose |
|---|---|---|
| `raw_` | Raw / inbound | Unprocessed source records — uploads, API payloads, webhook events, OCR results |
| `stg_` | Staging | Validated, normalised records awaiting promotion to fact tables |
| `dim_` | Dimension | Master reference data — tenants, suppliers, customers, ledger accounts |
| `fact_` | Fact | Promoted, analytics-ready records used for reporting and cashflow |
| `wf_` | Workflow | Task management — nudges, escalations, approval chains, audit log |
| `int_` | Integration | External connection state — credentials, sync cursors, job history |
| `ai_` | AI / Anomaly | Flags raised by the dedup and anomaly-detection layer |

### Key tables

| Table | Description |
|---|---|
| `raw_invoice_uploads` | One row per uploaded file; carries status machine state |
| `raw_ocr_results` | Raw OCR JSON from each engine per upload |
| `raw_api_payloads` | Unprocessed JSON from all API sources |
| `raw_webhook_events` | Unprocessed webhook payloads (signature verified externally) |
| `raw_ingestion_errors` | Quarantined failed records |
| `stg_invoices` | Normalised AR invoices |
| `stg_bills` | Normalised AP bills |
| `stg_payments` | Normalised payments (all gateway sources) |
| `stg_invoice_line_items` | Line items for AR invoices |
| `stg_bill_line_items` | Line items for AP bills |
| `stg_journal_entries` | Journal header + `stg_journal_entry_lines` |
| `dim_tenants` | Tenant master with settings JSON |
| `dim_suppliers` | Supplier/vendor master |
| `dim_end_customers` | Customer master |
| `dim_ledger_accounts` | Chart-of-accounts entries (pulled from Tally) |
| `fact_invoices` | Promoted AR invoices (analytics ready) |
| `fact_bills` | Promoted AP bills |
| `fact_payments` | Promoted payments |
| `payment_schedules` | Instalment rows linked to fact_invoices |
| `payment_transactions` | Individual payment attempt records |
| `wf_tasks` | Workflow task queue (NUDGE, APPROVE, ESCALATE, REVIEW, ALERT) |
| `wf_nudges` | Outbound nudge messages |
| `wf_escalations` | Escalation records |
| `wf_audit_log` | Full entity-change audit trail |
| `bill_approval_chain` | Per-bill approval history (submit / approve / send_back) |
| `tenant_chain_config` | Per-tenant approval chain step configuration |
| `bill_attachments` | File attachments per bill/invoice |
| `ai_anomalies` | Dedup and payment-failure anomaly records |
| `int_connections` | External system connection config + last_sync_at cursor |
| `int_sync_jobs` | Individual sync-job run history |
| `coa_rules` | COA mapping rules: `(vendor_name, category)` → `exp_head` |
| `dim_charges` | Charges master with HSN/SAC codes and default ledger mapping |
| `ledger_mapping_log` | Per-supplier per-HSN ledger usage history (drives auto-suggest) |
| `supplier_bank_accounts` | Multiple bank accounts per supplier (with primary flag + verification status) |
| `vendor_outreach_log` | Log of vendor info-request emails sent via `/api/vendors/{id}/request-info` |

### Staging record lifecycle

```
sync_status:  PENDING --> SYNCED  (promoted to fact table)
                     \-> ERROR   (blocked: exact duplicate or unrecoverable error)

validation_flag: OK       (clean record, eligible for promotion)
                 DUPLICATE (exact dup — blocks promotion, sync_status forced ERROR)
                 REVIEW    (soft dup — non-blocking; promotion still proceeds)
                 MISMATCH  (field-level validation failure from OCR)
```

---

## 5. Pipeline Engine

All workers inherit from `pipelines/base.py:BaseWorker`.

### Base Worker behaviour — CDC Lifecycle

Every worker follows a two-phase lifecycle defined in `pipelines/base.py`.

**Phase 1 — Backfill (startup)**
- Drains all existing unprocessed rows in large batches (`backfill_batch`, default 200) with no sleep between iterations (just `asyncio.sleep(0)` to yield the loop)
- Stops when `process_batch()` returns 0, then enters Phase 2
- Time-driven workers (`approval`, `tally_read`, `tally_sync`) set `skip_backfill = True` and jump straight to Phase 2

**Phase 2 — Incremental (CDC)**
- *Data-driven workers* (`notify_channel` set): open a dedicated LISTEN connection. `pg_notify` on the channel wakes the processing loop immediately via `asyncio.Event`. A periodic safety-poll (`idle_poll_interval_s`, default 60 s) runs as fallback even when no notification arrives
- *Time-driven workers* (`notify_channel = None`): exponential backoff polling — idle sleep grows 1.5× each empty cycle up to `idle_poll_interval_s`
- **Error backoff**: exponential 5 s → 120 s cap on exceptions
- Graceful shutdown via `asyncio.CancelledError` on SIGINT / SIGTERM

**NOTIFY trigger map** — installed idempotently at startup by `pipelines/cdc.py`:

| Source table | Event | Channel | Worker woken |
|---|---|---|---|
| `raw_api_payloads` | INSERT | `ch_api_sync` | ApiSyncWorker |
| `raw_webhook_events` | INSERT | `ch_webhook` | WebhookWorker |
| `raw_invoice_uploads` | INSERT | `ch_upload_ocr` | UploadOcrWorker |
| `stg_invoices/bills/payments` | INSERT | `ch_staging_promotion` | StagingPromotionWorker |
| `stg_bills` | INSERT OR UPDATE | `ch_tds_processing` | TdsProcessingWorker |
| `fact_invoices` | INSERT | `ch_category_enrichment` | CategoryEnrichmentWorker |
| `fact_invoices` | INSERT | `ch_deduplication` | DeduplicationWorker |
| `dim_suppliers / dim_end_customers` | INSERT | `ch_gst_verification` | GstVerificationWorker |
| `dim_suppliers` | INSERT | `ch_bank_verification` | BankVerificationWorker |

**Uniform config** — all tuning lives in `config.PIPELINE_CFG`. Workers declare only `name`, `notify_channel`, and optionally `skip_backfill`. The `_default` block applies to all workers; per-worker keys override:

```python
PIPELINE_CFG = {
    "_default": {
        "backfill_batch": 200, "incremental_batch": 50,
        "poll_interval_s": 5.0, "idle_poll_interval_s": 60.0,
        "error_backoff_s": 5.0, "error_backoff_cap_s": 120.0,
    },
    "upload_ocr":     { "backfill_batch": 20, "incremental_batch": 5,  "poll_interval_s": 2.0 },
    "tds_processing": { "backfill_batch": 100, "incremental_batch": 50, "poll_interval_s": 5.0 },
    "approval":       { "poll_interval_s": 30.0, "idle_poll_interval_s": 90.0 },
    # ... one entry per worker
}
```

---

### 5.1 Upload / OCR Worker

**File**: `pipelines/upload_ocr.py`
**Source table**: `raw_invoice_uploads`
**Batch size**: `UPLOAD_BATCH` (default 10)

Implements a 5-stage status machine:

```
RECEIVED
   |
   v
PREPROCESSING    -- validates file type (PDF/PNG/JPG/TIFF/CSV/XLSX)
   |
   v
OCR_PRIMARY      -- GPT-4o vision extraction
   |                confidence >= 0.6 -> VALIDATING
   |                confidence < 0.6  -> OCR_FALLBACK
   v
OCR_FALLBACK     -- Sarvam AI; merged per-field by confidence weight
   |
   v
VALIDATING       -- field extraction + routing by document type
   |                AP (bill)  -> stg_bills + stg_bill_line_items
   |                AR (invoice) -> stg_invoices + stg_invoice_line_items
   v
DONE  (or ERROR on unrecoverable failure)
```

**OCR confidence scoring**

| Field extracted | Score contribution |
|---|---|
| invoice_number | +0.2 |
| invoice_date | +0.2 |
| total_amount | +0.2 |
| vendor.name | +0.2 |
| line_items (>=1) | +0.2 |

Score >= 0.7 -> `validation_flag = OK`; score < 0.7 -> `validation_flag = REVIEW`

**Structured file support** (CSV / XLSX)

Column expectations: `invoice_number`, `invoice_date`, `due_date`, `total_amount`, `vendor_name`. Additional columns map to line items. No OCR engine is invoked — records go directly to VALIDATING.

---

### 5.2 Staging Promotion Worker

**File**: `pipelines/staging_promotion.py`
**Batch size**: `PROMOTION_BATCH` (default 100)

Runs 3 sub-promotions per batch cycle:

#### Promote Invoices (AR)
- Reads `stg_invoices` where `sync_status = 'PENDING'`
- Writes `fact_invoices` with computed fiscal period (`fiscal_year`, `fiscal_quarter`, `fiscal_month`)
- Fetches `risk_bucket` from linked `dim_end_customers`
- ON CONFLICT on `stg_invoice_id` -> update status, amounts, risk_bucket
- Sets `stg_invoices.sync_status = 'SYNCED'`

#### Promote Bills (AP)
- Reads `stg_bills` where `sync_status = 'PENDING'` and `validation_flag != 'DUPLICATE'`
- Writes `fact_bills` with fiscal period
- ON CONFLICT on `stg_bill_id` -> update status, amounts
- Sets `stg_bills.sync_status = 'SYNCED'`

#### Promote Payments
- Reads `stg_payments` where `sync_status = 'PENDING'`
- Writes `fact_payments`; links to `fact_invoices` via `stg_invoice_id` if present
- **Credit recalculation** on the linked invoice:
  ```
  amount_paid        = SUM(fact_payments.paid_amount WHERE status = 'CLEARED')
  outstanding_amount = GREATEST(total_amount - amount_paid, 0)
  status             = PAID | PARTIAL | SENT  (based on outstanding)
  ```
- Mirrors updated credit back to `stg_invoices`
- Sets `stg_payments.sync_status = 'SYNCED'`

---

### 5.3 Deduplication Worker

**File**: `pipelines/deduplication.py`
**Runs per-tenant** every poll cycle.

Executes 4 sub-processes in order:

#### 1. Bill deduplication

| Check | Condition | Action |
|---|---|---|
| Exact duplicate | Same (tenant, supplier, bill_number, bill_date, total_amount), duplicate `stg_bill_id` | `validation_flag = DUPLICATE`, `sync_status = ERROR` |
| Cross-table dup | Matches an existing `fact_bills` row | Same flags |
| Soft duplicate | Same supplier, `ABS(amount diff) < 1.0 INR`, `ABS(date diff) <= 7 days`, different bill_number | `validation_flag = REVIEW` (non-blocking) |

#### 2. Invoice deduplication

Same 3-tier check for `stg_invoices` vs `fact_invoices`.

#### 3. Failed payment reconciliation

For each AP bill / AR invoice with `FAILED | BOUNCED | REVERSED | CANCELLED` payment_transactions:
- Recalculates `amount_paid` and `outstanding_amount` from COMPLETED transactions only
- Corrects `status` (OVERDUE / PARTIAL / PAID) and mirrors to staging tables

#### 4. Anomaly flagging

Writes idempotent records to `ai_anomalies`:

| `anomaly_type` | Trigger |
|---|---|
| `DUPLICATE_BILL` | Exact bill duplicate detected |
| `SOFT_DUPLICATE_BILL` | Soft bill duplicate detected |
| `DUPLICATE_INVOICE` | Exact invoice duplicate |
| `SOFT_DUPLICATE_INVOICE` | Soft invoice duplicate |
| `PAYMENT_FAILURE_AP` | Failed payment on a bill |
| `PAYMENT_FAILURE_AR` | Failed payment on an invoice |

**Race condition note**: Both the deduplication worker and staging_promotion worker filter `sync_status = 'PENDING'`. If staging_promotion promotes a bill first, dedup will skip it. Soft-dup flagging is therefore best-effort and non-blocking by design. Exact duplicate detection remains reliable because it runs before `sync_status` changes.

---

### 5.4 Approval Workflow Worker

**File**: `pipelines/approval.py`
**Batch size**: `APPROVAL_BATCH` (default 50)
**Poll multiplier**: 3x (runs every 3 standard poll intervals)

Runs 8 sub-tasks per cycle:

| Sub-task | Description |
|---|---|
| `_mark_overdue_schedules` | Sets `payment_schedules.status = OVERDUE` for past-due rows |
| `_create_nudge_tasks_for_overdue_invoices` | Creates `wf_task (NUDGE)` for each overdue AR invoice |
| `_create_approve_tasks_for_new_ar_invoices` | Creates `wf_task (APPROVE)` for AR invoices within 48 h |
| `_create_approve_tasks_for_large_payments` | Creates `wf_task (APPROVE)` for `payment_transactions` above threshold |
| `_auto_approve_small_payments` | Auto-advances small `payment_transactions` to `PROCESSING`; disabled via `dim_tenants.settings_jsonb.auto_approve_enabled` |
| `_generate_nudges` | Resolves primary contact; inserts `wf_nudge (EMAIL)` for each pending NUDGE task |
| `_escalate_stale_tasks` | Creates `wf_escalation` for NUDGE tasks stale > 7 days |
| `_audit_bill_approval_chain` | Writes `wf_audit_log` for unaudited `bill_approval_chain` actions |

**Auto-approval threshold**

Priority order: `dim_tenants.settings_jsonb.auto_approve_threshold_inr` → `config.AUTO_APPROVE_THRESHOLD` (default INR 50,000).

---

### 5.5 API Sync Worker

**File**: `pipelines/api_sync.py`
**Source table**: `raw_api_payloads`
**Batch size**: `API_SYNC_BATCH` (default 50)

**Supported sources**: Tally, ZOHO, QBO, XERO, FRESHBOOKS, SAGE, MYOB, WAVE, UPLOAD

**Supported entity types**: INVOICE, PAYMENT, BILL, CUSTOMER, SUPPLIER, JOURNAL

**Processing flow**:
1. Batch-fetch `raw_api_payloads WHERE is_processed = false`
2. Tenant null-guard: quarantine immediately if `tenant_id` missing
3. Route by `entity_type` to normalisation + upsert:
   - `CUSTOMER` -> `dim_end_customers`
   - `SUPPLIER` -> `dim_suppliers`
   - `JOURNAL` -> `stg_journal_entries` + `stg_journal_entry_lines`
   - `INVOICE` -> `stg_invoices` + `stg_invoice_line_items`
   - `PAYMENT` -> `stg_payments` (links to stg_invoice if reference found)
   - `BILL` -> `stg_bills`
4. Mark `is_processed = true`
5. Retry logic: `retry_count` incremented on failure; quarantined to `raw_ingestion_errors` after 3 attempts

**Normalisation**

| Source | Invoice normaliser | Payment normaliser |
|---|---|---|
| Apideck | `_normalise_apideck_invoice()` | `_normalise_apideck_payment()` |
| Tally | `_normalise_tally_invoice()` | `_normalise_tally_payment()` |

---

### 5.6 Webhook Worker

**File**: `pipelines/webhook.py`
**Source table**: `raw_webhook_events`
**Batch size**: `WEBHOOK_BATCH` (default 50)
**Filter**: `is_processed = false AND is_signature_verified = true`

**Razorpay events handled**

| Event | Handler | Result |
|---|---|---|
| `payment.captured` / `payment.authorized` | `_razorpay_payment_captured` | `stg_payments` (CLEARED) |
| `payment.failed` | `_razorpay_payment_failed` | `stg_payments` (BOUNCED) |
| `refund.created` | `_razorpay_refund_created` | Original REFUNDED + negative refund payment |

**Stripe events handled**

| Event | Handler | Result |
|---|---|---|
| `payment_intent.succeeded` | `_stripe_payment_intent_succeeded` | `stg_payments` (CLEARED) |
| `payment_intent.payment_failed` / `payment_intent.canceled` | `_stripe_payment_intent_failed` | `stg_payments` (BOUNCED) |
| `invoice.paid` | `_stripe_invoice_paid` | `stg_payments` (CLEARED) |
| `charge.refunded` | `_stripe_charge_refunded` | Original REFUNDED + negative refund payment |

Amount conversion: Razorpay paise / 100 -> INR; Stripe cents / 100 -> INR.

---

### 5.7 Tally Read Worker

**File**: `pipelines/tally_read.py`
**Sync interval**: `TALLY_SYNC_INTERVAL_MINUTES` (default 15 min)
**First-run window**: `TALLY_PULL_DAYS` (default 30 days)
**Thread pool**: `TALLY_THREAD_POOL` (default 4, for blocking HTTP)

PULL-only sync from Tally Prime. Each cycle runs for every `int_connections` row where `last_sync_at` is older than the sync interval. A connection row is auto-created if none exists for the tenant.

**PULL cycle**

1. Fetch ledgers (XML) → upsert `dim_ledger_accounts` + `dim_end_customers`
2. Fetch vouchers for `[from_date, today]` → upsert `stg_invoices` / `stg_bills` / `stg_payments`

**Incremental window**

```python
to_date   = date.today()
from_date = last_sync_at.date()                  # last successful sync
          # first run: today − TALLY_PULL_DAYS
```

`last_sync_at` is written back on success so each cycle fetches only the delta.

**Resilience**: `consecutive_failures` incremented per error, reset on success; after 3 failures `int_connections.status = 'ERROR'` (skipped until re-enabled).

**Tally XML helpers**

| Module | Responsibility |
|---|---|
| `tally2database/tally_client.py` | HTTP POST to Tally Prime at `TALLY_HOST:TALLY_PORT`; `fetch_ledgers`, `fetch_vouchers` |
| `tally2database/tally_parser.py` | `parse_ledgers`, `parse_vouchers`; Tally amount ("123.45 Dr/Cr") and date (YYYYMMDD) |
| `tally2database/tally_builder.py` | `build_sales_voucher`, `build_receipt_voucher`, `build_ledger_master` (for PUSH use) |
| `tally2database/sync_audit_logger.py` | Appends sync events to `logs/sync_audit.jsonl` |

---

### Tally Connector Agent (`tally_agent/`)

The agent is an alternative to `TallyReadWorker` for deployments where the pipeline server cannot reach Tally Prime directly (e.g., Tally runs on a customer's LAN, cloud server is on the internet).

**Distribution**: Single-file Windows executable `OnsummTallyAgent.exe` built with PyInstaller. Customer double-clicks → setup UI → runs silently in the system tray forever.

**Pairing flow (one-time setup):**

```
Dashboard         Agent (on customer PC)         Cloud API
   |                       |                          |
   |  Generate token        |                          |
   |─────────────────────── ▶  Customer pastes token   |
   |                       |  POST /api/tally/pair ──▶|
   |                       |  ◀── { api_key, tenant }  |
   |                       |  saves api_key to config  |
```

**Ongoing sync cycle (every 15 min):**
1. Check Tally is running on `localhost:9000`
2. `fetch_ledgers()` → XML via Tally XML socket
3. `fetch_vouchers(from_date, to_date)` → Voucher Register XML (fallback: Day Book)
4. `POST /api/tally/ingest` with `Bearer api_key` → cloud parses + upserts staging tables

**Windows features:**
- Auto-start on login via `HKCU\...\Run` registry key (no admin needed)
- Optional Windows Service install (`--install-service`, admin once) for no-login headless use
- Self-update: polls `/agent/version` on startup; downloads new `.exe`; uses `.bat` trampoline to replace the running binary (Windows can't overwrite a running `.exe` in place)
- System tray icon: green/red dot, last sync tooltip, right-click for Sync Now / Open Log / Quit
- Headless mode (`--headless` + `ONSUMM_TOKEN` env var) for scripted/Docker deploys

**Circuit breaker**: 5 consecutive failures → pause 1 hour, then auto-resume.

**Cloud-side handler**: `backend_ocr/app/tally_agent_api.py` — FastAPI router mounted in `main.py`. Auth via SHA-256 hash of `api_key` stored in `int_connections.agent_api_key_hash`.

**Files:**

| File | Purpose |
|---|---|
| `tally_agent/agent.py` | Full agent implementation (sync, tray, self-update, setup UI) |
| `tally_agent/build.bat` | PyInstaller Windows build script → `OnsummTallyAgent.exe` |
| `tally_agent/build.sh` | PyInstaller Linux/Mac build script |
| `tally_agent/requirements.txt` | Agent dependencies (requests, pystray, Pillow, pywin32) |
| `backend_ocr/app/tally_agent_api.py` | FastAPI router: pair, ingest, version endpoints |

---

### 5.8 GST Verification Worker

**File**: `pipelines/gst_verification.py`
**Source tables**: `dim_end_customers` (`kyc_status = 'PENDING'`) + `dim_suppliers` (`status = 'UNVERIFIED'`)
**Batch size**: 20 per table | **Concurrency**: 5 simultaneous API calls (`asyncio.Semaphore`)

Verifies GSTIN against Sandbox.co.in `/gst/compliance/public/gstin/verify`.

**Decision logic (sequential early-exit):**

| Check | Pass | Fail reason written to audit log |
|---|---|---|
| GSTIN registered | `validGstin = true` | `invalid_gstin` |
| Taxpayer active | `status = "Active"` | `gstin_status_<value>` |
| Name match | `db name == api.legalName` (case-insensitive) | `trade_name_mismatch` |
| PAN match | `db.pan == api.pan` (skipped + backfilled if blank) | `pan_mismatch` |

Outcomes: `VERIFIED` or `FAILED`. Each record is processed **exactly once** — status change removes it from the poll filter permanently.

---

### 5.9 Bank Verification Worker

**File**: `pipelines/bank_verification.py`
**Source tables**: `dim_end_customers` + `dim_suppliers` where `bank_verified = false`
**Batch size**: 20 per table | **Concurrency**: 5 simultaneous API calls (`asyncio.Semaphore`)

Verifies bank accounts via Sandbox.co.in penny-less verify.

**Three-state outcome:**

| Result | `bank_verified` written | Meaning |
|---|---|---|
| `ok=true, account_exists=true` | `true` | Confirmed — no further calls |
| `ok=true, account_exists=false` | `NULL` | Definitively not found — WHERE `= false` skips NULL forever |
| API error (transient) | unchanged (`false`) | Retry on next batch |

`name_at_bank` stored in `wf_audit_log.new_values_jsonb`. Account numbers masked to last 4 digits in logs.

---

### 5.10 Category Enrichment Worker

**File**: `pipelines/category_enrichment.py`
**Source**: `fact_invoices WHERE category IS NULL OR category = ''`
**Poll interval**: 30 s | **Batch size**: 100

Backfills `category` using a three-tier resolution:

| Priority | Source | Condition |
|---|---|---|
| 1 | COA rule | `coa_rules` row with matching `vendor_name` substring AND `category` set |
| 2 | Supplier default | `dim_suppliers.category` already populated |
| 3 | Keyword match | 30+ built-in keywords across 6 categories |
| — | Skip | No blind guessing — NULL left as-is |

**Built-in categories**: Software/SaaS · Rent · Food & Beverages · Travel & Expenses · Utilities · Reimbursement

**Writes to three places**: `fact_invoices.category` + `stg_bills.category` (if linked) + `dim_suppliers.category` (backfill so future bills skip this queue).

---

### 5.11 Expense Report Generator

**File**: `pipelines/expense_report.py`
**Type**: Standalone CLI script + importable async module (not a pipeline worker)

Queries `fact_invoices` + `coa_rules` for a given tenant/month, resolves each bill's `exp_head` via a 3-tier COA match, and writes two files:

| Output | Filename | Contents |
|---|---|---|
| RAW data | `Expense_Report_RAW_<MON-YY>.csv` | One row per bill: COMPANY, VENDOR NAME, INVOICE NO, SERVICE MONTH, SUB HEAD, CATEGORY, EXP HEAD, TOTAL, OPEX, MONTHLY EXPENSE |
| SUMMARY | `Expense_Report_SUMMARY_<MON-YY>.csv` | EXP HEAD TOTAL, AMOUNT, EXP RATIO IN % + GRAND TOTAL row |

**COA matching (3-tier, highest priority first):**

| Tier | Match condition |
|---|---|
| 1 | `coa_rules` row where both `vendor_name` (substring) AND `category` match |
| 2 | `coa_rules` row where only `vendor_name` matches (no category constraint) |
| 3 | `coa_rules` row where only `category` matches (no vendor constraint) |
| — | Default → `OTHER` |

**Valid EXP HEADs**: `ACCOUNTS`, `ADMINISTRATION`, `ASSETS`, `DUTIES & TAXES`, `IT`, `LEGAL`, `MAN POWER`, `MARKETING`, `OFFICE`, `PANTRY`, `PROFESSIONAL`, `RENT`, `UTILITY`, `OTHER`

**CLI usage:**

```bash
# Current month, all statuses
python pipelines/expense_report.py

# Specific month
python pipelines/expense_report.py --month 2026-04

# With status filter
python pipelines/expense_report.py --month 2026-04 --status APPROVED

# Custom tenant and output directory
python pipelines/expense_report.py --month 2026-04 --tenant <uuid> --out reports/
```

**Importable API** (used by the FastAPI endpoint):

```python
from pipelines.expense_report import generate_expense_csv

raw_path, summary_path = await generate_expense_csv(
    tenant_id=tenant_id,
    month="2026-04",        # optional; defaults to current month
    status_filter="APPROVED",  # optional
    output_dir="reports/",
)
```

The `OPEX` column is set to `Y` when `status` is `PAID` or `PARTIAL`; blank otherwise.

---

### 5.12 TDS Processing Worker

**File**: `pipelines/tds_processing.py`
**Source table**: `stg_bills` (`tds_status = 'PENDING'` or NULL)
**notify_channel**: `ch_tds_processing` (wakes on INSERT and UPDATE to `stg_bills`)
**Config key**: `tds_processing` (`backfill_batch=100`, `incremental_batch=50`)

Calculates Tax Deducted at Source (TDS) on every AP bill for Indian tax compliance.

**Processing flow per bill:**

1. Fetch `stg_bills` rows with `tds_status = 'PENDING'` joined to `dim_suppliers` for PAN and verification status — `FOR UPDATE SKIP LOCKED`
2. Build a `TdsInput` (from `utils/tds_engine.py`):
   - `deductee_type` derived from PAN character at index 3 (C=company, P=individual, …)
   - `is_pan_available`, `is_pan_operative` (operative only if supplier is VERIFIED)
3. Call `calculate_tds(conn, inp)`:
   - Looks up `dim_tds_sections` for the bill's `tds_section_id`; falls back to category default
   - Calls Sandbox.co.in TDS Calculator API with PAN + section + amount
   - On API failure: applies local rate table as fallback
4. Write results to `stg_bills`:

| Column | Value |
|---|---|
| `tds_status` | `CALCULATED` / `NA` / `ERROR` |
| `tds_section_code` | e.g. `194C`, `194J` |
| `tds_rate_percent` | Decimal % applied |
| `tds_base_amount` | Taxable base |
| `tds_amount` | ₹ deducted |
| `net_payable` | `total_amount − tds_amount` |

5. Back-patches `fact_bills` with the same values if the bill was already promoted

**UI impact**: Bill detail modal shows a TDS card with section code, rate, TDS amount, net payable. Bills with `tds_status='PENDING'` (supplier not yet categorised) show an amber badge.

**TDS statuses:**

| Status | Meaning |
|---|---|
| `PENDING` | Bill arrived before supplier's TDS category was set; worker will re-process on next UPDATE notify |
| `CALCULATED` | TDS computed successfully |
| `NA` | Bill type or section is exempt (rate = 0) |
| `ERROR` | API and fallback both failed; manual review required |

---

### 5.13 Tally Sync Worker

**File**: `pipelines/tally_sync.py`
**Type**: Bidirectional Tally PUSH + PULL (time-driven, `skip_backfill = True`)
**Config key**: `tally_sync` (`poll_interval_s=60`, `idle_poll_interval_s=120`)

Handles bidirectional synchronisation with Tally Prime — pulling new vouchers from Tally and pushing approved bills/payments back. Unlike `TallyReadWorker` (PULL-only), this worker also writes back to Tally via the XML gateway, making it suitable for deployments where the pipeline server has full read+write LAN access.

Use `TallyReadWorker` when only ingestion is needed; use `TallySyncWorker` when the pipeline should also post approved payables back to Tally as payment vouchers.

---

## 6. Backend API Reference

**Base URL**: `http://localhost:8001`
**Framework**: FastAPI
**CORS origins**: `localhost:5173`, `localhost:5174`, `localhost:3000`

### Endpoints

#### Health

```
GET /health
Response: {"status": "ok"}
```

#### OCR

```
POST /api/invoices/ocr
Content-Type: multipart/form-data
Body:    file (PDF, PNG, JPG, TIFF — required)
         doc_type (optional: "invoice" | "bill")

Response 200:
{
  "upload_id":      "uuid",
  "ocr_id":         "uuid",
  "confidence":     0.85,
  "extracted":      { ...normalised fields... },
  "raw_text":       "...",
  "engine":         "MERGED" | "PADDLEOCR" | "SERVAM"
}
```

```
POST /api/invoices/ocr-bulk
Content-Type: multipart/form-data
Body:    files[] (multiple files)

Response 200: [ { ...single ocr result... }, ... ]
```

```
GET /api/docs/{upload_id}
Response: PDF binary (application/pdf)
```

#### Ingestion

```
POST /api/invoices/ingest
Content-Type: application/json
Body:
{
  "payload": {
    "invoice_number": "INV-001",
    "invoice_date":   "2026-05-10",
    "due_date":       "2026-06-09",
    "total_amount":   50000.00,
    "subtotal":       42372.88,
    "vendor": {
      "name":   "Acme Supplies",
      "gstin":  "29AABCA1234B1Z5",
      "email":  "billing@acme.in"
    },
    "taxes": {
      "taxable_amount": 42372.88,
      "cgst_amount":    3813.56,
      "sgst_amount":    3813.56
    },
    "line_items": [
      {
        "description": "Services rendered",
        "hsn_sac":     "998315",
        "quantity":    1,
        "rate":        42372.88,
        "amount":      42372.88
      }
    ],
    "_source_file": "INV-001.pdf"
  }
}

Response 200:
{
  "status":          "success",
  "supplier_id":     "uuid",
  "upload_id":       "uuid",
  "ocr_id":          "uuid",
  "stg_bill_id":     "uuid",
  "line_items_count": 1
}
```

Conflict resolution: `ON CONFLICT (tenant_id, source='UPLOAD', source_bill_id=invoice_number) DO UPDATE` — posting the same `invoice_number` twice is an idempotent upsert.

#### Bills (AP)

```
GET /api/bills
Response: [ { bill record + supplier + line items }, ... ]

GET /api/bills/{invoice_id}
Response: { bill record + approval chain history }

PUT /api/bills/{invoice_id}
Body: { vendor, dates, amounts — partial update }
Response: { updated bill }

POST /api/bills/{invoice_id}/action
Body: { "action": "SUBMIT" | "APPROVE" | "SEND_BACK", "comment": "..." }
Response: { "status": "ok", "chain_id": 123 }
```

#### Vendors

```
GET /api/vendors
Query params: company_id
Response: { vendors: [ { supplier_id, name, gstn, email, bank_account, bank_ifsc,
                          bank_verified, pan, status, total_bills, total_billed,
                          outstanding_amount, last_invoice_date,
                          vendor_category_id, vendor_category_name } ], total: N }
Description: vendor_category_name drives the TDS Category and TDS Status columns in the
             vendor list table (green "TDS Ready" badge when set, amber "Not Set" when null).

POST /api/vendors
Body: { name, gstn (required), email, payment_terms_days, bank_account, bank_ifsc, company_id }
Response: { supplier_id, status: "created", verification_status: "UNVERIFIED" }
Description: Creates supplier as UNVERIFIED; GST + bank verification run asynchronously
             by GstVerificationWorker and BankVerificationWorker.

POST /api/vendors/bulk-excel
Body: multipart file (XLSX or CSV); columns: name, gstn, email, payment_terms_days
Response: { created: N, skipped: N, errors: [...] }
Description: Bulk import vendors from Excel/CSV. Rows with invalid/missing GSTN are skipped.

POST /api/vendors/{supplier_id}/verify-bank
Body: { account_number, ifsc }
Response: { verified: true, name_at_bank, account_number, ifsc }
Description: On-demand penny-less bank verify via Sandbox. Stores result on dim_suppliers.
```

#### Vendor Bank Accounts

```
GET    /api/vendors/{supplier_id}/bank-accounts
Response: [ { id, account_number, ifsc, bank_name, is_primary, verified, name_at_bank } ]
Description: Returns all bank accounts; falls back to legacy single-account on dim_suppliers.

POST   /api/vendors/{supplier_id}/bank-accounts
Body: { account_number, ifsc, bank_name, is_primary, company_id }
Response: { id, account_number, ifsc, is_primary, verified, ... }

DELETE /api/vendors/{supplier_id}/bank-accounts/{account_id}
Response: { deleted: true }

POST   /api/vendors/{supplier_id}/bank-accounts/{account_id}/set-primary
Response: [ ...full accounts list with updated primary flag... ]
```

#### Vendor Outreach

```
POST /api/vendors/{supplier_id}/request-info
Body: { requested_by, email_to (optional), company_id }
Response: { status: "logged", email_to, subject, body }
Description: Logs a vendor info-request (missing GSTN/PAN/bank) to vendor_outreach_log.
             An email is composed but sending requires SMTP config.

GET /api/vendors/{supplier_id}/outreach
Query params: company_id
Response: { logs: [ { id, requested_by, requested_at, email_to, subject, status } ] }
```

#### Ledgers

```
GET /api/ledgers
Query params: company_id
Response: { ledgers: [ { account_id, account_name, account_code, account_type } ] }
Description: All active ledger accounts for the tenant (used by line-item autocomplete).

POST /api/ledgers/suggest
Body: { supplier_id, hsn_sac, description, company_id }
Response: { suggestions: [ { account_id, account_name, account_code, confidence, reason, uses } ] }
Description: Returns ranked ledger suggestions (up to 5).
             Tier 1: supplier + description history | Tier 2: HSN/SAC history
             Tier 3: dim_charges default | Tier 4: any active ledger
```

#### AI Invoice Enrichment

```
POST /api/enrich-invoice
Body: { invoice: { ...ocr payload... }, company_id }
Response: { category, notes, line_items: [ { account_id, account_name } ],
            bank_details (if vendor found in DB and invoice is missing it) }
Description: Uses GPT-4o-mini to auto-select ledger accounts per line item, classify category,
             and generate a 1–2 sentence AP note. Reuses last known category for the vendor
             from fact_invoices history — GPT cannot override a vendor's established category.
```

#### Approval Chain Settings

```
GET /api/settings/chain
Query params: company_id
Response: { steps: [ { step_order, label, role, locked } ] }
Description: Returns the tenant's approval chain. Default: Submitted → Approver → Accountant → Finance Controller.

POST /api/settings/chain
Body: [ { step_order, label, role, locked }, ... ]
Response: { status: "saved", steps: N }
```

#### Bulk Bill Actions

```
POST /api/bills/bulk-action
Body: {
  bill_ids: ["uuid", ...],   max 100
  action: "APPROVE" | "PUSH_TALLY" | "MARK_PAID",
  actor_name, actor_role,
  company_id,
  options: { payment_date, payment_method }   (for MARK_PAID)
}
Response: { results: [ { bill_id, success, status|error } ], succeeded: N, failed: N, total: N }
Description: APPROVE — advances each bill through the next approval step.
             PUSH_TALLY — sets tally_push_pending=true (admin role only).
             MARK_PAID — records payment and sets status=PAID (admin role only).
```

#### Notifications

```
GET /api/notifications/count
Response: { "count": 12 }
```

#### Tally Connector Agent

```
GET  /api/tally/connection
Response: { connection_id, status, agent_version, last_sync_at, error_message, paired_at }
Description: Dashboard polls this to show current Tally connection status.
```

```
POST /api/tally/pair
Body: { "token": "<one-time pairing token>", "agent_version": "1.0.0" }
Response: { "api_key": "<permanent key>", "tenant_name": "..." }
Description: Agent exchanges dashboard-generated token for a permanent Bearer key.
             Token is single-use and expires in 30 minutes.
             Only the SHA-256 hash of api_key is stored (never the raw key).
```

```
POST /api/tally/ingest
Auth: Bearer <api_key>
Body: { "agent_version": "1.0.0", "ledgers_xml": "...", "vouchers_xml": "..." }
Response: { "status": "ok", "invoices": N, "bills": N, "payments": N, "ledgers": N, "errors": N }
Description: Agent pushes Tally XML. Server parses + upserts to stg_invoices / stg_bills /
             stg_payments / dim_ledger_accounts and updates last_sync_at heartbeat.
```

```
GET  /agent/version
Response: { "version": "1.0.0", "download_url": "...", "sha256": "...", "min_version": "...", "release_notes": "..." }
Description: Version manifest polled by agents on startup for self-update.
             Set AGENT_LATEST_VERSION and AGENT_DOWNLOAD_URL env vars to publish a new build.
```

#### Expense Reports

```
GET /api/reports/expense-xlsx
Query params: company_id, month (YYYY-MM), status (optional)
Response: application/vnd.openxmlformats-officedocument.spreadsheetml.sheet
          Filename: Expense_Report_<MON-YY>.xlsx
          Sheet layout: raw data tab + COA pivot summary tab
```

```
GET /api/reports/expense-csv
Query params: company_id, month (YYYY-MM), status (optional), report=summary|raw|both
Response (summary):  text/csv  — EXP HEAD TOTAL, AMOUNT, EXP RATIO IN %
Response (raw):      text/csv  — one row per bill with COA-mapped EXP HEAD
Response (both):     application/zip — both CSVs in one archive
```

COA rules in `coa_rules` are applied to map `(vendor_name, category)` → `exp_head`. Bills with no matching rule fall back to the `category` column, then to `"OTHER"`.

#### TDS Settings

Served by `backend_ocr/app/tds_api.py` — mounted in `main.py` under `/api/tds`.

```
GET  /api/tds/sections
Query params: company_id
Response: [ { section_id, section_code, description, default_rate_percent, threshold_amount } ]
Description: All TDS sections (194C, 194J, …) used to populate section picker on bills and
             vendor category assignment.

GET  /api/tds/categories
Query params: company_id
Response: [ { category_id, category_name, section_id, section_code, default_rate_percent } ]
Description: Vendor TDS categories defined in Settings → TDS.

POST /api/tds/categories
Body: { category_name, section_id, company_id }
Response: { category_id, category_name, section_code }

GET  /api/tds/settings
Query params: company_id
Response: { tds_enabled, tan_number, deductor_name, deductor_type }

PUT  /api/tds/settings
Body: { tds_enabled, tan_number, deductor_name, deductor_type, company_id }
Response: { status: "saved" }

PUT  /api/vendors/{supplier_id}/tds-category
Body: { vendor_category_id, company_id }
Response: { supplier_id, vendor_category_id }
Description: Assigns a TDS category to a vendor. Triggers a pg_notify on ch_tds_processing
             so TdsProcessingWorker immediately re-processes all PENDING bills for this vendor.
```

---

## 7. Configuration Reference

Loaded from `.env` (pipeline) and `backend_ocr/.env` (API server).

### Database

| Variable | Default | Description |
|---|---|---|
| `DB_URL` | — | Full asyncpg DSN `postgresql://user:pass@host/db` |
| `DB_HOST` | `localhost` | PostgreSQL host |
| `DB_PORT` | `5432` | PostgreSQL port |
| `DB_NAME` | — | Database name |
| `DB_USER` | — | Database user |
| `DB_PASSWORD` | — | Database password |
| `DB_SSL` | `false` | Enable SSL (`true`/`false`) |

### Pipeline tuning — PIPELINE_CFG

All worker batch sizes, poll intervals, and backoff parameters are defined in `config.PIPELINE_CFG` (not environment variables). Edit `config.py` directly to tune:

| Key | `_default` | Description |
|---|---|---|
| `backfill_batch` | `200` | Rows per batch during Phase 1 startup backfill |
| `incremental_batch` | `50` | Rows per batch during Phase 2 CDC mode |
| `poll_interval_s` | `5.0` | Cooldown between drain cycles after a notify wakeup |
| `idle_poll_interval_s` | `60.0` | Max wait between safety-polls (or idle poll for time-driven workers) |
| `error_backoff_s` | `5.0` | Initial retry delay after an exception |
| `error_backoff_cap_s` | `120.0` | Maximum retry delay (exponential cap) |

Per-worker overrides exist for `upload_ocr`, `api_sync`, `webhook`, `staging_promotion`, `tds_processing`, `category_enrichment`, `gst_verification`, `bank_verification`, `deduplication`, `approval`, `tally_read`, `tally_sync`.

### Approval

| Variable | Default | Description |
|---|---|---|
| `AUTO_APPROVE_THRESHOLD` | `50000` | INR threshold for auto-approval |
| `APPROVAL_SECRET` | — | Secret key for signing time-limited approval email tokens (itsdangerous) |

### Email (approval notifications)

| Variable | Default | Description |
|---|---|---|
| `SMTP_HOST` | — | SMTP host for approval notification emails |
| `SMTP_PORT` | `465` | SMTP port (SSL) |
| `SMTP_USER` | — | SMTP sender address |
| `SMTP_PASSWORD` | — | SMTP password |
| `SMTP_ADMIN_EMAIL` | — | Always CC'd on approval notifications |

### KYC / Sandbox

| Variable | Default | Description |
|---|---|---|
| `SANDBOX_API_KEY` | — | Sandbox.co.in API key (GST + bank verification) |
| `SANDBOX_API_SECRET` | — | Sandbox.co.in API secret |

### OCR

| Variable | Default | Description |
|---|---|---|
| `OPENAI_API_KEY` | — | OpenAI key for GPT-4o vision |
| `SARVAM_API_KEY` | — | Sarvam AI key (fallback OCR) |
| `POPPLER_PATH` | — | Path to Poppler `pdftoppm` binary |

### Tally Prime

| Variable | Default | Description |
|---|---|---|
| `TALLY_HOST` | `localhost` | Tally Prime host |
| `TALLY_PORT` | `9000` | Tally Prime XML gateway port |
| `TALLY_COMPANY` | — | Tally company name to sync |
| `TALLY_SYNC_INTERVAL_MINUTES` | `15` | Minimum minutes between syncs |
| `TALLY_PULL_DAYS` | `30` | Lookback window for voucher pull |
| `TALLY_THREAD_POOL` | `4` | Threads for blocking Tally HTTP calls |

### Tally Connector Agent (cloud-side)

| Variable | Default | Description |
|---|---|---|
| `AGENT_LATEST_VERSION` | `1.0.0` | Latest agent version number (agents self-update if behind) |
| `AGENT_DOWNLOAD_URL` | — | HTTPS URL to latest `OnsummTallyAgent.exe` |
| `AGENT_DOWNLOAD_SHA256` | — | SHA-256 checksum of download (optional integrity check) |
| `AGENT_MIN_VERSION` | `1.0.0` | Minimum supported version (older agents are force-updated) |

### Ledger defaults

| Variable | Default | Description |
|---|---|---|
| `DEFAULT_SALES_LEDGER` | `Sales A/c` | Tally sales ledger name |
| `DEFAULT_TAX_LEDGER` | — | Tally GST ledger name |
| `DEFAULT_BANK_LEDGER` | `Cash` | Tally bank/cash ledger |

### Multi-tenancy

| Variable | Default | Description |
|---|---|---|
| `TENANT_ID` | — | Single-tenant fallback UUID (used when payload carries no tenant context) |

---

## 8. Enumerations

All enums are Python classes in `models/enums.py` mapping PostgreSQL enum types.

| Enum | Values |
|---|---|
| `DataSource` | TALLY, ZOHO, QBO, XERO, FRESHBOOKS, SAGE, MYOB, WAVE, RAZORPAY, STRIPE, UPLOAD, MANUAL, GENERIC_REST |
| `EntityType` | INVOICE, PAYMENT, BILL, CREDIT_NOTE, CUSTOMER, SUPPLIER, JOURNAL |
| `InvoiceStatus` | DRAFT, SENT, PARTIAL, PAID, OVERDUE, VOID |
| `PaymentStatus` | PENDING, CLEARED, BOUNCED, REFUNDED |
| `SyncStatus` | PENDING, SYNCED, ERROR |
| `UploadStatus` | RECEIVED, PREPROCESSING, OCR_PRIMARY, OCR_FALLBACK, VALIDATING, DONE, ERROR, PREPROCESS_ERROR |
| `OcrEngine` | PADDLEOCR, SERVAM, MERGED, NONE |
| `ValidationFlag` | OK, MISMATCH, DUPLICATE, REVIEW |
| `RiskBucket` | LOW, MEDIUM, HIGH, CRITICAL |
| `TxnStatus` | INITIATED, PROCESSING, COMPLETED, FAILED, BOUNCED, REVERSED, CANCELLED |
| `ScheduleStatus` | PENDING, PARTIAL, PAID, OVERDUE, WAIVED, DISPUTED |
| `PaymentCycleType` | PAYABLE, RECEIVABLE |
| `PaymentMethod` | BANK_TRANSFER, UPI, CARD, CHEQUE, CASH, GATEWAY |
| `WfTaskType` | NUDGE, ESCALATE, APPROVE, REVIEW, ALERT |
| `WfTaskStatus` | PENDING, IN_PROGRESS, DONE, SKIPPED |
| `WfEntityType` | INVOICE, CUSTOMER, PAYMENT, SUPPLIER, BILL |
| `NudgeChannel` | EMAIL, SMS, WHATSAPP, SLACK, IN_APP |
| `NudgeStatus` | PENDING, SENT, FAILED, CANCELLED |
| `ConnectionStatus` | ACTIVE, PAUSED, ERROR, DISCONNECTED |
| `SyncJobStatus` | RUNNING, COMPLETED, FAILED, PARTIAL |
| `ConflictResolution` | OUTBOUND_WRITE, SKIP, LOG_CONFLICT |

---

## 9. Indian Fiscal Calendar

`utils/fiscal.py` implements India's April-to-March fiscal year.

| Function | Input | Output | Example |
|---|---|---|---|
| `get_fiscal_year(d)` | `date` | FY end year (int) | `2024-04-01` -> `2025` |
| `get_fiscal_quarter(d)` | `date` | Q1-Q4 (int) | Apr-Jun -> `1`, Jan-Mar -> `4` |
| `get_fiscal_month(d)` | `date` | 1-12 (int) | April -> `1`, March -> `12` |
| `fiscal_period(d)` | `date` | `(fy, fq, fm)` tuple | `2024-11-15` -> `(2025, 2, 8)` |

Fiscal period is stored on every `fact_invoices`, `fact_bills`, and `fact_payments` row for slice-and-dice reporting.

---

## 10. Testing

[Consolidated application stress-testing report](STRESS_TESTING.md) covers feature tests, load measurements, Copilot evaluations and outstanding failures.

### Unit tests (no live DB required)

```bash
pytest tests/ -v --tb=short
```

All unit tests use `unittest.mock` with asyncpg mocks.

| Test file | Lines | Coverage area |
|---|---|---|
| `tests/test_deduplication.py` | 653 | Exact/soft/cross-table dup detection, credit reconciliation, anomaly flags, per-tenant isolation |
| `tests/test_api_sync.py` | 144 | Payload routing, normalisation (Apideck + Tally), customer/supplier resolution, retry/quarantine |
| `tests/test_staging_promotion.py` | 122 | Invoice/bill/payment promotion, credit recalc, fiscal period, audit logging |
| `tests/test_approval.py` | 116 | Overdue marking, nudge/escalation/approve task creation, auto-approval threshold |
| `tests/test_webhook.py` | 111 | Razorpay and Stripe event parsing, amount conversion, refund handling |
| `tests/test_tally_sync.py` | 105 | Ledger/voucher fetch, Tally API HTTP calls, incremental sync state |
| `tests/test_base_worker.py` | 98 | Worker lifecycle, idle backoff, error backoff, graceful shutdown |
| `tests/test_upload_ocr.py` | 89 | Status machine transitions, OCR confidence scoring, CSV/XLSX parsing |
| `tests/test_fiscal.py` | 50 | All fiscal year/quarter/month boundary conditions (Indian FY) |
| **Total** | **1488** | |

### Integration tests (live Neon DB required)

```bash
# All 12 workers — module imports, fiscal utils, Tally XML, DB connectivity, batch runs
python test_pipelines.py   # 21 tests
```

Requires `DB_URL` in `.env` pointing to a live Neon (or PostgreSQL) instance with the full schema applied. Full results are documented in [the pipeline test report](docs/pipelines/PIPELINE_TEST_REPORT.md).

---

## 11. Running Locally

Use Python 3.11.9 for the deployed API runtime, Node.js 20 for the frontend, and an isolated PostgreSQL 15 development database with the base schema available. Use Poppler where a document-processing path requires PDF rasterization. Configure `DB_URL` or `DEV_DB_URL` through the environment, and set provider credentials only for the integrations you exercise.

Install the API and pipeline requirements in separate environments. From the repository root:

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install -r backend_ocr/requirements.txt

python3.11 -m venv venv
venv/bin/python -m pip install -r requirements.txt

(cd frontend && npm ci)
```

On an isolated development database, run the API migrations before exercising database-backed features. Run the API, frontend, and pipeline in separate terminals:

```bash
# Run from the repository root to apply uat2 migrations to the development database.
.venv/bin/python scripts/run_api_migrations.py

# API
(cd backend_ocr && ../.venv/bin/python -m uvicorn app.main:app --reload --port 8001)

# Frontend, in a separate terminal
(cd frontend && VITE_API_URL= npm run dev)

# Background pipeline, in a separate terminal when developing worker flows
venv/bin/python main.py
```

### Verify

- Check that `curl -fsS http://127.0.0.1:8001/health` returns `{"status":"ok"}`.
- Confirm a representative database-backed operation for the workflow you are developing. The health endpoint checks the API process.
- Run `npm test` and `VITE_API_URL= npm run build` from `frontend/`. The Python suite spans API and worker code. Use a Python 3.12 test environment with the API requirements plus `pytest`, `pytest-asyncio`, and `requests`, then run `python -m pytest tests/ --tb=short` from the repository root.
- Set `RECON_WORKER_ENABLED` or `CASHAPP_WORKER_ENABLED` before starting the API when testing the corresponding background worker against isolated data. Database test suites use dedicated throwaway databases.

[UAT2 deployment reference](docs/aws-deploy/DEV_ENVIRONMENT.md) · [Frontend CI](.github/workflows/frontend-ci.yml) · [Worker scheduler](backend_ocr/app/review/scheduler.py)

---

## 12. Repository Structure

```
Processing_Pipline/
|
|-- main.py                          Pipeline entry point (12 workers + CDC trigger setup)
|-- db.py                            asyncpg pool (min 2, max 10, timeout 60s)
|-- config.py                        All env-driven config + PIPELINE_CFG tuning dict
|
|-- models/
|   |-- enums.py                     21 Python enum classes (maps to Postgres enums)
|
|-- utils/
|   |-- fiscal.py                    Indian fiscal year helpers
|   |-- ocr_engine.py                OCR integration wrapper (GPT-4o + Sarvam)
|   |-- tds_engine.py                TDS calculation: section lookup, Sandbox API, local fallback
|
|-- scripts/
|   |-- test_tds_live.py             Live smoke-test: runs TDS calc against Sandbox API
|   |-- fix_tds_tenant_rules.py      One-shot script to seed tenant TDS section rules
|
|-- backend_ocr/
|   |-- app/
|   |   |-- main.py                  FastAPI app + all routes (port 8001)
|   |   |-- ingest.py                ingest_invoice() - writes 5 tables
|   |   |-- ocr.py                   OCR orchestration
|   |   |-- config.py                Backend-specific config
|   |   |-- tds_api.py               TDS settings REST API (sections, categories, tenant config)
|   |   |-- tally_agent_api.py       Tally Agent cloud router (pair/ingest/version)
|   |-- stored_uploads/              Uploaded PDF/image storage
|
|-- pipelines/
|   |-- base.py                      BaseWorker: CDC lifecycle (Phase 1 backfill, Phase 2 LISTEN/NOTIFY)
|   |-- cdc.py                       Idempotent NOTIFY trigger installer (runs at startup)
|   |-- upload_ocr.py                Worker  1: OCR status machine
|   |-- staging_promotion.py         Worker  2: stg -> fact promotion (copies TDS cols)
|   |-- deduplication.py             Worker  3: dedup + credit reconciliation
|   |-- approval.py                  Worker  4: workflow automation (P0-P3 priority)
|   |-- api_sync.py                  Worker  5: raw API payloads -> staging
|   |-- webhook.py                   Worker  6: payment gateway events
|   |-- tally_read.py                Worker  7: incremental Tally PULL (ledgers + vouchers)
|   |-- tally_sync.py                Worker  8: bidirectional Tally PUSH+PULL
|   |-- gst_verification.py          Worker  9: GSTIN verify → kyc_status / status
|   |-- bank_verification.py         Worker 10: penny-less bank verify → bank_verified
|   |-- category_enrichment.py       Worker 11: COA + keyword → fact_invoices.category
|   |-- tds_processing.py            Worker 12: TDS calculation → stg_bills + fact_bills
|   |-- expense_report.py            Standalone CSV expense report generator
|
|-- tally_agent/                     Tally Connector Agent (distributable Windows .exe)
|   |-- agent.py                     Full agent: sync loop, setup UI, tray, self-update
|   |-- build.bat                    PyInstaller build script (Windows → OnsummTallyAgent.exe)
|   |-- build.sh                     PyInstaller build script (Linux/Mac)
|   |-- requirements.txt             Agent deps: requests, pystray, Pillow, pywin32
|
|-- tally2database/
|   |-- tally_client.py              HTTP XML calls to Tally Prime
|   |-- tally_parser.py              Tally XML -> Python dicts
|   |-- tally_builder.py             Python dicts -> Tally XML
|   |-- sync_audit_logger.py         JSONL sync event log writer
|   |-- logs/
|       |-- sync_audit.jsonl
|       |-- tally_sync.log
|
|-- tests/
|   |-- test_deduplication.py        653 lines
|   |-- test_api_sync.py             144 lines
|   |-- test_staging_promotion.py    122 lines
|   |-- test_approval.py             116 lines
|   |-- test_webhook.py              111 lines
|   |-- test_tally_sync.py           105 lines
|   |-- test_base_worker.py           98 lines
|   |-- test_upload_ocr.py            89 lines
|   |-- test_fiscal.py                50 lines
|
|-- test_pipelines.py                Integration tests — all 12 workers (live DB)
|
|-- frontend/                        React + Vite + TypeScript SPA (port 5173/5174)
|   |-- src/pages/
|   |   |-- BillsPage.tsx            Bill list + detail modal with TDS card
|   |   |-- VendorsPage.tsx          Vendor list with TDS Category + TDS Status columns
|   |   |-- ReportsPage.tsx          Dashboard, Category Breakdown, Spend Analysis, Aging, Vendor, Approval
|   |   |-- DataExtractionPage.tsx   Expense export: Excel, Raw CSV, Summary CSV, ZIP
|   |   |-- ...                      Other pages unchanged
|   |-- src/components/
|   |   |-- Sidebar.tsx              Data Extraction nav item added
|-- logs/                            Runtime pipeline logs
|-- .env                             Environment configuration (not committed)
|-- docs/
|   |-- pipelines/PIPELINE_README.md           Worker-by-worker operational reference
|   |-- pipelines/PIPELINE_TEST_REPORT.md      Combined test results
|   |-- finance-operations/COA_RULES_AND_REPORTS.md     COA rules + expense report spec
|   |-- architecture/full_database_schema.md      Full DB schema reference
|   |-- architecture/Design.md                    System design notes
|
|-- README.md                        This document
```

---

## 13. Audit Trail (`wf_audit_log`)

Every entity change that matters for compliance, debugging, or reconciliation is written to `wf_audit_log`. The table is append-only — rows are never updated or deleted.

### Schema

| Column | Type | Description |
|---|---|---|
| `log_id` | uuid | Surrogate primary key |
| `tenant_id` | uuid | Tenant scope |
| `table_name` | text | Source table of the audited entity |
| `entity_id` | uuid | PK of the audited row in its source table |
| `action` | text | `INSERT`, `UPDATE`, or domain verb (`submit`, `approve`, `send_back`) |
| `user_id` | uuid | Actor (nullable for system actions) |
| `correlation_id` | uuid | Groups related events in one pipeline batch |
| `old_values_jsonb` | jsonb | Row state before the change |
| `new_values_jsonb` | jsonb | Row state after the change |
| `created_at` | timestamptz | Event timestamp |

### What is audited

| Source | `table_name` | `action` | Written by |
|---|---|---|---|
| Invoice promoted to fact | `fact_invoices` | `INSERT` | `StagingPromotionWorker` |
| Bill promoted to fact | `fact_bills` | `INSERT` | `StagingPromotionWorker` |
| Payment auto-approved | `payment_transactions` | `UPDATE` | `ApprovalWorker._auto_approve_small_payments` |
| Bill submitted for approval | `bill_approval_chain` | `submit` | `ApprovalWorker._audit_bill_approval_chain` |
| Bill approved | `bill_approval_chain` | `approve` | `ApprovalWorker._audit_bill_approval_chain` |
| Bill sent back (rejected) | `bill_approval_chain` | `send_back` | `ApprovalWorker._audit_bill_approval_chain` |
| GSTIN verified / failed | `dim_end_customers` / `dim_suppliers` | `UPDATE` | `GstVerificationWorker` |
| Bank account verified | `dim_end_customers` / `dim_suppliers` | `UPDATE` | `BankVerificationWorker` |
| TDS calculated on bill | `stg_bills` | `UPDATE` | `TdsProcessingWorker` |

### `bill_approval_chain` audit (added to `ApprovalWorker`)

`_audit_bill_approval_chain()` runs as the 8th sub-task in every `ApprovalWorker` batch. It polls `bill_approval_chain` for rows that do not yet have a corresponding `wf_audit_log` entry and writes one per action:

```
bill_approval_chain (submit / approve / send_back)
         |
         v  (polled each ApprovalWorker cycle)
_audit_bill_approval_chain()
         |
         v
wf_audit_log  (entity_id = invoice_id, new_values_jsonb contains
               chain_id, step, actor_role, actor_name, action, comment)
```

This guarantees a **complete, immutable record** of every approval decision — who took it, when, and what state the bill was in — without requiring the API layer to write audit entries directly.

### Querying the audit trail

```sql
-- Full approval history for a bill
SELECT action, new_values_jsonb->>'actor_name' AS actor,
       new_values_jsonb->>'action'             AS decision,
       new_values_jsonb->>'comment'            AS comment,
       created_at
FROM   wf_audit_log
WHERE  table_name = 'bill_approval_chain'
  AND  entity_id  = '<invoice_id>'::uuid
ORDER  BY created_at;

-- All system auto-approvals today
SELECT entity_id, new_values_jsonb->>'status' AS new_status, created_at
FROM   wf_audit_log
WHERE  table_name = 'payment_transactions'
  AND  action     = 'UPDATE'
  AND  created_at >= CURRENT_DATE;
```

---

## 14. Key Design Decisions

### Poll-based workers, not a message queue

Workers poll their source tables independently using asyncio. This removes Kafka/RabbitMQ operational overhead while retaining horizontal isolation between workers. The trade-off is that pipeline latency is bounded by `POLL_INTERVAL_S` rather than event latency. At 5 s with idle backoff, this is acceptable for a cashflow platform where second-level freshness is not required.

### Two-layer staging -> fact pattern

Staging tables act as a validation buffer. Records are promoted to fact tables only after passing deduplication and field validation. This decouples ingest speed from data quality guarantees and allows replaying promotions without re-fetching from source systems.

### Soft-dup is non-blocking

A `REVIEW` flag on a bill does not prevent staging_promotion from promoting it to `fact_bills`. Only `DUPLICATE` blocks promotion (sets `sync_status = ERROR`). This is intentional: in AP processing, a supplier legitimately re-issues invoices with the same amount on nearby dates (e.g., monthly retainers). Blocking all soft-dups would cause unacceptable false-positive rejection rates. The REVIEW flag and `ai_anomalies` record surface the issue for human review without halting the workflow.

### OCR dual-engine with confidence weighting

GPT-4o provides high accuracy on structured documents but can hallucinate on low-quality scans. Sarvam AI provides a character-accurate fallback on Indian-language documents. The merged result picks the higher-confidence value per field, so the merged output is always at least as good as the better engine.

### Two Tally integration modes, one schema

`TallyReadWorker` (server-side pull) and the Tally Connector Agent (agent-side push) both write to the same `stg_invoices`, `stg_bills`, `stg_payments`, and `dim_ledger_accounts` tables using identical upsert logic. The rest of the pipeline is unaware which mode was used — `StagingPromotionWorker`, `DeduplicationWorker`, etc. treat both identically. Customers with LAN access use the simpler pull mode; cloud-only customers install the agent exe.

The agent uses a **token-then-hash** auth pattern: the dashboard generates a short-lived pairing token, the agent exchanges it once for a permanent `api_key`, and only the SHA-256 hash is ever stored server-side. The raw key is shown exactly once (at pairing time) and never retrievable again.

### Tally uses incremental cursors via `last_sync_at`

`TallyReadWorker` stores `last_sync_at` in `int_connections` after each successful cycle. The next run sets `from_date = last_sync_at.date()` so only the delta is fetched from Tally. First-run falls back to `today − TALLY_PULL_DAYS` (default 30 days). Tally's HTTP XML gateway is synchronous, so all Tally calls run in a `ThreadPoolExecutor` to keep the asyncio event loop unblocked.

### KYC verification is one-shot per record

`GstVerificationWorker` and `BankVerificationWorker` use concurrent `asyncio.gather` (semaphore-capped at 5) so a batch of 20 records completes in ~1 API round-trip instead of 20 sequential calls. Crucially, each record is processed exactly once: GST records move to `VERIFIED`/`FAILED` (removed from the filter); bank records use a three-state flag (`true` / `NULL` / `false`) so "not found" accounts are never retried.

### Category enrichment never blindly guesses

`CategoryEnrichmentWorker` leaves `category` as NULL if none of the three resolution tiers (COA rule → supplier default → keyword) match. It also backfills `dim_suppliers.category` so future bills from the same vendor are categorised at ingest time, progressively shrinking the enrichment queue.

### Upsert-everywhere conflict resolution

Every staging write uses `ON CONFLICT (tenant_id, source, source_<entity>_id) DO UPDATE`. This makes all ingest operations idempotent: re-posting the same payload updates the existing record rather than creating a duplicate. The `source_<entity>_id` is the source system's native key (e.g., `invoice_number` for UPLOAD source, Tally voucher number for TALLY source).

### Multi-tenant isolation

Every table carries a `tenant_id` column. Deduplication and approval workers run their queries per-tenant. API payloads without a resolvable `tenant_id` are quarantined immediately to `raw_ingestion_errors` (the C5 null-guard pattern) rather than being attributed to a default tenant, which would pollute cross-tenant reporting.

### CDC over pure polling: LISTEN/NOTIFY + safety-poll

The original architecture polled every 5 seconds unconditionally. At steady state with few bills, this wasted connections and added up to 5 s of avoidable latency. The CDC rewrite uses PostgreSQL's native `LISTEN/NOTIFY` so workers wake the instant a row is inserted or updated — typical lag is < 50 ms. A periodic safety-poll (60 s default) runs even when no notification arrives, ensuring rows that slip through a trigger gap (e.g., a bulk import that bypasses triggers) are never permanently stuck.

The trigger function `_pipeline_notify()` is a single shared plpgsql function; each trigger passes its channel name as `TG_ARGV[0]`. This means adding a new worker requires only: (1) declare `notify_channel` on the class, (2) add one row to `_TRIGGERS` in `cdc.py` — no schema migrations needed.

### Phase 1 backfill prevents CDC cold-start gaps

Workers that use `FOR UPDATE SKIP LOCKED` are safe to start mid-stream — existing PENDING rows are fully drained before the worker switches to LISTEN mode. Without Phase 1, a worker restart after downtime would only process new rows, leaving a backlog. The tight loop (no sleep, just `asyncio.sleep(0)` to yield) maximises backfill throughput while staying co-operative with the event loop.

### TDS is calculated in the pipeline, not the API

TDS could have been calculated synchronously at ingest time (in the FastAPI `/ingest` endpoint). We chose the pipeline instead because: (a) the Sandbox TDS API is external and can be slow or unavailable — blocking the ingest path would hurt upload UX; (b) the vendor category needed for the section lookup is often assigned *after* the bill arrives (a buyer sets the TDS category once, not per-bill); (c) the pipeline naturally handles re-calculation when the category changes (the `stg_bills` UPDATE trigger wakes the worker). The PENDING → CALCULATED lifecycle mirrors the GST verification pattern already established for vendors.

### Priority P0–P3 with value-based adjustment

Approval priority was previously a binary flag. The P0–P3 model aligns with engineering incident severity conventions that finance teams are familiar with. Bills above ₹50 k are escalated one tier (P2→P1); bills below ₹10 k are de-escalated one tier (P1→P2). The tier is clamped to [P0, P3] so edge cases never produce invalid values. The score is computed in the approval worker and stored on `wf_tasks.priority` — not derived at query time — so it can be indexed and filtered efficiently.

### Data Extraction as a separate page from Reports

Expense export (XLSX, CSV, ZIP) was originally inside the Reports page. Moving it to a dedicated Data Extraction page separates two distinct user intents: *analysis* (charts, trends, breakdowns) and *extraction* (downloading raw data for accountants). This avoids cluttering the reporting dashboard with file-download UI and allows the Reports page to be expanded with more visualisations without becoming a dumping ground for export controls.

---

*Reckon.ai — Intelligent Cashflow for Indian SMEs*
