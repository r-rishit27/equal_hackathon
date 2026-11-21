# CAPEX Reconciliation — Implementation Plan (hybrid / Plan C)

**Status:** For build · 18 November 2026
**Decision:** Build **Plan C (hybrid)** — one durable extraction record, a **permanent
append-only decision log**, and the match surface as a **rebuildable projection**.
**Audience:** the engineers implementing Recon.

**Built on, and reconciled against:**

| Source | What it contributes |
|---|---|
| `RECON_APPROACH_RESEARCH.html` · `RECON_APPROACH_BAKEOFF_SUMMARY.html` | The bake-off: C 89.2 / 16-of-16 vs A 78.6 / 13 vs B 48.4 / 8 |
| `QUESTIONS_FOR_BATA.md` | Bata's confirmed business rules (16 Nov 2026 call) |
| `docs/RECON_VOCABULARY.md` | The dictionary **as adopted** — §17a engine outcomes, §21 machine form |
| `RECON_SCHEMA_V1.md` | The rev-2 proposal. **Superseded in part** — see §2.3 |
| `docs/full_database_schema.md` | What is actually in the database (pulled 18 Nov 2026) |

---

## 1. The decision in one page

The bake-off found that all three designs compute the payable correctly. They differ in what
happens *after* the first run. Plan C is the only one where:

1. a **reviewer's decision survives** a document being re-read after a parser fix;
2. a verdict can be **replayed exactly as of** the date it was made;
3. **no second database has to be up** for payments or reviews to proceed.

So the three rules this plan exists to enforce:

> **R-I. Postgres is the source of truth** for documents *and* for every human decision.
> **R-II. Decisions are append-only** and keyed to a line identity that survives re-extraction.
> **R-III. The match surface is a projection** — wipe it, rebuild it, lose nothing.

Everything in §4–§9 follows from those three.

---

## 2. Where the build actually stands

This is not a greenfield plan. **≈6,120 lines across 23 modules** in
`backend_ocr/app/recon/` and **13 live tables** already exist.

### 2.1 What is already built, and is right

| Live table | Role | Verdict |
|---|---|---|
| `vocab_codes`, `vocab_aliases`, `vocab_meta` | The dictionary, synced from `recon/vocab.py` | **Keep as-is** |
| `recon_doc_pages`, `recon_doc_segments` | Page classification → document parts | **Keep** |
| `recon_evidence_rows` | Audit-report rows (po/vendor/audit qty, remark, verdict) | **Keep, extend** |
| `recon_invoice_lines` | Invoice lines | **Keep, extend** |
| `recon_cases`, `recon_case_segments` | A reconciliation case and its documents | **Keep, extend** |
| `recon_line_results`, `recon_header_checks` | Outcomes, derived | **Keep** — correctly rebuilt per run |
| `recon_events` | Append-only event log (`kind`, `payload`, `actor`, `at`) | **Keep — this is the spine of R-II** |
| `recon_match_overrides` | Reviewer-confirmed pairings | **Must change — see §2.2** |

Three things already in place that the bake-off asked for, and which are better than the
rev-2 proposal:

- **Generated code columns** (vocabulary §21). `verification_status`, `line_origin`, `uom`,
  `outcome` and the rest are computed **by Postgres from each row's own values**, with FKs
  to `vocab_codes`. A reviewer's correction re-derives them with no application code. The
  rev-2 trigger was a weaker way to reach the same place.
- **Corrections keep their original.** `recon_evidence_rows` carries `verdict` (the
  reviewer) beside `auto_verdict` (the classifier), plus `corrected_by`, `corrected_at`,
  `original_json` and `value_history`.
- **Result hashing.** `recon_cases.result_hash`, `engine_version`, `ack_hash` and
  `acknowledged_by` already give idempotency and an acknowledgement trail.

### 2.2 The three gaps that make this Plan A today

**Gap 1 — re-extraction destroys reviewer work.** `repo.py:411` and `repo.py:383`:

```sql
DELETE FROM recon_evidence_rows WHERE segment_id = $1::uuid
DELETE FROM recon_invoice_lines  WHERE segment_id = $1::uuid
```

Re-reading a document deletes its rows and re-inserts them. Every `verdict`,
`corrected_by`, `value_history` and `original_json` on those rows goes with them. This is
exactly the failure the bake-off measured as **22 of 26 confirmed matches lost**, and it is
live.

**Gap 2 — confirmed matches are case-scoped and cascade-deleted.**

```
recon_match_overrides
  PRIMARY KEY (case_id, other_key)
  FOREIGN KEY (case_id) → recon_cases.id ON DELETE CASCADE
```

Two consequences: a confirmation is **overwritten in place** on re-decision (so there is no
"as of"), and it is **deleted outright** if the case is rebuilt. `repo.py:208` already
deletes cases where `bill_id IS NULL`.

**Gap 3 — no replay, and re-runs ignore decisions.** `result_hash` covers the *result*, not
the *inputs plus the decisions in force*. So a re-run after a reviewer decision can return
the previous verdict, and a replay a year later shows today's decisions rather than the ones
that were in force. Bake-off findings 4.2 confirm both.

### 2.3 What `RECON_SCHEMA_V1.md` contributes, and where it is now wrong

Rev 2 proposed a single `recon_extractions` JSONB row. **That is not what shipped, and it is
not what we are building.** The bake-off scored that shape (Plan B) **48.4**, and the live
relational tables with generated code columns are the better instrument.

What rev 2 still contributes, and this plan keeps: the leg model, `receipt_granularity`,
keeping two evidence layers apart, `QTY_PAYABLE` never stored on an extraction, and §11 —
the Bata rules, which are the whole of §5 below.

**Action:** mark `RECON_SCHEMA_V1.md` §0–§6 superseded by this document, and keep its §11.
`RECON_SCALABILITY.md` argues for the Plan B shape and is now a historical note — say so at
its top rather than deleting it.

---

## 3. Target architecture

```
          documents in (email · upload · SFTP)         MSD extract (GRN)
                        │                                     │
                   classify → segment                   structured ingest
                        │                                     │
         ┌──────────────┴───────────────┐                     │
         ▼                              ▼                     ▼
  recon_doc_pages              recon_doc_segments ──── recon_grn_lines  (NEW §7)
                                        │
                     ┌──────────────────┼──────────────────┐
                     ▼                  ▼                  ▼
          recon_evidence_rows   recon_invoice_lines   recon_po_lines
                     │                  │                  │
                     └──────────┬───────┴──────────────────┘
                                ▼
                        recon_line_identity   (NEW §6.1)  ← stable key
                                │
          ┌─────────────────────┴─────────────────────┐
          ▼                                           ▼
   recon_decisions  (NEW §6.2)                  recon_edges  (NEW §6.3)
   append-only · never deleted                  projection · rebuildable
          │                                           │
          └──────────────────┬────────────────────────┘
                             ▼
                    engine.py  →  recon_line_results · recon_header_checks
                             │
                             ▼
                    recon_cases.summary_json  →  fact_invoices.verification_flag
```

**On the graph database.** Not in v1. The bake-off measured the questions the rules actually
ask as **1–2 hops**, answered by Postgres in ~1.5 ms, and found that making a graph critical
stops payments and reviews when it is down. `recon_edges` is a Postgres table with the same
shape as the graph projection, so if TigerGraph is adopted later it loads from the same rows
and nothing above it changes.

---

## 3.1 The four comparisons, and why a graph is the right model for them

A reviewer asks four questions about one invoice, and only four:

| | Question | Compared at |
|---|---|---|
| invoice ↔ **PO** | Was it ordered, at this rate? | line: qty · rate · amount · description |
| invoice ↔ **audit report** | Was it verified on site? | line: qty · description (rate/amount are **NA** — an auditor certifies what is there, not what it costs) |
| invoice ↔ **GRN** | Was it received? | line: qty · rate · amount · description |
| invoice ↔ **payment** | Was it settled in full? | **document**: an advice settles an invoice, not a line |

`recon/fourway.py` reshapes one engine result into those four panels. It decides
nothing — the engine already did — it only presents the same invoice lines four
times, so a reviewer reads one list rather than four unrelated screens. Panels that
cannot be filled still appear and say why, because a missing screen reads as a
forgotten one.

### Why the relationships want a graph

The documents are **many-to-many in both directions**, which is what makes this
awkward in plain SQL:

```
one PO            → many invoices        (R6: one PO, several bills)
one invoice       → many PO lines
one audit report  → many invoices        (the report is the hub, 4–5 invoices hang off it)
one GRN           → many invoice lines
one payment       → many invoices        (a remittance advice settles several)
```

A verdict rests on a *path*, not a row: *this invoice line → bills against → this PO
line → certified by → this audit row → received as → this GRN line → settled by →
this advice*. Expressing that in SQL is a four-way join whose shape changes with every
question asked.

**The recommendation: keep Postgres, add a graph over it.** `recon_edges` (§3) already
holds exactly these relationships as `BILLS_AGAINST`, `CERTIFIES`, `RECEIVED_FOR`,
`PAID_BY`, `COVERED_BY` — derived, rebuildable, nothing authored in it. Two ways
forward, in order of cost:

1. **Recursive CTEs over `recon_edges`** — no new dependency. The traversals the rules
   actually need are 1–2 hops, which the bake-off measured at ~1.5 ms.
2. **Apache AGE** (`CREATE EXTENSION age`) — openCypher *inside* Postgres, so the graph
   would live in the same database and transaction as the rows it is derived from.
   **Checked on dev, 19 Nov 2026: AGE is not available on this instance.**
   `pg_available_extensions` offers `ltree` and nothing else graph-shaped, which is
   expected — managed RDS ships a fixed extension list and AGE is not on it. Adopting
   it would mean self-managed Postgres or a different host, which is a far larger
   decision than this feature warrants.

**So option 1 is the recommendation**, not a stepping stone to option 2. A recursive
CTE over `recon_edges` answers every traversal listed above, needs no new dependency,
and keeps the path inside the same transaction as the verdict that cites it. Revisit
only if a question appears that genuinely needs variable-depth traversal — and price in
the hosting change at that point, not before.

What this is **not**: a separate graph database. The bake-off scored that design 48.4
against 89.2, because a graph outage stopped payments *and* reviews, and reviewer
decisions stored only in the graph did not survive a rebuild. Whichever option is
taken, the rule stands — Postgres owns the documents and the decisions, the graph is a
projection that can be wiped and rebuilt with nothing lost.

---

## 4. Build phases

| Phase | Goal | Status (18 Nov 2026) |
|---|---|---|
| **P1** | Stable line identity + append-only decisions; re-extraction stops losing work | **Done** — DDL live on dev; 94.4% / 100% of real rows get a trusted key |
| **P2** | Bata rule set (R1–R10): PO as cap, ₹100, credit-note lifecycle | **Mostly done** — see §4.1 |
| **P3** | GRN ingest from the MSD extract | **Done bar the file** — `recon_grn_lines` live on dev; `grn.load_extract` picks the data sheet, maps columns from the tenant's declared mapping (inference as fallback) and reports what it skipped; `pipeline.ingest_grn_extract` saves and logs; `receipt_total` and `receipt_lines` plumbed through `CaseBuilder`. Supporting Bata's real export is now a `grn_column_map` entry in their recon settings |

**Endpoints** (both resolve to the `recon` licence via the `/api/recon` prefix rule):

| | |
|---|---|
| `POST /api/recon/grn/upload` | loads an extract; returns the load report, not a count |
| `GET /api/recon/grn/mapping` | the tenant's declared mapping plus the canonical fields |

**A delivery proof is named as one.** When the POD answers the receipt question the coverage
strip says *"receipt confirmed at consignment level, not per item"*, and each coverage chip
states what it proves rather than only that it is present. A tick beside "Delivery proof"
would otherwise imply item-level receipt, which is the one thing a POD never gives (V§1).

**One upload, two bills, one recon document.** Re-uploading an invoice creates a *second*
bill row against the **same upload**. `adopt_bill` keyed its recon document on
`bill-upload:<upload_id>`, so both bill rows shared one document: deleting the old bill's
copy took the live bill's invoice with it, and the live bill could never be read again. On
the real vendor, upload `b4c3fec7` carried two rows of `IS-HO-26-27-120` — one deleted, one
active — and the active one was unreadable because of the deleted one.

The key is now the **bill** (`bill:<bill_id>`), so each bill row owns its document and one
deletion cannot poison another. An upload-keyed row from before the change still serves its
bill while it is alive; a deleted one is left alone, so a new bill gets a document of its own
rather than inheriting somebody else's deletion.

**A PO could wait forever for an invoice that already existed.** A purchase order with no
invoice yet *adopts* the vendor's bill — `repo.adopt_bill` creates a recon document pointing
at the bill's own upload, and the worker reads it. That was idempotent per bill **including
rows the user had deleted**, which is right as a default: removing a document from Recon
should not be undone by the next background pass.

It left a dead end with no way out. Delete the adopted bill, upload the PO again, and the PO
sits on *"Waiting for its invoice"* while the invoice is right there in Bills — nothing on
the screen explains it and nothing in the UI can undo it. On the real vendor both adopted
bills were soft-deleted, so `adopt_bill` found the dead row, returned its id and queued
nothing; the log even read *"reading 1 existing bill(s)"* while reading none.

`adopt_bill(..., revive=True)` now clears the deletion and re-queues, and
`_read_waiting_bills` passes it — a PO actively waiting for its invoice is a fresh request to
read that bill, not the loop resurrecting a deletion on its own. Everywhere else the default
holds, and a deleted row that nobody asked for now returns `None` rather than an id pointing
at a document that will never be read.

End to end on the real vendor: PO and invoice both `LINKED`, a case created, **₹9,56,733.55
billed, ₹0 at risk, confidence 0.89, PO leg 89%, audit leg 98%**.

**A deleted bill left its reconciliation in the queue.** A vendor showing *Bills 1* listed
two invoices on the recon dashboard, which looked like a counting bug in the new screen and
was not: both invoices are real, and one of them — `IS-HO-26-27-120` — had its bill
soft-deleted (`fact_invoices.soft_status = 'deleted'`). The Bills folder honours that flag;
`cases_for_supplier` never had, so the reconciliation for a deleted bill went on sitting in
the payable queue with ₹11,28,945.59 against it.

**Hiding it was the wrong fix, and it showed within minutes.** Excluding the case took its
*documents* off the screen too: the PO and the audit report stayed linked to a case nothing
resolved, so their rows lost the invoice, the coverage and the check, and the vendor looked
entirely unreconciled with a purchase order sitting right there.

So the case is listed and **flagged** instead. `bill_deleted` comes off a join to
`fact_invoices`, the status chip says *Bill deleted* — outranking whatever the engine last
concluded, because a withdrawn bill is not a stage of the reconciliation — the case carries
no exposure, the dashboard's counts and money leave it out, and it sorts last. Its documents
go on resolving exactly as before.

*A note on the diagnosis, because it cost a detour.* The case's `bill_id` appeared to be
dangling: it was in neither `fact_bills` nor `stg_bills`. It was not dangling — the Bills
list reads **`fact_invoices`**, a different table, and the ids were correct there all along.
Two tables in this schema hold something called a bill, and checking the wrong one produced a
confident wrong answer.

**The reconciliation screen had no front door.** A case could only be opened by finding a
*document* that happened to belong to it and clicking the invoice number inside its row —
which is why "take me to the reconciliation" kept having no answer. The dashboard screen now
lists the invoices its own counts are made of, and every row opens that case.

Each column is something a reviewer decides on: what is at stake, how much of the bill its
documents cover, and how sure the matching underneath is. **Coverage is the weakest leg that
has arrived, not the average** — a reconciliation is only as covered as its thinnest
supporting document, and averaging 100% with 40% to report 70% hides exactly the gap worth
seeing. Nothing at stake shows a dash rather than a ₹0.00 in the same weight as a real
exposure, and the dashboard's filters narrow the list.

`CaseStatusChip` moved to its own file on the way: it is the smallest thing in Recon and the
most widely used, and importing it from `ReconFolder` pulled in the document viewer, react-pdf
and pdfjs behind it — enough to break a test that wanted a coloured label, and enough to drag
a PDF renderer into any bundle that showed one.

**The dashboard is a screen, reached from the sidebar.** It had been a panel inside the
documents folder — which meant it existed only for somebody already looking at the list of
files. *Recon dashboard* is now its own entry in the vendor's sidebar, beside *Recon*, with
its own URL (`?folder=recon-board`), so it is linkable, survives a reload and is marked
`aria-current` when you are on it. Where the whole queue stands is a different question from
where one file is, and it is the one a finance manager opens first. Each screen carries a
button to the other, and the case card has one back to the dashboard.

**The case view says how much its verdict is worth.** The four comparison cards said *what*
each document concluded and were silent on the question underneath: **how much is this
conclusion worth?** A card reading "all agree" on a leg covering a fifth of the invoice
looked exactly like one covering all of it, and most of the card was empty while three
measures that answer it had already been computed and reached nobody.

`CaseVitals` puts them above the cards: **what each document covers** (a meter per leg, a
dash where the document has not arrived), **how sure the matching is** (the money-weighted
figure, with the lines banded Exact / Strong / Fair / Unpaired so the headline can be read
behind — the bands partition the lines, and a test asserts the counts add up), and **how the
documents read** (cells two readers could not agree on; a scanned sheet is read twice and a
disagreement is left for a person rather than settled by a coin toss). Each card now carries
its own coverage bar too.

**There is a way out of the case.** It opens over the Recon folder, and the only exit was
the close cross — so the dashboard and every other document were reachable only by guessing
that. A labelled *Dashboard* button sits beside Export and Re-run.

**Every document says how much of the bill it accounts for.** The question an accounts
manager asks about a supporting document is not "did it arrive" but *"how much of this
invoice does it cover"*, so each folder row carries that figure: the PO leg by how well the
lines paired, the audit leg by how much of the money the auditor certified, the receipt and
payment legs by whether they cover the bill. Weighted by money throughout — a document that
covers thirty small lines and misses the one large one has not covered the invoice. On dev:

```
case 1: PO  94%  audit 100%  receipt   —   payment  —
case 2: PO  90%  audit  97%  receipt   —   payment  —
case 3: PO  86%  audit   —   receipt 100%  payment  —
```

A dash, never a zero, where the document has not arrived: an audit report that is missing is
not an audit report performing badly, and 0% would accuse it of something.

**The dashboard has a real control.** A button with `aria-expanded`, keyboard reachable,
remembered per browser and open by default — somebody opens this screen to see where the
money stands, not to click a toggle first. The panels arrive on a short stagger and the bars
grow from their baseline so they read as filling rather than sliding, all of it inside
`prefers-reduced-motion: no-preference`: nothing moves for anyone who asked the system for
less of it.

**The confident edges teach the uncertain ones.** When the Decisions layer is asked about a
doubtful pair it now gets, as shared input, the pairings on those same two documents that we
are already sure of — the confident edges of the match graph. It is the most useful thing we
can offer: this vendor's PO says *"6 A plug with PVC conduits for looping circuits
Anchor/Roma /Crabtree/"* and the invoice bills it as *"6 A plug with PVC conduits for looping
circuits"*, and the way to learn that the make is dropped is from the lines that already
matched cleanly. Case 2 produces **21 such pairs**.

It is evidence about **wording and nothing else**. Neighbours in document order are
deliberately not sent: position may not decide a match (plan §3), and feeding it as context
would smuggle it back in through the model.

Which pairings teach was measured, not assumed. The first rule — EXACT and HUMAN — produced
an **empty** glossary on the real case, because a match is EXACT precisely when the words
already agree, so it has nothing to say. What carries vocabulary is a pairing we are sure of
whose wordings *differ*: HUMAN (somebody looked and said yes), ALIAS (a learned mapping, which
is a glossary entry by definition), and a high-scoring match **whose rate also agrees** — the
money corroborating the text is what separates this from teaching one guess with another.

The glossary rides in the shared input, which is the cacheable prefix, keyed by case, so it
is paid for once across all 27 questions and again on every re-run of that case.

**An invoice can bill in two levels, and we were counting both.** `IS-HO-26-27-120` opens
with two section headings — *Supply Installation of HVAC Work* ₹4,66,769.65 and *Supply &
Installation of Sprinkler & FAS System* ₹2,82,401.14 — and then lists thirty-six lines that
come to **exactly** ₹7,49,170.79, the same figure, and the same as the invoice's own total.
Added up naively the bill read ₹14,98,341.58 against a total of ₹7,49,171: every rupee twice.

The whole of that invoice's reported exposure was the duplicate. After `rollup.py`:

| | before | after |
|---|---|---|
| money at risk | **₹7,49,170.79** | **₹0.00** |
| pairing confidence | 0.429 | **0.935** |

The confidence moved too because a heading is unmatchable by construction — no purchase
order has a line called "Supply Installation of HVAC Work" — so it sat in the unmatched pile
dragging the score down for a reason no reviewer could act on.

**The test is arithmetic, never wording.** Nothing keys on "supply" or "installation";
vendors write what they like and a rule built on one vendor's vocabulary breaks on the next.
Detection needs *both* halves: the candidate headings must add up to everything below them,
**and** everything below them must add up to the invoice's stated total. Without a stated
total it declines outright — dropping a line that was a real charge understates a bill, and
an understated bill is the error nobody downstream catches. It found the two headings on
case 1 and nothing at all on cases 2, 3 and 4.

It also refuses to guess attribution. This invoice lists its details alphabetically *across*
both sections, so there is no contiguous run under either heading; `belongs_to` comes back
empty rather than plausible. Which section a line sits in is a nicety — not counting the
work twice is the point. The excluded headings are listed on the case with their amounts,
because a line dropped in silence is how an understated invoice gets paid.

**The queue has a dashboard, and every panel is a filter.** Light and flat, four answers in
the order a reviewer asks them: the exposure as a figure (a one-bar chart of one number is a
number with decoration), the status split as a thin segmented bar read beside its named
counts, a **meter per leg** because each leg has its own whole — the gap is the story, it
names the document to chase — and confidence banded on one hue. Clicking any panel narrows
the folders beneath it; a dashboard that shows a problem and leaves you to find it below has
only told you to go looking. `matchesFilter` is the single definition the panels and the list
share, so they cannot drift.

The status fills were **re-stepped after validation**: the obvious choice, the app's
`danger-600` beside `warn-600`, measures ΔE 9.1 to *normal* vision — below the floor of 15,
adjacent in one bar most people cannot tell them apart, and the token file's "colour-blind
safe" comment would have been taken on trust. The shipped four clear every check (worst
adjacent pair 29.4 normal, 21.1 protan). Amber is under 3:1 on white, so every segment is
also named, counted and given an icon: colour is never the only thing carrying a status.

**A case now says how sure its matching is.** `summary.confidence` is the share of billed
value resting on a pairing we trust, **weighted by money** — averaged over lines, one shaky
pairing on a ₹5,00,000 item would vanish behind forty tidy ₹500 ones, and it is the
₹5,00,000 that decides whether the invoice can be paid. An exact or human-confirmed pairing
counts whole, a scored one counts for what it scored, and a billed line with no counterpart
counts for nothing. `confidence_weakest` names the five worst, biggest money first.

Null, not zero, when nothing has been paired: a case waiting for its PO is a missing
document, not an untrustworthy match, and reporting it as 0 would seat it at the bottom of
the chart beside a case whose matching is genuinely bad. Measured on dev: 0.865 and 0.895 on
the two complete cases, **0.429 on case 1** — two large "Supply & Installation" lines
(₹4,66,769 and ₹2,82,401) that the matcher cannot place, which is exactly the population the
Decisions layer adjudicates.

**Recon has folders.** A reviewer looks for "the POs" or "the audit reports", not for a
filename in a list of forty, so documents are filed: Invoices, Purchase orders, Audit
reports, Goods receipt & delivery proof, Payment receipts, Approvals, and *Not filed yet* for
anything read but unrecognised. The classification already existed — every segment has
carried its kind since it was read — so this is a grouping of what is there rather than new
work, and **documents uploaded long before the folders existed land in them the first time
the screen opens**; nothing is re-read.

A Bata PDF often holds several kinds at once, so a file goes in exactly one folder — the most
significant kind it contains, invoice before PO before audit before receipt — and its row
still lists everything inside it. Filing it in four places would make one file look like
four. Empty folders are not shown. `SegmentKind` was also missing `PAYMENT_ADVICE` on the
frontend although the backend has emitted it since the payment leg shipped.

**Every pairing says how sure it is.** `match_score` was computed from the first matcher and
reachable only inside an expanded row, yet every figure on a line rests on it: a 62% match
means the difference beside it may be between two unrelated items. The case table has a
**Match** column and the four-way panels carry the same badge, tinted by confidence. An exact
or human match shows no percentage — a reviewer should read a number as *"this one is a
judgement"*, not as decoration on every row.

**A judgement layer, for the places the rules run out.** `recon/decisions.py` puts typed
questions to the OpenAI Decisions API (`gpt-6-luna` at `/v1/decisions`) and is deliberately
confined to two of them: a page the rule classifier cannot name, and a line whose natural key
scored below `keys.TRUST_FLOOR`, where position is the only thing left and position alone may
never decide. Nothing it returns touches a rate, a quantity or a total.

Three properties keep it advisory. **It abstains by default** — every call returns `Abstain`
unless the answer clears the caller's threshold (0.85 by default), and an abstention means
the caller does exactly what it did before this module existed. **It never overrules
evidence**: it is asked to choose between readings the documents support, never to supply a
number, and `LineMatcher._guardrail` still has the last word. **It cannot break the
pipeline**: no key, no network, a timeout, a malformed body, a refusal or an unknown answer
type all come back as abstentions with a reason, and the pipeline logs and carries on.

The matcher stays pure and synchronous, because its output is what a reviewer has to be able
to reproduce. `ReconPipeline._adjudicator` runs the match once with a `Collector` to find out
what is genuinely in doubt, asks about those pairs in **one** request (the API takes up to
400 questions, batched beyond that), and hands the answers back as a lookup for a second
pass. Where nothing is in doubt, or nothing could be judged, it returns `None` and the
deterministic path is untouched.

Measured on dev: case 2 offers 27 doubtful pairs and case 1 offers 6 — one call each — and
with the endpoint stubbed to fail, all four cases still recomputed. Two synthetic probes
against the live endpoint returned 0.96 for a true pair and a confident no for an unrelated
one. Configuration is `OPENAI_DECISIONS_URL`, `OPENAI_DECISION_MODEL`,
`OPENAI_DECISION_TIMEOUT_S` and `RECON_DECISIONS_ENABLED`, all defaulted, so the feature can
be switched off without touching a caller.

**The document says what the case says.** The priced audit leg reached the reconciliation
table and not the site report's own screen, where a reviewer reads the paper — that table had
a Rate column and left them to do the multiplication. It now carries **Value of audited ₹**
beside the rates, and `rules.audit_row_rate` / `audit_row_value` are the single definition
both screens use: `engine._audit_rate` and `_audit_value` are now aliases of them, so the
case table and the document can never disagree about what the report says. On the real sheet
the first row prices at 3 × ₹6,365 = **₹19,095**, which is exactly the TOTAL printed on the
scan.

**A rate against nothing verified is the report pricing a line the auditor found undone.**
Those rows show a rate and a value of zero, and the zero is the answer — the site supports
nothing for them. It is a different answer from *"we cannot price this row"*, which is what a
blank means, so the two are not collapsed: the rate is muted with a tooltip, exactly as the
invoice's own rate-with-no-quantity is.

**The report's own total is now read, and checked.** The sheet prompt asked for `rate` and
`rate_after_discount` and ignored the **TOTAL** column printed beside them, so there was
nothing to hold our own multiplication against. `EvidenceRow.amount` carries it as printed —
never computed — the document viewer shows it as *Total as printed*, and
`rules.audit_row_arithmetic` compares it with `po_qty × rate_after_discount`.

The check is against the **ordered** quantity, because that is what these reports extend: a
row reading `QTY 3 · RATE 6,700 · AFTER 5% 6,365 · TOTAL 19,095` is 3 × 6,365 even where the
auditor went on to certify something else, and checking against the audited quantity would
raise a difference on every row the auditor corrected. A disagreement is almost always a
misread figure — a rate scanned as 6,365 when it says 6,866 is invisible until its own total
contradicts it — so it surfaces as a row flag in the viewer and a conflict on the case line.

Additive DDL applied to dev, verified: `recon_evidence_rows.amount NUMERIC(16,2)`, 234 rows
untouched. It fills as documents are read again; nothing is backfilled, because the figure
has to come off the page.

**A list rate is not a disagreement.** The rate conflict added with the priced audit leg
fired twice on the real case — ₹50.00 against a PO rate of ₹47.50, which is exactly the 5%
discount. A report carrying the list rate and no discount column is saying what the rate was
discounted *from*, so the conflict now needs `rate_after_discount`, the rate the parties
settled on. Both false findings are gone; all four dev cases are clean of it.

**The site report prices the work, and we were throwing that away.** `EvidenceRow` has
carried `rate` and `rate_after_discount` since the first extractor, and nothing read them:
the audit leg compared quantities only, so a reviewer could see that 408 of 760 SF were
verified but not what the site says those 408 are worth. On the real Inner Space case **78 of
86 evidence rows carry a rate**. `LineResult.verified_rate` and `verified_amt` now carry it
through, the table has Rate and Value ₹ columns under Site audit, and the four-way audit
panel compares rate and amount for real instead of printing NA.

The discounted rate is the one used where a report prints one — that is the rate the parties
settled on, and the gross beside it is what it was discounted from. A report carrying no rate
values nothing rather than zero, since zero would read as "the site supports nothing": the
JPC typed annexure has no rate column at all (its table is Sr · Vendor · Work · FA Code ·
Item · Unit · PO qty · Given · Verified · remarks), so those cases stay quantity-only and the
panel says why. **The PO remains what is payable** — a site rate that differs from the PO
rate is recorded as a conflict on the line, not a new basis for payment, because one of the
two documents is then wrong about what was agreed.

**A rate against no quantity is the vendor's paper, not our error.** On `IS-HO-26-27-120` the
invoice lists Main Incomer MCCB at ₹13,680 and bills a quantity of zero, so nothing is
charged. The screen was faithful and read like a bug; the rate is now muted and its tooltip
says the item is listed but not billed.

**The receipt leg shows its money.** The Goods receipt group had a quantity and nothing
else, so the one figure a reviewer reconciles against — what the receipt is worth — was
driving the ±₹100 check without ever appearing on screen. `LineResult.received_amt` now
carries it and the table has a **Value ₹** column beside Received. From a Dynamics GRN it is
the line's booked value, which excludes tax; from a delivery proof it is the carrier's
declared consignment value, which includes it, and the column heading and cell tooltips say
which of the two a reviewer is looking at.

**Two corrections from Bata, 20 Nov 2026.**

*An invoice that prints no PO number is not a finding.* Plenty of their vendors never print
one, the case is linked to its PO by other means, and a Review that every such invoice fails
teaches reviewers to scroll past the checks. `po_reference` now stays silent when the invoice
quotes nothing. Quoting the **wrong** PO is still a BLOCKER — an invoice billed against
another PO would consume this one's value in silence — so only the half that was never a
finding was removed.

*The receipt leg compares like with like.* `ReconInput.receipt_basis` says which side of the
invoice `receipt_total` is held against: `"gross"` for a carrier's declared consignment
value, which includes tax, and `"taxable"` for a Dynamics GRN, which books goods at the PO
price. `CaseBuilder` now falls back to the delivery proof's declared value when no extract
exists, so the ±₹100 check runs on a POD case instead of abstaining — on the real Bosch case,
*"Invoice ₹6,75,432.00 incl. tax vs receipt ₹6,75,432.00 (difference ₹0.00)"*. Without the
basis it would have reported a difference of exactly the GST on every correctly delivered
consignment; a test states that failure so it cannot come back.

**A check that asks a question has somewhere to answer it.** `pod_invoice_ref_match` asked a
reviewer to confirm a waybill and gave them no way to do it, so the flag would have sat on
the case forever and been learned as noise. A check may now declare itself confirmable by
publishing `confirmable` — the exact text the reviewer is being shown — and the case view
puts a *Yes, confirm* button beside it. `POST /api/recon/cases/{id}/confirm` records the
answer as an append-only case decision (`recon_decisions` with `line_uid IS NULL`, read back
by `repo.case_decisions`) and recomputes.

Two refusals hold it honest. A check that did not publish `confirmable` cannot be answered at
all — a screen that lets a reviewer tick away an arithmetic failure is not a review. And the
answer is stored with what was on screen: if the document is read again and the reference
comes out differently, `engine._confirmed` rejects the stored yes, because it was given about
other words. No new DDL — `recon_decisions` already allowed a case-level row.

**The receipt column, where a delivery proof can honestly fill it.** A POD proves a
consignment — so many packages, worth so much, signed for — and cannot say how much of item 3
arrived, which is why the Goods receipt column is blank on a multi-line bill (V§1). One case
is not ambiguous: when the invoice bills exactly **one** line and the proof's declared value
is that invoice's gross, the consignment has nowhere else to be, so the quantity billed is
the quantity received. `engine._receipt_from_consignment` fills it and records
`receipt_basis="single_line_consignment"`; a figure read from a Dynamics GRN records `"grn"`.
The table marks the derived one with a dotted underline and says in its tooltip where it came
from, because a derived number must never look like a read one. Everything else stays blank:
two lines and one consignment value admits many splits, and inventing one would put a number
a reviewer trusts against evidence that does not carry it.

**Corroborated is not read.** When a waybill's reference is accepted because a scanner
confusion plus a matching declared value make it the likeliest consignment, the case now
carries `pod_invoice_ref_match` at REVIEW saying exactly that — the paper does not have this
invoice's number on it, and a machine should not settle that alone. It is not a BLOCKER: the
value and the receipt stamp both support the payment, so it asks for a confirmation rather
than withholding one. An exact reference raises no flag, and a reference refused outright
raises only `pod_matches`, so one problem is never counted twice.

**A panel says what it proves, and what it assumed.** `note` and `confirm` are separate
fields from `absent_reason`, which only ever explained an *empty* panel and so was never
rendered on a filled one — the delivery-proof caveat was invisible for that reason. `confirm`
sits above the tally, because a reviewer who reads "all agree" first has already been told
the machine was certain when it was only persuaded. The reference comparison also became a
real one: it had compared the POD's number against itself, which always matched, and now
compares it against the invoice's — named `reference`, not `description`, since labelling a
waybill number "Item" misnames what is on screen. With no receipt evidence at all the panel
names *both* documents that would answer the leg — the signed delivery proof or the Dynamics
extract — rather than only Dynamics, which read as a missing feature instead of a missing
document.

**The reviewer's exposure is not the vendor's loss.** The line chips used to read
*"Flagged 26"* when 25 of those were lines the vendor under-billed — harmless to the payer
and no reason to hold a payment. The chip row now splits the three groups a reviewer acts on
differently: **Over-billed** (with the money, warning-toned), **To check** (flagged, but
nothing at stake either way: descriptions, units, handwriting) and **Vendor under-billed**
(neutral, their loss). `over` and `under` are the same sets the engine totals into
`money_at_risk` and `under_billed`, so a chip can never disagree with the PayVerdict banner
above the table, and the three partition `flagged` so no line is double-counted or lost. The
view opens on the exposure when there is one, then on what needs reading, else on all lines;
empty groups show no chip at all.

**Storage vs parsing.** A document whose bytes were never reachable is not a file we failed
to read, so the Needs-you list no longer offers "Read again" for one — that button could never
have succeeded. `object_store.unreadable_here` names the cause, and the UI offers re-upload
instead. `scripts/recon_doc_triage.py` relabels any rows already in that state.

**UI:** `GrnUpload.tsx` renders the report in the flow rather than behind a toast — the sheet
used, whether the mapping was declared or guessed, every skipped row, the columns ignored and
the sheets rejected. A load with rows saved *and* rows skipped shows both, because a partial
load that reads as a clean one understates the receipt.

**To declare a client's columns** (alongside `rule_profile`, no deploy, no DDL — or
`python scripts/recon_settings.py set --tenant <name> --key grn_column_map --json '{…}'`):

```sql
UPDATE tenant_service
   SET config = COALESCE(config,'{}'::jsonb) || jsonb_build_object('grn_column_map',
       '{"po_number":"Purchase Order","qty_received":"Qty Passed","amount":"Line Value"}'::jsonb)
 WHERE service_key = 'recon' AND tenant_id = '<tenant>';
```
| **P4** | Replay: decision-aware fingerprint, as-of reconstruction | **Done** — `repo.input_fingerprint` + `case_fingerprint`; read path via `live_decisions(as_of=…)` / `overrides(as_of=…)`; DDL live on dev |
| **P5** | `recon_edges` projection + rebuild command | **Done** — `edges.derive()` pure + `repo.rebuild_edges()`; DDL live on dev; wired into `pipeline.recompute`. Verified on dev: 67 and 75 edges, rebuild idempotent. Acceptance test 7 passes |

**One step left needs sign-off, because it is destructive.** `recon_match_overrides` can now
become a view over `recon_decisions`: reads already come from the decision log, writes go to
both, and `repo.backfill_override_decisions()` migrates legacy rows idempotently (it reports
`unanchored` rather than dropping an override whose row no longer exists). Replacing the table
with a view means `DROP TABLE`, so it is **not** part of the autonomous loop — it needs an
explicit go-ahead and a verified backfill on every environment first.
| **P6** | Vocabulary learning loop with the payment guard | Guard already the default |

### 4.1 Rule-by-rule status

| Rule | State | Where |
|---|---|---|
| `R_PAYABLE_QTY` · `R_OVER_EXECUTED` | **Already shipped** | `rules.py` — `min(PO qty, verified qty)`, `cap_at_po` |
| `R_PO_CAP_QTY` (value, cumulative) | **Already shipped** | `engine._within_po_value`, with `prior_billed_value` |
| `R_RATE_EQUAL` | **Built** — `rate_must_equal` | `engine._po_line`; off by default, on for Bata |
| `R_VARIANCE_100` | **Built** — abstains without a receipt total | `engine._receipt_variance`, `invoice_vs_receipt_tol` |
| `R_SINGLE_PO` | **Built** | `engine._single_po`, `_po_refs` |
| `R_NOT_IN_PO` + remedy | **Built** | `engine._not_in_po` sets `LineResult.remedy` |
| `R_CREDIT_NOTE_OFFSET` | **Partial** — status exists, offset matching needs a sample CN | `CaseStatus.AWAITING_CREDIT_NOTE` |
| `R_EARLY_INVOICE` | **Built** — `CaseStatus.AWAITING_RECEIPT` | a case with no receipt leg parks; it is never reconciled |
| `GRN_VS_AUDIT` | **Built** — `grn.compare_with_audit` | the GRN is raised from the certified quantity, so a difference is a GRN finding, worded so nobody argues with the vendor about it |
| Tenant rule profiles | **Built and wired** — `profiles.BATA`, selected per tenant | every value traced to a dated statement on the call |

**Bata is on its profile as of 19 Nov 2026** (`tenant_service.config.rule_profile = "bata"`,
`enabled` unchanged at `true`). Recomputing both existing cases under each profile produced
**identical** verdicts, so the switch changed nothing retrospectively — the stricter rules are
latent until a case trips them. The statement used, for other environments:

```sql
UPDATE tenant_service SET config = COALESCE(config, '{}'::jsonb) || '{"rule_profile":"bata"}'::jsonb
 WHERE service_key = 'recon' AND tenant_id = '<Bata>';
```

Every tenant on dev is currently unset, so all of them reconcile under the shipped defaults.
That is deliberate: turning on `rate_must_equal` changes which invoices fail, so it should be
a conscious switch, not something a deploy does quietly.
| `R_PO_AMENDMENT` | Documented only (never occurs for Bata) | vocabulary §2 |

**A finding worth keeping.** `within_po_value` and `receipt_variance` both fail *because of*
out-of-PO lines — the invoice is booked at full value, so it exceeds the PO and the receipt by
exactly the excess. They are therefore not independent findings in that flow, and the case
rolls to `AWAITING_CREDIT_NOTE` rather than `NEEDS_REVIEW` when the excess accounts for them.
Without that, every credit-note case would show three red checks for one cause.

---

## 5. Phase 2 — the Bata rule set

Confirmed on the 16 Nov call (`QUESTIONS_FOR_BATA.md`). Codes are the adopted ones from
vocabulary §17a, so nothing new enters the dictionary.

### 5.1 The legs

```
COMMITMENT   PURCHASE_ORDER                   — cap only: maximum quantity, fixed rate
RECEIPT      GOODS_RECEIPT_NOTE (MSD extract) — the compared receipt leg
CERTIFYING   PHYSICAL_VERIFICATION_REPORT     — the authority the GRN quantity comes from
BILLING      TAX_INVOICE (+ CREDIT_NOTE)      — the claim, and its correction
```

The PO is **not** a compared leg. It is a ceiling on quantity and an equality on rate.

### 5.2 The rules, as code

| Rule | Logic | Emits (§17a) |
|---|---|---|
| `R_PO_CAP_QTY` | `grn_qty ≤ po_qty` and `Σ invoiced_qty ≤ po_qty` across all invoices on that PO | `OVER_PO` → FAIL |
| `R_OVER_EXECUTED` | `audit_qty > po_qty` → payable capped at `po_qty`; the excess is **not** payable on this PO | `OVER_EXECUTED_CAPPED` → WARN |
| `R_RATE_EQUAL` | `invoice_rate == po_rate` **exactly**. Not a tolerance | `RATE_HIGHER` → FAIL · `RATE_LOWER` → WARN |
| `R_PAYABLE_QTY` | `payable = min(audit_certified_qty, po_qty)`. The vendor's claim never sets it | `OVER_VERIFIED`, `UNDER_BILLED` |
| `R_VARIANCE_100` | `invoice_total − grn_total > 100.00` → exception, route to **costing team** | `WITHIN_PO_VALUE` → HOLD |
| `R_SINGLE_PO` | An invoice referencing two PO numbers **fails validation outright** | `PO_REFERENCE` → FAIL |
| `R_NOT_IN_PO` | A billed line with no PO line → exception with prescribed action *obtain credit note* | `NOT_IN_PO` → HOLD |
| `R_CREDIT_NOTE_OFFSET` | A credit note referencing the invoice clears the matching `NOT_IN_PO` holds | lifecycle, §5.4 |
| `R_EARLY_INVOICE` | Invoice present, no audit report yet → **park, do not fail** | `NO_EVIDENCE` → HOLD |
| `R_PO_AMENDMENT` | `PO_AMENDMENT` never appears for Bata; a revision arrives as a **new PO** | validation note |

### 5.3 The ₹100 threshold, precisely

```
exception  ⟺  (invoice_total − grn_total) > 100.00 INR
```

Three things that are easy to get wrong:

1. **Absolute, not a percentage.** Asked directly about a percentage band, Bata's answer was
   "₹100, whichever is lower". On a ₹7.5 lakh invoice that is ~0.013% — far tighter than any
   percentage rule we would have proposed.
2. **Invoice against GRN.** Not against the PO, and not line by line.
3. **The additional-lines case breaches it by design.** The invoice is booked at full value
   against a lower GRN, so the breach is expected and clears when the credit note arrives.
   **This exception must not render as a failure** — if it does, the costing team sees a red
   queue every morning and stops reading it. Render it as *awaiting credit note*.

### 5.4 The credit-note lifecycle

This is the single most important workflow, because it is Bata's standard resolution path —
not an edge case.

```
invoice arrives with lines not on the PO
   → book the invoice at FULL value
   → raise exception per line: NOT_IN_PO, action = "obtain credit note from vendor"
   → case status = AWAITING_CREDIT_NOTE, money_at_risk = Σ excess lines
   → credit note arrives, references the invoice
   → match CN lines to the excess lines → holds clear → case settles
   → the balance work, if payable at all, needs a NEW PO + a NEW invoice (new case)
```

Three implementation notes:

- The credit note is a `doc_role = CREDIT_NOTE` segment with `original_invoice_ref`. It
  joins the **existing** case; it does not open a new one.
- An **email approval does not clear a `NOT_IN_PO` hold.** Attach it as evidence on the
  exception. Vocabulary §11 has been annotated accordingly.
- `AWAITING_CREDIT_NOTE` needs adding to `recon_cases.status` and to the Review Hub filters.

### 5.5 Out of scope, confirmed by Bata

Advance (60% against the PO, parked in the vendor ledger), retention, LD. Bata's position is
that matching does not require the advance ledger. **Remove** `advance_adjustment`,
`retention`, `ld_penalty` and the `pending_inputs` list from the payable summary.

---

## 6. Phase 1 — identity and decisions (the heart of the plan)

### 6.1 Stable line identity

The bake-off's sharpest warning: carrying decisions forward **by line position** would have
put a battery correction onto the wrong line (the MCP hooter) **with no warning**. So
position is never the key.

```sql
CREATE TABLE recon_line_identity (
    line_uid        uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       uuid NOT NULL REFERENCES dim_tenants(tenant_id),
    doc_id          uuid NOT NULL,          -- the document, stable across re-extraction
    leg             text NOT NULL,          -- COMMITMENT / RECEIPT / BILLING / CERTIFYING
    natural_key     text NOT NULL,          -- see the ladder below
    key_basis       text NOT NULL,          -- PRINTED_NO | ASSET_CODE | NORM_DESC_RATE | HUMAN
    key_confidence  numeric(4,3) NOT NULL,
    first_seen_at   timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, doc_id, leg, natural_key)
);
```

**The key ladder**, highest confidence first:

1. `asset_code` where printed (`recon_evidence_rows.asset_code`) — strongest.
2. Printed line number **plus** `norm` (the normalised description). Either alone is unsafe:
   numbers get renumbered, descriptions repeat.
3. `norm` + `unit` + `rate` fingerprint.
4. **Human.** A reviewer binds the line, and that binding is itself a decision (§6.2).

**When the ladder cannot reach confidence**, the decision does **not** silently migrate. The
row surfaces as `UNCHECKED_READING` with a *please re-confirm* task. A visible re-confirm is
the acceptable failure mode; a silent mis-attachment is not.

### 6.2 The append-only decision log

```sql
CREATE TABLE recon_decisions (
    decision_id    bigserial PRIMARY KEY,
    tenant_id      uuid NOT NULL REFERENCES dim_tenants(tenant_id),
    line_uid       uuid REFERENCES recon_line_identity(line_uid),   -- NULL for case-level
    case_id        uuid,                       -- context, NOT ownership: no FK, no cascade
    kind           text NOT NULL,              -- MATCH_CONFIRMED | MATCH_REJECTED
                                               -- | QTY_CORRECTED | VERDICT_SET
                                               -- | EXCEPTION_RESOLVED | PRECEDENT
    payload        jsonb NOT NULL,             -- {was, now, reason, counterpart_line_uid}
    supersedes     bigint REFERENCES recon_decisions(decision_id),
    actor          text NOT NULL,
    actor_kind     text NOT NULL CHECK (actor_kind IN ('human','rule','model')),
    decided_at     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX recon_decisions_line ON recon_decisions (tenant_id, line_uid, decided_at DESC);
CREATE INDEX recon_decisions_case ON recon_decisions (tenant_id, case_id, decided_at DESC);
```

Four properties, each one deliberate:

- **No `ON DELETE CASCADE` anywhere.** `case_id` is context, not ownership. Deleting a case
  must never delete the record of what a person decided. This is the direct fix for Gap 2.
- **Append-only.** A changed mind is a **new row** with `supersedes` set. Current state is
  `the latest row per (line_uid, kind)`; history is the whole set. That is what makes as-of
  replay possible at all.
- **`actor_kind`** separates a human decision from a rule or model output, so "what did a
  person actually decide?" is one predicate.
- **Keyed on `line_uid`, not `segment_id`.** A re-extraction creates new rows but the same
  `line_uid`, so decisions re-attach. This is the fix for Gap 1.

**Migration.** `recon_match_overrides` becomes a view over the latest `MATCH_CONFIRMED` rows,
and existing overrides are backfilled as decisions with `actor_kind='human'`. Keep the
existing `recon_events` as the operational log; `recon_decisions` is the narrower,
load-bearing subset that reconciliation reads.

### 6.3 Re-extraction, rewritten

The current path (`repo.py:383`, `repo.py:411`) deletes and re-inserts. Replace with:

```
1. extract into a NEW segment version      (never touch the old rows)
2. resolve each new row to a line_uid via the §6.1 ladder
3. replay recon_decisions for those line_uids onto the new rows
4. any decision that cannot be re-attached  →  re-confirm task, never dropped
5. mark the prior segment superseded        (keep it; it is the audit trail)
```

**Acceptance test, from the bake-off:** re-extract the Thane audit report after a parser fix
and keep **26 of 26** confirmed matches plus the reviewer's correction. Today it keeps 4.

---

## 7. Phase 3 — GRN ingest

The receipt leg is an **MSD entry**, not a document. No OCR, no parser — which makes it the
cheapest and most reliable input in the whole pipeline.

```sql
CREATE TABLE recon_grn_lines (
    grn_line_id   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id     uuid NOT NULL REFERENCES dim_tenants(tenant_id),
    grn_number    text NOT NULL,
    grn_date      date,
    po_number     text NOT NULL,              -- a GRN exists only against a PO
    po_line_no    text,
    item_code     text,
    description   text,
    norm          text,
    unit          text,
    qty_received  numeric(14,3) NOT NULL,
    rate          numeric(14,4),
    amount        numeric(14,2),
    msd_voucher   text,
    source_file   text NOT NULL,
    ingested_at   timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, grn_number, po_line_no, item_code)
);
```

Rules that follow from the call: `channel = ERP_EXPORT`, no `ocr_id`;
`receipt_granularity = ITEM_QTY`; `qty_received` originates from the auditor-certified
quantity, so **GRN vs audit report should agree** — a disagreement is a finding about the
GRN's creation, not about the invoice.

**The POD is not the receipt leg.** It stays as delivery evidence for goods, at
`receipt_granularity = PACKAGE`, and must never be used as item-level receipt.

**Blocked on Bata.** Until the Excel extracts arrive, the column set above is an informed
guess. Build the loader against a **declared mapping file** rather than hard-coded column
names, so the real extract costs a mapping, not a rewrite.

---

## 8. Phase 4 — replay

```sql
ALTER TABLE recon_cases
  ADD COLUMN input_fingerprint  text,   -- hash(doc versions + engine_version
                                        --      + rule_version + max(decision_id) in scope)
  ADD COLUMN rule_version       text,
  ADD COLUMN replay_of          uuid REFERENCES recon_cases(id),
  ADD COLUMN as_of              timestamptz;
```

The fingerprint **must include the decision high-water mark**, or a re-run after a decision
returns the stale verdict — bake-off finding 4.2. A replay sets `as_of` and the engine reads
`recon_decisions WHERE decided_at <= as_of`, which is the whole reason the log is append-only.

---

## 9. Phase 6 — the vocabulary loop and its guard

The bake-off's most expensive finding: with the payment guard **off**, a misleading header
("Qty Verified by Vendor", which is really the vendor's claim) auto-mapped to the audited
quantity and **silently over-paid ₹18,660** on three lines.

Non-negotiable rules, two of which the adopted vocabulary §21 already enforces:

1. **A label that affects payment never auto-maps.** Anything resolving to a `qty_role`,
   `rate_role` or `pricing_basis` goes to a person. Auto-mapping is for cosmetic labels only.
2. **Ambiguous words never get a global alias.** A bare `QTY` resolves only with
   `context_doc_role` (vocabulary §18). Plan B's seeder created a global `QTY` entry and
   silently read a goods-receipt column as *ordered*.
3. **Learned aliases are tenant-scoped** — already a CHECK constraint (§21). Global aliases
   come only from the dictionary file.
4. **An unknown column never rejects the document.** Save it, queue it with its values. Plan
   B rejected whole documents; A and C queued them.

---

## 10. Vocabulary status

Of the five terms the bake-off flagged as missing (which would have made all three plans
reject the Thane report), the adopted dictionary has fixed two:

| Term | `docs/RECON_VOCABULARY.md` | `recon/vocab.py` | Note |
|---|---|---|---|
| `evidence_layer` | present | present | fixed |
| `date_role` | present | present | fixed |
| `quantity_legend` | absent | absent | a rev-2 header key; needed only if §5.2 of that doc is adopted |
| `role_alias_raw` | absent | absent | same — the live design keeps the raw label on the segment |
| `RECEIPT_DATE` | absent | absent | a `date_role` **value**; add when GRN ingest lands (§7) |

So this is no longer a blocker: the three remaining are artefacts of the rev-2 spec, not of
the shipped pipeline. `RECEIPT_DATE` is the one genuinely needed, and it arrives with Phase 3.

---

## 11. One business decision still required

**Which evidence layer sets the payable** — the typed audit table or the signed site sheet?

```
typed annexure sets payable   →  ₹6,06,740.50
signed site sheet sets payable →  ₹6,08,143.50
difference                     →      ₹1,403.00
```

The agreed Thane figure of ₹6,06,740.50 only comes out if the **typed audit table** governs,
while the extraction spec says the **signed sheet** should. Both layers are stored and kept
apart, so this is a one-line configuration — but it must be a stated decision, not a default
that falls out of extraction order. **Ask Bata, then record it in the template.**

---

## 12. Acceptance criteria

Plan C scored 16 of 16. These are the ones this plan must demonstrate, in order:

| # | Test | Pass condition |
|---|---|---|
| 1 | Thane payable | ₹6,06,740.50 payable · ₹30,000 held · ₹1,850 unbilled · ₹6,34,890.50 invoiced |
| 2 | All 12 flags | AHU 7 TR vs 8.5 TR · buyer GSTIN typo · advance not netted · LD exposure · 3 out-of-audit holds · MCP hooter unbilled · battery count conflict |
| 3 | Mangalore discount | Pays `RATE_NET`: ₹21,29,134.95, not the list rate (₹93,586 over-payment avoided) |
| 4 | Re-extraction | 26 of 26 confirmed matches and the reviewer's correction survive |
| 5 | As-of replay | A replay reproduces the verdict in force on that date, not today's |
| 6 | Re-run after a decision | Produces a fresh result, not the cached one |
| 7 | Projection rebuild | Wipe `recon_edges`, rebuild, byte-identical; zero decisions lost |
| 8 | Vocabulary guard | "Qty Verified by Vendor" goes to a person; the ₹18,660 over-payment does not occur |
| 9 | Ambiguous label | A bare `QTY` on a goods receipt never silently maps to *ordered* |
| 10 | Unknown column | Document saves; the column queues with its values |
| 11 | Concurrent reviewers | Two reviewers editing different lines — both edits survive |
| 12 | Retired code | Old documents stay correctable; only new use is blocked |
| 13 | ₹100 threshold | ₹99 variance books silently; ₹101 routes to costing |
| 14 | Credit-note lifecycle | Excess lines hold; the credit note clears them; the case settles |
| 15 | Single-PO rule | An invoice citing two POs fails validation |
| 16 | PO cap | An invoice for 11.1 against a PO of 10 caps at 10 and flags the excess |

Tests 1–3 are already met by the shipped engine and must not regress. 4–7 are Phase 1 and 4.
13–16 are the Bata rules, new.

---

## 13. Risks and dependencies

| Risk | Why it matters | Mitigation |
|---|---|---|
| **GRN extract not yet received** | The receipt leg has no real input; the column set is a guess | Build the loader on a declared mapping file; chase Harminder |
| **Stable-key confidence on unnumbered lines** | Some invoices and all emails have no printed line numbers | The ladder's rung 3 plus an explicit re-confirm task; never silent |
| **`recon_match_overrides` migration** | Live reviewer confirmations must not be lost in the move | Backfill as decisions first, verify counts, then swap to the view |
| **Dynamics posting unanswered** | Decides whether we need write access and who guarantees no double-post | Open question in `QUESTIONS_FOR_BATA.md` §6 |
| **₹100 per invoice or per line** | Changes the exception volume materially | Written confirmation before coding `R_VARIANCE_100` |
| **Two GSTINs fail checksum** | Consignor GSTIN on the POD, and the dictionary's "corrected" Karnataka GSTIN | Verify against Bata master data before seeding |

---

## 14. Explicitly not building

A graph database in v1 (§3). Advance, retention and LD (§5.5). `PO_AMENDMENT` handling for
Bata (R4 — it never occurs). The single-JSONB-row `recon_extractions` table (§2.3). AI
extraction quality work, which the bake-off correctly separated from the storage decision and
which needs approval to use client documents plus ~200 labelled examples.

---

## 15. Document status after this plan

| Document | Status |
|---|---|
| **This file** | The build plan. Current. |
| `QUESTIONS_FOR_BATA.md` | Current — the business-rule record |
| `docs/RECON_VOCABULARY.md` | Current — the adopted dictionary. **The root-level copy is stale; delete it** |
| `RECON_APPROACH_RESEARCH.html` | Current — the evidence for Plan C |
| `RECON_SCHEMA_V1.md` | §0–§6 **superseded** by this plan; §11 (Bata rules) still current |
| `RECON_SCALABILITY.md` | **Historical.** It argues the Plan B shape, which lost the bake-off |
