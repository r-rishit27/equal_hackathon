# 07 · Test Plan

## 1. Layers

| Layer | Location | Runs | Inputs |
|---|---|---|---|
| Unit: pure | `tests/recon/test_normalize.py`, `test_num.py`, `test_rules.py`, `test_match.py`, `test_engine.py`, `test_link_scoring.py`, `test_hungarian.py` | every commit, no DB, no network | in-code fixtures plus golden JSON |
| Extraction: text layer | `tests/recon/test_extract_textlayer.py` | every commit | the sample PDFs that have a text layer (Bosch PO/invoice, Anjile PO/invoice/JPC p1–17, Inner Space POs, Civil memo) |
| Extraction: vision | `tests/recon/test_extract_vision.py` | **marked `@pytest.mark.llm`**, run manually or nightly | scanned samples; asserts against golden values |
| Integration | `tests/recon/test_pipeline_db.py` | CI with Postgres | upload → worker → case, with the LLM stubbed from recorded responses |
| API | `tests/recon/test_router.py` | CI | tenant isolation, licence gate, every route |
| Frontend | vitest, see [04_LLD_FRONTEND.md §8](04_LLD_FRONTEND.md) | every commit | mocked API |

## 2. Fixtures

```
tests/recon/fixtures/
  samples/                 # copies of the 4 Bata folders (git-ignored if sensitive → load from S3 dev bucket in CI)
  golden/
    bosch.json             # ExtractedPO, ExtractedInvoice, ExtractedPOD, ExtractedMemo (hand-verified)
    anjile.json            # PO (39 lines), invoice annexure (36), JPC AHU section (44 rows)
    innerspace_civil.json  # PO (36), invoice detail (35), Matolia FAMILY-INTERIOR section
    innerspace_red.json    # PO (25), invoice detail (28), Matolia FURNITURE section
  llm_recordings/          # recorded LLM JSON responses keyed by prompt hash → deterministic integration tests
```

The golden JSON is written by hand from the documents. The values are in
[../BATA_RECON_ANALYSIS_AND_PLAN.md §4–5](../BATA_RECON_ANALYSIS_AND_PLAN.md).

**Sensitivity.** These are a prospect's real documents. Commit only the golden JSON (numbers and
descriptions). Keep the PDFs out of git and load them from the dev bucket for the `llm` tests.
Confirm with the user before committing anything derived from them.

## 3. Golden expectations (engine, from golden JSON)

### 3.1 Bosch: PPO00030541-1 ↔ 26GJ/KMW/SI15224

| Assertion | Expected |
|---|---|
| Lines | 1 matched, method SCORE or EXACT; conflicts `[]`; "W/O CONN. KIT" kept in invoice_text |
| expected_total / billed taxable | 5,72,400.00 / 5,72,400.00 |
| Header `tax_regime` | pass (24 → 29, IGST 18% = 1,03,032.00) |
| Header `pod_matches` | pass (total 6,75,432.00, invoice listed) |
| Header `delivery_timeliness` | pass (21-09-2026 ≤ 29-09-2026) |
| Header `payment_terms` | **fail, REVIEW** (60% Advance / 40% IMM vs 100% – 30 days) |
| Line status | `NO_EVIDENCE` must **not** be raised as REVIEW. The POD counts as evidence for goods, so the line is MATCHED |
| Summary | money_at_risk 0; counts REVIEW = 1 (payment terms) |

### 3.2 Anjile: PPO00024046-1 ↔ AMP/26-27/070 ↔ JPC Annexure-4

| Assertion | Expected |
|---|---|
| PO lines matched to invoice | 36 of 36 invoice lines matched; PO line 34 "Supply & Installation" ↔ invoice "15 MM Air Punch Valve" (by rate 1,500) |
| PO lines with no invoice line | Input Module (NOT_DONE, INFO), Fault Isolator (NOT_DONE, INFO), **MCP Hooter (UNDER_BILLED, REVIEW, delta −1,850.00)** |
| expected_total | **6,36,740.50** |
| billed taxable | 6,34,890.50 |
| under_billed | **1,850.00** |
| money_at_risk | 0.00 |
| OVER_EXECUTED_CAPPED | butterfly valve, acoustic insulation, acoustic lining, drain pipe (4 lines) |
| NOT_VERIFIABLE | scaffolding, panel programming, FAS integration (3 lines) |
| UNDER_USED | the 13 lines listed in analysis §5 |
| ADDITIONAL_ON_SITE | 5 rows (audit rows 40–44) |
| Header `header_vs_annexure` | pass (3,95,567.50 + 2,39,323.00 = 6,34,890.50) |
| Header `tax_regime` | pass (07 → 27, IGST) |
| Line HSN info | 2 lines with `993463` |

### 3.3 Inner Space Civil: PPO00024378-1 ↔ IS-HO-26-27-120 ↔ Matolia 1859

| Assertion | Expected |
|---|---|
| expected goods | **9,49,608.55**; plus Malba 7,125.00 = **9,56,733.55** = billed taxable |
| money_at_risk / under_billed | 0.00 / 0.00 |
| Capped lines | false ceiling 1665→1531, tiles 1683→1531, plastic emulsion 1705→1605, add point 146→142 |
| DESCRIPTION_CONFLICT | Integrated Main LT Panel Type D vs Type E |
| UOM_CONFLICT | Aluminium armoured cable SF vs m |
| NOT_IN_PO (INFO, qty 0) | "8 Way TPN Distribution Board" @ 6,270; "Floor Chipping" |
| NOT_DONE / expected 0 | dismantling ×3, PVC conduit ("Not allowed separately"), MCCB 100 A (blank → see below), 12-way SPN, Cu 2×4, 8 SWG, RJ45 |
| MCCB 100 A | audit blank, no remark → `UNKNOWN` → expected = PO qty 1, billed 0 → **UNDER_BILLED REVIEW**. This is *correct* behaviour: a human confirms the auditor's blank means "not installed". Golden: severity REVIEW, delta −13,680 counted in under_billed. **Open question for Bata.** |
| NOT_VERIFIABLE | Malba disposal (not in scope → PO qty 3) |
| Header `tax_regime` | pass (29 → 29, CGST 9 + SGST 9 = 1,72,212.04) |

> MCCB note. With the rule as written, Civil's under_billed would show 13,680.00 for MCCB. If Bata
> confirms "blank audit = not installed", set the tenant config `blank_audit_means: NOT_DONE`.
> The golden test covers both settings.

### 3.4 Inner Space Red Furniture: PPO00023557-1 ↔ IS-HO-26-27-109 ↔ Matolia 9621

| Assertion | Expected |
|---|---|
| expected goods | **5,45,985.90** (with PO rate 2,105.20) |
| Line "Metal Shelf CRC sheet with PC led" | billed_rate 2,105.00 (RATE_LOWER within tol → OK), DESCRIPTION_CONFLICT (600 vs 1200), AUDITOR_REMARK (LED strips removed) |
| Header `invoice_arithmetic` | **fail, REVIEW**: printed lines 5,45,973.90 vs subtotal 5,45,985.90 |
| Packing | billed 27,299.30 = 5% × 5,45,985.90; PO fixed 28,078.00 → `PCT_CHARGE_MISMATCH` REVIEW under default config; OK under `packing: PERCENT_OF_GOODS` |
| Header `handwritten_corrections` | **fail, REVIEW** (108 → 109) |
| NOT_IN_PO (INFO, qty 0) | Metal shelf 1200 @ 1,159; Metal shelf PC led 600 @ 1,121; See-through channel 10 ft @ 1,948 |
| UNDER_USED | hanging bar 1200 (60 → 54), impulse buy (2 → 1), metal shelf 600 (21 → 13), see-through 8 ft (2 → 0) |

## 4. Unit test checklist

| Module | Must cover |
|---|---|
| `num.parse_inr` | `1,26,312.00`, `₹ 11,28,945.59`, `6,75,432.00`, `####`, `-`, `(500)`, `1.4e+09`, `2,105.2` |
| `normalize` | every SPELLING entry; prefixes; `8 point 5 TR` → `8.5 tr`; variant extraction `600x450x100mm`, `Type E`, `3point5x35SqMM` |
| `UnitCanon` | all alias groups; `RMT == m`; `SF != m` |
| `VerdictClassifier` | every pattern in §11.1 of the LLD, case-insensitive, with and without audit qty |
| `BillingRule` | cap on/off; NOT_DONE; NOT_COUNTABLE; UNKNOWN with/without evidence; charges fixed vs % |
| `LineMatcher` | the 4 golden sets; duplicate-rate PO; alias hit; override precedence; LLM guardrail rejection (stub) |
| `Hungarian` | square, rectangular, all-equal costs, 1×1, 80×80 timing < 100 ms |
| `HeaderChecks` | each code pass and fail |
| `DocumentLinker` | exact ref; ambiguity margin; store-only; amount-only (POD) |
| `Segmenter` | label sequences: PO+T&C; invoice+annexure; JPC narrative+annexures+field sheets; Matolia 6-section |

## 5. Extraction accuracy targets (vision, `@llm`)

| Doc | Target |
|---|---|
| Inner Space invoice detail (scanned, printed) | 100% of qty/rate/amount cells |
| Matolia printed columns | 100% of item/unit/qty/rate |
| Matolia handwritten audit qty | ≥ 98% auto-accepted correct; 0 wrong values auto-accepted (every disagreement routed to review) |
| POD | invoice no., total value, receipt date |
| Memos | approver names, statuses, dates |

## 6. End-to-end acceptance (manual, on dev)

1. Create the demo tenant, licence `recon`, and vendors Bosch Home Comfort, Anjle MEP, Inner
   Space with the GSTINs from the documents.
2. Ingest the 4 invoices through the normal bill upload.
3. Upload each sample folder's other files into the vendor's Recon folder, **in random order**.
4. Expect:
   - 4 cases with the totals in §3;
   - FOREIGN sections listed for Voltas, Atspire, Blue Star, Universal Refrigeration, VDM,
     Manoviraj;
   - no manual linking needed, except the Matolia FAMILY-INTERIOR section in the Red report
     (no PO uploaded), which stays UNLINKED.
5. Correct one handwritten cell. The case recomputes, the event is logged, and the original is
   kept.
6. Override one match. The alias is saved. Re-upload the invoice under a new number: the alias
   hits.
7. Acknowledge. Review Hub finding resolves. The approval screen shows acknowledged.
8. Delete the PO. The case → AWAITING_PO.
