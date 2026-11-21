# Finance Desk API and data models

**Status:** Proposed. Use FastAPI/Pydantic with generated OpenAPI when implemented. Keep this contract and the [LLD](LLD.md) aligned. All paths below are under `/api/finance-desk`. Use the current Reckon.ai authentication and permission middleware.

## API surface

| Method and path | Request | Response and effects |
|---|---|---|
| `GET /snapshot` | `account_id`, business date | `SnapshotRef`, opening balance, reserve, coverage and freshness. Read only. |
| `POST /forecast/preview` | `ScenarioInput` | `ForecastResult` with dates, scheduled flows, risks and references. Read-only computation. |
| `POST /inventory/compare` | `ScenarioInput`, SKU/location, quote selection if narrowed | Stock outlook and `OfferEvaluation[]`. Read-only computation. |
| `POST /assistant/query` | Question, `SnapshotRef`, active scenario, bounded conversation reference | `AssistantResult` with cited, typed data and scope. Read-only tools. |
| `POST /plans` | Same snapshot and scenario, explicit draft or submit action, note | Versioned plan. Server recomputes canonical metrics on submission. |
| `GET /plans/{plan_id}` | Authorized plan ID | State, snapshot and sanitized audit history. |
| `POST /plans/{plan_id}/decision` | Expected version, approve/return, note, `Idempotency-Key` | One authorized persisted decision. No transfer, order or ledger posting. |

Verify tenant using the authenticated context. IDs never override authorization. Bound the demo horizon to seven days, chat question to 2,000 characters and quote comparisons to an explicit small maximum. Define pilot bounds from load tests. Return validation failures as 422, conflicting or stale revisions as 409, and rate limits as 429 with retry information. Use current access conventions for protected resources. Expose a safe error code, message and request ID. No database or upstream provider errors are returned verbatim.

## Data model

Names below are proposed logical mappings. Tenant-scoped composite foreign keys prevent a plan or graph projection from pointing across tenants. Store immutable snapshot versions and mutable pointers separately. Use integer paise for INR money. Dates for business events are local dates; timestamps are UTC.

| Entity | Core typed fields and integrity |
|---|---|
| `fd_snapshot` | Tenant, UUID, account ID, monotonic revision, as-of and balance timestamps, currency, available paise, reserve paise, source watermarks, coverage. Unique tenant/account/revision. |
| `fd_cash_event` | Tenant, snapshot ID, occurrence key, source type/ID/revision, effective date, direction, positive paise, eligibility status, settlement link, category. Unique occurrence per snapshot; index by snapshot and effective date. |
| `fd_stock_position` | Tenant, import revision, SKU, location, date, normalized unit, physical and reserved quantity, observed demand window, provenance. Unique per SKU/location/revision. Inbound lines carry quantity, arrival and PO identity. |
| `fd_supplier_offer` | Tenant, quote ID/revision, supplier, SKU/location, valid window, unit/fixed cost, MOQ, pack multiple, lead time, milestone schedule. Positive pack and nonnegative costs. Milestones reconcile to landed spend without rounding drift. |
| `fd_plan` | Tenant, plan ID, version, actor, state, base snapshot/revision, policy version, normalized scenario, canonical hash, projected metrics, timestamps. Frozen submitted versions. |
| `fd_decision` | Tenant, plan ID/version, approver, decision, reason, idempotency key, input hash, timestamp and result. Unique decision per submitted version and tenant-scoped replay key. |
| Graph evidence projection | Tenant, node type, canonical source identity/revision, label and approved edge types. Store document/classification lineage as references. Reauthorize at hydration and on link open. |

**Shared response models**

- `SnapshotRef`: UUID, positive revision, as-of timestamp and coverage state. Echoed by every result to explain consistency.
- `ScenarioInput`: snapshot identity, expected/committed/downside view, allowed date overrides and selected offer quantities. Tenant, computed money and access rules come from the server.
- `ForecastResult`: currency, daily day buckets and signed net changes, minimum balance and its earliest date, first reserve breach, assumptions, exclusions and citations.
- `OfferEvaluation`: quote revision, units, scheduled arrival and payment milestones, landed paise, shortage impact, post-order minimum, eligibility and typed rejection reasons.
- `AssistantResult`: intent, short narrative, discriminated typed result, citations, coverage and fallback indicator. Numeric fields originate from deterministic tools.
- `Citation`: unique response-local ID, authorized source type and ID, source revision/date, safe title, field or derived calculation identity and approved UI path.

### Example · forecast preview

```json
{
  "snapshot_id": "0d2e07d4-cf69-47a1-9972-b6eeb56e4dea",
  "revision": 7,
  "view": "expected",
  "overrides": [{"source_type": "bill", "source_id": "demo-bill-90k", "effective_date": "2026-11-25"}],
  "orders": [{"offer_id": "demo-offer-a", "quote_revision": 2, "quantity": 20}]
}
```

Example response excerpt using the Day 3 close from the [demo fixture](DELIVERY_AND_VERIFICATION.md), with Day 1 set to November 21, 2026:

```json
{
  "revision": 7,
  "currency": "INR",
  "reserve_paise": 5000000,
  "minimum_closing_paise": 5200000,
  "first_reserve_breach_date": null,
  "days": [
    {"date": "2026-11-23", "opening_paise": 6000000, "inflow_paise": 0, "outflow_paise": 800000, "closing_paise": 5200000, "citation_ids": ["offer-a"]}
  ]
}
```

## Persistence and audit

Use one transaction for approve/return and the matching audit event. Lock or compare-and-swap the submitted row, recheck scope and source applicability, then persist the sole decision. Same key and equivalent canonical input return the stored response. Conflicting reuse of a key returns 409. If async refresh is introduced, write an outbox event in the same transaction and deduplicate consumer activity by tenant, job type and source revision. Data retention follows approved finance and audit policy. Keep model context and operational log retention shorter than retained decision records.
