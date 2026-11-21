# Application stress and functional evaluation

**Reckon.ai | dev revision `a964c4a` | Local evaluation**

**Decision: hold release sign-off for Nova invoice reconciliation and concurrent authenticated workloads.** Nova undercounted an invoice with two lines for one service. At four concurrent clients, 11 of 24 authenticated reads missed the combined response-and-content check during an overlapping browser run. A quieter retry completed, but one request took 6.55 seconds. These results establish a correctness defect and a repeatable latency concern. They do not establish production capacity.

## Evaluation scorecard

| Evidence | Passed | Failed | Skipped | Interpretation |
|---|---:|---:|---:|---|
| Python, 1,667 distinct tests | 1,626 | 38 | 3 | Final result per test after rerunning the reconciliation and AR suites with PostgreSQL |
| Frontend, 720 tests in 66 files | 719 | 1 | 0 | Vitest components, routes, stores and policy checks |
| **Distinct existing tests** | **2,345** | **39** | **3** | **2,387 total** |
| Frontend production build | Pass | | | Build and static prerender completed |
| Supplemental browser, API and algorithm checks | See below | | | Kept outside the suite totals |

The first Windows backend run produced 41 failures. With Python UTF-8 mode, the full run took 65.19 s and returned 1,603 passes, 38 failures and 26 skips. Then 493 of 496 reconciliation and receivables tests passed against two disposable PostgreSQL databases in 39.07 s. This supplied results for 23 previously skipped database tests. The scorecard counts each Python test once by class and name. The three remaining skips require original document fixtures.

## Reckon Copilot and workspace chat

**The live evaluation measured language selection, SQL-grounded answers, citation validity and a first/repeat latency pair. The focused regression rerun passed 59 backend and 3 UI tests.** The historical live run used `gpt-6-luna` and role-scoped reporting data. The fresh regression run used test fixtures. These 62 regression cases overlap the application scorecard above. [Original Copilot evaluation](docs/finance-desk/COPILOT_EVALUATION.md) and [evaluation script](scripts/eval_copilot_chat.py).

| Question for the evaluator | Recorded result | What the result establishes |
|---|---|---|
| Did the assistant reply in the requested language? | 6/6 live prompts passed | English, Hindi in Devanagari, Tamil, a switch from English to Spanish, Romanized Hindi and an explicit Spanish request. One answer per prompt, scored by script or keyword with empty workspace evidence. Human-rated fluency and financial translation quality remain unmeasured. |
| Did retrieval return the right facts and cite them? | 4/4 questions passed all assertions | Vendor and inventory counts compared with independent SQL. Overdue bill references and supplier relationships checked against source records. The retrieval harness disabled model generation; this measures the evidence and fallback-answer path. |
| Did financial totals preserve currency and unit? | 2/2 payables currency groups and 7/7 inventory unit groups matched SQL | Aggregates checked within the same tenant and scope. These groups are checks within the evaluation, not nine additional conversations. |
| Did a live model give a correct financial answer? | 2/2 responses matched the SQL count | One question about vendors with payment terms of at least 30 days, asked twice. This is one distinct question. |
| How long did an answer take? | First call 14.62 s; identical repeat 4.28 s | End-to-end service calls including retrieval and access verification. Two observations cannot establish p50/p95, cache benefit or throughput. |
| Did follow-up context persist and expire correctly? | Focused backend and UI suites passed on rerun | Backend recovered the saved vendor-query context for the original identity, rejected a changed tenant or role, and rejected expired context. Browser-component tests retained context after a document question. Pagination also required a previous authorized bill plan. |
| What happened when access or model output changed? | Focused regression suites passed | Covered revoked access during a model call, unlicensed tools and citations, one citation-repair attempt, currency-checked comparisons and a model-unavailable fallback. These are deterministic regression cases. |
| What remains unscored? | No measured rate found | Long-conversation recall, unsupported-claim frequency across a representative question set, human-rated relevance and fluency, live fallback frequency, cost per conversation and concurrent chat p95. The authenticated-read timings below apply to other endpoints. |

**Reproduction.** From the repository root, run the following focused backend suite. From `frontend`, run the two UI suites. The fresh run completed in 4.14 s and 5.15 s respectively. For the historical SQL check, run `python scripts/eval_copilot_chat.py --display-name "<authorized workspace user>"`. Add `--language-only` for the six live model prompts. These two commands exercise different paths. [Context and citation assertions](tests/test_finance_desk_workspace_chat.py).

```powershell
python -X utf8 -m pytest -q tests/test_llm_client.py tests/test_finance_desk_workspace_chat.py tests/test_finance_desk_copilot.py tests/test_copilot_finance_sql.py
# From frontend
npx vitest run src/pages/WorkspaceChat.test.tsx src/pages/CopilotPage.test.tsx
```

## Earlier application evaluations

Historical outcomes below retain their original datasets and denominators. The application scorecard counts its own test cases once. Adding older runs, audit findings, parser scores or repeated prompts to that total would inflate coverage.

| Feature and evidence | Recorded outcomes | Interpretation |
|---|---|---|
| Pipeline integration and deduplication. [Pipeline report](docs/pipelines/PIPELINE_TEST_REPORT.md) | 76/76 passed: 21 pipeline integration, 38 mocked deduplication and 17 live PostgreSQL deduplication checks. Tally processed 103 items across two tenants. | Tested duplicate suppression, AP failures, AR reversals, balance corrections and replay. Several worker queues were empty; their successful cycles do not measure throughput. |
| TDS engine. [Case results](scripts/tds_test_report.html) | 27/34 passed. Seven failures across misconfiguration guards (1/4 passed), zero taxable base (0/1), aggregate arrears (1/3) and fiscal-year bounds (3/4). | Historical arithmetic and guard failures remain open for evaluation until the same cases pass on a named revision. |
| Vendor card UX. [Source audit](docs/vendors/VENDOR_CARD_UX_AUDIT.md) | 15 high, 39 medium and 22 low findings on the audited branch. | A code review, including explicitly marked inferences. These 76 findings are neither failed automated tests nor a current open-defect count. |
| Bata reconciliation design comparison. [Comparative evaluation](docs/reconciliation/RECON_APPROACH_BAKEOFF_SUMMARY.html) | Relational design 13/16 (weighted score 78.6/100), JSON plus graph 8/16 (48.4), hybrid with decision log and vocabulary 16/16 (89.2). | All three calculated the payable on the tested Bata documents. Replay and retention of reviewer decisions helped distinguish the designs. |
| Receivables cash application. [AR verification](docs/receivables/README.md) | 49 engine/parser cases passed. The source also documents two PostgreSQL end-to-end cases and a passing frontend suite of 617 existing plus four route tests. | Covers import, allocation, review, unapply, duplicate handling and revision conflicts. The pilot auto-match rate on actual statements remains unmeasured here. |
| AP reconciliation stress. [Stress evidence](docs/reconciliation/STRESS_TESTING.md) | Matched 50/50 lines in 0.11 s, 100/100 in 0.22 s, 250/250 in 1.70 s, 500/500 in 6.99 s and 1,000/1,000 in 28.16 s. Nine defects documented as fixed. One of four forced races initially failed on concurrent case recomputation. | Final snapshot: 416 passed/22 skipped without DB, 16 passed/2 skipped with scratch DB, and 700 frontend passes with four existing failures. Source reports two manual correction decisions left on dev; their current state was not checked. |
| Payment Hub. [QA checklist](docs/payments_docs/PAYMENT_HUB_QA_CHECKLIST.md) | 43/43 payment UI tests passed; typecheck and scoped lint clean. Unauthenticated queue and recent routes returned 401. | Wizard and receipt components exercised. The historical checklist left browser Table/Lanes switching, scroll and wizard handoff open. |
| Finance Desk forecast and inventory. [Verification fixture](docs/finance-desk/DELIVERY_AND_VERIFICATION.md) | Expected seven-day minimum cash: original schedule INR -30,000, rescheduled INR 60,000, offer A INR 52,000, offer B INR 48,000, delayed receipt with A INR -38,000. | Seeded reference values for regression. The document lists pilot outcomes to measure, including reserve-breach recall and forecast error; it does not report observed pilot values. |
| HSN item classification. [Evaluation harness](scripts/hsn_match_eval.py) | Five-fold evaluation specified. No measured score established from the inspected artifacts. | The expected labeled workbook is absent from this checkout and the script imports `sysxxx`. Reporting classification accuracy requires a runnable harness and its labeled corpus. |

### Document extraction benchmark

Quality is a weighted 0-100 score covering money-critical fields, rows, printed cells, handwriting, text and safety. GSTIN exact matches and invented monetary rows are separate release checks. The PDF text-layer result covers 56 digital pages; comparing its score directly with the mixed-page vision corpus would favor the easier inputs. [Parser benchmark, scoring method and corpus](docs/reconciliation/RECON_PARSER_EVAL.md).

| Reader | Quality / 100 | Handwriting / 100 | Exact GSTIN | Invented money rows | Per-page p50 / p95 |
|---|---:|---:|---:|---:|---|
| GPT-5.4 vision | 93.0 | 84.0 | 93/96 | 0 | 23 / 172 s |
| Sarvam Document AI | 90.3 | 77.4 | 91/96 | 1 | 56 / 456 s |
| LlamaParse | 82.8 | 49.7 | 74/96 | 0 | 33 / 65 s |
| GPT-4o vision | 82.1 | 83.6 | 77/96 | 23 | 17 / 159 s |
| Digital PDF text layer | 98.5 | N/A | 65/65 | 0 | Distribution unavailable |

All four parsers completed every page in the final run. On 332 handwritten cells, GPT-5.4 and Sarvam agreed on 203 (61% coverage), with every agreed value correct in that sample. No vision parser read every GSTIN exactly. In a separate 14-page scanned agreement check, GPT-5.4-mini extracted seven terms for USD 0.011 after transcription, compared with five terms for USD 0.033 from GPT-4o. Two additional terms were verified against the document. These are historical measurements on the named inputs. [Document-level checks and measured costs](docs/reconciliation/RECON_PARSER_EVAL.md).

## Workload and measured results

Windows desktop, Python 3.12.10, pytest 9.2, Vitest 2.1.9, PostgreSQL 15.20 and local Chromium/Edge. Frontend on 5174, application API on 8003, Nova on 8100. HTTP probes used closed-loop clients. Algorithm timings cover single-process execution without network or database latency. Times are elapsed milliseconds, percentiles use nearest rank. Some browser and server probes overlapped. Samples are short and lack controlled hardware and production baselines.

| Workload and success condition | Volume / concurrency | Result | p50 ms | p95 ms | Max ms |
|---|---|---|---:|---:|---:|
| Application health, HTTP success | 80 / 1 | 80 OK, 140 req/s | 4.3 | 19.7 | 29.2 |
| Application health, HTTP success | 80 / 8 | 80 OK, 251 req/s | 21.9 | 111.1 | 115.0 |
| Nova health, HTTP success | 40 / 4 | 40 OK, 411 req/s | 7.6 | 20.3 | 22.2 |
| Authenticated reads, status and content matched baseline | 24 / 1 | 24 matched, 1.15 req/s | 808 | 1,076 | 1,098 |
| Same reads during browser activity, 20 s timeout | 24 / 4 | 13 matched, 0.30 req/s overall | 9,977 | 20,014 | 20,022 |
| AP reconciliation, Anjile golden fixture, expected underbilling INR 1,850 | 30 / 1 | 30 correct | 103.692 | 133.150 | 134.943 |
| AR cash application, correct automatic allocation from 100 invoices | 20 / 1 | 20 correct | 3.769 | 4.639 | 5.766 |
| Same AR workload from 1,000 invoices | 20 / 1 | 20 correct | 37.802 | 43.691 | 43.926 |
| CFO workflow evaluator, stage order and approval/payment gates | 6,000 / 1 | All correct across approved, pending and rejected inputs | 0.013 | 0.024 | 0.403 |
| Nova monthly reconciliation, 1,000 distinct services per run | 50 / 1 | Every run had 500 quantity mismatches and 1,000 matching rates | 14.681 | 24.401 | 43.207 |

The authenticated mix rotated bills, vendors, Review counts and the invoice-processing list six times for one Bata login. The content check compared sorted record IDs or the Review total against sequential baselines. The failing run recorded timeouts but did not distinguish every timeout from a status or content mismatch. Its latency figures include unsuccessful attempts.

**Quiet retry:** Four clients made 16 requests. All returned HTTP 200 and parseable JSON. Bills took 2,177-3,968 ms, vendors 2,046-4,231 ms, Review counts 1,332-6,546 ms and invoice processing 765-4,230 ms. This retry used a weaker content check. DTL Fact Graph also timed out once at 18 s with a 25-record limit; the same route returned 200 for Bata. No bottleneck was isolated. Health endpoint throughput should not be used to size authenticated traffic.

## Feature-by-feature evaluation

Each row identifies what was exercised and where the evidence ends. A rendered heading is a navigation smoke check. A mocked integration tests application behavior at the provider boundary.

| Product area | Evidence from this evaluation | Result or remaining gap |
|---|---|---|
| Public entry, sign-in and workspace navigation | Frontend build and prerender, route and navigation tests, real password sign-in in Chromium for two user scopes, invalid password rejected | Password flow exercised. Federated sign-in and account recovery were not exercised end to end. |
| Brands, licensing, roles and administration | Entitlement, isolation and route-map suites; shared login read bills and pending notification counts for Acme (347/266), Bata (3/2), DTL (1/1). Approval Chain settings rendered. | Distinct brand results observed. Three policy assertions failed across frontend and backend. No role-by-role production audit. |
| Main dashboard, search and notifications | Workspace search component and notification suites; scoped API counts above | Signed-in dashboard heading was not confirmed within the browser observation window. Real notification delivery and badge refresh during rapid switching remain unverified. |
| Bill intake, OCR, data extraction and deduplication | Upload/OCR, document reading, duplicate and staging suites; Upload invoices and Data Extraction pages rendered. Synthetic 11-page PDF exercised JPEG conversion in batches of 4/4/3 with a fake model. | Parser and batching exercised. Actual provider OCR accuracy, mailbox intake throughput and sustained large-file ingestion remain unmeasured. |
| Bills, vouchers, approvals and GST breakdown | Bill, approval, GST breakdown, settlement and payment-flow suites; Bills page rendered. Brand-scoped reads and concurrent workload above. | Functional coverage with a concurrent-read concern. No simultaneous live approval/write load. |
| Vendor master, KYC, bank details and vendor card | Master records, GSTIN primary selection, compliance adapters, sandbox bank verification, document claims, activity, inbox and card suites; Vendors page rendered | Local flows exercised. External verification providers and simultaneous edits were outside the run. |
| Review Hub, findings, evidence and actions | Ranking, routing, agent, bulk status, audit, evidence drawer, proposals and store suites; page rendered and real counts fetched | 13 paging checks failed. Counts alone do not verify sorting or paginated findings. |
| AP four-way reconciliation, dashboard and supporting documents | Golden fixture, PostgreSQL persistence and frontend dashboard, graph, case, evidence and four-way tests; repeated calculation verified a known monetary variance | Strong local functional evidence. Two original Anjile document scenarios skipped. Live full-document ingestion and sustained concurrent reconciliation remain open. |
| DTL Playground | Formula and check suites exercised vendor calculation logic | No completed interactive DTL create/edit/save/reopen cycle in this run. |
| Nova billing and reconciliation | Panel-state tests, browser route, health checks and 50 x 1,000 distinct-service calculations; adversarial accounting input described below | **Failed repeated-service quantity handling.** No successful live upstream ledger fetch was established. |
| Agent Hub, independent workers and Fact Graph | Agent Hub page rendered. Callable operations for communication, compliance, verification, recon, payable, contract, TDS, GST and receivable; analytics callable separately. Nine worker advisory-lock IDs were unique. | Entrypoints checked. Continuous worker liveness, queue recovery and duplicate-event handling under load remain open. Graph timeout observed for DTL. |
| CFO orchestrator | 6,000 evaluator runs; authenticated workflow call for one invoice under each of three brands returned all five stages in order. Chromium selection on a populated brand returned 200 and displayed four review stages and blocked payment. | KYC, vendor setup, reconciliation, approval and payment gating exercised. Thousands of evaluator calls do not measure persisted orchestration throughput. |
| Communication/email agent and contract extraction | Communication extraction, stalled work, buyer contact, review-adapter wake-up, contract text and contract-to-bill variance suites | Boundary behavior exercised; no real mailbox burst, outbound mail or externally delivered attachment replay. |
| WhatsApp agent | Earlier product scope specifies a Twilio-based agent. No live sandbox message, callback or end-to-end result collected here. | Unverified; excluded from deployed-feature pass totals. |
| Payment Hub, disbursements, OTP and receipts | Browser route, bank status-code suites, sweeper, guard, OTP, receipt and payment-sidebar tests; targeted batch retest described below | Payment regressions remain open. Real banks, transfer execution and signed settlement callbacks were outside scope. |
| Tax and withholding | GST breakdown and verification checks, TDS preferences and sections returned 200. Supplementary cases exercised a 91-day backdated bill and missing vendor. | Partial. Historical TDS report recorded 27/34 passing; those historical results were not upgraded by the two new cases. |
| Currency conversion and fiscal logic | Fiscal and FX regression suites | 14 FX failures. Converted totals and missing-rate handling need a clean rerun. |
| Receivables, customers, sales invoices and cash application | Receivables suite against dedicated PostgreSQL; Customers and Cash Application screens rendered; reference-based allocation benchmark above | Matching and persistence exercised. Sales-invoice page heading was not confirmed within 5-8 s. No end-to-end collections or statement-import soak. |
| Inventory planning | Inventory domain, page and vendor picker tests; browser route rendered | Local logic and navigation exercised. No large catalogue or production demand-forecast benchmark. |
| Reckon Copilot, workspace chat and finance queries | Finance SQL, Copilot, chat and intent suites; browser route rendered | Local behavior exercised. Live model accuracy, cost, multi-turn load and Review-page overlay positioning were not verified in this run. |
| Reports, exports and audit | Report series and review audit suites. Activity report returned JSON, monthly CSV parsed as two rows including header, XLSX opened with two sheets; Reports screen rendered. | File readability verified. Large exports, source-to-report total reconciliation and concurrency remain open. |
| Integrations, Tally, API sync and webhooks | Integration screen rendered; API sync, Tally and webhook suites executed | Adapter evidence only. Live ERP, banking, email and cloud endpoints were not exercised. |
| Object storage, runtime and observability | Object-store, worker, logging/observability, imports and syntax suites; local service health probes | Windows mock tempfile and import/compatibility failures remain. No deployed S3/RDS/compute failover, restart, soak, resource profiling or recovery-time measurement. |

## Failure register and retests

| Suite or finding | Failures in scorecard | Observed behavior and disposition |
|---|---:|---|
| Nova repeated service | Supplemental | Invoice quantities 45 and 55 for the same canonical service, compared with 100 billed operations, produced one comparison using 55. The invoice index overwrites a previous line. Correct the aggregation or explicitly reject ambiguous lines; retest both orders and distinct rates/units. |
| Authenticated read load | Supplemental | 11 of 24 attempts missed the combined check. Repeat with per-request outcome codes, tenant, query/pool timings and CPU/memory before setting a capacity target. |
| FX | 14 | Missing rate IDs, missing-rate expectations, asynchronous fixture handling, staging expectations and a protected request returning 401. Separate fixture defects from conversion defects and rerun with deterministic rates. |
| Review paging | 13 | Direct handler calls leave a framework Query default where brand normalization expects a string. Exercise the HTTP route for filters, pagination and sorting and supply explicit defaults in direct-call tests. |
| Disbursement batch isolation / guards | 3 + 1 | Batch fixture patches a legacy force-success switch. With the effective demo gateway-skip flag disabled and bank mocked, all five batch tests passed. A separate source assertion for the demo badge failed. Original failures remain in the scorecard. |
| Import resolution | 2 | Relative-import and module-import checks failed; one example is the legacy disbursement API's relative auth import. Check which modules are mounted before evaluating runtime impact. |
| Object store / payment receipt / Python syntax | 1 + 1 + 1 | Windows tempfile reopen permission, unavailable Asia/Kolkata timezone data and byte-order marks encountered by the syntax checker. Rerun on Windows and the deployment OS. |
| Tenant route map | 2 | Bank catalogue exception and route snapshot expectations differ from current code. Review expected route access before updating the snapshot. |
| Frontend permissions | 1 | A policy test detects a hardcoded Acme workspace allowlist in AuthContext. This is a failed policy assertion; no unauthorized access was demonstrated. |
| **Suite failures** | **39** | Supplemental findings have no effect on this total. |

The remaining skipped tests are the original scanned-page JPEG batching case, the Anjile out-of-order end-to-end case and the waiting purchase-order case using existing vendor bills. The synthetic batching retry supplied different evidence and did not replace those original fixtures.

## Repeat the evaluation

1. Check out revision `a964c4a`. Install the repository's backend and frontend test dependencies. Start the local frontend, API and Nova using the [development environment guide](docs/aws-deploy/DEV_ENVIRONMENT.md). Use disposable database targets for test writes.
2. From the repository root, run `python -X utf8 -m pytest tests -q --disable-warnings --junitxml=backend.xml`. For the isolated suite run, set `RECON_TEST_DB_URL` and `AR_TEST_DB_URL` to separate, freshly created PostgreSQL databases and run `python -X utf8 -m pytest tests/recon tests/receivables -q --junitxml=persistence.xml`. Merge results by test class and name. The broad run here used an unavailable default database and an empty model API key to isolate external effects.
3. From `frontend`, run `npx vitest run --reporter=json --outputFile=frontend-results.json` and `npm run build`. The [backend tests](tests) and [frontend source and colocated tests](frontend/src) define the assertions.
4. For the read benchmark, sign in with a test tenant. Record baseline IDs or counts from GET `/api/bills`, `/api/vendors`, `/api/review/counts` and `/api/agents/invoice-processing`. Cycle through these six times, first sequentially, then with four clients and a 20 s deadline. Retain per-route HTTP status, content comparison, elapsed time and timeout separately. Repeat in isolation and with browser traffic.
5. For the Nova regression, use one mapped vendor/service, a rate of INR 2 per hit and 100 monthly operations. Supply two invoice lines mapped to that same service with quantities 45 and 55. Inspect the compared invoice quantity; the expected total is 100. Swap line order and repeat. See the [reconciliation algorithm](services/nova_reconciliation/app/algorithm.py).
6. For PostgreSQL and document tests, restore the missing original fixtures and repeat on a clean database. For release sign-off, run the authenticated workloads against a representative staging dataset with multiple tenants, sustained reads and writes, worker queues and provider sandboxes. Record hardware, duration, per-route percentiles, error rates and resource saturation. Agree service targets before assessing a pass.

Historical reconciliation stress results are in the [earlier reconciliation report](docs/reconciliation/STRESS_TESTING.md). They came from a different run. This report records observed application behavior on the stated local revision; deployed capacity, third-party availability and production financial accuracy require separate evidence.
