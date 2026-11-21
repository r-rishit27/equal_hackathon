# Cash Flow Forecast — UI Specification

| | |
|---|---|
| **Status** | Draft for build · v1.0 · 21 Nov 2026 |
| **Audience** | Frontend engineers, designers, QA |
| **Reads with** | [User flows](05_USER_FLOWS.md) · [LLD §11](04_LLD.md#11-frontend-low-level-design) · design tokens in [`frontend/src/styles/tokens.css`](../../frontend/src/styles/tokens.css) · UI kit in [`frontend/src/ui`](../../frontend/src/ui) |

All sample values in the wireframes come from the synthetic tenant ([dummy-data](dummy-data/README.md)): **expected view, snapshot revision 1, as of 20 Nov 2026 18:30 IST**.

---

## 1. Design principles for this page

1. **The answer comes first.** One sentence at the top says whether cash stays above the reserve, and if not, when and by how much. Numbers, chart and table support that sentence.
2. **Every number is clickable.** KPI, chart point, ledger row and driver bar all open the evidence behind them.
3. **Words and icons, not just colour.** A breach is red *and* says “below reserve” *and* carries an icon.
4. **Calm by default.** The page uses the app's existing navy and teal palette. Red is reserved for days below the reserve. Amber is for stale inputs and assumptions.
5. **No money moves here.** No button on this page says Pay, Send or Transfer.

## 2. Screen inventory

| ID | Screen / surface | Type | Who sees it |
|---|---|---|---|
| S-01 | Cash flow forecast (main) | Page `/finance-desk/cash-forecast` | view |
| S-02 | Day drawer | Right drawer (480 px) | view (Move actions: edit) |
| S-03 | Exclusions drawer | Right drawer | view |
| S-04 | Inputs drawer: Balances · Recurring · Adjustments · Payment windows · Promises · Settings | Right drawer (640 px) with tabs | view (forms: edit; Settings: settings) |
| S-05 | Scenario panel | Inline panel (right column), expands to a full-width sheet on mobile | edit |
| S-06 | Submit plan dialog | Modal | edit |
| S-07 | Plans and history | Tab on page (`/finance-desk/cash-forecast/plans`) | view |
| S-08 | Plan review | Page section (`…/plans/{id}`) | view (decide: approve) |
| S-09 | Decision dialog (approve / return) | Modal | approve |
| S-10 | Setup checklist | Page state | edit |
| S-11 | Stale plan dialog | Modal | approve |

## 3. Layout and grid

- The page sits inside the existing app shell: sidebar (56/216 px) and top bar (54 px). Content max width is 1440 px with 24 px padding (16 px below 768 px).
- Desktop uses a 12-column grid with a 24 px gutter. Order: header, freshness strip, KPI strip (6 cards), chart (full width), a two-column row (Drivers 5 cols, Scenario/Plan 7 cols) and the ledger table (full width).
- Tablet (768–1199 px): KPIs wrap to a 3×2 grid. The Drivers and Scenario panels stack.
- Mobile (< 768 px): KPIs become a horizontally scrollable row of 2.5 visible cards. The chart is 220 px tall. The ledger table switches to a card list. Drawers become full-screen sheets. The scenario panel opens as a bottom sheet.

## 4. Wireframes

### 4.1 S-01 Main page (desktop, expected view, with breach)

```
┌───────────────────────────────────────────────────────────────────────────────────────────────┐
│ Insights / Cash flow forecast                                                                 │
│ Cash flow forecast                      [ Expected ▾ | Downside | No new collections ]        │
│ Next 30 days · 21 Nov – 20 Dec 2026 · Revision 1        ⟳ Refresh   ⇩ Export   ☰ Inputs  ⓘ    │
├───────────────────────────────────────────────────────────────────────────────────────────────┤
│ ● HDFC Operations XX4821  ₹43,51,483  20 Nov 18:30  statement      ● SBI Collections XX0937   │
│   ₹5,18,949  20 Nov 18:30  statement     ○ SBI Cash Credit XX5512 (not in forecast) ₹40 L free│
│ Coverage: complete · 229 items · 7 excluded ›                                                 │
├───────────────────────────────────────────────────────────────────────────────────────────────┤
│ ▲ Cash drops to ₹9,99,874 on Mon 30 Nov, ₹5,00,126 below your ₹15,00,000 reserve.             │
│   Payroll (₹21.8 L), insurance renewal (₹6.85 L) and six supplier bills land the same day.    │
│   [ See 30 Nov ]  [ Try a fix ]                                                               │
├──────────────┬──────────────┬──────────────┬──────────────┬──────────────┬────────────────────┤
│ CASH TODAY   │ LOWEST       │ FIRST BREACH │ RUNWAY, NO   │ 30-DAY NET   │ CC HEADROOM        │
│ ₹48.70 L     │ ₹10.00 L     │ Mon 30 Nov   │ COLLECTIONS  │ +₹30.26 L    │ ₹40.00 L           │
│ 20 Nov 18:30 │ Mon 30 Nov   │ ▼ ₹5.00 L    │ 5 days       │ in ₹2.23 Cr  │ not counted in     │
│              │ ▲ below res. │ below reserve│ ends 26 Nov  │ out ₹1.92 Cr │ balance            │
├──────────────┴──────────────┴──────────────┴──────────────┴──────────────┴────────────────────┤
│  ₹ L                                                                                          │
│  60 ┤                                                                                         │
│  50 ┤●╮       ╭──╮                                                                   ╭──●     │
│  40 ┤ │       │  │          ╭──╮  ╭╮      ╭──╮ ╭──╮     ╭────╮   ╭─╮ ╭──╮  ╭───╮ ╭──╯   │    │
│  30 ┤ ╰──╮  ╭─╯  │       ╭──╯  ╰──╯╰──────╯  ╰─╯  ╰─────╯    ╰───╯ ╰─╯  ╰──╯   ╰─╯          │
│  20 ┤    ╰──╯    │       │                                                                  │
│  15 ┼ ─ ─ ─ ─ ─ ─│─ ─ ─ ─│─ ─ ─ ─ ─ ─ ─ ─ ─ ─ Reserve ₹15 L ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─   │
│  10 ┤            ╰───◆───╯                                                                    │
│   0 ┼─────────────────────────────────────────────────────────────────────────────────────    │
│      21 23 25 27 29 │1  3  5  7  9  11 13 15 17 19                                            │
│      Nov            Dec       ░ non-banking day   ◆ below reserve   ── closing balance        │
├────────────────────────────────────────┬──────────────────────────────────────────────────────┤
│ WHAT DRIVES THE NEXT 30 DAYS           │ SCENARIO                          [ + New scenario ] │
│ Collections        +₹2,21,14,651  ████ │ No scenario applied.                                 │
│ GST refund (est.)     +₹1,42,000  ▏    │ Try moving a supplier payment inside its agreed      │
│ Suppliers         −₹1,29,69,886  ███   │ window, or test a late customer.                     │
│ Payroll              −₹21,80,000  ▌    │                                                      │
│ Statutory            −₹21,33,550  ▌    │ Saved: [ Defer three windowed supplier payments ▾ ]  │
│ Insurance             −₹6,85,000  ▏    │                                                      │
│ Capex                 −₹4,50,000  ▏    │ PLAN                                                 │
│ Rent                  −₹3,15,000  ▏    │ No plan awaiting decision.  Last approved: —         │
│ Debt (EMI)            −₹2,15,800  ▏    │                                                      │
│ Other                 −₹2,81,000  ▏    │                                                      │
│ Beyond 20 Dec: +₹1.28 Cr in · −₹20.6 L │                                                      │
├────────────────────────────────────────┴──────────────────────────────────────────────────────┤
│ DAY BY DAY                                         [ Show non-banking days ☐ ]  [ ⇩ CSV ]    │
│ Date         Opening         In             Out            Closing         vs reserve         │
│ Sat 21 Nov   48,70,431.84    —              23,31,354.60   25,39,077.24    +10,39,077.24      │
│ Mon 23 Nov   25,39,077.24     4,61,680.00   10,87,057.00   19,13,700.24     +4,13,700.24      │
│ Wed 25 Nov   19,13,700.24    14,61,548.00   11,73,053.50   22,02,194.74     +7,02,194.74      │
│ …                                                                                             │
│ ◆ Mon 30 Nov 42,83,944.24    18,93,408.00   51,77,478.00    9,99,874.24     −5,00,125.76 Below│
│ …                                                                                             │
└───────────────────────────────────────────────────────────────────────────────────────────────┘
```

Notes:
- Compact KPI values use 2 decimals in lakh or crore (`₹48.70 L`). Summary sentences round to whole rupees, half up (`₹48,70,432`).
- **The ledger table, day drawer and exports show exact paise** (`48,70,431.84`). Rounding each column to rupees separately breaks the row identity opening + in − out = closing. On the fixture, 25 Nov would show 19,13,700 + 14,61,548 − 11,73,054 = 22,02,194 against a closing of 22,02,195. Exact figures keep every row reconcilable, which is what an accountant checks first.
- Non-banking days are hidden in the ledger by default, because they never carry flows. The toggle shows them.
- The chart's daily points sit at the closing balance. The line is a step-after shape (balance holds over non-banking days).

### 4.2 S-01 with a scenario applied

```
┌ SCENARIO · Defer three windowed supplier payments            Expected · rev 1   [ Save ] [⋯] ┐
│ Lowest ₹9,99,874 → ₹19,13,700  (+₹9,13,826)      Breach 30 Nov → none ✓                       │
│ Closing 20 Dec ₹78,96,847 → ₹78,96,847 (no change)                                            │
│                                                                                               │
│  DECISION  Move  Ankur Corrugators · ANK/2610/234  ₹5,65,920   25 Nov → 4 Dec  window ✓  ✕    │
│  DECISION  Move  Indus Strapping · IND/2610/884    ₹4,65,705   26 Nov → 3 Dec  window ✓  ✕    │
│  DECISION  Move  Raigad Kraft Paper · RAI/2610/203 ₹4,95,180   30 Nov → 2 Dec  window ✓  ✕    │
│                                                                                               │
│  [ + Add change ▾ ]  Move payment · Move receipt · Delay customer · Collect only X% ·          │
│                      Exclude receipt · Add item                                               │
│                                                                                               │
│  Downside with this scenario: lowest −₹17,66,767 on 2 Dec; below reserve from 23 Nov.          │
│                                                                    [ Submit as plan → ]       │
└───────────────────────────────────────────────────────────────────────────────────────────────┘
Chart: solid line = baseline (ink-400, 1.5 px) · dashed line = scenario (brand-600, 2 px)
```

### 4.3 S-02 Day drawer

```
┌ Mon 30 Nov 2026 · Expected view                                   ✕ ┐
│ Opening ₹42,83,944   In +₹18,93,408   Out −₹51,77,478               │
│ Closing ₹9,99,874   ▲ ₹5,00,126 below reserve                       │
├─────────────────────────────────────────────────────────────────────┤
│ OUT  (9)                                               −₹51,77,478  │
│ Salaries (net pay, 46 staff)        payroll   FIXED    ₹21,80,000   │
│   Monthly · last banking day                                        │
│ Annual insurance renewal            insurance COMMITTED ₹6,85,000   │
│   Adjustment · “Policy renews 1 Dec; broker debit note …”           │
│ Ankur Corrugators · ANK/2610/974    supplier  COMMITTED ₹6,43,145   │
│   Due 30 Nov · net of TDS ₹545.50 ›                         [ Move ]   │
│ Polyshield Films · POL/2610/362     supplier  COMMITTED ₹5,31,140   │
│ Raigad Kraft Paper · RAI/2610/203   supplier  COMMITTED ₹4,95,180   │
│   Due 29 Nov (Sun) → 30 Nov · Window to 2 Dec ⓘ          [ Move ]   │
│ Sutlej Adhesive Tapes · SUT/2610/786 supplier COMMITTED ₹4,45,662   │
│ Mahalaxmi Pallets · MAH/2610/313    supplier  COMMITTED ₹1,18,872   │
│ Diesel for delivery fleet           operations ESTIMATED   ₹46,000  │
│ Bharat Roadlines · BHA/2611/463     supplier  COMMITTED    ₹32,480  │
├─────────────────────────────────────────────────────────────────────┤
│ IN  (5)                                                +₹18,93,408  │
│ Chambal Cement · KPD/26-27/01316    customer  EXPECTED  ₹6,11,901   │
│   23 days overdue · remaining 8 days median (customer, n=8) ›       │
│ Kalinga Home Essentials · …01235    customer  EXPECTED  ₹5,57,667   │
│   5 days overdue · remaining 7 days median (customer, n=13)         │
│ …                                                                   │
├─────────────────────────────────────────────────────────────────────┤
│ Daily totals. Timing within a day isn't modelled.                   │
└─────────────────────────────────────────────────────────────────────┘
```

Row anatomy: label (counterparty · document, linked) · category · confidence badge · amount (right-aligned, tabular figures) · second line with the date basis · actions (`Move`, `⋯` → *Agreed later date*, *Promise to pay*, *Open source*).

### 4.4 S-03 Exclusions drawer

```
┌ Not in this forecast (7)                                          ✕ ┐
│ These records exist but are left out so nothing is counted twice    │
│ or forecast without basis.                                          │
├─────────────────────────────────────────────────────────────────────┤
│ Already in the bank balance                                         │
│  Kalinga Home Essentials · KPD/26-27/01479      ₹2,84,333           │
│   Receipt of 20 Nov awaits cash application.  [ Apply receipt › ]   │
│  Raigad Kraft Paper · RAI/2610/209              ₹3,39,552           │
│   Paid 19 Nov via Payment Hub; bill status not yet synced.          │
├─────────────────────────────────────────────────────────────────────┤
│ Counted once elsewhere                                              │
│  Ankur Corrugators · ANK/2610/248               ₹4,11,943           │
│   Payout in flight; counted as the payout on 21 Nov.                │
├─────────────────────────────────────────────────────────────────────┤
│ Held for review                                                     │
│  Polyshield Films · POL/2611/899                ₹2,35,800           │
│   Suspected duplicate.  [ Review in Review Hub › ]                  │
│  Chambal Cement · KPD/26-27/01480               ₹3,10,000           │
│   Disputed by customer.                                             │
├─────────────────────────────────────────────────────────────────────┤
│ Not payable                                                         │
│  Pune Hydraulics · PUN/2611/330                   ₹55,680           │
│   Rejected in approval.                                             │
├─────────────────────────────────────────────────────────────────────┤
│ Downside view only                                                  │
│  Thar Handicraft Exports · KPD/26-27/01481      ₹2,18,300           │
│   74 days overdue; counted in Expected only.                        │
└─────────────────────────────────────────────────────────────────────┘
```

### 4.5 S-04 Inputs drawer: Recurring tab

```
┌ Forecast inputs                                                                    ✕ ┐
│ [Balances] [Recurring ●] [Adjustments] [Payment windows] [Promises] [Settings]       │
├──────────────────────────────────────────────────────────────────────────────────────┤
│ Recurring obligations (10)                                     [ + Add ] [ Templates ]│
│ Name                               Amount       When                       Next      │
│ Salaries (net pay, 46 staff)       ₹21,80,000   Monthly · last banking day  30 Nov   │
│ GST payment - GSTR-3B              ₹9,84,300    Monthly · 20th · prev day   19 Dec   │
│ Advance tax - Q3 instalment        ₹6,50,000    Quarterly · 15th · prev day 15 Dec   │
│ Warehouse rent (net of TDS)        ₹3,15,000    Monthly · 5th · next day     5 Dec   │
│ PF and ESI contribution            ₹3,02,400    Monthly · 15th · prev day   15 Dec   │
│ Term loan EMI - SBI                ₹2,15,800    Monthly · 10th · next day   10 Dec   │
│ TDS deposit (previous month)       ₹1,96,850    Monthly · 7th · prev day     7 Dec   │
│ Electricity - MSEDCL      est.       ₹78,400    Monthly · 3rd                3 Dec   │
│ Diesel for delivery fleet est.       ₹46,000    Weekly · Monday             23 Nov   │
│ Internet and telephone    est.       ₹18,600    Monthly · 12th · next day   14 Dec   │
└──────────────────────────────────────────────────────────────────────────────────────┘
```

Edit form (inline expansion): Name · Category · Amount (`useAmountField`, Indian grouping) · Frequency (segmented) · Anchor · “If not a banking day” (Previous / Next) · Confidence · Start / End · preview line “Next: Mon 30 Nov, Thu 31 Dec, Sat 30 Jan”.

### 4.6 S-06 Submit plan dialog

```
┌ Submit cash plan for approval                                   ✕ ┐
│ Defer three windowed supplier payments · Expected · revision 1    │
│                                                                   │
│ Lowest balance   ₹9,99,874  →  ₹19,13,700                         │
│ Reserve breach   30 Nov     →  none                               │
│ Downside         still below reserve from 23 Nov (lowest −₹17.67 L)│
│                                                                   │
│ 3 decisions · 0 assumptions                                       │
│                                                                   │
│ Note for approver (required)                                      │
│ ┌───────────────────────────────────────────────────────────────┐ │
│ │ All three suppliers agreed in writing (see windows). Keeps us │ │
│ │ above reserve on payroll day.                                 │ │
│ └───────────────────────────────────────────────────────────────┘ │
│ ⓘ Approval records the plan. It doesn't pay or schedule anything. │
│                                        [ Cancel ]  [ Submit plan ] │
└───────────────────────────────────────────────────────────────────┘
```

### 4.7 S-08 Plan review and S-09 decision

```
┌ Plans / Defer three windowed supplier payments                         SUBMITTED · v1 ┐
│ Submitted by Accountant · 21 Nov 10:42 · Snapshot revision 1 · Expected view           │
├────────────────────────────────────────────────────────────────────────────────────────┤
│ [ mini chart: baseline vs plan, reserve line ]                                         │
│ Lowest ₹9,99,874 → ₹19,13,700 · Breach 30 Nov → none · Closing unchanged ₹78,96,847     │
│ Downside: below reserve from 23 Nov; lowest −₹17,66,767 on 2 Dec. CC headroom ₹40 L.    │
├────────────────────────────────────────────────────────────────────────────────────────┤
│ Changes                                                                                │
│ DECISION Ankur ANK/2610/234   ₹5,65,920  25 Nov → 4 Dec  Window: email from supplier   │
│                                                          accounts, 17 Nov ›           │
│ DECISION Indus IND/2610/884   ₹4,65,705  26 Nov → 3 Dec  Window: email thread, 18 Nov  │
│ DECISION Raigad RAI/2610/203  ₹4,95,180  30 Nov → 2 Dec  Window: WhatsApp confirmation │
├────────────────────────────────────────────────────────────────────────────────────────┤
│ Note: “All three suppliers agreed in writing …”                                        │
│ ⓘ Approving records these payment dates for future forecasts. Payments still go        │
│   through Payment Hub with its usual approvals and OTP.                                │
│                                              [ Return with note ]   [ Approve plan ]   │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

Approve opens S-09 with an optional note and a final **Approve** button. Return requires a note. Both buttons disable while the request is in flight. A repeated click reuses the same `Idempotency-Key`.

### 4.8 Mobile (S-01, 390 px)

```
┌──────────────────────────────┐
│ ☰  Cash flow forecast     ⟳  │
│ [Expected][Downside][No coll]│
│ ▲ Drops to ₹9.99 L on Mon    │
│   30 Nov · ₹5.0 L below      │
│   reserve   [See day]        │
│ ┌────────┐┌────────┐┌───    │
│ │CASH    ││LOWEST  ││FIRST   │
│ │₹48.70 L││₹10.00 L││BREACH  │
│ └────────┘└────────┘└───    │
│ [ chart 220px, swipe-scrub ] │
│ Drivers ▸                    │
│ Scenario ▸                   │
│ Day by day                   │
│ ┌──────────────────────────┐ │
│ │ Mon 30 Nov   ◆ Below     │ │
│ │ Closing ₹9,99,874        │ │
│ │ In 18.93 L · Out 51.77 L │ │
│ └──────────────────────────┘ │
└──────────────────────────────┘
```

### 4.9 S-10 Setup checklist

```
┌ Set up your cash forecast                                     3 of 4 done ┐
│ ✓ 1  Choose bank accounts            HDFC Operations, SBI Collections     │
│ ✓ 2  Confirm today's balances         2 accounts · 20 Nov 18:30            │
│ ● 3  Recurring obligations            8 of 10 have amounts  [ Continue ]   │
│      ⚠ PF and ESI, Advance tax need amounts                               │
│ ○ 4  Set your cash reserve            Owner sets this   [ Ask owner ]      │
│                                           [ Build forecast anyway → ]      │
└───────────────────────────────────────────────────────────────────────────┘
```

## 5. Component specifications

Reuse the UI kit (`frontend/src/ui`): `PageHeader`, `Card`, `Badge`, `Button`, `IconButton`, `Dropdown`, `Modal`, `ConfirmDialog`, `DataTable`, `EmptyState`, `ErrorState`, `Skeleton`, `Tooltip`, `useToast`, `useFocusTrap`, `useAmountField`. Use `formatMoney` and `formatMoneyCompact` from `ui/format.ts` with `paise / 100`. Add only `formatPaise(paise, {compact?})` as a thin wrapper.

| Component | Props | States | Notes |
|---|---|---|---|
| `ForecastHeader` | `view`, `snapshot`, `canEdit`, `onView`, `onRefresh`, `onExport`, `onInputs` | refreshing (spinner on button, disabled), rate-limited (tooltip with retry time) | The view switch is a segmented control with `role="radiogroup"` |
| `FreshnessStrip` | `balances[]`, `coverage`, `odHeadroom` | fresh (green dot), stale (amber dot + “2 days old”), expired (red dot + “Update balance”) | Each chip opens Inputs → Balances for that account |
| `SummarySentence` | `metrics`, `reserve`, `view` | breach / no breach / negative | Copy rules in §8. Includes up to 3 drivers of the minimum day. |
| `KpiCard` | `label`, `value`, `sub`, `tone`, `onClick` | default, warning, danger, skeleton | Value in `--fs-xl` with tabular figures. Clickable cards are `<button>`. |
| `ForecastChart` | `baseline: DayRow[]`, `scenario?: DayRow[]`, `reserve`, `selected?`, `onSelectDay` | loading (skeleton), empty, with scenario | §6 |
| `DriversPanel` | `categoryTotals`, `beyond` | — | Bars are proportional to the absolute value within the panel. A click filters the ledger to that category. |
| `ScenarioPanel` | `scenario`, `preview`, `refusals`, `canEdit` | empty, editing, previewing (inline spinner), refused rows, saved, needs_review | Each row shows a kind tag: DECISION (brand), ASSUMPTION (amber) |
| `AddChangeMenu` | `snapshot`, `view` | — | Event pickers search by counterparty or document. Date picker disables non-banking days and out-of-window dates. |
| `DayLedgerTable` | `days`, `showNonBanking`, `onSelectDay`, `filter?` | — | `DataTable`, sticky header, row click opens S-02. Below-reserve rows carry the ◆ icon and the word “Below”. |
| `DayDrawer` | `date`, `view`, `scenarioId?`, `canEdit` | loading, loaded, error | Focus trap. Esc closes. Returns focus to the trigger. |
| `ExclusionsDrawer` | `snapshotId`, `view` | — | Grouped by reason family (§4.4) |
| `InputsDrawer` | `tab`, `canEdit`, `canSettings` | per tab: list, empty, form, saving | Forms validate on blur and submit. After a save, the toast offers *Refresh forecast*. |
| `PlanPanel` | `activePlan?`, `lastApproved?` | none, draft, submitted (awaiting), returned (note shown), approved | — |
| `DecisionDialog` | `plan`, `decision` | idle, submitting, stale (switches to S-11), error | Generates the idempotency key on open |

## 6. Chart specification

| Element | Spec |
|---|---|
| Size | Full width. Height 320 px desktop, 260 px tablet, 220 px mobile. |
| X axis | One tick per banking day. Labels every 2nd day desktop, every 5th on mobile, with the month label at month change. Non-banking days drawn as `--surface-2` bands. |
| Y axis | Compact INR (`₹40 L`, `₹1 Cr`). Domain `[min(0, minClosing) × 1.1, maxClosing × 1.1]` rounded with `niceCeil`. A zero rule in `--ink-300` if the domain crosses 0. |
| Baseline line | `--brand-600`, 2 px, step-after. When a scenario is active the baseline becomes `--ink-400` at 1.5 px. |
| Scenario line | `--brand-600`, 2 px, dashed `6 4` |
| Reserve | `--danger-500` dashed 1 px horizontal rule, labelled “Reserve ₹15 L” at the right end |
| Below-reserve points | ◆ marker in `--danger-600`, 8 px. A segment below the reserve gets a `--danger-50` fill between the line and the reserve. |
| Hover / focus | Vertical guide plus a tooltip: date, closing (exact), in, out, “below reserve by ₹X”. Keyboard: Left/Right moves day, Enter opens the drawer. |
| Accessibility | `role="img"` with an `aria-label` summary sentence. Linked to the ledger table via `aria-describedby`. The table is the full-data equivalent. |
| Animation | 180 ms (`--dur-base`) on view switch. No animation under `prefers-reduced-motion`. |

## 7. Visual tokens

| Use | Token |
|---|---|
| Page background | `--canvas` |
| Cards | `--surface-0`, border `--line-200`, radius `--r-lg` |
| Primary action | `--brand-600` |
| Positive amount (inflow) | `--success-700` text, `+` sign |
| Negative amount (outflow) | `--ink-800` text, `−` sign (U+2212). Outflows are not red. |
| Below reserve | `--danger-600` text, `--danger-50` background, ◆ icon |
| Stale / assumption | `--warn-700` text, `--warn-50` background |
| Confidence badges | CONFIRMED `info` · COMMITTED `neutral` · PIPELINE `warn` · EXPECTED `neutral` · ESTIMATED `warn` · FIXED `brand` |
| Category colours in Drivers | `--cat-1`…`--cat-8` (collections `--cat-3`, suppliers `--cat-1`, payroll `--cat-4`, statutory `--cat-2`, rent `--cat-5`, debt `--cat-6`, insurance `--cat-7`, other `--cat-8`) |
| Numbers | `font-variant-numeric: tabular-nums`, right-aligned |

## 8. Copy and messages

### 8.1 Summary sentence

| Condition | Template | Fixture example |
|---|---|---|
| No breach | “Stays above your {reserve} reserve. Lowest {min} on {day}.” | (plan) “Stays above your ₹15,00,000 reserve. Lowest ₹19,13,700 on Mon 23 Nov.” |
| Breach, positive | “Cash drops to {min} on {day}, {gap} below your {reserve} reserve.” | “Cash drops to ₹9,99,874 on Mon 30 Nov, ₹5,00,126 below your ₹15,00,000 reserve.” |
| Goes negative | “Cash runs out on {first_negative}. Lowest {min} on {day}.” | (downside) “Cash runs out on Mon 30 Nov. Lowest −₹32,44,064 on Mon 30 Nov.” |
| No collections view | “Without new collections, cash runs out in {runway} days, on {first_negative}.” | “Without new collections, cash runs out in 5 days, on Thu 26 Nov.” |

Driver line: “{top 3 outflows by amount on the min day} land the same day.”

### 8.2 Refusal and error copy

| Code | Message |
|---|---|
| `OUTSIDE_PAYMENT_WINDOW` | “{supplier} agreed to payment no later than {latest}. Record a new agreement to move it further.” |
| `OUTSIDE_PAYMENT_WINDOW` (no window) | “This bill is due {due}. To pay later, first record the supplier's agreement.” |
| `FIXED_OBLIGATION` | “Payroll, statutory dues and loan EMIs can't be moved in a plan.” |
| `NON_BANKING_DAY` | “{date} isn't a banking day. Choose another date.” |
| `BEFORE_HORIZON` | “Choose a date on or after {start}.” |
| `INFLOW_ONLY` | “Only receipts can be excluded. Payments can be moved inside their agreed window.” |
| `EXCEEDS_OD_HEADROOM` | “That's more than the ₹{headroom} available on your cash-credit line.” |
| `SHIFT_TOO_FAR` | “Move recurring items by 15 days at most.” |
| `PLAN_STALE` | “Things changed since this plan was submitted.” plus the diff list |
| `SELF_APPROVAL` | “You submitted this plan, so someone else needs to approve it.” |
| `BALANCE_EXPIRED` | “Update bank balances first. They're over 3 banking days old.” |
| `PLAN_STATE` | “This plan was already decided. Refresh to see the latest.” |
| `NO_OPENING_BALANCE` | “Add today's bank balance to see your forecast.” |
| `RATE_LIMITED` | “Refreshed too often. Try again in {n} seconds.” |
| Network / 5xx | “Couldn't load the forecast. Your inputs are safe. Try again.” plus the request ID |

### 8.3 Microcopy rules

- Dates use the format “Mon 30 Nov”. The year appears only when the horizon crosses a year boundary.
- Amounts are always in rupees with the ₹ sign. Use “L” and “Cr” only in compact contexts.
- Say “payment”, “receipt” and “bill”. Avoid jargon like “AP”, “AR” and “outflow” in user-facing copy. The Drivers panel may use “Collections” and “Suppliers”.
- Every assumption-type change carries an “Assumption” tag and tooltip: “A prediction, not a decision. Not carried into future forecasts.”

## 9. Interaction details

| Interaction | Behaviour |
|---|---|
| View switch | Keeps the selected day, the scenario and the scroll position. Updates the URL `?view=`. |
| Refresh | Optimistic spinner. On `changed=false`: toast “No changes since {time}”. On a new revision while a scenario is open: rebase banner “Scenario checked against revision 2: all changes still valid” (or *needs review*). |
| Move from day drawer | Opens a date picker anchored to the row. Allowed dates are enabled and others are disabled with a tooltip giving the reason. Confirming adds a change to the scenario panel (it creates an unsaved scenario if none exists) and runs the preview. |
| Preview | Debounced 250 ms. Shows a skeleton delta card. A refused change keeps the previous valid preview and marks the row red. |
| Unsaved scenario | A “Unsaved changes” chip appears. Navigating away prompts with `ConfirmDialog`. |
| Export | CSV of the current view and scenario. Filename `cash-forecast_{tenant-short}_{start}_{view}[_{scenario}].csv`. |
| Loading | Skeletons for the KPI cards (6), chart (block) and table (8 rows). The freshness strip loads first. |

## 10. Accessibility checklist

- [ ] All controls reachable by Tab in visual order. The view switch uses arrow keys inside the radiogroup.
- [ ] Drawers and modals trap focus (`useFocusTrap`). Esc closes them and focus returns to the opener.
- [ ] Chart `aria-label` summarises the result. The ledger table is the data equivalent.
- [ ] Colour contrast ≥ 4.5:1 for text (tokens are pre-checked). Below-reserve state carries an icon and text.
- [ ] Amounts are read correctly by screen readers. Use `aria-label` with the full rupee value on compact numbers (“48 lakh 70 thousand 432 rupees”).
- [ ] Live region (`aria-live="polite"`) announces the preview outcome: “Lowest balance now ₹19,13,700; breach cleared.”
- [ ] Hit targets ≥ 40 px on touch.

## 11. Analytics events (front end)

`cf_viewed{view}`, `cf_kpi_clicked{kpi}`, `cf_day_opened{source: chart|table|kpi|alert}`, `cf_exclusions_opened`, `cf_input_saved{tab}`, `cf_scenario_change_added{op, kind}`, `cf_scenario_refused{code}`, `cf_scenario_saved`, `cf_plan_submitted`, `cf_plan_decided{decision}`, `cf_export{view}`. No amounts, names or IDs other than opaque snapshot and plan IDs.

## 12. Build checklist (frontend)

1. Add `PATHS.cashForecast`, the route in `App.tsx` with `RequireService service="cash_forecast"` and `RequireRole roles={['admin','finance_controller','accountant','auditor']}`, the sidebar item under **Insights** (icon `LineChart`), and the mobile overflow item.
2. Add `api.ts` and `types.ts` mirroring [LLD §7.2](04_LLD.md#72-models-pydantic-abridged).
3. Build the page with the fixture first. A dev-only `?fixture=1` loads `expected_forecast.json` through a mock adapter, so the UI can be built before the API.
4. Write component tests against the fixture numbers in this document (T-32 to T-34 in [LLD §13](04_LLD.md#13-test-case-catalogue)).
