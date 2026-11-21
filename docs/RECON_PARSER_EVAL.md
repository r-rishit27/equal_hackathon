# Recon document parser evaluation: development reference

**Run:** 2026-11-16 · **Harness:** `eval/parsers/` · **Published report:** https://claude.ai/artifact/1ta8u4a7F3gBJmwiAZeqiX

Use this document when changing how Recon reads documents: OCR routing, the sheet extractor, GSTIN handling, or a new parser. Every number here comes from `eval/parsers/results/*.json`. Re-run the harness (section 9) before you quote a number after any change.

---

## 1. Decisions for the codebase

| # | Decision | Evidence | Where it lands |
|---|---|---|---|
| D1 | Digital pages are read from the PDF text layer, never from a vision parser. | Text layer scores 98.5 quality at $0, with 65/65 GSTINs exact. Every parser adds misreads on the same pages. | `OCR_TO_USE=auto` (text layer first). Keep it. |
| D2 | Scanned and handwritten pages: **gpt-5.4 vision** is the primary reader. | Best quality (93.0), handwriting (84.0) and safety (99.2), most GSTINs exact (93/96), 0 invented money rows. | `RECON_SHEET_MODEL=gpt-5.4` in `backend_ocr/app/recon/config.py` |
| D3 | Handwritten cells are read **twice, by independent readers**. A value is accepted only when both agree; otherwise it goes to review. | When two readers agreed on a handwritten cell, the value was correct 100% of the time, for every pair tested. | `extract/pv_sheet.py` (`sheet_rows` + `sheet_rows_check`, `_align`, `_row`) |
| D4 | Keep the review flag for `+`, `=`, `~` and strike-through in audit cells. | No parser resolves "348+102 = 450": all of them returned 348 or 345. Two parsers took a struck-through 18 instead of the 15 written beside it. | `pv_sheet.py::_row` (`odd`) |
| D5 | **Never trust a GSTIN read from a scan.** Validate the checksum character and match it against the vendor master. | No parser passes the GSTIN gate. Errors seen include `29AABCB1043Q1Z1` for `…1ZI`, `244ABCA2392K1ZR`, and 14-character strings. | **To build:** GSTIN checksum validator in `recon/clean.py`, used by `link.is_foreign` and `repo.save_extraction` |
| D6 | Don't adopt LlamaParse or gpt-4o as a reader. | LlamaParse left about half the handwritten boxes empty (D 49.7) and missed 26 rows. gpt-4o invented 23 rows carrying money and got 356 values wrong (F 85.7), failing the G2 gate. | — |
| D7 | Sarvam is the measured candidate for the **second** reader (instead of gpt-5.4-mini). | When gpt-5.4 and Sarvam agree, 100% correct, covering 61% of handwritten cells. Cheapest (₹0.50/page) and processed in India. Slow: p95 456 s per page. | Optional. Measure gpt-5.4 + gpt-5.4-mini the same way before switching. |

---

## 2. Results

Quality = 0.30·A + 0.15·B + 0.15·C + 0.25·D + 0.05·E + 0.10·F (0–100). Gates are pass/fail.

| Parser | Quality | A Money | B Rows | C Printed | D Handwriting | E Text | F Safety | G1 GSTIN | G2 Invented ₹ rows | G3 Failed pages |
|---|---|---|---|---|---|---|---|---|---|---|
| **gpt-5.4 vision** | **93.0** | **92.0** | **99.2** | **98.4** | **84.0** | 95.8 | **99.2** | 93/96 ✗ | 0 ✓ | 0 ✓ |
| Sarvam Document AI | 90.3 | 88.8 | 99.1 | 98.1 | 77.4 | 95.9 | 99.0 | 91/96 ✗ | 1 ✗ | 0 ✓ |
| LlamaParse (agentic) | 82.8 | 89.6 | 98.0 | 94.2 | 49.7 | **96.4** | 98.7 | 74/96 ✗ | 0 ✓ | 0 ✓ |
| gpt-4o vision | 82.1 | 73.0 | 94.7 | 79.8 | 83.6 | 90.9 | 85.7 | 77/96 ✗ | 23 ✗ | 0 ✓ |
| *Text layer (56 digital pages)* | *98.5* | *97.1* | *100* | *99.9* | — | *96.3* | *99.7* | *65/65 ✓* | *0* | *0* |

Sub-scores:

| Parser | A1 IDs | A2 Totals | A3 ₹-weighted lines | B1 Recall | B2 Precision | D strict¹ | Wrong / values output |
|---|---|---|---|---|---|---|---|
| gpt-5.4 | 95.0 | 85.7 | 95.3 | 99.4 | 99.0 | 73.6 | 21 / 2631 |
| Sarvam | 95.0 | 80.0 | 91.5 | 99.0 | 99.3 | 64.4 | 26 / 2628 |
| LlamaParse | 86.7 | 85.7 | 96.3 | 96.2 | 99.8 | 26.7 | 30 / 2388 |
| gpt-4o | 65.8 | 71.4 | 81.6 | 95.7 | 93.6 | 72.9 | 356 / 2482 |

¹ D strict also counts a handwritten "–" box that came back blank as a miss (see 6.3). The ranking is the same either way.

### 2.1 By document family (quality; handwriting D in brackets)

| Family | Pages | gpt-5.4 | Sarvam | LlamaParse | gpt-4o |
|---|---|---|---|---|---|
| Digital PO | Bata POs | **97.0** | 92.7 | 94.3 | 84.0 |
| Digital invoice | Bosch, Anjile | 96.0 | 90.8 | **97.5** | 86.0 |
| Scanned invoice | Inner Space main invoices | 95.1 | **97.4** | 95.0 | 95.5 |
| Memo | Approval memos | 100 | 100 | 100 | 100 |
| Typed audit annexure | AHU pp. 7–17 | 93.4 | **96.6** | 83.7 | 91.7 |
| Matolia audit sheet | Yelanka, Mangalore (mostly typed qty) | 97.4 | **97.7** | 92.2 | 66.5 |
| Rotated handwritten field sheet | AHU pp. 18–36 | **95.4 (83.7)** | 93.3 (77.0) | 86.6 (48.3) | 65.4 (84.0) |
| POD photo | Bosch waybill (1 page) | 19.4 | 19.4 | 19.4 | 19.4 |

### 2.2 Two-reader agreement on handwritten cells (332 cells)

| Pair | Both agree | Correct when agreeing | Disagree (→ review) | gpt-5.4 right when they disagree |
|---|---|---|---|---|
| gpt-5.4 + Sarvam | 203 (61%) | 100% | 50 | 40 |
| gpt-5.4 + gpt-4o | 217 (65%) | 100% | 50 | 26 |
| gpt-5.4 + LlamaParse | 85 (26%) | 100% | 166 | 158 |

### 2.3 Operations

| Parser | Cost / page | Latency p50 | p95 | API | Limits | Data processed in |
|---|---|---|---|---|---|---|
| gpt-5.4 vision | $0.019 (measured tokens) | 23 s | 172 s | sync | image per call | US |
| Sarvam | ₹0.50 (~$0.006) | 56 s | 456 s | async job + poll + ZIP | 30 pages, 200 MB per job | India |
| LlamaParse agentic | $0.015 (10 credits) | 33 s | 65 s | async job + poll | — | US / EU |
| gpt-4o vision | $0.012 | 17 s | 159 s | sync | image per call | US |

All four read rotated pages upright. None failed a page in the final run; LlamaParse needed one retry for 2 pages.

---

## 3. The cells that decide money (regression cases)

These are the cases to keep in mind, or turn into tests, when touching the sheet extractor. Every one was verified on a zoomed crop (`eval/parsers/crops/adj_*.png`).

| Case | On the page | Correct | gpt-5.4 | Sarvam | LlamaParse | gpt-4o |
|---|---|---|---|---|---|---|
| AHU p26 r35, Show-window plug, Mounted | "18" struck through, "15" written beside it | 15 | ✓ 15 | ✗ 18 | ✗ 18 | blank |
| Yelanka p4, Ceiling emulsion, Vendor Qty | Faded print renders 8 as "S" ("1S3S") | 1838 | ✓ | ✗ 1535 | ✗ 1535 | row missing |
| Yelanka p6, Seat wooden, Vendor/Audit Qty | Faint 6; asset codes …44093–44098 = 6 | 6 | ✓ | ✗ 5 | ✗ 5 | blank |
| Mangalore p7, Aluminium fins, Qty | Sheet printed skewed: numbers sit half a row above their item | 1,100 | ✓ | ✗ 110 | ✓ | ✗ 110 |
| Yelanka p6, Blisters rods, Audit Qty | "348+102 = 450" | 450 | ✗ 348 | ✗ 348 | ✗ 348 | ✗ 345 |
| Civil / Red main invoice, PO ref | `PPO000…` | PPO… | ✗ `PP0000…` | ✓ | ✗ `PP0000…` | — |

Implications:
- **Skewed rows:** pair qty and rate with the item by checking against the PO (qty × rate = amount, PO line match), not by visual row position.
- **O vs 0 in PO numbers:** normalise `PP0` to `PPO` before linking. `po_base()` should tolerate it.

---

## 4. Scoring matrix (as implemented in `eval/parsers/score.py`)

| # | Dimension | Measure | Weight |
|---|---|---|---|
| A1 | Identifiers | GSTIN, PO no., invoice no., store no., waybill: exact, ignoring case, spaces, `.` and `/`. PO no. and PO ref allow a `-N` revision suffix; PO ref is a prefix match | part of A |
| A2 | Totals | taxable, CGST, SGST, IGST, subtotal, grand total: to ₹1 | part of A |
| A3 | ₹-weighted lines | Σ amount of rows whose qty, rate and amount are all correct ÷ Σ gold amount | part of A |
| A | Money-critical | mean(A1, A2, A3) | 30% |
| B | Table completeness | mean(row recall, row precision) | 15% |
| C | Printed cells | qty, unit, rate, rate after discount, amount; exact (amounts ±0.01) | 15% |
| D | Handwriting | cells listed in the gold row's `handwritten`; exact | 25% |
| E | Text fidelity | token similarity of item and name text in matched rows | 5% |
| F | Safety | 1 − wrong non-null ÷ all non-null output | 10% |
| G1 | Gate | every gold GSTIN present exactly in the parser's own text | pass/fail |
| G2 | Gate | no unmatched output row that carries an amount | pass/fail |
| G3 | Gate | under 2% of pages fail | pass/fail |

Rows are matched with the Hungarian algorithm: `token_set_ratio` on item text plus 8 points when qty or amount agree, accepted at 70 or more. Dimensions with no data on a page are left out and the weights re-normalised.

---

## 5. Pipeline (identical for every parser)

1. **Split:** `split_pages.py` writes one-page inputs to `pages/<doc>/p<N>.pdf|png`, plus a 150-dpi JPEG for the vision models.
2. **Parse:** `run_parsers.py <parser>` writes `out/<parser>/<doc>/p<N>.md` and `.meta.json` (seconds, cost_usd, error). The vision models all get the same `TRANSCRIBE` prompt, at `detail: high` and `reasoning_effort: none`.
3. **Structure:** `structure.py <parser>`. One fixed text-only model (gpt-5.4-mini, `EVAL_STRUCT_MODEL`) maps the markdown to the gold schema. It never sees the image.
   - **Calibration:** it scores 98.5 on the text layer (gpt-5.4 scored 99.8).
   - **Fixed post-rule `post()`:** fills GSTIN roles from the parser's own text. A GSTIN containing Bata's PAN `AABCB1043Q` is the buyer; a single other GSTIN is the vendor.
4. **Score:** `score.py <parsers…>` writes `results/<parser>.json` (overall, families, docs, ops, errors).
5. **Adjudicate:** `score.py --disagreements p1 p2 …` lists gold values that two or more parsers dispute. Re-check each on a crop and log it in `gold/ADJUDICATION.md`. This run had 11 disputes and 0 corrections.

---

## 6. Scoring rules (applied to every parser alike)

1. **PO store number** is not scored on `*_po` pages: it is inferred from "PO SN", not printed as a field.
2. **Zero totals** (a printed 0 tax) are not scored.
3. **"–" boxes:** a gold 0 that comes back blank is neutral, because the structurer drops dashes inside combined cells like `Mounted [5] Unmounted [-]`. A wrong number there still counts. The strict figure is reported as `D_strict` and `C_strict`.
4. **Not-covered rows:** `audit_qty` on rows with unit `NA` or a "not covered" remark is unreadable (`?`), because "–" there means "not verified".
5. **Summary lines:** Total, Sub Total, G.Total, CGST/SGST/IGST and Round Off emitted as rows are ignored (`score.SUMMARY`).
6. **Audit sheet totals:** an audit sheet's own TOTAL and G Total lines are not scored.
7. **Unreadable gold:** a gold value of `?` is excluded.

---

## 7. Answer key (`eval/parsers/gold/`)

- 107 pages, 682 rows, 332 handwritten cells. Digital pages come from the text layer, checked against the image and the arithmetic. Scanned pages come from 200–300 dpi crops.
- The handwriting score D rests mainly on the AHU J P Chawla field sheets (pp. 18–36, PDF `/Rotate=90`). The Matolia Yelanka and Mangalore sheets are **typed**, with only a few handwritten cells.
- The Red main invoice number is struck through, with "109" written by hand.
- Files: one JSON per document. `ahu_report` and `civil_yelanka_report` are split into parts (see `common.GOLD_FILES`).

---

## 8. Known gaps

- POD: only 1 photo, and every parser scored 19.4, so PODs are not judged.
- Not tested: Mistral OCR, Gemini 2.5 Pro and Azure Document Intelligence. They are implemented in `run_parsers.py` and need `MISTRAL_API_KEY`, `GEMINI_API_KEY`, `AZURE_DI_ENDPOINT` and `AZURE_DI_KEY` in the repo-root `.env`.
- The production gpt-5.4 + gpt-5.4-mini two-model read (whole-row prompt `SHEET_ROWS`) was **not** measured. This run used one plain transcribe prompt for every model.
- Page-type accuracy (around 55–60%) reflects the structurer, not the parsers, and is not scored.

---

## 9. Re-running

```bash
cd eval/parsers
# keys in repo-root .env: OPENAI_API_KEY, SARVAM_API_KEY, LLAMA_CLOUD_API_KEY (+ optional MISTRAL/GEMINI/AZURE)
export EVAL_BUDGET_USD=4          # hard cap on OpenAI spend; ledger in spend.jsonl
python3.12 split_pages.py                       # once
python3.12 run_parsers.py openai --jobs 4       # cached: re-runs only missing/failed pages
python3.12 structure.py openai --jobs 6         # cached; --repost re-applies post() for free
python3.12 score.py textlayer sarvam llamaparse openai openai_4o
python3.12 score.py --disagreements sarvam llamaparse openai openai_4o
```

Cost of a full run: about $0.019/page for gpt-5.4 vision, about $0.003/page for structuring, ₹0.50/page for Sarvam, and $0.015/page for LlamaParse. This run cost $2.77 in OpenAI usage.

---

## 10. Implementation: shared reader (branch `feat/shared-doc-reader`)

**Bill OCR is untouched.** `utils/ocr_engine.py` and the `OCR_TO_USE` path are unchanged, and nothing in bills imports the new package.

| Piece | File | What it does |
|---|---|---|
| Shared reader | `backend_ocr/app/docread/reader.py` | Reads **per page**: the text layer when a page has ≥20 words or no picture at all; otherwise gpt-5.4 vision transcription; Sarvam Document AI if OpenAI fails; `failed` if both fail. Renders one page at a time (150 dpi JPEG, long side ≤1800), 2 pages in parallel. |
| Sarvam client | `docread/sarvam.py` | Document AI job (submit → poll → ZIP markdown, embedded images stripped), plus `sarvam-105b` chat → JSON. `sarvam-m` is deprecated. |
| Checks | `docread/checks.py` | `gstin_valid` (mod-36 check character), `find_gstins`. |
| Settings | `docread/config.py` | `DOCREAD_VISION_MODEL` gpt-5.4, `DOCREAD_CHECK_MODEL` gpt-5.4-mini, `DOCREAD_SARVAM_FALLBACK` true, DPI and size, concurrency. |
| Recon | `recon/config.py`, `recon/llm.py`, `recon/extract/misc.py` | `RECON_VISION_MODEL` gpt-4o → **gpt-5.4**. `ReconLLM` falls back to Sarvam (read + sarvam-105b JSON) when OpenAI fails; a spent quota is no longer retried for 35 s. A `…_check` read never falls back, so two reads can't "agree" by both being Sarvam. Field sheets are read **twice** (gpt-5.4 + `RECON_FIELD_CHECK_MODEL`); a row whose boxes differ goes to review with both readings. |
| Contracts / IO / PO | `review/comm_extract.py`, `review/comm_extraction_worker.py` | **One prompt per kind:** `CONTRACT_SYSTEM` (unchanged), `IO_SYSTEM` (campaign, model, payout per event, billable event, budget, flight dates, billing basis), `PO_SYSTEM` (every line's rate and quantity, PO number, date, total, advance, retention, penalty, price basis). The two-party rules and the RULES/output block are shared word for word. `detect_document_kind()` picks the prompt. Documents are read through docread, so a mixed PDF pays for vision only on its scanned pages. A `vendor_gstin` claim that fails its check character is dropped. `COMM_CONTRACT_MODEL` gpt-4o → **gpt-5.4-mini**. |
| Shared LLM call | `ai/llm.py` | `complete_json` sends gpt-5 parameters (no temperature, `max_completion_tokens`, `LLM_REASONING_EFFORT` none); prices added for gpt-5.4 and gpt-5.4-mini. |

**Live checks (2026-11-16):**
- **Digital PO:** text layer, $0, 0.1 s.
- **Scanned Yelanka sheet page:** gpt-5.4, $0.031, 15 s. "6" and "348+102 = 450" transcribed exactly.
- **Same page with OpenAI forced to fail:** Sarvam, 11.5 s.
- **AHU field sheet p26:** both readers read the struck-through value as 15 and agree; $0.021.
- **Aforv agreement:** a 14-page scan, $0.22 to transcribe. gpt-5.4-mini returned 7 terms for $0.011; gpt-4o returned 5 for $0.033. The 2 extra terms are real: clause 4.3, the 15-day minimum gap before invoicing, and a 7-day breach cure period.
- **Bosch PO with `PO_SYSTEM`:** line rate and quantity exact, plus PO number, date, total, payment schedule, delivery date and penalty, for $0.006.

**Cost per page:**

| Page type | Cost | Path |
|---|---|---|
| Digital | $0 | text layer |
| Scan | ~$0.02–0.03 | gpt-5.4 |
| Handwritten sheet or field sheet | ~$0.03–0.04 | two readers |
| Fallback | ₹0.50 (~$0.006) | Sarvam |

Structuring a contract with gpt-5.4-mini costs about $0.01 per document.

**Not covered yet:**
- Vendor-document classification, vendor logos and settings still make their own small vision calls; they classify documents and don't extract from them.
- IOs have no real sample; the IO prompt is untested on a live document.
