# Finance Desk delivery and verification

## Integrated fixture and reproduction

Start with ₹2,40,000 opening cash, ₹50,000 reserve, ₹1,80,000 out on Day 2, ₹90,000 due Day 3 with an approved window through Day 5, and ₹1,50,000 expected on Day 4. Hold the suspected ₹40,000 duplicate. PKG-01 starts at 10 units with four units of daily demand. Both offers arrive before Day 3 demand and require full payment that day. Offer A is 20 units at ₹400; Offer B is 30 units at ₹400.

| Scenario | Day 2 close | Day 3 close | Day 4 close | Day 5 close | Seven-day minimum |
|---|---:|---:|---:|---:|---:|
| Original schedule | ₹60,000 | −₹30,000 | ₹1,20,000 | ₹1,20,000 | −₹30,000 |
| Reschedule, no reorder | ₹60,000 | ₹60,000 | ₹2,10,000 | ₹1,20,000 | ₹60,000 |
| Reschedule plus Offer A | ₹60,000 | ₹52,000 | ₹2,02,000 | ₹1,12,000 | ₹52,000 |
| Reschedule plus Offer B | ₹60,000 | ₹48,000 | ₹1,98,000 | ₹1,08,000 | ₹48,000 |
| Offer A and receipt slips to Day 6 | ₹60,000 | ₹52,000 | ₹52,000 | −₹38,000 | −₹38,000 |

The no-order stock path starts Day 3 with two units and misses two units of Day 3 demand. Offer A ends Day 7 with two units. Offer B breaches reserve. These are seeded outcomes for the demo.

## Test matrix

| Test | Cases | Requirements |
|---|---|---|
| Forecast reducer | Partial payment, settlement deduplication, missing date, duplicate hold, baseline and downside exact values | CASH-01–04 |
| Stock and offer reducers | Arrival timing, pack and MOQ, expired term, insufficient reserve and no-feasible path | INV-01–02 |
| Import contract | Same row and revision inserted once, invalid units and conflicting source versions surfaced | INV-03 |
| Assistant contract | Expected answers, exact cited IDs, ambiguous question, unavailable model and rejected citations | CHAT-01–03 |
| Authorization | Unauthorized actor, another tenant's record, and assistant with view-only scope | OPS-01, PLAN-02 |
| Plan persistence | Submit, approve, return, stale version, concurrent decisions, replay with same or conflicting intent | PLAN-01–02 |
| Browser walkthrough | Snapshot, comparison, cited answer, downside, approval and reload; record latency | OPS-02 |

## Eight-hour sequence

1. **0:00–1:00** Align on contracts, fixture, demo accounts, and exact expected outputs.
2. **1:00–2:45** Implement cash reducers and source rows, then scenario chart.
3. **2:45–4:15** Implement offer comparison and visible rejection reasons.
4. **4:15–6:00** Wire three assistant intents, source links and fallback.
5. **6:00–7:15** Persist owner decisions and verify tenant, role and revision checks.
6. **7:15–8:00** Reset and rehearse the three-minute demo. Cut CSV export, live connectors, long horizons and semantic search before cutting a P0 step.

## Pilot exit criteria

Agree on success thresholds with a design partner before measuring. Record preparation minutes per finance run, time on collection and purchase exceptions, end-of-day forecast absolute error, reserve-breach recall, stockout days and recommendation acceptance. Measure cash-timing shifts and actual avoided costs separately. Expand the horizon or automate data imports when source freshness and reconciliation quality support it.

## AWS and model release checks

Run a two-tenant test of cache isolation, graph authorization and citation reuse after permission changes. Test the inventory path with a candidate whose pack rounding exceeds reserve and a quote that becomes stale between preview and approval. Simulate an unavailable OpenAI project and verify typed results and fallback. Rehearse an AWS synthetic deployment, queue deduplication, feature flag rollback and database restore. Refer to [guardrails](FINANCIAL_GUARDRAILS.md) and [deployment](AWS_DEPLOYMENT.md).
