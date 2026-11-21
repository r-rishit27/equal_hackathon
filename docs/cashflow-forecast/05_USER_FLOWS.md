# Cash Flow Forecast — User Flows

| | |
|---|---|
| **Status** | Draft for build · v1.0 · 21 Nov 2026 |
| **Audience** | Product, design, frontend, QA |
| **Reads with** | [PRD](01_PRD.md) (stories US-xx) · [UI spec](06_UI_SPEC.md) (screens S-xx) · [LLD](04_LLD.md) (API #) |

Each flow lists its trigger, preconditions, steps, exits and edge cases, followed by a diagram. Screen IDs (`S-01`…) refer to the [UI spec](06_UI_SPEC.md#2-screen-inventory). API numbers (`#16`) refer to [LLD §7.1](04_LLD.md#71-endpoint-catalogue). Numbers come from the synthetic tenant in [dummy-data](dummy-data/README.md).

Diagram legend: rounded boxes are user actions, rectangles are system responses, diamonds are decisions, and dotted lines are optional or asynchronous steps.

---

## 0. Flow index

| ID | Flow | Primary persona | Stories |
|---|---|---|---|
| UF-00 | Navigation map | All | — |
| UF-01 | First run: set up the forecast | Accountant, then Owner | US-20, US-21, US-25 |
| UF-02 | Morning cash check | Accountant / Owner | US-01–05, US-13 |
| UF-03 | Investigate a reserve breach | Accountant | US-10–12 |
| UF-04 | Maintain inputs (balance, recurring, adjustment, window, promise) | Accountant | US-20–24 |
| UF-05 | Build a what-if scenario | Accountant | US-30–33 |
| UF-06 | Submit, review and decide a cash plan | Accountant and Owner | US-34–36 |
| UF-07 | Plan went stale before approval | Owner and Accountant | US-35 |
| UF-08 | Breach alert to action (P1) | Owner | US-40 |
| UF-09 | Auditor review and export | Auditor | US-37 |
| UF-10 | Degraded states (no balance, stale, partial sources, no access) | All | US-13 |

---

## UF-00 · Navigation map

```mermaid
flowchart LR
    SB["Sidebar · Insights"] --> CF["Cash flow forecast<br/>S-01"]
    CF --> DD["Day drawer<br/>S-02"]
    CF --> EX["Exclusions drawer<br/>S-03"]
    CF --> IN["Inputs drawer<br/>S-04 tabs"]
    CF --> SC["Scenario panel<br/>S-05"]
    SC --> PS["Submit plan dialog<br/>S-06"]
    CF --> PH["Plans & history<br/>S-07"]
    PH --> PR["Plan review<br/>S-08"]
    PR --> DC["Decision dialog<br/>S-09"]
    DD -- "source link" --> BILL["Bill detail<br/>(existing)"]
    DD -- "source link" --> ARI["AR invoice<br/>(existing)"]
    DD -- "source link" --> PAY["Payment Hub<br/>(existing)"]
    EX -- "Apply receipt" --> CA["Cash application<br/>(existing)"]
    EX -- "Review duplicate" --> RH["Review Hub<br/>(existing)"]
    CF -. "first run" .-> SU["Setup checklist<br/>S-10"]
    CF -. "alert link" .-> CF
```

Deep links use the URL state, for example `/finance-desk/cash-forecast?view=downside&day=2026-11-30`, `…?scenario={id}` and `…/plans/{id}`.

---

## UF-01 · First run: set up the forecast

**Trigger:** the first visit by any `edit` user to a tenant with no `cf_settings` row, or with no included balance.
**Preconditions:** the `cash_forecast` entitlement is on and the user has the `accountant`, `finance_controller` or `admin` role.
**Goal:** the first forecast in under 10 minutes.

| # | User | System | Screen / API |
|---|---|---|---|
| 1 | Opens Insights → Cash flow forecast | Detects no settings or balance. Shows the setup checklist instead of the chart. | S-10 · `GET /settings`, `GET /accounts` |
| 2 | Step 1, **Accounts**: ticks HDFC Operations and SBI Collections; leaves the SBI CC unticked and enters the ₹40 L limit | Saves the include flags and the OD limit | `PATCH /accounts/{id}` (#4) |
| 3 | Step 2, **Balances**: sees statement balances already found for HDFC (₹43,51,483) and SBI (₹5,18,949), dated 20 Nov 18:30. Confirms, or types a newer figure. | Marks the statement balance as used, or saves a manual balance | `POST /balances` (#5) |
| 4 | Step 3, **Recurring obligations**: clicks *Add Indian statutory templates* | Creates GST (20th), TDS (7th), PF/ESI (15th), advance tax (quarterly 15th) and payroll (last banking day) with blank amounts | `POST /setup/seed-templates` (#10) |
| 5 | Fills in the amounts: payroll ₹21,80,000; GST ₹9,84,300; and so on. Adds rent ₹3,15,000 on the 5th and EMI ₹2,15,800 on the 10th. | Validates and saves. Templates still blank stay listed as *needs setup*. | `PATCH /recurring/{id}` (#8), `POST /recurring` (#7) |
| 6 | Step 4, **Reserve**: an owner-only field. An accountant sees “Ask your owner to set the reserve” and can continue with a ₹0 reserve. | Saves the reserve (owner only) | `PUT /settings` (#2) |
| 7 | Clicks **Build forecast** | Builds snapshot rev 1 and opens the forecast | `POST /snapshots` (#15) → S-01 |

```mermaid
flowchart TB
    A([Open Cash flow forecast]) --> B{Settings and<br/>a balance exist?}
    B -- yes --> Z[Show forecast S-01]
    B -- no --> C[Setup checklist S-10]
    C --> D([Step 1: choose accounts,<br/>set OD limits])
    D --> E{Statement balance<br/>found per account?}
    E -- yes --> F([Confirm or overwrite])
    E -- no --> G([Enter balance and as-of time])
    F --> H([Step 3: add statutory templates])
    G --> H
    H --> I([Fill amounts · add rent, EMI, utilities])
    I --> J{User can set reserve?}
    J -- owner/admin --> K([Set reserve ₹15,00,000])
    J -- accountant --> L[Notice: owner sets reserve;<br/>continue with ₹0]
    K --> M([Build forecast])
    L --> M
    M --> N[POST /snapshots → rev 1]
    N --> O{Coverage complete?}
    O -- yes --> Z
    O -- needs setup --> P[Forecast with banner:<br/>“2 templates have no amount”]
    P --> Z
```

**Exits:** the forecast is visible, or the user leaves with the checklist progress saved. Every step persists on its own.
**Edge cases:**
- An account in a foreign currency is listed as “not supported in this release” and cannot be ticked.
- An as-of time in the future is refused (422).
- A user without `edit` sees “Your admin hasn't set up the cash forecast yet” and no form.

---

## UF-02 · Morning cash check

**Trigger:** the daily routine, or the 07:00 snapshot.
**Preconditions:** a snapshot exists.
**Goal:** answer “are we OK this month?” in under 30 seconds.

| # | User | System |
|---|---|---|
| 1 | Opens the page (bookmark or sidebar) | Loads the latest snapshot and the expected view (#14, #16). If the snapshot is older than today's 07:00, or the balance is stale, shows the freshness banner. |
| 2 | Reads the KPI strip | Shows Cash today **₹48,70,432** · Lowest **₹9,99,874 on Mon 30 Nov** · First breach **30 Nov (−₹5,00,126 vs reserve)** · Runway without collections **5 days** · 30-day net **+₹30,26,415** · CC headroom **₹40,00,000** |
| 3 | Scans the chart | The line dips below the dashed reserve on 30 Nov, with a red marker |
| 4a | All clear → closes the page | — |
| 4b | Breach shown → continues to UF-03 | — |
| 5 | (Optional) Switches to **Downside** | Same revision. Lowest −₹32,44,064 on 30 Nov. First breach 23 Nov. |
| 6 | (Optional) Clicks **Refresh** after importing today's statement | `POST /snapshots`. A toast says “Updated to revision 2”, or “No changes since 07:00”. |

```mermaid
flowchart TB
    A([Open forecast]) --> B[Load latest snapshot + expected view]
    B --> C{Balance freshness}
    C -- fresh --> D[KPI strip + chart]
    C -- stale 2-3 days --> E[Amber banner:<br/>“HDFC balance is 2 days old”<br/>+ Add balance]
    C -- expired > 3 days --> F[Red banner: plans blocked<br/>+ Add balance]
    E --> D
    F --> D
    D --> G{First breach<br/>within horizon?}
    G -- no --> H[Green summary:<br/>“Stays above reserve; lowest ₹X on D”]
    G -- yes --> I[Red summary:<br/>“Drops to ₹9,99,874 on Mon 30 Nov,<br/>₹5,00,126 below reserve”]
    H --> J([Done])
    I --> K([Investigate → UF-03])
    D -.-> L([Switch view]) -.-> D
    D -.-> M([Refresh]) -.-> N{Inputs changed?}
    N -- yes --> O[New revision, toast] --> D
    N -- no --> P[Toast: no changes] --> D
```

Runway check: in the no-collections view the first negative day is 26 Nov, five days after the 21 Nov start.

---

## UF-03 · Investigate a reserve breach

**Trigger:** a red marker on the chart, or the “First breach” KPI.
**Goal:** know exactly which payments and collections cause the dip, and spot errors.

| # | User | System |
|---|---|---|
| 1 | Clicks the 30 Nov marker, a ledger row, or the KPI | Opens the day drawer (S-02, #17). Header: opening ₹42,83,944 · in ₹18,93,408 · out ₹51,77,478 · closing ₹9,99,874. |
| 2 | Reviews the outflows, sorted by amount | Payroll ₹21,80,000 (*fixed*, last banking day); insurance ₹6,85,000; six supplier bills ₹22,66,478, of which Raigad RAI/2610/203 (₹4,95,180) has an **agreed window to 2 Dec** chip; diesel ₹46,000. The other two windowed bills fall earlier in the week (Ankur ANK/2610/234 on 25 Nov, Indus IND/2610/884 on 26 Nov). Together the three hold ₹15,26,805 of movable outflow. |
| 3 | Hovers the date basis of an inflow | “Kalinga Home Essentials · 5 days overdue; remaining 7 days median (customer, n = 13)” |
| 4 | Opens a source link | Bill or invoice detail in a new tab. The drawer keeps its state. |
| 5 | Opens **Exclusions** | Seven rows. The ₹2,35,800 Polyshield duplicate links to Review Hub, and Kalinga's ₹2,84,333 links to Cash application. |
| 6 | Spots a wrong date (for example, a supplier agreed to a later date) | Goes to UF-04 (payment window), or straight to UF-05 to try a change |

```mermaid
flowchart LR
    A([Click 30 Nov]) --> B[Day drawer:<br/>opening · in · out · closing]
    B --> C{What looks wrong?}
    C -- "nothing; need a fix" --> D([Try a change → UF-05])
    C -- "supplier agreed later date" --> E([Record payment window → UF-04])
    C -- "customer promised a date" --> F([Record promise → UF-04])
    C -- "amount or status wrong at source" --> G([Open source record,<br/>fix there]) --> H([Refresh]) --> B
    C -- "something missing" --> I([Open Exclusions])
    I --> J{Reason}
    J -- SUSPECTED_DUPLICATE --> K([Review Hub])
    J -- SETTLED_PENDING_APPLICATION --> L([Cash application])
    J -- DISPUTED / AGED --> M([Collections follow-up])
    J -- PAID_VIA_DISBURSEMENT --> N[Info only:<br/>already in balance]
```

**Edge cases:**
- A day with more than 50 events paginates within the drawer, and the totals are still for the whole day.
- An auditor sees the same drawer without the *Move* actions.
- A source the user cannot open (no module access) shows the label and amount with “No access to source”.

---

## UF-04 · Maintain inputs

All inputs live in the **Inputs drawer (S-04)** tabs and can also be reached from the day drawer's context actions. Every save shows a toast and offers **Refresh forecast**. Inputs never change the open snapshot until a refresh.

### UF-04a · Record a manual balance

```mermaid
flowchart LR
    A([Inputs → Balances]) --> B([Choose account])
    B --> C([Enter amount ₹ and as-of date/time])
    C --> D{Valid?<br/>as-of ≤ now, account active}
    D -- no --> E[Inline error] --> C
    D -- yes --> F[POST /balances]
    F --> G[Freshness chip turns green]
    G --> H([Refresh forecast?]) --> I[POST /snapshots]
```

### UF-04b · Add or edit a recurring obligation

| Field | Example | Validation |
|---|---|---|
| Name | “Warehouse rent - Bhiwandi (net of TDS)” | 1–120 characters |
| Category | Rent | Enum |
| Amount | ₹3,15,000 | > 0. Blank keeps it as a template. |
| Frequency and anchor | Monthly, on the 5th | Monthly 1–31 or *last banking day*; weekly Mon–Sat; quarterly with months |
| If not a banking day | Pay next banking day | Statutory and payroll default to *previous* |
| Confidence | Committed | committed / estimated |
| Starts / ends | 1 Apr 2026 / — | end ≥ start |

A preview line under the form shows the next three dates. For example: “Next: Sat 5 Dec, Tue 5 Jan, Fri 5 Feb” (these dates come from the tenant calendar).

### UF-04c · Record a supplier payment window

```mermaid
flowchart TB
    A([Day drawer: bill row → ⋯ → Agreed later date]) --> B[Dialog prefilled:<br/>supplier, bill, due date]
    B --> C([Latest date + who agreed + evidence text<br/>or attach email/WhatsApp screenshot])
    C --> D{latest ≥ due?}
    D -- no --> E[Error: must be on or after due date] --> C
    D -- yes --> F[POST /payment-windows]
    F --> G[Bill row shows chip<br/>“Window to 4 Dec”]
    G --> H([Now movable in scenarios up to 4 Dec])
```

### UF-04d · Record a promise to pay

From the AR invoice row in the day drawer, or the Inputs tab: enter the date, amount (defaults to the outstanding amount, net of expected TDS), source (call, email, meeting…) and a note. The expected view moves the receipt to that date, with basis *promise to pay*. The downside view is unchanged. A promise that passes unpaid shows as **Broken promise** in that day's drawer (P1: alert).

### UF-04e · Add a one-off adjustment

Name, category, in/out, amount, date and confidence. Use it for things that are not in AP: insurance renewal ₹6,85,000 (30 Nov), forklift down payment ₹4,50,000 (9 Dec), expected GST refund ₹1,42,000 (16 Dec, *estimated*, so it appears in the expected view only).

---

## UF-05 · Build a what-if scenario

**Trigger:** a breach to fix, or a question like “what if Sahyadri pays late?”.
**Preconditions:** the `edit` capability and a snapshot.

| # | User | System |
|---|---|---|
| 1 | Clicks **New scenario** (or *Move* on an event in the day drawer) | The scenario panel opens with the active view and revision shown |
| 2 | Adds a change: **Move payment** Ankur ANK/2610/234 → 4 Dec | Date picker greys out non-banking days and dates outside the window (after 4 Dec). Preview runs (#19). |
| 3 | Adds Indus → 3 Dec and Raigad → 2 Dec | Each change updates the dashed scenario line and the delta card: “Lowest ₹9,99,874 → ₹19,13,700 · breach cleared” |
| 4 | Tries Raigad → 3 Dec | The picker blocks it. If typed through the API: 422 `OUTSIDE_PAYMENT_WINDOW`, and the row shows the error with “Window ends 2 Dec”. |
| 5 | Tries to move payroll | No *Move* action on fixed items. Tooltip: “Payroll and statutory dues can't be moved in a plan.” |
| 6 | Adds an assumption: **Delay customer** Sahyadri +10 days | The row is tagged *Assumption*. Closing on 20 Dec drops by ₹14,50,000; the minimum is unchanged. |
| 7 | Clicks **Save as** “Defer three windowed supplier payments” | `POST /scenarios`. The scenario appears in the selector. |
| 8 | Switches to **Downside** with the scenario on | Downside minimum −₹32,44,064 → −₹17,66,767. The breach persists, and the CC headroom (₹40 L) chip is highlighted. |
| 9 | Continues to UF-06 | — |

```mermaid
flowchart TB
    A([New scenario]) --> B[Scenario panel<br/>view + revision shown]
    B --> C([Add change])
    C --> D{Change type}
    D -- Move payment --> E([Pick event + date])
    D -- Move receipt --> F([Pick invoice + date])
    D -- Delay customer --> G([Customer + days])
    D -- Collect only X% --> H([Customer + percent])
    D -- Exclude receipt --> I([Pick invoice])
    D -- Add item --> J([Label, in/out, amount, date,<br/>category, confidence])
    E & F & G & H & I & J --> K[POST /forecast/preview]
    K --> L{Valid?}
    L -- refused --> M[Row error with reason<br/>FIXED_OBLIGATION / OUTSIDE_PAYMENT_WINDOW /<br/>NON_BANKING_DAY / EXCEEDS_OD_HEADROOM] --> C
    L -- ok --> N[Chart: baseline solid + scenario dashed<br/>Delta card: min, breach, closing]
    N --> O{Satisfied?}
    O -- no --> C
    O -- yes --> P([Save scenario]) --> Q[POST /scenarios]
    Q --> R{Submit as plan?}
    R -- yes --> S([UF-06])
    R -- later --> T([Done; reopen from selector])
```

**Rebase on reopen:** opening a scenario saved on an older revision triggers revalidation. Each change gets a badge: ✓ *still valid*, ⚠ *now outside window* (the window was shortened), or ✕ *bill no longer open* (it was paid). The scenario status becomes *Needs review* until the user resolves the badges.

---

## UF-06 · Submit, review and decide a cash plan

Swimlane view: accountant and owner.

```mermaid
flowchart TB
    subgraph ACC["Accountant"]
        a1([Scenario ready]) --> a2([Submit as plan + note:<br/>“Ankur/Indus/Raigad agreed in writing;<br/>keeps us above reserve on payroll day”])
        a5([Read return note]) --> a6([Edit scenario]) --> a7([Resubmit → v2])
    end
    subgraph SYS["System"]
        s1[Revalidate on pinned revision<br/>recompute metrics · freeze v1<br/>state = submitted · audit] --> s2[Notify owners in-app<br/>email P1]
        s4[Lock plan · checks:<br/>state, version, not self,<br/>fresh balance, not stale]
        s4 --> s5{Decision}
        s5 -- approve --> s6[state = approved<br/>supersede previous<br/>adopt planned dates · audit]
        s5 -- return --> s7[state = returned · audit<br/>notify submitter]
        s8[Next snapshot: three bills<br/>dated by approved plan]
    end
    subgraph OWN["Owner"]
        o1([Open plan from notification<br/>or Plans list]) --> o2([Review: baseline vs plan chart,<br/>changes list with decision/assumption tags,<br/>downside result, evidence links])
        o2 --> o3{Agree?}
        o3 -- yes --> o4([Approve + optional note])
        o3 -- no --> o5([Return + required note])
    end
    a2 --> s1
    s2 --> o1
    o4 --> s4
    o5 --> s4
    s7 --> a5
    a7 --> s1
    s6 --> s8
```

**Plan review screen (S-08) content, from the fixture:**
- Header: “Defer three windowed supplier payments · v1 · submitted by Accountant · rev 1 · Expected view”.
- Outcome card: “Lowest balance ₹9,99,874 → **₹19,13,700**. Reserve breach on 30 Nov → **none**.”
- Downside card: “Still below reserve from 23 Nov; lowest −₹17,66,767 on 2 Dec. Depends on collections or the CC line (₹40 L available).”
- Changes list: three *decisions*, each with its window evidence (“Email from supplier accounts, 17 Nov”).
- A notice that cannot be dismissed: “Approving records the plan. It does not make or schedule any payment. Payments go through Payment Hub as usual.”

**Decision rules (server-enforced):** the approver must have the `approve` capability, must not be the submitter (unless the tenant allows self-approval), and the balance must not be expired. The plan must not be stale (UF-07). A double click on Approve creates one decision, because both requests share an idempotency key.

---

## UF-07 · Plan went stale before approval

**Trigger:** the owner clicks Approve, but inputs changed after submission. For example, a new bill was approved, or Indus was paid.

```mermaid
flowchart TB
    A([Owner clicks Approve]) --> B[Build/reuse current snapshot]
    B --> C{Revision changed?}
    C -- no --> OK[Approve]
    C -- yes --> D[Revalidate overrides<br/>recompute key metrics]
    D --> E{Overrides valid AND<br/>metrics identical?}
    E -- yes --> OK2[Approve<br/>“validated on revision 3”]
    E -- no --> F[409 PLAN_STALE]
    F --> G[Dialog: what changed<br/>• Indus IND/2610/884 paid on 24 Nov — change dropped<br/>• Lowest balance now ₹16,02,110 vs ₹19,13,700 submitted]
    G --> H{Owner choice}
    H -- "Return to accountant" --> I[Return with auto-note listing changes]
    H -- "Cancel" --> J([Close; plan stays submitted])
```

The values in this diagram illustrate the dialog. The diff is computed live.

---

## UF-08 · Breach alert to action (P1)

```mermaid
sequenceDiagram
    autonumber
    participant J as 07:00 job
    participant O as Owner
    participant UI as Forecast page
    participant A as Accountant
    J->>J: Build snapshot, expected view
    J->>O: In-app (+email): "Cash may fall to ₹9.99 L on Mon 30 Nov — ₹5.0 L below reserve"
    O->>UI: Open link (?view=expected&day=2026-11-30)
    UI-->>O: Day drawer open on 30 Nov
    O->>A: Assign: "Please propose a plan" (comment on alert, P2)
    A->>UI: UF-05 → UF-06
    Note over J: Next day: same breach date → no repeat alert.<br/>Breach moves or deepens by > 10% → new alert.
```

---

## UF-09 · Auditor review and export

| # | Auditor | System |
|---|---|---|
| 1 | Opens Cash flow forecast | Read-only: no Refresh, no Move, no inputs editing. View switch and drawers work. |
| 2 | Opens **Plans & history** (S-07) | Lists plans with state, version, submitter, approver, timestamps and the revision used |
| 3 | Opens an approved plan | Shows the frozen metrics, overrides, decision note, `validated_on_revision` and the audit trail |
| 4 | Clicks **Export CSV** | `GET /export.csv`. The file header carries the tenant, revision, view, as-of, reserve and plan ID. It has a daily rows section, an events section (with date basis) and an exclusions section. |

---

## UF-10 · Degraded and empty states

```mermaid
flowchart TB
    A([Open page]) --> R{Has view capability?}
    R -- no --> R1[403 page:<br/>“Cash forecast is available to finance roles.<br/>Ask your admin for access.”]
    R -- yes --> B{Snapshot exists?}
    B -- no --> B1{Has edit?}
    B1 -- yes --> SU[Setup checklist UF-01]
    B1 -- no --> B2[Empty state:<br/>“Not set up yet” + who to ask]
    B -- yes --> C{Coverage}
    C -- complete --> OK[Normal]
    C -- partial: source failed --> P[Amber banner naming source:<br/>“Receivables couldn't be read at 07:00.<br/>Figures exclude customer receipts.”<br/>Retry · plans blocked]
    C -- needs setup --> NS[Info banner:<br/>“Payroll has no amount — forecast may be optimistic”<br/>Set up]
    OK --> D{Balance freshness}
    D -- expired --> E[Red banner + Add balance<br/>Submit/Approve disabled with reason]
    D -- ok --> F[Normal]
```

| State | Copy (headline) | Primary action |
|---|---|---|
| No access | “Cash forecast is available to finance roles.” | — |
| Not set up (edit) | “Set up your cash forecast” | Start setup |
| Not set up (view only) | “Your finance team hasn't set up the cash forecast yet.” | — |
| No balance | “Add today's bank balance to see your forecast.” | Add balance |
| Stale balance | “HDFC Operations balance is 2 banking days old.” | Add balance |
| Expired balance | “Balances are over 3 banking days old. Plans can't be submitted or approved until you update them.” | Add balance |
| Partial sources | “Receivables couldn't be read. Figures exclude customer receipts.” | Retry |
| No breach | “Stays above your ₹15,00,000 reserve. Lowest ₹X on D.” | — |
| Preview refused | Reason-specific (see [UI spec §8](06_UI_SPEC.md#8-copy-and-messages)) | Fix the change |
