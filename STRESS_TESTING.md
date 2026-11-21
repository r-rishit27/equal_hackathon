# Stress testing the reconciliation agent

A deliberate attempt to break it: adversarial inputs to the code that decides
money, forced concurrency, an integrity audit of live data, and a check of
whether the audit trail supports the claims made for it.

*Written for the engineers who maintain the recon agent. It records what was
tried, what broke, what was fixed, and — the part that matters most — what is
still untested. Run 20–21 November 2026 against dev (`3.110.208.167`);
**testing is complete and this is the closed record of it.** Every figure was
re-verified against dev and the source on the last day (§9).
Companion documents: `docs/RECON_AGENT.md` (how the agent works),
`RECON_IMPLEMENTATION_PLAN.md` (why it is built this way),
`docs/RECON_VOCABULARY.md` (every code it emits).*

---

## The standard being tested

One sentence, and every test below is an attempt to violate it:

> **The agent may decline to answer, but it may not be confidently wrong, and
> it may not crash a reconciliation.**

That shapes what counts as a pass. An abstention is a pass. A flagged cell is
a pass. A number quietly 5% out is a failure even if nothing throws, and so is
a crash on a document a vendor can really send.

---

## Summary

**Nine defects found and fixed.** Five were pre-existing; **four were mine**,
introduced earlier in the same week's work and caught here. Two of mine had
dead-stopped a production path and nobody had noticed.

| # | Defect | Whose | Severity |
|---|---|---|---|
| 1.1 | A key claiming `ASSET_CODE` while scored as positional | pre-existing | latent |
| 1.2 | `same_consignment("N/A", "N/A")` → "same reference" | pre-existing | real |
| 1.3 | One upload, two bills, one shared recon document | pre-existing | **broke a live vendor** |
| 1.4 | Two recomputes doubled a case's lines | pre-existing | **silent corruption** |
| 1.5 | A deleted adopted bill was an inescapable dead end | pre-existing | **broke a live vendor** |
| 1.6 | `_save_evidence_rows`: 30 arguments for 31 placeholders | **mine** | **path dead** |
| 1.7 | `_save_invoice_lines` passed an undefined name | **mine** | **path dead** |
| 1.8 | Every case matched twice | **mine** | 2× cost |
| 1.9 | The receipt rule lived in the loader, not the rules | **mine** | inconsistent verdicts |

Plus two fixes to the test harness itself — a missing `tenant_service` stub
and a suite that made live API calls (§3.1).

**One finding is still open, and the test run created it.** Two stress probes
wrote live `QTY_CORRECTED` decisions that will replay onto real evidence rows
at the next re-extraction, attributed to a human reviewer. An earlier draft of
this document called them inert; they are not. The revert is written out in §6
and needs approval to run — it is item 1 of §9.

This file has itself been corrected twice: three claims in an earlier draft
were wrong (§3), and a verification pass on 21 November found three stale
counts and the false "inert" claim above (§9).

---

## 1. What broke

### 1.1 A key that lied about itself

`keys.disambiguate` gives a duplicate row an occurrence suffix and drops it to
ORDINAL *confidence*, so a decision on it is re-confirmed rather than
migrated. It kept the original *basis*.

The result was rows reading `basis=ASSET_CODE, confidence=0.40`: claiming to
be identified by a printed asset code while scored as identified by position.
A reviewer reads the basis to understand **how** a line was recognised, and
that one was lying. **13 such rows in dev.**

Fixed: the basis becomes `ORDINAL` too, because the pairing *is* positional
now. The key still carries the code it came from, so nothing is lost by saying
so plainly. No decisions rested on those rows (checked: 0). Four rows written
before the fix were re-stamped by re-saving their segment; the distribution
now reads `ASSET_CODE 0.99 ×45`, `ORDINAL 0.40 ×13`, `PRINTED_NO 0.95 ×176`.

### 1.2 Two documents agreeing about nothing

`same_consignment("N/A", "N/A")` returned **"same reference"**. Placeholders
are what scanners emit where a reference should be, and treating two of them
as agreement confirms receipt of goods against a bill neither document names.

Fixed: `NA`, `NIL`, `NONE`, `XX`, `0` and friends are rejected as references
before any rung of the ladder runs.

### 1.3 One upload, two bills, one document

Re-uploading an invoice creates a *second* bill row against the **same
upload**. `adopt_bill` keyed its recon document on the upload, so both bill
rows shared one document: deleting the old bill's copy took the live bill's
invoice with it, and the live bill could never be read. The log read
*"reading 1 existing bill(s)"* while reading none.

**26 shared uploads in dev; 1 had already collided**, which is what had a real
vendor's PO stuck on "Waiting for its invoice". Fixed by keying on the bill.

### 1.4 Two recomputes of one case doubled its lines

Forced on dev: two `recompute` calls at the same time left **98 line rows for
49 lines**. Every line twice, and with it every sum over the line table.

`save_result` deletes then inserts inside a transaction, which is not enough
at READ COMMITTED. Both transactions delete the rows they can see, both
insert, and nothing stops the second adding a parallel set. The verdicts
agreed — the engine is deterministic — so the symptom was invisible in the
summary and plain in the table.

Fixed by taking `SELECT 1 FROM recon_cases WHERE id = $1 FOR UPDATE` as the
first statement of the transaction. The same race now gives 49 for 49.

### 1.5 A dead end with no way out

A PO with no invoice adopts the vendor's bill. That was idempotent *including
deleted rows*, so once the adopted copy was removed there was no way to read
that bill again — the PO waited forever for an invoice sitting in Bills, with
nothing on screen to explain it.

Fixed with an explicit `revive` for the one moment that justifies it: a PO
actively waiting. The default still holds everywhere else, and a deleted row
nobody asked for now returns `None` rather than an id for a document that will
never be read.

### 1.6 / 1.7 Both save paths were broken, and nothing noticed

The worst finding, and self-inflicted. Adding the `amount` column to
`recon_evidence_rows` put the new placeholder in one INSERT and the new
argument in **a different one**:

- `_save_evidence_rows` declared `$31` and passed 30 arguments →
  `InterfaceError` on **every re-read of a site audit**;
- `_save_invoice_lines` was handed an extra `r.amount`, where `r` is not even
  a name in that scope → `NameError` on **every invoice save**.

Both had been dead since the column was added. Neither path runs during an
ordinary recompute, and the database suite that would have caught them was
skipped (§3).

Fixed, and then guarded: `tests/recon/test_sql_arity.py` walks the AST of
`repo.py` and `routers/recon.py`, counts the highest `$N` in every literal SQL
string and compares it with the arguments passed beside it. No database
needed. Writing it immediately surfaced the second bug.

### 1.8 Every case was matched twice

The decisions layer runs a *collector* pass to discover what is in doubt, then
threw that result away: `_adjudicator` returned a lookup or `None`, and
`recompute` reconciled again either way. Invisible at 90 lines (0.2 s), a full
minute at 1000.

`_adjudicated` now returns the first pass's result. Only a case where
something was actually judged pays for a second one.

### 1.9 A rule in the loader instead of the rules

The delivery-proof fallback — *"no Dynamics extract, so use what the carrier
declared"* — was implemented in `CaseBuilder`, which only the database path
runs. The same documents reconciled **differently depending on how they
arrived**, and `reconcile(inp)` silently skipped the ±₹100 receipt check on
every POD case.

Moved into `engine._receipt_variance`, where every caller sees it.

---

## 2. What held

### 2.1 Arithmetic and precision

| Attack | Result |
|---|---|
| Invoice with no billed lines (0/0) | confidence 1.0, no division |
| A charge and its exact credit, summing to zero | no division by zero; weights use `abs()` |
| 408.5 SF × ₹190.25 | ₹77,717.13 exactly — `Decimal` throughout |
| Fifty lines of ₹99,99,999.99 | adds up exactly |
| A zero rate on a report row | priced at **zero** — different from *unpriceable* |
| A report row with no quantity | unpriceable (`None`), not zero |

The zero-versus-none distinction recurs and is deliberate: *"the site supports
nothing for this line"* and *"we cannot price this line"* are different facts,
and collapsing them is how a missing document comes to look like a finding.

### 2.2 Text, unicode and scanner junk

| Attack | Result |
|---|---|
| `""`, spaces, `—`, zero-width space as a reference | refused |
| A reference one character longer | refused — length differences are not misreadings |
| `Pipe ⌀25 mm — 90° bend, ±2 mm` | key built, within the 120-char column |
| A description of only punctuation | falls to `ORDINAL`, and says so |
| 200 identical lines on one invoice | 200 distinct keys, **exactly one** trusted |

### 2.3 Roll-up detection against hostile shapes

The two-level invoice detector is the newest and most dangerous piece — a
false positive **deletes a real charge from a bill** — so it was attacked
specifically:

| Attack | Result |
|---|---|
| A single-line invoice equal to its own total | not a roll-up |
| Every line zero (trivially "balances") | not a roll-up |
| Negative headings | not a roll-up |
| A `None` amount in the middle | detected correctly regardless |
| ₹1 of rounding | tolerated |
| ₹30,000 out | refused |

### 2.4 Volume

| Lines | Match | Keys | Matched |
|---|---|---|---|
| 50 | 0.11 s | 0.000 s | 50/50 |
| 100 | 0.22 s | 0.000 s | 100/100 |
| 250 | 1.70 s | 0.001 s | 250/250 |
| 500 | 6.99 s | 0.002 s | 500/500 |
| **1000** | **28.16 s** | 0.006 s | 1000/1000 |

Accuracy holds all the way up — every line placed, every key unique, with the
invoice worded differently from the PO so the matcher had to work rather than
hit an exact string. Key building is free at any size. This measurement is
what exposed §1.8.

### 2.5 Concurrency — all four races forced

Dev had nothing pending to race over, so the harness **made** something
pending and put it back afterwards.

| Race | Result |
|---|---|
| Two workers claim one pending document | **pass** — A took it, B took none. `FOR UPDATE SKIP LOCKED` held |
| Two recomputes of one case | **failed**, fixed — §1.4 |
| A recompute racing a reviewer's correction | **pass** — 49 lines, the reviewed mark carried over |
| Two confirmations of one check | **pass** — both rows kept, last writer in force |

### 2.6 A correction survives a re-extraction

The whole justification for the line-identity work — decisions used to be
keyed to a row surrogate that DELETE + re-insert destroyed — and it had never
been checked on real data.

Forced: a reviewer's correction on a real row (`audit_qty` 15 → 22), then all
**84 rows of that segment deleted and re-inserted**, and the correction came
back on the new row with `corrected_by` intact. Repeated against a second
segment keyed `PRINTED_NO`: same result.

### 2.7 The decision log replayed

Two decisions written against one line a second apart: the later in force now,
the earlier in force as of a point between them, `supersedes` pointing at the
right row.

**It only works anchored on the database's clock.** `decided_at` is
server-generated and dev's server runs **1.0 s ahead of this machine**; the
first attempt anchored on `datetime.now()` got *nothing back* — which reads as
"no decision was in force", the worst way for an audit replay to fail. Every
caller today anchors on `recon_cases.as_of`, a server-side column, so the live
path is safe. The hazard is now in the `live_decisions` docstring.

### 2.8 Schema drift — none

Every column named in an INSERT or UPDATE across `repo.py` and the router,
checked against `information_schema`: **323 column references, all valid.**
This is the sibling of §1.6 — naming a column that was never applied — and it
ends the same way, as a runtime error on a path no test reaches.

### 2.9 Both save paths round-trip

With §1.6 and §1.7 fixed: 35 invoice lines and 84 evidence rows deleted and
re-inserted, read back identical, amounts preserved.

### 2.10 The audit trail

| Claim | Verified on dev |
|---|---|
| A verdict says what it was computed from | 3/3 cases carry `input_fingerprint` |
| …and which rules applied | 3/3 carry `rule_version=bata`, `engine_version=e1` |
| Every emitted code is in the vocabulary | 12 check codes, 14 line statuses, **0 missing** |
| Each case's events reach back to its creation | 3/3, first event 0–3 s after |

The vocabulary guard is checked against the **live data**, not just the
source, so a code the engine emits in production and nobody documented would
be caught.

### 2.11 Referential integrity

Nine of twelve integrity checks clean on the first pass: no orphaned line
results or header checks; no decision resting on an untrusted key; no case
pointing at a missing or withdrawn bill; no segment attached to a deleted
document; no document stuck mid-read; no case whose stored risk contradicts
its own lines. The three that failed became §1.1, §1.3 and §1.4; all twelve
are clean now but for the latent shared-upload population (§7).

---

## 3. The database suite: it existed unrun, and now runs

**Three claims in an earlier draft of this file were wrong**, in the same way:
"22 skipped" in the pytest summary was read as "there is nothing there". The
suite has since been run — §3.2 has the result — but the mistake is left on
the record because it is the most transferable thing in this document.

`tests/recon/test_repo_db.py`, `test_pipeline_db.py` and `test_router_db.py`
are a real harness — **18 tests** (10 + 2 + 6) that stand up throwaway app
tables, apply `recon/schema.py` **twice** to prove idempotency, push the
golden sets through the database path and assert the result equals the
in-memory one. They skipped entirely, because they need `RECON_TEST_DB_URL`
and nothing set it.

So *"the suite has no database fixture"* was false; *"`adopt_bill` has no
test"* was false, though with a caveat that took another run to surface
(§3.2); and **the arity bug of §1.6 would have been caught by this suite on
its first run.**

The failure was never a missing test. It was **22 skips that nobody read as a
gap**, and a stress run that trusted a summary line instead of opening the
files. A skipped test looks like a passing one at a glance.

### 3.1 What running it found

**The harness had drifted.** First run died on `relation "tenant_service" does
not exist`. Recon started reading that table when tenant rule profiles
shipped; the harness stubs every other app table it reads and nobody added
this one. Stubbed.

**`recompute` had stopped being a pure function of its input.** It consults
the Decisions API, so the golden test comparing the database path with the
in-memory one was comparing *adjudicated over the network* against
*deterministic*. It failed, and the run took **3 h 19 m** making real HTTP
calls.

Fixed in the tests rather than the product, so the default stays honest: an
autouse fixture in `tests/recon/conftest.py` turns the layer off for the whole
suite. **3 h 19 m → 1 m 28 s.** A suite that silently spends money on a paid
API is a bug in its own right, whatever else it is testing.

**One rule lived in the loader** — §1.9, found once the network was out of the
way.

### 3.2 Running it

```bash
RECON_TEST_DB_URL=postgresql://…/recon_scratch?sslmode=require \
  python -m pytest tests/recon/test_repo_db.py tests/recon/test_pipeline_db.py \
                   tests/recon/test_router_db.py -q
```

It **drops and recreates its stub tables**, so point it at a throwaway
database, never at dev proper. A `recon_scratch` database was created on the
dev server for this run and can be reused.

**Result, 21 November 2026, with every fix in this document in place:**

```
16 passed, 2 skipped in 347.75s (0:05:47)
```

Clean. The first run of this suite was `15 passed, 1 failed, 2 skipped`; the
failure was §3.1 and is fixed.

**The 2 skips are the whole of `test_pipeline_db.py`**, and they are worth
naming rather than leaving as a number — that mistake is what §3 is about.
They skip because they need sample PDFs in `AHU by Anjile/`, which is not in
the repository:

- `test_anjile_out_of_order_end_to_end`
- `test_waiting_po_reads_the_vendors_existing_bill`

The second is the one cited above as covering `adopt_bill`. It does cover that
path — but **it has never run here**, because the fixtures are missing. The
`adopt_bill` logic is covered by `tests/recon/test_adopt_bill.py`, which fakes
the connection and does run; the end-to-end version needs those PDFs committed
or fetched from somewhere, which is the next gap worth closing.

The arity bug of §1.6 would still have been caught by the suite as it stands:
`test_db_recompute_equals_in_memory` calls `save_extraction`, which goes
through `_save_evidence_rows`.

---

## 4. Where the next bug will be

§1.6 and §1.7 were not unlucky. They were methods **with callers and no test**,
on a path an ordinary recompute never reaches. That describes a lot of the
repository:

| | Count |
|---|---|
| Methods on `ReconRepository` | 83 |
| Called by the app, never by a test | **55** |
| Called by nothing at all | 5 |

The five are `backfill_override_decisions` (a documented migration for other
environments — keep), `cases_for_po`, `edges`, `mark_recon_upload` and
`po_line_position`. The last four look genuinely orphaned; removing them is a
deliberate decision rather than something a stress pass should do quietly, so
they are reported here instead.

Two things help with the 55: `tests/recon/test_sql_arity.py` catches the shape
of error that killed both save paths without a database at all, and **setting
`RECON_TEST_DB_URL` in CI would turn 18 skips into 16 running tests** (the
other two need sample PDFs — §3.2).

---

## 5. Still untested

**No reviewer has used the decision log in anger.** It has been exercised
(§2.6, §2.7) and the replay path is proven, but every row in it was written by
this harness. What a real reviewer does differently — correcting a value they
disagree with, rather than one chosen to be easy to restore — is unobserved.

**Extraction accuracy is out of scope here.** This document tests what the
agent does with what it read. Whether it read correctly is
`docs/RECON_PARSER_EVAL.md`.

**The UI is covered by its own suite, not by this run.** 700 frontend tests
pass; four pre-existing failures in `authedFiles.test.ts` are unrelated and
predate this work.

**No multi-tenant isolation testing.** One test asserts another tenant sees
nothing for a case; nothing probes the boundary systematically.

---

## 6. Litter left on dev

The concurrency and replay runs wrote **10 rows** into `recon_decisions`:
4 `QTY_CORRECTED`, 4 `race_probe` and 2 `STRESS_PROBE`.

The 6 `race_probe` and `STRESS_PROBE` rows are inert. No such decision kind is
read anywhere, so they are noise in the log and nothing more.

**The 4 `QTY_CORRECTED` rows are not inert, and an earlier draft of this
document said they were.** That was wrong, and the way it was wrong is worth
recording, because it is the same mistake the agent itself is built to avoid:
a confident claim that nobody checked against the code.

`QTY_CORRECTED` is a live decision kind. `_save_evidence_rows` calls
`_replay_evidence_decisions` on every save (`repo.py:642`), and that method
re-applies the newest `QTY_CORRECTED` decision per `line_uid` onto the freshly
extracted row — unattended, whenever the row's key is trusted. The 4 probe rows
form two chains:

| line_uid | live head | `audit_qty` it would apply | pre-probe value | key |
|---|---|---|---|---|
| `c7c2325d…589c` | #14 (of #12→#13→#14) | **22.000** | 1.000 | trusted |
| `6d35942f…6a7d` | #15 | **7** | 0.000 | trusted |

Both `line_uid`s still resolve to a live evidence row with a trusted key, and
neither head is superseded. Both were written with `actor_kind = 'human'`. So
the next re-extraction of either segment would silently stamp a stress-test
quantity onto real data and present it as a reviewer's correction — precisely
the "confidently wrong" outcome the standard at the top of this document
forbids, planted by the test rather than by the agent.

The log is append-only, so the fix is not a `DELETE`. It is one more decision
per line, superseding the probe head and restoring the value the probe itself
recorded in its own `was` field, written with `actor_kind = 'system'` so the
trail never pretends a person asked for it:

```sql
-- for each live stress-probe head: supersede it, restore `was`
INSERT INTO recon_decisions
       (tenant_id, line_uid, case_id, kind, payload, supersedes, actor, actor_kind)
SELECT d.tenant_id, d.line_uid, d.case_id, 'QTY_CORRECTED',
       jsonb_build_object('audit_qty', d.payload #>> '{was,audit_qty}',
                          'vendor_qty', d.payload #>> '{was,vendor_qty}',
                          'reverts', d.decision_id,
                          'note', 'stress-test probe reverted'),
       d.decision_id, 'system', 'system'
  FROM recon_decisions d
 WHERE d.kind = 'QTY_CORRECTED' AND d.actor = 'stress-probe'
   AND NOT EXISTS (SELECT 1 FROM recon_decisions s
                    WHERE s.supersedes = d.decision_id);
```

**This has not been run.** Writing to the decision log was refused as a
destructive action, which is the right default for an audit trail — so it needs
a person to approve it. Until it runs, treat those two segments as carrying a
pending correction that nobody asked for. The two `line_uid`s are in the table
above.

The lasting lesson is for the test harness, not the log: **a probe that writes
a live decision kind has to write its own revert in the same run**, or it
leaves a trap. Nothing in the suite enforces that yet, and §9 now carries it.

A **`recon_scratch` database** was created on the dev server for the test
suite. It holds only throwaway stub tables and can be dropped at any time.

---

## 7. Data findings that are not code defects

**44 invoice numbers have two live bill rows.** All identical in amount, none
with an `upload_id` — seeded demo rows (`AR-2026-xxx`, `B-0xx`), not a
duplication bug. Worth knowing before anyone counts invoices on dev.

**26 uploads are shared by several bill rows.** This is §1.3 as a population.
One had already collided; the rest are harmless now the adopted document is
keyed by bill. No migration needed — old upload-keyed rows still serve their
bill while they are alive.

---

## 8. Running it again

```bash
# Adversarial unit tests and the SQL guard (no database)
python -m pytest tests/recon/ -q              # 416 passed, 22 skipped

# Integrity, schema drift and dead-path audit
python scripts/recon_audit.py                 # against DEV_DB_URL from .env
python scripts/recon_audit.py --code-only     # no database needed

# Frontend
cd frontend && npx vitest run && npx tsc --noEmit
```

`scripts/recon_audit.py` is the ad-hoc checks promoted. Each is phrased so
that **a non-zero count is a finding**, with a line saying what would be
wrong, so the output can be read by somebody who did not write it. It exits
non-zero when it finds something, so it can be wired into CI.

### The checks that found things

| Check | What a non-zero count means |
|---|---|
| key basis and confidence disagree | a row claiming a printed code while scored as positional |
| one upload shared by several bill rows | two bills fighting over one recon document |
| line results outnumber their lines | two recomputes raced; every sum over them is doubled |
| two live bill rows for one invoice number | a re-upload that duplicated instead of replacing |
| case points at a bill that does not exist | a reconciliation about nothing |
| stored risk with no positive-delta line | a stale verdict nobody recomputed |

---

## 9. State at the end of this run

```
tests/recon          416 passed, 22 skipped          (no database)
database suite        16 passed,  2 skipped in 5m47s (recon_scratch)
frontend             700 passed (4 pre-existing authedFiles failures, unrelated)
tsc --noEmit         clean
recon_audit          1 finding (26 shared uploads — latent, §7)
schema drift         none (323 column references)
dev cases            3, all with fingerprint and rule version
data repairs         4 crossed-key rows re-stamped; 1 doubled case corrected
```

**All testing is done.** Every suite named in this document has been run to
completion, including the database suite end to end, and every figure quoted
here has been re-verified against dev and the source. What remains in the list
below is follow-up work, not outstanding tests — with one exception, item 1,
which is a cleanup the run itself made necessary.

**Every figure in this document was re-checked against dev and the source on
21 November 2026, after the last fix landed.** That pass found three stale
numbers and one false claim, all now corrected in place:

| Was | Is | Why it drifted |
|---|---|---|
| 13 distinct check codes (§2.10) | **12** | `po_reference` stopped being emitted when it was changed to stay silent for an invoice quoting no PO |
| 8 probe rows (§6) | **10** | the stated total never matched its own breakdown of 4+4+2 |
| 84 methods on `ReconRepository` (§4) | **83** | counted by hand once; now counted by AST |
| "the `QTY_CORRECTED` probe rows are inert" (§6) | **false** | the kind is live and replays unattended — see §6 |

The three counts were cosmetic. The fourth was not: it told a maintainer that
something harmless was sitting on real data when it is not. It is the one
finding of this run that the run itself created.

That pass is now `scripts/verify_stress_doc.py`. It prints each of the 13
figures above beside what dev and the source actually say, and exits non-zero
when any has drifted, so this document can be re-checked in one command rather
than audited by hand:

```
python scripts/verify_stress_doc.py
```

**What to do next, in order:**

1. **Revert the two live stress-probe decision chains** (§6). This is first
   because it is the only item that can still put a wrong number in front of a
   person. The statement is written out in §6 and needs approval to run.
2. **Set `RECON_TEST_DB_URL` in CI.** 16 tests that nobody runs are 16 tests
   that will drift again — that is exactly how §1.6 and §3.1 happened.
3. **Make the two pipeline tests runnable** by committing or fetching the
   `AHU by Anjile/` samples. Until then the only end-to-end path through
   ingest → classify → extract → link → match → engine is untested.
4. **Make the harness clean up after itself.** A probe that writes a live
   decision kind must write its revert in the same run; nothing enforces that,
   which is why item 1 exists.
5. **Decide on the four orphaned methods** in §4.
6. Chip at the 55 untested repository methods, worst-trafficked first.
