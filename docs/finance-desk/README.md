# Onsumm Finance Desk

Design package for extending Onsumm's `uat2` payables and receivables baseline with cash-flow forecasting, vendor and inventory optimization, and a finance assistant. The Finance Desk is proposed. The baseline product and its deployment constraints are documented in the [repository README](../../README.md).

## Read in this order

| Document | Use it for |
|---|---|
| [PRD](PRD.md) | Target users, product thesis, scope, outcomes, and the one-day investor demo |
| [Requirements](REQUIREMENTS.md) | Prioritized functional and operational requirements, with acceptance evidence |
| [High-level design](HLD.md) | System boundaries, flow of data, integration with Onsumm, and design decisions |
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
| [Inventory reference and adaptation](INVENTORY_REFERENCE.md) | Paytm code architecture, QUBO/EOQ limitations, and Onsumm's dated feasibility checks |
| [Assistant architecture](ASSISTANT_ARCHITECTURE.md) | Fact Graph integration, RBAC, citations, OpenAI and scale |
| [Financial guardrails](FINANCIAL_GUARDRAILS.md) | Cross-service controls and release evidence |
| [API and data models](API_AND_DATA_MODELS.md) | Proposed endpoints, typed payloads, storage and versioning |
| [AWS deployment](AWS_DEPLOYMENT.md) | Current-to-target rollout, infrastructure, security, observability and rollback |
