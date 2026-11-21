# 08 · Build Plan

Build in this order. Each step is independently testable, and nothing later changes an earlier
step's contract. **Branch:** feature branch `feat/bata-recon` off `uat2`, merged back into `uat2`.

## Step 0: Scaffolding (½ day)

- [ ] Create `backend_ocr/app/recon/` with empty modules per [03 §1](03_LLD_BACKEND.md#1-module-layout).
- [ ] `recon/types.py`: every enum and dataclass from [02](02_CLASS_DIAGRAMS.md), with `to_json`
      / `from_json` (Decimal kept as str in JSON).
- [ ] `recon/config.py` with the defaults from [03 §3](03_LLD_BACKEND.md#3-configuration-reconconfigpy).
- [ ] Licence key `recon` in the licensing catalogue (see `docs/LICENSING_AND_ADMIN.md`).
- **Done when:** `python -c "import app.recon.types"` passes, and the types round-trip through JSON
  in a test.

## Step 1: Pure core (2 days). The heart of the system; no I/O

- [ ] `num.py`, `normalize.py` (+ `UnitCanon`), `rules.py`, `engine.py` (HeaderChecks,
      LineChecks, summary).
- [ ] `match.py`: scoring, `Hungarian`, accept/adjudicate split, with the LLM behind an injected
      callable.
- [ ] Golden JSON for the 4 sets (hand-written from the analysis doc).
- [ ] `tests/recon/test_engine.py` reproduces **every** assertion in [07 §3](07_TEST_PLAN.md#3-golden-expectations-engine-from-golden-json).
- **Done when:** all golden engine tests are green, with no network and no DB.

## Step 2: Database and repository (1 day)

- [ ] `migrations.py::_ensure_recon_tables()` with the DDL in [03 §2](03_LLD_BACKEND.md#2-database).
      Register it in the migration runner. Add `'recon'` to `DOC_TYPES`.
- [ ] `recon/repo.py`, with asyncpg in the style of the review package.
- [ ] Add the recon tables to the vendor-merge routine (E-CS-07).
- **Done when:** `scripts/run_api_migrations.py` is idempotent on the dev DB (run it twice), and
  the repo tests pass.

## Step 3: Reading (2 days)

- [ ] `pages.py` PageReader: text probe, page-by-page render, vision OCR through `ocr_engine`, the
      `recon_doc_pages` cache, the page cap, rotation, the garbage-text detector (E-IN-10).
- [ ] `llm.py` ReconLLM: OpenAI JSON-schema calls, retry/backoff, cost accounting, recording and
      replay for tests.
- [ ] `classify.py`: rules tier, Jev tier, LLM tier, and the hint regexes.
- [ ] `segment.py` per [03 §9](03_LLD_BACKEND.md#9-segmenter).
- **Done when:**
  - every sample file is classified and segmented as in [07 §4](07_TEST_PLAN.md#4-unit-test-checklist);
  - the 36-page JPC report runs with peak RSS < 400 MB.

## Step 4: Extractors (4 days)

- [ ] `extract/po.py`, tested against the 4 PO PDFs (text layer): line counts 1 / 39 / 36 / 25,
      totals match.
- [ ] `extract/invoice.py`: header, annexure, charges, corrections.
- [ ] `extract/pv_jpc.py`: the AHU annexure, 44 rows, vs golden.
- [ ] `extract/pv_sheet.py`: printed pass, PO alignment, double handwriting read, agreement,
      verdicts.
- [ ] `extract/pv_field.py`, `pod.py`, `memo.py`, `generic.py`, `spreadsheet.py`.
- [ ] `extract/prompts.py`: every prompt and JSON schema in one place, versioned (`PROMPT_VERSION`).
- **Done when:** text-layer extraction tests are green; `@llm` vision tests meet [07 §5](07_TEST_PLAN.md#5-extraction-accuracy-targets-vision-llm).

## Step 5: Linking, pipeline, worker (2 days)

- [ ] `link.py` DocumentLinker, plus `aliases.py` AliasStore.
- [ ] `case.py` CaseBuilder (DB → ReconInput, overrides and corrections applied).
- [ ] `pipeline.py` ingest + recompute + `relink_supplier`.
- [ ] `worker.py` ReconWorker. Register it in `review/scheduler.py`. Add the stale-lock recovery
      and the `RECON_WORKER_ENABLED` flag.
- [ ] Bill-ingest hook: `pg_notify('recon_docs', {kind:'bill'…})` after `stg_bills` insert/update
      (F8, E-CS-05).
- **Done when:** the integration test (recorded LLM) takes the 4 folders, uploaded in random
  order, to 4 correct cases.

## Step 6: API (1½ days)

- [ ] `routers/recon.py`: every route in [03 §4](03_LLD_BACKEND.md#4-api). Mount it with
      `require_service("recon")`.
- [ ] Crop endpoint with S3 caching and a 5-minute signed URL.
- [ ] `export.py`: xlsx.
- [ ] `GET /api/bills/{id}/recon`.
- **Done when:** the router tests pass, including cross-tenant 404s and a missing licence giving
  403.

## Step 7: Review Hub adapter (½ day)

- [ ] `review/adapters/recon_variance.py`, registered in `adapters/__init__.py`.
- [ ] `links.vendor_recon_case()` deep link.
- **Done when:** a finding appears for the Anjile case (under-billed) and resolves on acknowledge.

## Step 8: Frontend (4 days)

- [ ] `api/recon.ts`.
- [ ] Add `'recon'` to `DocFolder` and the nav entry (licence-gated).
- [ ] ReconFolder, UploadZone, DocQueue, DocRow, LinkPicker, KindPicker.
- [ ] ReconCaseList, ReconCaseView with all sections, LineReconTable, LineDetail, EvidenceCrop.
- [ ] MatchOverrideDialog, CellCorrectDialog, Acknowledge flow.
- [ ] ReconBadge on bill detail and the approval screen.
- [ ] Tests from [04 §8](04_LLD_FRONTEND.md#8-tests-vitest--testing-library).
- **Done when:** the manual acceptance in [07 §6](07_TEST_PLAN.md#6-end-to-end-acceptance-manual-on-dev)
  passes on dev, and `npm run build` and `npm test` are green.

## Step 9: Hardening and demo (1 day)

- [ ] Backfill script `scripts/recompute_recon_cases.py`.
- [ ] Demo tenant seed script `scripts/seed_bata_recon_demo.py`, loading from the dev S3 bucket.
- [ ] Update `docs/agents/RECON_AGENT.md`: PO recon mode ✅, with a link here.
- [ ] Changelog entry.

**Estimate:** about 18–19 working days for one developer. Steps 1–2 and 8 can run in parallel
once the types are frozen (Step 0).

## Deployment notes

- After pulling `uat2` on the box, run `scripts/run_api_migrations.py`; it is idempotent.
- Env:
  - `RECON_VISION_MODEL`, `RECON_FAST_MODEL`, `RECON_MAX_PAGES`;
  - `RECON_WORKER_ENABLED=true` on dev/prod only;
  - **false locally**, because local and dev share the dev DB (review-workers-lock incident).
- The backend box is a t2.micro with no swap. Keep worker concurrency at 1 doc at a time with
  `claim_pending(limit=2)` processed sequentially, and render pages one by one. Consider a 1 GB
  swapfile before the Bata pilot.
- The frontend is on Amplify with separate dev and prod apps. No routing change is needed; the
  feature uses the existing vendor route and query params.

## Open questions that change code (answer before Step 1 is finalised)

| # | Question | Config switch if undecided |
|---|---|---|
| 1 | Packing: fixed vs % of goods | `charge_rules.packing = PERCENT_OF_GOODS \| FIXED` (default `min(pct, fixed)`) |
| 2 | Blank audit cell = not installed? (Civil MCCB) | `blank_audit_means = UNKNOWN \| NOT_DONE` (default UNKNOWN → review) |
| 3 | Over-execution always capped? | `cap_at_po = true` |
| 4 | "Not allowed separately" = not billable? | `verdict_overrides` |
| 5 | Rate tolerance | `rate_abs_tol`, `rate_rel_tol` |
| 6 | Running bills per PO? | Cumulative check is always on; no switch needed |
| 7 | Can Bata give ERP/Excel exports? | SpreadsheetMapper already supports them |
