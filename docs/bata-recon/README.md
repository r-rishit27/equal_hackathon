# Bata Recon: Design Doc Set

| | |
|---|---|
| **Feature** | Recon: PO ↔ Invoice ↔ On-ground evidence reconciliation, inside Vendor card → Documents |
| **Branch** | `uat2` |
| **Status** | Design v1.0, ready to build |
| **Owner** | Subhash Bishnoi |
| **Last updated** | 2026-11-12 |
| **Source analysis** | [../BATA_RECON_ANALYSIS_AND_PLAN.md](../BATA_RECON_ANALYSIS_AND_PLAN.md): sample findings, the billing rule and its numeric proof |

## Documents

Read them in order. Each one assumes the ones before it.

| # | Doc | What it answers |
|---|---|---|
| 1 | [01_HLD.md](01_HLD.md) | What the system is, its components, data flow, where it plugs into the existing app |
| 2 | [02_CLASS_DIAGRAMS.md](02_CLASS_DIAGRAMS.md) | Every class, dataclass and enum, and how they relate |
| 3 | [03_LLD_BACKEND.md](03_LLD_BACKEND.md) | Modules, DDL, APIs, worker, algorithms, prompts and function signatures |
| 4 | [04_LLD_FRONTEND.md](04_LLD_FRONTEND.md) | Components, state, API client, screens |
| 5 | [05_USER_FLOWS.md](05_USER_FLOWS.md) | Every user journey as a flow diagram |
| 6 | [06_EDGE_CASES.md](06_EDGE_CASES.md) | Edge-case catalogue, the handling for each, and decision diagrams |
| 7 | [07_TEST_PLAN.md](07_TEST_PLAN.md) | Golden fixtures from the 4 sample sets, with expected outputs |
| 8 | [08_BUILD_PLAN.md](08_BUILD_PLAN.md) | Ordered task list, file by file, with done-criteria |

## Glossary

| Term | Meaning |
|---|---|
| **PO** | Bata purchase order (`PPO000xxxxx-N`). It is always **pre-tax**, and its quantities are estimates |
| **Invoice / bill** | The vendor's tax invoice. It already exists in the app as `stg_bills` + `stg_bill_line_items` |
| **Annexure** | The invoice's detail page(s) ("Details of invoice", "Performa Invoice"). The real line items live here |
| **PV report** | Physical-verification / site-visit report by Bata's auditor (JPC, Matolia Rai). It is store-level and covers several vendors |
| **Evidence** | Any document that states what was actually delivered: PV report rows, POD, GRN, measurement sheet |
| **Verified qty** | The quantity the auditor confirmed on site |
| **Countable / non-countable** | Whether the auditor *could* count the item. Non-countable items are "not covered / out of audit / not in scope" |
| **Expected qty** | What the vendor should bill, by Bata's rule: `min(PO, verified)`. Non-countable items take the PO qty; not-done items take 0 |
| **Recon case** | One invoice with its linked PO, evidence, memo and the line results |
| **Store SN** | Bata store number (1859, 9621, 8255, 9648). It is the cross-document join key |
| **Δ / money at risk** | Σ (billed − expected) over the lines where the invoice is above expected |

## Locked design decisions

1. **Reuse over rebuild.** Uploads use `vendor_documents` / `store_vendor_document`. Processing is
   a `BaseWorker` subclass. Flags reach Review Hub through a `FindingAdapter`. The OCR helpers
   (`ocr_engine`) and spreadsheet rows (`vendor_doc_rows`) are reused. No new service or process.
2. **The recon engine is pure.** It takes typed inputs and returns typed results, with no DB and no
   LLM. Everything non-deterministic happens before it: extraction, classification, LLM line
   adjudication.
3. **Advise only (L1).** Recon never edits a bill and never blocks approval. 🔴 lines show on the
   approval screen and need an explicit "Acknowledge".
4. **Text layer first. Vision only for pages without one.** Pages are rendered one at a time to
   avoid the out-of-memory crash from the 88-page OCR incident.
5. **Every extracted number carries a source:** page, bounding box and confidence. Low-confidence
   numbers are never used silently.
6. **Documents are never public.** Access is only through 5-minute signed links after the tenant
   check.
7. **The tenant comes from the JWT** (`require_tenant()`). The client's `company_id` is ignored.
