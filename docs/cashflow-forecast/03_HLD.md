# Cash Flow Forecast — High-Level Design

| | |
|---|---|
| **Status** | Draft for build · v1.0 · 21 Nov 2026 |
| **Scope** | System context, containers, components, data flow, key interactions, deployment, decisions |
| **Reads with** | [PRD](01_PRD.md) · [Technical design](02_TECHNICAL_DESIGN.md) · [LLD](04_LLD.md) |

Diagrams are Mermaid; they render in GitHub and in VS Code's Markdown preview. Colour key used throughout:

| Colour | Meaning |
|---|---|
| Blue | Existing Reckon.ai component or table (read only for this module) |
| Green | New component introduced by Cash Flow Forecast |
| Amber | External system or person |
| Grey | Storage owned by this module |

---

## 1. System context

Who uses the module and what it touches.

```mermaid
flowchart LR
    owner(["👤 Owner<br/>finance_controller"]):::ext
    acct(["👤 Accountant<br/>accountant"]):::ext
    ca(["👤 CA / Auditor<br/>auditor"]):::ext

    subgraph reckon["Reckon.ai platform"]
        cff["<b>Cash Flow Forecast</b><br/>daily projection · views ·<br/>scenarios · cash plans"]:::new
        ap["Payables<br/>bills · approvals · TDS"]:::existing
        ph["Payment Hub<br/>disbursements · OTP"]:::existing
        ar["Receivables<br/>invoices · cash application"]:::existing
        bank["Bank statements<br/>stg_bank_statements"]:::existing
        cop["Reckon Copilot"]:::existing
        rep["Reports"]:::existing
    end

    banks[("Bank portals /<br/>statement files")]:::ext
    mail["Email (user's<br/>connected mailbox)"]:::ext

    acct -- "maintains inputs,<br/>builds scenarios, submits plan" --> cff
    owner -- "reviews forecast,<br/>approves / returns plan" --> cff
    ca -- "reads forecast,<br/>plans, history" --> cff
    ap -- "approved bills, net payable,<br/>schedules" --> cff
    ph -- "payouts in flight /<br/>succeeded" --> cff
    ar -- "open invoices, history,<br/>unapplied receipts" --> cff
    bank -- "running balances" --> cff
    banks -. "statement import<br/>(existing flow)" .-> bank
    cff -- "publishes fact_cashflow_daily" --> cop
    cff -- "publishes fact_cashflow_daily" --> rep
    cff -. "breach alert (P1)" .-> mail

    classDef existing fill:#e6eefa,stroke:#004080,color:#0b1c30
    classDef new fill:#ecfdf5,stroke:#047857,color:#052e16
    classDef ext fill:#fffbeb,stroke:#b45309,color:#3b1d02
```

**Boundary rules**

- The module **reads** payables, payouts, receivables and statements. It **never writes** to them.
- It **writes** only its own `cf_*` tables and (optionally) the forecast columns of `fact_cashflow_daily`.
- It **never** initiates payments, sweeps, drawdowns or collection messages. Payment Hub keeps sole authority over money movement.

## 2. Containers

```mermaid
flowchart TB
    subgraph client["Browser"]
        spa["React SPA (Vite)<br/>/finance-desk/cash-forecast<br/>CashForecastPage + drawers"]:::new
    end

    subgraph edge["Hosting"]
        amp["Amplify / CloudFront<br/>static assets"]:::existing
    end

    subgraph api["FastAPI app — backend_ocr/app (EC2)"]
        mw["Auth middleware<br/>JWT → tenant, roles<br/>require_service('cash_forecast')"]:::existing
        router["routers/cash_forecast.py<br/>REST /api/finance-desk/cash-forecast"]:::new
        pkg["cashflow package<br/>sources · snapshot · engine ·<br/>scenario · plans · publish"]:::new
        mw --> router --> pkg
    end

    subgraph worker["Worker process — main.py"]
        jobs["cashflow.jobs<br/>07:00 refresh · alerts ·<br/>accuracy · prune"]:::new
    end

    subgraph db["PostgreSQL (onsumm_db)"]
        src[("Source tables<br/>fact_invoices · stg_bills · payment_schedules ·<br/>fact_disbursements · ar_invoices · ar_payments ·<br/>stg_bank_statements · dim_bank_accounts")]:::existing
        cf[("cf_* tables<br/>settings · inputs · snapshots ·<br/>events · scenarios · plans · audit")]:::store
        fcd[("fact_cashflow_daily")]:::existing
    end

    spa -- "HTTPS JSON" --> amp
    amp -- "API calls" --> mw
    pkg -- "READ ONLY,<br/>REPEATABLE READ" --> src
    pkg -- "read / write" --> cf
    pkg -- "upsert forecast cols" --> fcd
    jobs -- "same package" --> pkg

    classDef existing fill:#e6eefa,stroke:#004080,color:#0b1c30
    classDef new fill:#ecfdf5,stroke:#047857,color:#052e16
    classDef store fill:#f1f5f9,stroke:#4b5563,color:#0b1c30
```

No new deployable is introduced: the router runs inside the existing FastAPI process and the jobs inside the existing worker. This matches how inventory, Copilot and receivables were added.

## 3. Components (backend)

```mermaid
flowchart LR
    subgraph router["routers/cash_forecast.py"]
        R1["Settings & inputs endpoints"]
        R2["Snapshot & forecast endpoints"]
        R3["Scenario & preview endpoints"]
        R4["Plan endpoints"]
        R5["Export endpoint"]
        AZ["_require(capability)<br/>role map"]
    end

    subgraph core["cashflow/ (domain)"]
        SB["SnapshotBuilder"]
        DD["Deduplicator"]
        CM["CollectionModel"]
        BC["BusinessCalendar"]
        EN["ForecastEngine<br/>(pure)"]
        OV["OverrideValidator +<br/>apply_overrides"]
        PS["PlanService"]
        PUB["DailyPublisher"]
        ACC["AccuracyService (P1)"]
    end

    subgraph sources["cashflow/sources/"]
        S1["BankBalanceSource"]
        S2["DisbursementSource"]
        S3["PayablesSource"]
        S4["ReceivablesSource"]
        S5["RecurringSource"]
        S6["AdjustmentSource"]
        S7["FixtureSource"]
    end

    REPO["CashForecastRepo<br/>(all cf_* SQL)"]

    R1 --> REPO
    R2 --> SB
    R2 --> EN
    R3 --> OV --> EN
    R4 --> PS
    R5 --> EN
    SB --> S1 & S2 & S3 & S4 & S5 & S6
    SB -. "test / demo" .-> S7
    S4 --> CM
    S3 & S4 & S5 & S6 --> BC
    SB --> DD
    SB --> REPO
    PS --> SB
    PS --> OV
    PS --> EN
    PS --> REPO
    SB --> PUB
    ACC --> REPO

    classDef default fill:#ecfdf5,stroke:#047857,color:#052e16
```

| Component | Responsibility | Depends on | Must not |
|---|---|---|---|
| Sources | Read one domain, convert to `CashEvent`/`Exclusion`/`OpeningBalance`, paise, local dates | DB cursor, calendar, collection model | Write anything; know about views beyond per-view dates |
| SnapshotBuilder | Orchestrate sources in one read txn, dedupe, hash, persist new revision | Sources, Deduplicator, Repo | Compute balances |
| Deduplicator | Cross-source “count once” rules | Source results | Touch DB |
| CollectionModel | Customer profiles, expected/downside dates with basis | History rows | Know about bills |
| BusinessCalendar | Banking-day tests and roll rules | Tenant holidays | — |
| ForecastEngine | Daily buckets, metrics, deltas | Snapshot, overrides | I/O, clock |
| OverrideValidator | Typed checks and refusal codes | Snapshot, windows, calendar | Persist |
| PlanService | Lifecycle, stale check, idempotency, adoption | Builder, Engine, Validator, Repo | Move money |
| DailyPublisher | Upsert forecast columns of `fact_cashflow_daily` | Engine result, DB | Touch actual columns |
| Repo | All `cf_*` SQL, tenant-scoped | DB | Business rules |

## 4. Data flow

From source rows to a number on screen.

```mermaid
flowchart LR
    subgraph S["Sources (existing)"]
        B1["stg_bank_statements<br/>cf_bank_balances"]
        P1["fact_invoices AP<br/>stg_bills (TDS, net)"]
        P2["payment_schedules"]
        D1["fact_disbursements"]
        A1["ar_invoices (open)"]
        A2["ar_invoices (paid, 12m)"]
        A3["ar_payments (unapplied)"]
    end
    subgraph I["Inputs (new)"]
        I1["cf_recurring_items"]
        I2["cf_adjustments"]
        I3["cf_payment_windows"]
        I4["cf_collection_promises"]
        I5["cf_planned_dates"]
        I6["cf_settings + calendar"]
    end

    B1 --> OB["Opening balance<br/>per account + freshness"]
    D1 --> DS["In-flight / succeeded<br/>payout sets"]
    P1 & P2 & I5 --> APE["AP events<br/>amount net of TDS ·<br/>planned → schedule → due"]
    DS --> APE
    A2 --> PROF["Payment profiles<br/>median · p80 · n"]
    A1 & PROF & I4 --> ARE["AR events<br/>expected / downside dates ·<br/>minus expected TDS"]
    A3 --> ARE
    I1 --> REC["Recurring expansion<br/>+ business-day roll"]
    I2 --> ADJ["Adjustment events"]
    I6 --> APE & ARE & REC & ADJ

    OB & APE & ARE & REC & ADJ & DS --> DEDUP["Deduplicate +<br/>Exclusions"]
    DEDUP --> SNAP[("Snapshot rev N<br/>events · exclusions ·<br/>content hash")]
    SNAP --> ENG["ForecastEngine<br/>view × overrides"]
    I3 --> VAL["Override validation"]
    VAL --> ENG
    ENG --> OUT1["KPI strip · chart ·<br/>ledger · drawers"]
    ENG --> OUT2["Plans (frozen metrics)"]
    ENG --> OUT3["fact_cashflow_daily<br/>→ Copilot, Reports"]
```

## 5. Key interactions

### 5.1 Open the page

```mermaid
sequenceDiagram
    autonumber
    actor U as Accountant
    participant UI as CashForecastPage
    participant API as cash_forecast router
    participant REPO as Repo
    participant ENG as ForecastEngine

    U->>UI: Open /finance-desk/cash-forecast
    par settings & accounts
        UI->>API: GET /settings
        UI->>API: GET /accounts
    and latest forecast
        UI->>API: GET /snapshots/latest
        API->>REPO: latest snapshot for tenant
        REPO-->>API: SnapshotRef (rev 14, as_of, coverage)
        UI->>API: GET /forecast?snapshot_id&view=expected
        API->>REPO: load events (cache miss)
        API->>ENG: project(snapshot, expected)
        ENG-->>API: ForecastResult
        API-->>UI: 200 ForecastResult (ETag)
    end
    UI-->>U: KPIs, chart, ledger, freshness
    Note over UI: If latest snapshot is older than today 07:00<br/>or coverage partial → banner offers Refresh
```

### 5.2 Refresh (build snapshot)

```mermaid
sequenceDiagram
    autonumber
    actor U as Accountant
    participant API as Router
    participant SB as SnapshotBuilder
    participant SRC as Sources (6)
    participant DB as PostgreSQL
    participant PUB as DailyPublisher

    U->>API: POST /snapshots {reason: "manual"}
    API->>SB: build(tenant, actor)
    SB->>DB: BEGIN READ ONLY ISOLATION REPEATABLE READ
    loop disbursements → payables → receivables → recurring → adjustments
        SB->>SRC: read(ctx)
        SRC->>DB: parameterised SELECT (tenant_id)
        DB-->>SRC: rows
        SRC-->>SB: events + exclusions
    end
    SB->>DB: COMMIT (read txn)
    SB->>SB: dedupe · canonicalise · sha256
    alt hash equals latest
        SB-->>API: SnapshotRef(rev 14, changed=false)
    else new content
        SB->>DB: BEGIN · pg_advisory_xact_lock(tenant)
        SB->>DB: INSERT cf_snapshots (rev 15) + events + exclusions
        SB->>DB: COMMIT
        SB->>PUB: publish(expected view)
        PUB->>DB: UPSERT fact_cashflow_daily (30 rows)
        SB-->>API: SnapshotRef(rev 15, changed=true)
    end
    API-->>U: 201 / 200 SnapshotRef
```

### 5.3 Scenario preview

```mermaid
sequenceDiagram
    autonumber
    actor U as Accountant
    participant UI as ScenarioPanel
    participant API as Router
    participant VAL as OverrideValidator
    participant ENG as ForecastEngine

    U->>UI: Drag Raigad RAI/2610/203 to 3 Dec
    UI->>API: POST /forecast/preview {snapshot_id, rev 14, view, overrides[]}
    API->>VAL: validate(overrides, snapshot)
    VAL-->>API: refused OUTSIDE_PAYMENT_WINDOW (latest 2 Dec)
    API-->>UI: 422 {code, message, details.latest_date}
    UI-->>U: Inline error, snaps back
    U->>UI: Move to 2 Dec instead
    UI->>API: POST /forecast/preview
    API->>VAL: validate → ok
    API->>ENG: project(base) and project(base + overrides)
    ENG-->>API: baseline, scenario, delta
    API-->>UI: 200 PreviewResult
    UI-->>U: Two lines, min ₹9.99 L → improved, breach cleared
```

### 5.4 Submit and approve a plan

```mermaid
sequenceDiagram
    autonumber
    actor A as Accountant
    actor O as Owner
    participant API as Router
    participant PS as PlanService
    participant SB as SnapshotBuilder
    participant DB as PostgreSQL

    A->>API: POST /plans {scenario_id, note}
    API->>PS: create_and_submit
    PS->>PS: re-validate + recompute metrics on pinned rev
    PS->>DB: INSERT cf_plans (v1, submitted, metrics, hash)
    PS->>DB: INSERT cf_audit_log
    API-->>A: 201 Plan v1 submitted

    O->>API: POST /plans/{id}/decision {approve, expected_version 1, Idempotency-Key}
    API->>PS: decide
    PS->>SB: current snapshot (build or reuse)
    alt revision changed AND metrics differ
        PS-->>API: PLAN_STALE + diff
        API-->>O: 409, "Bills changed since submission"
    else not stale
        PS->>DB: BEGIN, SELECT plan FOR UPDATE
        PS->>DB: check state=submitted, version=1, approver≠submitter
        PS->>DB: INSERT cf_plan_decisions (idempotency key)
        PS->>DB: UPDATE plan → approved, supersede previous approved
        PS->>DB: UPSERT cf_planned_dates for decision overrides
        PS->>DB: INSERT cf_audit_log, COMMIT
        API-->>O: 200 Plan approved
    end
```

### 5.5 Daily job and alert

```mermaid
sequenceDiagram
    autonumber
    participant CRON as Worker scheduler (07:00 IST)
    participant JOB as cf_daily_refresh
    participant SB as SnapshotBuilder
    participant ENG as ForecastEngine
    participant DB as PostgreSQL
    participant N as Notifications

    CRON->>JOB: tick
    JOB->>DB: tenants with cash_forecast entitlement
    loop each tenant (advisory lock)
        JOB->>SB: build(reason=scheduled)
        SB-->>JOB: SnapshotRef
        JOB->>ENG: project(expected)
        ENG-->>JOB: first_breach_date
        alt breach within 7 days and not alerted for this date
            JOB->>N: in-app notification (+ email P1) to finance_controller users
            JOB->>DB: INSERT cf_alerts (dedupe key)
        end
    end
```

## 6. Deployment view

```mermaid
flowchart TB
    subgraph aws["AWS ap-south-1 (current UAT/prod topology)"]
        subgraph pub["Public"]
            cf["CloudFront + Amplify<br/>React build"]
            alb["HTTPS endpoint"]
        end
        subgraph ec2["EC2 application host"]
            api["uvicorn — FastAPI<br/>+ cash_forecast router"]
            wk["worker — main.py<br/>+ cashflow.jobs"]
        end
        rds[("PostgreSQL<br/>onsumm_db<br/>+ cf_* tables")]
    end
    user(["Browser"]) --> cf
    user --> alb --> api
    api --> rds
    wk --> rds
```

No infrastructure change is required. Resource impact: one snapshot build per tenant per morning plus ad-hoc refreshes; CPU-light pure Python; DB load dominated by five indexed reads per build. Scale-out path (if needed later): move `cashflow.jobs` to its own worker task; keep the API in-process.

## 7. Data lifecycle

```mermaid
stateDiagram-v2
    direction LR
    [*] --> Built: refresh / 07:00 job
    Built --> Current: newest revision
    Current --> Historical: newer revision built
    Historical --> Pinned: referenced by scenario or plan
    Historical --> DailyKeep: the day's 07:00 snapshot
    Historical --> Pruned: unreferenced and > 90 days
    Pinned --> [*]: kept for audit
    DailyKeep --> [*]: kept for accuracy
```

## 8. Cross-cutting concerns

| Concern | Approach |
|---|---|
| **Tenancy** | Tenant from JWT; every SQL filters `tenant_id`; composite FKs; foreign IDs return 404 |
| **Authorisation** | Role → capability map in router (`view`, `edit`, `approve`, `settings`); entitlement `cash_forecast` at mount |
| **Consistency** | One `REPEATABLE READ` read transaction per build; immutable snapshots; plans pinned to revision with stale check |
| **Idempotency** | Content-hash snapshots; idempotency keys on decisions; upserts for planned dates and publish |
| **Money** | Integer paise; single conversion point; sums verified in tests |
| **Time** | Business dates in tenant timezone (Asia/Kolkata); timestamps UTC in DB; engine has no clock |
| **Performance** | Pure engine; per-snapshot LRU; previews never hit the DB except snapshot load (cached) |
| **Auditability** | `cf_audit_log` for every mutation; plans store metrics + override list + content hash |
| **Failure isolation** | Source failure → coverage `partial`, named source, approval blocked; model-free design means no LLM dependency |
| **Accessibility** | Chart has a ledger table equivalent; status text + icon, not colour alone |

## 9. Failure modes

| Failure | Detection | Behaviour |
|---|---|---|
| No bank balance for any included account | Bank source returns empty | Forecast `unavailable`; UI shows “Add today's balance” form |
| One account stale (> 3 banking days) | Freshness check | Forecast shown with warning; plan submit/approve blocked (`BALANCE_EXPIRED`) |
| A source query fails | Exception in adapter | Snapshot coverage `partial` with `failed_sources`; persisted so users see it; approve blocked |
| Payroll/GST templates missing amounts | Coverage check | Banner “Payroll not configured — forecast may be optimistic” |
| Concurrent refreshes | Advisory lock + hash | One revision created; the other returns it |
| Concurrent approvals | Row lock + version | One decision; the other gets 409 `PLAN_STATE` |
| Publish unique key missing | Migration check | Publishing disabled for tenant, logged; forecast unaffected |

## 10. Architecture decisions

| # | Decision | Alternatives considered | Why |
|---|---|---|---|
| ADR-1 | Run inside existing FastAPI + worker | Separate service | Matches inventory/receivables precedent; no new infra; low load |
| ADR-2 | Own `cf_*` tables; publish to `fact_cashflow_daily` | Write forecasts straight into `fact_cashflow_daily` only | Need immutable snapshots, events and plans for audit; `fact_cashflow_daily` has no per-event detail |
| ADR-3 | Persist snapshot events | Recompute from sources on demand | Plans must stay reproducible after sources change |
| ADR-4 | Content-hash revisions | Time-based revisions | No-op refreshes don't invalidate scenarios; cheap equality |
| ADR-5 | Statistical collection model (median/p80, conditional) | ML model, `ai_payment_predictions` | Explainable, no training data needed, backtestable; ML can plug in later behind the same interface |
| ADR-6 | Daily granularity, 30-day default, 91-day max | Weekly only | Payroll/GST/EMI are date-specific; weekly rollup derived from daily |
| ADR-7 | Decisions vs assumptions in overrides | Treat all overrides alike | Only decisions should change tomorrow's baseline; assumptions are opinions |
| ADR-8 | No LLM in the forecast path | LLM-generated narratives | Numbers must be exact; Copilot can narrate using the published data/tool (P1) |
| ADR-9 | Strict reserve comparison (`<`) | `≤` | Matches owner language (“don't go below”) and finance-desk precedent |
