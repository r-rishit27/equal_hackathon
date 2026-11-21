# The reconciliation agent

How a document becomes a verdict: the stages it passes through, the scores that
decide what happens at each one, where the agent refuses to decide, and the
numbers we measure it by.

*Written for engineers and analysts operating or extending the recon agent. It
describes what the code does today, with thresholds quoted from
`backend_ocr/app/recon/config.py` and measurements from the dev database on
20 November 2026. Companion documents: `docs/reconciliation/RECON_IMPLEMENTATION_PLAN.md` (why it is
built this way), `docs/reconciliation/RECON_VOCABULARY.md` (every code it can emit), and
`docs/reconciliation/QUESTIONS_FOR_BATA.md` (what the business still has to tell us).*

---

## 1. What the agent is for

A capital-expenditure invoice from a Bata vendor cannot be paid on its own say-so.
Four other documents have an opinion about it:

| Leg | Document | The question it answers |
|---|---|---|
| **Commitment** | Purchase order | Was this ordered, at this rate? |
| **Receipt** | Site audit report, or delivery proof / GRN | Did the work happen, and did the goods arrive? |
| **Billing** | Tax invoice | What is being charged? |
| **Payment** | Remittance advice | What has been settled? |

The agent reads all of them, pairs them line by line, applies Bata's billing
rules, and produces a verdict per line and per case. **The invoice is the
spine**: every comparison is some other document against the invoice.

Two principles run through the whole design and explain most of the decisions
below:

1. **Arithmetic decides; judgement only proposes.** Rates, quantities and totals
   come off documents and are compared by subtraction. Nothing probabilistic is
   ever allowed to produce a number that money moves on.
2. **Not deciding is a valid outcome.** At every stage the agent can hand the
   question to a person. A wrong auto-decision costs more than an unanswered
   one, so every threshold below is set to abstain rather than guess.

---

## 2. The flow, end to end

```
upload ──> claim ──> read ──> classify ──> extract ──> link ──> match ──> engine ──> save
                       │          │           │          │        │         │         │
                    pages      per page    per doc     to a     line to   checks    status,
                    + text     kind +      typed       case     line      + rules   totals,
                               hints       fields                                   decisions
```

Every stage writes its name to `vendor_documents.recon_stage`, so a stuck
document can be located precisely (`reading`, `classifying`, `extracting`,
`linking`, `matching`, `done`).

### 2.1 Claim — `worker.ReconWorker.process_batch`

A background worker polls for documents in `PENDING`, claims one at a time with
`SELECT … FOR UPDATE SKIP LOCKED`, and sets it `RUNNING`. Before its first batch
it calls `reset_stale`, which returns documents stranded in `RUNNING` by a crash
back to `PENDING` — without it, one killed process silently parks a document
forever.

The worker is **off by default** (`RECON_WORKER_ENABLED=false`). Local and dev
share a database, and the first worker to start would claim the other
environment's uploads.

> **Operational note.** If uploads sit in "waiting to be read", check this flag
> before suspecting storage. On 19 November 2026 three documents were stuck for
> hours and the diagnosis was initially "S3 is full"; S3 has no capacity limit
> and the bucket held 151 MB. Nothing was claiming them.

### 2.2 Read — pages and text

PDFs are opened with PyMuPDF. A page with a text layer gives its text directly;
a scanned page is rendered to JPEG at **150 dpi**, longest side **1800 px**,
quality **78**, and sent to a vision model. Those numbers are a memory
constraint, not an aesthetic one: 200 dpi PNG froze the 1 GB backend box on
13 November 2026. At most **4 page images** go in one model request, and below
**250 MB** free memory the worker defers the document rather than reading it
(`MemoryPressure` → back to `PENDING`, not `FAILED`).

Limits: 60 pages, 25 MB, and the extensions in `config.ALLOWED_EXT`
(PDF, PNG, JPG, HEIC, WEBP, TIFF, XLSX, XLSM, CSV).

### 2.3 Classify — what each page is

`classify.PageClassifier` labels every page, cheapest signal first:

| Method | When | Confidence |
|---|---|---|
| `blank` | no text, or under 40 words with no rule hit | 1.00 |
| `rule` | a regex names it (a PPO number, an audit column header) | 0.95 |
| `rule` (continuation) | previous page was a continuing kind and this one has ≥ 4 numbers | 0.80 |
| `llm` | nothing above matched | model's own, default 0.5 |
| `default` | no model available | 0.00 |

Two corrections are applied to the model's answer because it gets them wrong in
a predictable way:

- An auditor's sheet names the PO it checks ("FURNITURE PO") and the model reads
  it as a purchase order. Without a PPO number *and* without audit columns, it
  is not one.
- A GSTIN is kept only if its check digit holds. Scans misread them
  (`29AABC81043121`), and a wrong GSTIN silently links a document to the wrong
  vendor.

### 2.4 Extract — typed fields per document kind

One extractor per kind, each returning a typed dataclass rather than free text:

| Extractor | Reads | Notes |
|---|---|---|
| `po.py` | purchase orders | lines, rates, penalties, delivery dates |
| `invoice.py` | tax invoices | header + annexure lines, tax block |
| `pv_jpc.py` | typed auditor annexures | real tables via PyMuPDF; confidence 1.0, never needs a human check. **Carries no rate column** — this report kind prices nothing |
| `pv_sheet.py` | scanned auditor sheets | dense tables, handwritten quantities, rate / after-discount / printed total |
| `spreadsheet.py` | XLSX / CSV | GRN extracts, declared column mapping wins over inference |
| `misc.py` | delivery proofs, memos, payment advices | |

**Scanned sheets and handwritten field sheets are read twice**, by two models
independently (`SHEET_MODEL` and `SHEET_CHECK_MODEL`, both `gpt-5.4` family).
Where the two agree, the value was right every time in the parser evaluation.
Where they disagree, the cell is flagged `needs_review` and both readings are
shown to the reviewer — the agent does not pick a winner.

Cells are accepted unreviewed only above `CELL_ACCEPT_CONF = 0.90`.

### 2.5 Link — which invoice does this document belong to?

`link.score` rates each candidate case on five signals:

| Signal | Weight | 1.0 means |
|---|---|---|
| `ref` | **0.45** | the document names this invoice number or this PO number |
| `overlap` | **0.20** | its line items match this PO's lines (share of candidates scoring ≥ `MATCH_ACCEPT`) |
| `store` | **0.15** | same store number |
| `amount` | **0.15** | the total matches within ₹1 |
| `date` | **0.05** | within the window: PO date − 365 days to invoice date + 120 days |

Two overrides reflect how these documents actually behave: a document that
*names* the invoice or PO scores at least **0.95**, and a report whose rows
mostly match one PO (`overlap ≥ 0.6` with a plausible store) scores at least
`0.6 + 0.4 × overlap` — matching contents is as good as a reference.

**It links automatically only when the best candidate scores ≥ 0.85 *and* beats
the second by ≥ 0.15** (`LINK_AUTO_SCORE`, `LINK_AUTO_MARGIN`). A high score
that something else nearly matches is not a decision; those go to "Needs you"
with the top three candidates and their signals shown.

### 2.6 Match — which line is which?

Two mechanisms, used for different purposes.

**Stable identity** (`keys.py`) is what survives re-extraction. A line is named
by the first rung that applies:

| Rung | Basis | Confidence |
|---|---|---|
| 1 | asset / FA code printed on the row | **0.99** |
| 2 | printed serial number + normalised description | **0.95** |
| 3 | normalised description + unit + rate fingerprint | **0.85** |
| 4 | position in the table | **0.40** |

`TRUST_FLOOR = 0.80`, so **rung 4 is deliberately below it**: position alone can
name a row for storage, but never carries a decision. A reviewer's correction
keyed to an untrusted identity is re-confirmed rather than silently replayed
onto a different line.

**Pair scoring** (`match.py`) is what pairs a PO line with an invoice or report
line:

| Component | Weight | Scored on |
|---|---|---|
| `rate` | **0.35** | exact 1.0, within 5% 0.6, else 0.0; no rate at all 0.5 |
| `name` | **0.30** | `token_set_ratio` of normalised text, capped at 0.3 for contentless PO lines like "Supply & Installation" |
| `variant` | **0.12** | 1.0 agreeing variant tokens, 0.2 if they conflict (a 25 mm line against a 32 mm line) |
| `qty` | **0.10** | 1.0 if the PO quantity on the row matches |
| `unit` | **0.08** | 1.0 same unit, 0.0 different, 0.5 unknown |
| `position` | **0.05** | within 10% of the same relative position |

An identical normalised description scores **0.99** unless variant tokens
conflict — the conflict wins, because "25 mm" and "32 mm" piping read almost
identically to a fuzzy matcher and are not the same item.

Assignment is **Hungarian**, not greedy: the matcher optimises the whole
assignment so one plausible line cannot steal a counterpart that another line
needs more. Then:

- **≥ `MATCH_ACCEPT` (0.72)** → matched.
- **0.35 – 0.72** → the mid-band. One rescue applies: if the rate matches
  exactly *and* this is the only open PO line at that rate, it is matched on
  that basis, with the reason recorded.
- Still unresolved → offered to the adjudicator (§4), and if that abstains, left
  for a person.

Every pairing's method and score reach the screen: a 62% match means the
difference beside it may be between two unrelated items.

### 2.7 The engine — rules and checks

`engine.LineChecks` produces a verdict per line; `engine.HeaderChecks` produces
checks about the case. Both are pure functions of a `ReconInput`, which is why a
verdict can be reproduced exactly.

**The billing rule** (`rules.BillingRule.expected_qty`):

```
billable qty = min(PO qty, verified qty)        -- capped at the PO
not done on site                      ->  0
could not be counted / not in scope   ->  PO qty
found on site but not in the PO       ->  0     (needs a credit note, R5)
```

at the **PO rate**, always. A rate on the site report that differs from the PO
rate is recorded as a conflict on the line, never as a new basis for payment.

**Header checks**, in the order the engine runs them: `po_reference`,
`within_po_value`, `payment_terms`, `single_po`, `receipt_variance`,
`grn_vs_audit`, the payment checks, `tax_regime`, `invoice_arithmetic`,
`header_vs_annexure`, `handwritten_corrections`, `duplicate_invoice`,
`vendor_identity`, `buyer_gstin`, `store_consistency`, `date_order`,
`pod_matches`, `pod_invoice_ref_match`, `delivery_timeliness`, `approvals`.

**The tax basis rule** decides which figure each leg compares:

- The **main reconciliation** runs on the **taxable** amount — what the PO
  agrees and the auditor certifies.
- The **receipt and payment legs** compare the **gross**, because carriers and
  banks state tax-inclusive figures. `ReconInput.receipt_basis` records which,
  and getting it wrong reports a difference of exactly the GST on every
  correctly delivered consignment.

### 2.8 Save — results, decisions, and the projection

The verdict is written to `recon_line_results` and `recon_header_checks`, the
case gets its status and totals, and three things are stamped for auditability:

- `input_fingerprint` — what this verdict was computed from.
- `rule_version` — which tenant profile was in force.
- `recon_edges` — the match surface, rebuilt as a projection. It can be wiped
  and rebuilt with nothing lost; Postgres owns the documents and the decisions.

**Decisions are append-only.** A reviewer's correction, a match override, a
confirmation — each is a row in `recon_decisions`, never an update. A changed
mind is a new row that supersedes the last, so `as_of` can replay the case
exactly as it stood at any past moment. This exists because decisions used to be
keyed to a row surrogate that DELETE + re-insert destroyed: re-reading a
document lost every correction made against it.

---

## 3. Case statuses

| Status | Meaning | Next action sits with |
|---|---|---|
| `AWAITING_PO` | no purchase order yet | whoever files POs |
| `AWAITING_INVOICE` | documents arrived before the bill | the vendor |
| `AWAITING_RECEIPT` | invoiced before the audit — **early, not wrong** (R10) | the auditor |
| `AWAITING_CREDIT_NOTE` | lines billed outside the PO (R5) | the vendor |
| `NEEDS_REVIEW` | something needs a person | a reviewer |
| `RECONCILED` | nothing outstanding | nobody |
| `ACKNOWLEDGED` | a reviewer signed it off | nobody |

The roll-up order is the order above: a case waiting on a document is not
"needs review", because nobody can do anything about it yet. `AWAITING_RECEIPT`
and `AWAITING_CREDIT_NOTE` exist precisely so that a reviewer's queue contains
only things a reviewer can act on.

---

## 4. Decisioning: where judgement is allowed

The agent is deterministic almost everywhere. Three places use a model, and each
is fenced.

### 4.1 Reading a document

A vision model turns pixels into typed fields. This is extraction, not
judgement, and it is checked by **reading twice with two models** on the formats
where it is weakest (scanned sheets, handwritten field sheets). Disagreement
produces a flagged cell, not a chosen value.

### 4.2 The Decisions API layer (`decisions.py`)

Typed questions to `gpt-6-luna` at `/v1/decisions`, confined to two questions:

- **Which kind of document is this page?** — only when the rule classifier has
  no answer and the page would otherwise be filed as `OTHER`.
- **Are these two lines the same item?** — only for pairs in the mid-band, where
  the alternative is position, which may not decide.

Three properties keep it advisory:

| Property | Mechanism |
|---|---|
| **Abstains by default** | every call returns `Abstain` unless the answer clears the caller's threshold (**0.85** default). An abstention means the caller does exactly what it did before this existed |
| **Never overrules evidence** | it chooses between readings the documents support; `LineMatcher._guardrail` still requires a rate or unit agreement and consistency with the conflicts already found |
| **Cannot break the pipeline** | no key, no network, a timeout, a malformed body, a refusal, an unknown answer type — all return abstentions with a reason. The reconciliation it is trying to improve already works without it |

Both ends of a predicate are informative: 0.97 is a confident *yes*, 0.02 a
confident *no*, and the middle is an abstention. A 0.6 shown to a reviewer is a
coin toss with a decimal point on it; they will either trust it or learn to
ignore the lot.

**The matcher stays pure and synchronous**, because its output is what a
reviewer has to reproduce. `ReconPipeline._adjudicator` runs the match once with
a `Collector` to find what is genuinely in doubt, asks about every doubtful pair
in **one** request (up to 400 questions, batched beyond), and hands the answers
back as a lookup for a second pass. Nothing in doubt, or nothing judged, means
the deterministic path runs untouched.

Configuration: `OPENAI_DECISIONS_URL`, `OPENAI_DECISION_MODEL`,
`OPENAI_DECISION_TIMEOUT_S`, `RECON_DECISIONS_ENABLED` — all defaulted, so the
layer can be switched off without touching a caller.

### 4.3 Human confirmation

Some questions are not the agent's to answer. A check can declare itself
*confirmable* by publishing the exact text the reviewer is being shown; the UI
offers a **Yes, confirm** button and the answer is stored as an append-only case
decision.

Two refusals keep this honest. A check that did not publish `confirmable` cannot
be answered at all — a screen that lets someone tick away an arithmetic failure
is not a review. And the answer is stored *with what was on screen*: if the
document is read again and the text comes out differently, the stored yes says
nothing about the new words, so the check asks again.

---

## 5. Edge cases the agent handles explicitly

Each of these was a real document that broke something.

### Documents and reading

| Case | Behaviour |
|---|---|
| **One PDF, many documents** | a Bata upload holds a PO, three audit sections and a delivery proof. Each becomes its own segment with its own kind, linked independently |
| **Another vendor's section** | marked `FOREIGN` and excluded from every comparison, rather than polluting this vendor's case |
| **A continuation page** | no header of its own; inherits the previous page's kind only if it carries ≥ 4 numbers |
| **An auditor's sheet titled "FURNITURE PO"** | not a purchase order: no PPO number, and it has audit columns |
| **A misread GSTIN** | dropped unless the check digit holds |
| **Unreadable stored bytes** | a machine-local path written into a shared database is not a parse failure. `object_store.unreadable_here` names the cause and the UI offers re-upload, not "Read again" — that button could never have succeeded |
| **The box is low on memory** | the document goes back to `PENDING` with "it will be read shortly", not `FAILED` |

### Quantities and rates

| Case | Behaviour |
|---|---|
| **Auditor certified more than the PO** | capped at the PO quantity; status `OVER_EXECUTED_CAPPED`, informational — the vendor is not paid for it and nobody is at fault |
| **Auditor could not count it** | PO quantity stands (`NOT_VERIFIABLE`). Absence of a count is not evidence of absence |
| **Not done on site** | zero, `NOT_DONE`, blocker |
| **Found on site, not in the PO** | zero and `AWAITING_CREDIT_NOTE` (R5). The invoice is booked in full and the vendor issues a credit note; this is not a reviewer's decision |
| **A rate above the PO** | for Bata, never within tolerance — `rate_must_equal` is on, because a rate change requires a new PO |
| **The report prints a list rate, not a discounted one** | ₹50.00 against a PO rate of ₹47.50 is the 5% discount, not a disagreement. The conflict needs `rate_after_discount`, the rate the parties settled on |
| **A rate with no quantity billed** | the vendor listed and priced the item and billed none of it. Faithful to the paper; shown muted so it does not read as a bug |
| **A rate against nothing verified** | the report prices a line the auditor found undone. Value is **zero**, and zero is a different answer from blank ("this report prices nothing") |
| **The report's own total disagrees** | `rules.audit_row_arithmetic` compares the printed total with `po_qty × rate_after_discount`. These reports extend the **ordered** quantity, so checking against the audited one would flag every row the auditor corrected. A mismatch is almost always a misread figure on a scan |

### Receipt and delivery

| Case | Behaviour |
|---|---|
| **A delivery proof, no GRN** | a POD proves a consignment — packages and a value — never per-item quantities (V§1 `receipt_granularity`). The receipt column stays blank on a multi-line bill |
| **…on a single-line bill** | the consignment has nowhere else to be, so quantity billed = quantity received, recorded as `receipt_basis="single_line_consignment"` and marked on screen as derived, not read |
| **The waybill's reference is misread** | `266J/AM4/S115224` against `26GJ/KMW/SI15224`. Accepted only with a corroborating declared value, and then **flagged** at REVIEW for a person to confirm — never settled silently |
| **…with a changed digit** | refused. Digits carry the invoice's sequence; accepting one would confirm receipt of the next bill's goods, which can share a value |
| **A POD for a different invoice** | not used as receipt evidence at all |

### Money and tax

| Case | Behaviour |
|---|---|
| **A tax-inclusive printed amount** | recognised, and the line says nothing — it reconciles |
| **Over- vs under-billing** | separated everywhere. Over-billing is the payer's exposure; under-billing is the vendor's loss and never a reason to hold a payment |
| **Out-of-PO lines cause three red checks** | `within_po_value` and `receipt_variance` fail *because of* the excess, so they are treated as explained and the case rolls to `AWAITING_CREDIT_NOTE` rather than showing three findings for one cause |
| **An invoice quoting no PO number** | not a finding. Many vendors never print one, and a Review on every such invoice teaches reviewers to skip the checks. Quoting the **wrong** PO is still a blocker |
| **TDS withheld** | the payment compares the base amount: withheld is not unpaid |

---

## 6. Scores and thresholds, in one place

| Name | Value | Governs |
|---|---|---|
| `LINK_AUTO_SCORE` | 0.85 | auto-linking a document to a case |
| `LINK_AUTO_MARGIN` | 0.15 | how far ahead of the runner-up it must be |
| `MATCH_ACCEPT` | 0.72 | pairing two lines |
| `MATCH_LLM_FLOOR` | 0.35 | the mid-band floor; below this, no adjudication is offered |
| `keys.TRUST_FLOOR` | 0.80 | whether an identity may carry a decision unattended |
| `CELL_ACCEPT_CONF` | 0.90 | accepting a read cell without a human check |
| `decisions.DEFAULT_THRESHOLD` | 0.85 | accepting a model's judgement |
| `money_tol` | ₹1.00 | money comparisons |
| `qty_tol` | 0.01 | quantity comparisons |
| `invoice_vs_receipt_tol` | ₹100 | R7, per invoice, symmetric |

---

## 7. Metrics

### Measured on real data

| Metric | Value | Source |
|---|---|---|
| Evidence rows receiving a **trusted** identity | **94.4%** | dev, all cases |
| Invoice lines receiving a trusted identity | **100%** | dev, all cases |
| Parser accuracy, `gpt-5.4` vs `gpt-4o` | **93.0 vs 82.1** | `docs/reconciliation/RECON_PARSER_EVAL.md` |
| Invented money rows, `gpt-5.4` vs `gpt-4o` | **0 vs 23** | same |
| Lines in genuine doubt after deterministic matching | **27 of 90** (case 2), **6 of 46** (case 1) | dev, 20 Nov 2026 |
| Evidence rows carrying a rate | **78 of 86** | Inner Space site report |
| Site-report lines now priced | **34 of 90** | case 2 |

### Worth watching in production

- **Auto-link rate** — the share of documents linked without a person. A fall
  means references are being misread or stores are inconsistent.
- **Mid-band share** — lines between 0.35 and 0.72. This is the agent's honest
  uncertainty, and the population the Decisions layer operates on.
- **Adjudication acceptance** — of the pairs offered, how many clear 0.85. A
  high abstention rate is not a failure; it is the layer declining to guess.
- **Reviewer override rate** — how often a human contradicts an automatic match.
  This is the only true accuracy signal, and it is recorded: every override is a
  `MATCH_CONFIRMED` or `MATCH_REJECTED` decision.
- **Cells flagged by double-reading** — rising means the scans are getting
  worse, not the model.
- **Cases by status over time** — a growing `AWAITING_*` population is a
  document-supply problem, not a reconciliation problem, and should not be read
  as a backlog of work for reviewers.

### What is deliberately not measured as accuracy

A verdict the agent declined to make is not a miss. Abstentions, flagged cells
and "Needs you" items are the system working as designed; counting them as
failures would create pressure to lower exactly the thresholds that keep a
wrong number from reaching a payment.

---

## 8. Reproducibility and audit

Any verdict can be explained and reproduced:

- `recon_cases.input_fingerprint` records what it was computed from, and
  `rule_version` which tenant profile applied.
- `recon_decisions` is append-only, so `as_of` replays any past state.
- Every emitted code exists in both `recon/vocab.py` and
  `docs/reconciliation/RECON_VOCABULARY.md`, enforced by a guard test — the engine cannot
  invent a status that the vocabulary does not define.
- `recon_edges` is a rebuildable projection, walked by a recursive CTE for
  evidence chains. Apache AGE was evaluated and is **not** available on this RDS
  instance; the CTE is the answer, and no decision is stored only in the graph.

---

## 9. Where to look in the code

| Concern | File |
|---|---|
| Thresholds and model names | `backend_ocr/app/recon/config.py` |
| Worker loop, claiming, stale recovery | `recon/worker.py` |
| Stage orchestration | `recon/pipeline.py` |
| Page classification | `recon/classify.py` |
| Extractors | `recon/extract/` |
| Document → case linking | `recon/link.py` |
| Line pairing and scoring | `recon/match.py` |
| Stable line identity | `recon/keys.py` |
| Billing rules | `recon/rules.py` |
| Line and header checks | `recon/engine.py` |
| Four-panel view model | `recon/fourway.py` |
| Tenant rule profiles | `recon/profiles.py` |
| Model judgements | `recon/decisions.py` |
| Persistence, decision log | `recon/repo.py` |
| Codes and their meanings | `recon/vocab.py`, `docs/reconciliation/RECON_VOCABULARY.md` |
