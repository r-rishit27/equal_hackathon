# Finance Desk experience design

## Daily workflow

An accountant opens the desk and sees the dated balance, seven-day minimum and first reserve breach. Selecting a day reveals the bills, receipts and proposed orders contributing to that balance. The accountant compares supplier offers, checks assumptions, and submits a proposal. The owner reviews the cash effect and downside before approving or returning it.

## One-page layout

| Region | Content and interaction |
|---|---|
| Header | Account, date range, reserve, source freshness and stance selector for committed, expected or downside. |
| Cash chart | Daily baseline and scenario lines, reserve guide, selected day and accessible data table. Display minimum and first breach as text alongside the chart. |
| Supplier table | SKU, demand basis, arrival, units, landed spend, payment day, minimum cash and feasibility reason. Allow a comparison from the same active scenario. |
| Evidence drawer | Source type, date, open amount or stock units, data freshness and exact source link. Explain deferred, disputed or assumed values near the calculation. |
| Assistant | Example questions, answer and source chips. Keep the active account and scenario visible in the answer. Drafts require review before anyone copies them out. |
| Decision panel | Baseline versus proposal, remaining downside, warnings, accountant note, submit/return/approve, and persisted history. |

## States and wording

- **Available:** “Projected cash reaches ₹52,000 on Day 3, ₹2,000 above reserve.” Show the scenario and the source date.
- **Downside:** “If the Day 4 receipt moves to Day 6, cash falls to −₹38,000 on Day 5.” Link the invoice and purchase obligation.
- **Missing balance:** “Add a dated opening balance to calculate cash.” Preserve access to independently available AP and AR records.
- **Stale evidence:** Show the source timestamp, retain the saved comparison, and require fresh inputs before approval.
- **No feasible offer:** Explain the binding cash day or lead-time limit and give the accountant a path to review alternatives.
- **Unknown assistant answer:** State which source is missing or ask which account, date or SKU the user means. Use the same record-permission checks for source chips as direct record access.
- **Saved decision:** “Plan approved.” Keep payment execution distinct in the existing payment workflow.

Use text labels as well as color for warnings and feasibility. Keep chart, table, assistant, and approval controls keyboard accessible. Put focus on the evidence drawer when opened and return it to the originating control when dismissed.

## Approval and citation details

Display the approver's role and the submitted snapshot revision. A stale plan shows which input changed and returns the user to preview. Use source chips with an authorized title and as-of date. Distinguish restricted, missing and stale evidence without revealing inaccessible source details. [Assistant architecture](ASSISTANT_ARCHITECTURE.md) · [Financial guardrails](FINANCIAL_GUARDRAILS.md)
