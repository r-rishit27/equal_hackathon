# Finance Desk research and evidence

## Product references

| Reference | Design use |
|---|---|
| [Odoo Accounting](https://www.odoo.com/app/accounting) | Primary SaaS reference for a unified accounting workspace. |
| [RazorpayX](https://razorpay.com/x/) | Payout preparation, authorization and status are distinct actions. |
| [Zoho Books](https://www.zoho.com/in/books/) and [QuickBooks](https://quickbooks.intuit.com/) | Accessible accounting, bank reconciliation and invoice workflows. |
| [Mysa](https://www.mysa.io/) | India-focused finance operations positioning. |
| [Paytm inventory agent, pinned revision](https://github.com/r-rishit27/paytm/blob/cc1a4133022dfdde9cd1e5928623b8eab0aec5a1/backend/agents/inventory.py) and [QUBO example](https://github.com/r-rishit27/paytm/blob/cc1a4133022dfdde9cd1e5928623b8eab0aec5a1/backend/agents/qubo_solver.py) | **Inventory optimization only.** Illustrates EOQ, safety stock, reorder point and a budget/capacity objective. The Onsumm proposal evaluates supplier-specific terms and enforces dated cash constraints directly. |

Product references inform workflow choices. This is not a market-wide feature comparison or an assessment of equivalent product coverage.

## Technical sources

| Source | How the design uses it |
|---|---|
| [Onsumm README](../../README.md) and [backend structure](../BACKEND_STRUCTURE.md) | Current app boundaries, integrations, and deployment setup. |
| [Receivables implementation and rollout](../receivables/README.md) | Statement intake, matching, review and apply/unapply behavior. |
| [Payment guardrails](../PAYMENT_GUARDRAILS.md) | Approval and release remain in the existing payment workflow. |
| [Fact Graph implementation](../../backend_ocr/app/domain/fact_graph.py) and [Agent Hub routes](../../backend_ocr/app/routers/agent_hub.py) | Existing graph entities, search and neighbor traversal. |
| [PostgreSQL transaction isolation](https://www.postgresql.org/docs/current/transaction-iso.html) | Snapshot consistency and concurrent decisions. |
| [PostgreSQL constraints](https://www.postgresql.org/docs/current/ddl-constraints.html) | Unique occurrence keys, idempotency and relationship invariants. |
| [Forecasting: Principles and Practice](https://otexts.com/fpp3/tscv.html) | Time-ordered backtesting for pilot forecast evaluation. |
| [OWASP guidance on prompt injection](https://genai.owasp.org/llmrisk/llm01-prompt-injection/) | Treat retrieved text as data and keep tool execution under application control. |

## Assumptions to validate

- The seeded demo uses an owner-provided reserve, explicit supplier terms and timestamped opening cash. Pilot teams must agree on source quality and ownership.
- A credible cash forecast needs cleared bank actuals and dated obligations. Product and order data need a reviewed stock source. Voucher counts alone do not establish physical stock.
- The working thesis is that linking cash, inventory and evidence reduces preparation time and avoidable exceptions. Savings and forecast quality require pilot measurement.
- The existing environment previously returned a refused PostgreSQL connection. Use the isolated fixture for the hackathon path until a development database is reachable.

## Expanded source analysis

- [Paytm inventory code and method review](INVENTORY_REFERENCE.md) pins the inspected architecture and explains the limits of its soft constraints.
- [Assistant architecture](ASSISTANT_ARCHITECTURE.md) links the current Onsumm LLM wrapper, graph and RBAC implementation, plus OpenAI API and data controls.
- [AWS deployment](AWS_DEPLOYMENT.md) links the current UAT2 deployment notes and the AWS references for the proposed target.
