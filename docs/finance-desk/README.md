# Reckon.ai Finance Desk

Design package for extending Reckon.ai's `uat2` payables and receivables baseline with cash-flow forecasting, vendor and inventory optimization, and a finance assistant. The broader Finance Desk is proposed. The inventory planner is available at `/finance-desk/inventory` under Insights for users with payables viewing access and the Reports entitlement. The baseline product and its deployment constraints are documented in the [repository README](../../README.md).

## Reckon Copilot on dev

Open **Insights / Reckon Copilot** at `/finance-desk/copilot`. Workspace chat is available from the floating Reckon.ai logo throughout the signed-in application. It uses `gpt-6-luna` for tool selection and replies in the user's language. Tenant roles and live module entitlements determine the available context, including payables, receivables, cash application, inventory, purchasing, reconciliation, payments, review, tax, FX, vendor records and administrative configuration. Source relationships are projected from PostgreSQL at query time. Existing Fact Graph supplier-to-bill edges are verified against invoice ownership. Open a source to continue in its owning workflow.

Attach a UTF-8 CSV, text file or text PDF up to 2 MB (PDF limit 12 pages). CSV columns `quantity,unit_price,line_total` trigger decimal pre-tax line checks. Supply `invoice_number,invoice_total,currency` to compare up to eight distinct references with visible bills. Files are processed in memory and bounded excerpts are sent to the configured model. Each turn rereads source authorization before releasing an answer. Four previous questions supply conversational context within the open chat.

The **Approval evidence** tab covers current approval queues, overdue pending bills and supplier relationships. Each answer shows up to 12 bills with dated evidence and links to the source records. Select **Focus on bill** to narrow a follow-up to one invoice.

The approval evidence API verifies the signed-in user and the Bills, Approvals and Fact Graph entitlements on each retrieval. It uses the current department chain, falling back to the tenant chain and then the application's default chain. The personal queue follows the current step and its named assignees, with an admin override. **Show bills and decision history I can access** also covers bills outside pending stages. Admins can page through all bill records in their tenant, including held and deleted records. Accountants and finance controllers can read all active bill records in their tenant. Approvers and auditors can read active bills at their assigned steps and, in the records view, bills with a prior submit, approval or send-back under their unique recorded name. Focusing a records result displays its approval decision history. All Copilot roles have read-only access. Members and impersonated sessions cannot use this workflow. Ambiguous display names cannot satisfy named assignments.

PostgreSQL supplies the knowledge graph through `fact_graph_nodes` and `fact_graph_edges`. A supplier link must match both endpoints, the authorized invoice, its source supplier and the tenant. Approval-stage and latest-action evidence comes from the operational tables. Free-text questions use the existing budgeted model wrapper for intent and citation selection over minimized graph context. Preset questions and final source-grounded wording run locally. The in-process answer cache holds up to 128 derived results for 90 seconds. Fresh authorized evidence, actor identity, role, query scope and source values determine cache reuse.

## Inventory planner on dev

The planner reads the signed-in tenant's INR supplier bill lines from `onsumm_db`. Each price is tied to its bill date, quantity, unit and supplier. A planner selects a bill line and enters current stock, reserved units, daily demand, any confirmed inbound, lead time, MOQ, pack size and cash available after commitments and reserve. A confirmed landed price can replace the historical unit price for the calculation.

The seven-day preview shows the pack-rounded order, projected spend, closing stock with and without the order, and unmet demand. It flags arrival delays, expired confirmed quotes and quantities constrained by the entered cash budget. The planner maximizes seven-day demand covered within available purchasing cash and chooses the least spend for that coverage. A classical single-item QUBO solver selects pack counts on the API worker thread. Its binary encoding enforces the cash cap and minimum order. Changing the vendor or bill line clears the projection. The preview is read-only. Automated demand feeds, dated cash forecasting and persisted purchase decisions remain planned.

## Read in this order

| Document | Use it for |
|---|---|
| [PRD](PRD.md) | Target users, product thesis, scope, outcomes, and the one-day investor demo |
| [Requirements](REQUIREMENTS.md) | Prioritized functional and operational requirements, with acceptance evidence |
| [High-level design](HLD.md) | System boundaries, flow of data, integration with Reckon.ai, and design decisions |
| [Technical design](TECHNICAL_DESIGN.md) | Earlier integrated proposal, forecasting and inventory rules, assistant tools, and fixture |
| [Low-level design](LLD.md) | Typed contracts, finance calculations, storage, API behavior, and concurrency |
| [Experience design](UX_DESIGN.md) | Page structure, task flow, wording, and evidence states |
| [Delivery and verification](DELIVERY_AND_VERIFICATION.md) | Build order, reproducible demo results, tests, and pilot gates |
| [Research and evidence](REFERENCES.md) | Source index, what each reference supports, and assumptions to validate |

The requirements document defines release scope. The LLD owns API and state-transition details. Use the integrated fixture in [Delivery and verification](DELIVERY_AND_VERIFICATION.md) when earlier documents show a simpler cash-only example.

**Demo outcome:** Compare two vendor offers against a ₹50,000 reserve, ask the assistant to explain the recommendation with source records, stress-test a late receipt, and save the owner's decision. Use an isolated synthetic tenant for the demo.

## Detailed engineering references

| Document | Use it for |
|---|---|
| [Inventory reference and adaptation](INVENTORY_REFERENCE.md) | Paytm code architecture, QUBO/EOQ limitations, and Reckon.ai's dated feasibility checks |
| [Assistant architecture](ASSISTANT_ARCHITECTURE.md) | Fact Graph integration, RBAC, citations, OpenAI and scale |
| [Financial guardrails](FINANCIAL_GUARDRAILS.md) | Cross-service controls and release evidence |
| [API and data models](API_AND_DATA_MODELS.md) | Proposed endpoints, typed payloads, storage and versioning |
| [AWS deployment](AWS_DEPLOYMENT.md) | Current-to-target rollout, infrastructure, security, observability and rollback |
