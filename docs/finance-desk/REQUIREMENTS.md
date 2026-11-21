# Finance Desk requirements

**Status:** Proposed · **Scope:** one-day demo and pilot follow-up

P0 is required for the integrated demo. P1 is an extension after the seeded path passes. Existing Reckon.ai permissions continue to apply to underlying source records.

| ID | Priority | Requirement | Acceptance evidence |
|---|---|---|---|
| CASH-01 | P0 | Display dated opening cash, currency, reserve, source coverage and scenario selection. | Missing opening balance yields an unavailable forecast. A dated fixture produces seven consecutive local-date buckets. |
| CASH-02 | P0 | Use approved remaining AP, eligible AR and dated purchase obligations, accounting for partial settlements, held items and confirmed transactions exactly once. | A receipt already reflected in opening cash adds no projected inflow. A held ₹40,000 duplicate appears in exceptions and has no outflow. |
| CASH-03 | P0 | Compare expected and downside forecasts on the same snapshot. Show first reserve breach, minimum closing cash, and source events. | Moving the approved vendor payment produces a ₹60,000 expected minimum. Delaying the receipt after selecting Offer A produces −₹38,000 on Day 5. |
| CASH-04 | P0 | Permit only scenario changes within an agreed or explicitly authorized date window. | An out-of-window move is refused. The original bill date is preserved after preview and approval. |
| INV-01 | P0 | Project stock through the horizon using on-hand, reserved units, demand and firm inbounds. | PKG-01 falls short during Day 3 without replenishment. Offer A leaves two units at the end of Day 7. |
| INV-02 | P0 | Compare supplier offers using MOQ, pack size, lead time, landed cost, quote validity and payment terms. | Offer A is feasible at ₹52,000 minimum cash. Offer B is rejected at ₹48,000. Every rejection gives its reason and date. |
| INV-03 | P1 | Import stock, offers and firm inbound through typed, idempotent adapter contracts. | Reimporting the same source revision creates no duplicate inputs. Conflicting or incomplete rows surface precise validation errors. |
| CHAT-01 | P0 | Answer common cash-risk, due-receivables and supplier-comparison questions through typed read tools. | The seeded questions return the same amounts and dates as the screen and cite authorized source records. |
| CHAT-02 | P0 | Distinguish data, assumptions, stale inputs, and missing evidence. Ask for clarification where scope is ambiguous. | The assistant names the selected scenario and snapshot, refuses invented citations, and returns a labeled template when the model is unavailable. |
| CHAT-03 | P1 | Draft an editable collection note from an authorized invoice record. | A user can review or copy the draft. The assistant has no email, order, or payout action. |
| PLAN-01 | P0 | Persist an accountant's proposed plan and an owner's approve/return decision. | Actor, note, snapshot revision and comparison remain visible after reload. Repeated identical approval requests yield one decision. |
| PLAN-02 | P0 | Refuse stale revisions or unauthorized decisions. | A changed snapshot returns a recompute requirement. A non-owner cannot approve. |
| OPS-01 | P0 | Isolate tenant data and run the demo without production connectivity. | A cross-tenant source request reveals no record. Seed, preview, chat and approval operate against the isolated fixture. |
| OPS-02 | P0 | Keep the decision loop responsive and auditable. | Seeded previews target under one second; a complete walkthrough targets under three minutes. Persist decision references, with no raw model prompts required in logs. |

## Supported roles

The accountant inspects data and submits a plan. The owner may approve or return it. Use the existing authorizer to resolve those capabilities in a deployment; map explicit test roles in the demo. Viewing forecast inputs and assistant citations requires access to the underlying module and tenant.

## Scope boundary

The forecast is decision support. Plan approval records a proposed schedule. Existing procurement and payment workflows continue to govern external actions. Live bank connectivity, account-to-account sweeps, supplier ordering, tax advice, automatic collection sends, unrestricted SQL, and production inventory migrations are outside the one-day slice.

See the [test matrix](DELIVERY_AND_VERIFICATION.md) and [low-level design](LLD.md).

## Pilot requirements

| ID | Priority | Requirement | Acceptance evidence |
|---|---|---|---|
| ACCESS-01 | Pilot gate | Reauthorize every tool, graph result and citation across scope changes. | Revoked permissions prevent cached result disclosure and document drill-down. |
| CONTROL-01 | Pilot gate | Prevent financial actions through planning and assistant interfaces. Enforce independent approver and current snapshot. | Side-effect and self-approval tests pass; payment controls remain in the existing flow. |
| MODEL-01 | Pilot gate | Enforce per-tenant model budgets, privacy boundaries, validated citations and fallback. | Quota, timeout, scope and invalid-citation fixtures return grounded output or a clear limitation. |
| DEPLOY-01 | Pilot gate | Validate the isolated AWS pilot environment and rollback without using live gateways or shared production data. | Synthetic end-to-end rehearsal, restore exercise, alarms and rollback recorded. |

[Financial guardrails](FINANCIAL_GUARDRAILS.md) · [Assistant architecture](ASSISTANT_ARCHITECTURE.md) · [AWS deployment](AWS_DEPLOYMENT.md)
