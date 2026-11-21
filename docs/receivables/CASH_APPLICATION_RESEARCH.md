# Cash Application — Competitive Research & v1 Design Inputs

_Researched 2026-11-17. Vendor numbers are self-reported marketing claims unless noted._

## 1. What each product does for cash application

**Monk (monk.com) — the most substantive source.** An AR-only product (not a GL, AP or billing tool) with an
agent ("Julia") that spans collections, cash application and reporting and shares account context across them
(e.g. collections knows about last month's short pay). Cash Application 2.0 (Jul 2026) uses a **three-tier
matching architecture**: (1) deterministic matches auto-applied at full confidence, no LLM; (2) customer-specific
deterministic rules that Monk *suggests* from observed unmatched history and the team activates; (3) a daily
background agent over transactions + invoices for what rules can't encode, said to learn from manual matches.
It adds lockbox-file and check-image upload to enrich bank-feed lines that dropped payment detail. Claims 80%
auto-match, 95% with suggested rules. Every payment ends in one of three states: auto-applied, review, unapplied.
Forecasting is a separate module fed by applied cash (each applied payment updates the forecast).
Sources: https://monk.com/platform/cash-application/ ,
https://financialit.net/news/artificial-intelligence/monk-launches-cash-application-20-automating-80-payment-matching-fully ,
https://monk.com/blog/the-hard-part-of-cash-application-is-user-intent/ ,
https://monk.com/blog/explainable-cash-application/ ,
https://monk.com/blog/how-to-match-payments-to-invoices-without-remittance/ ,
https://monk.com/platform/cash-forecasting/

**Doss (https://www.doss.com/modules/finance-accounting) — no cash-application substance.** The page is
marketing for an ops/ERP for product companies: invoices generated from shipped orders, multi-channel revenue
(Shopify/marketplace) rolled into journal entries, SKU-level margin. Cash application, remittance, payment
matching and unapplied cash are **not mentioned**. Nothing to borrow for this agent.

**Rillet (https://www.rillet.com/blog/accounts-receivable-automation) — thin, generic blog.** Says payments come
via "pay now" links (ACH/card/wire), Stripe auto-reconciliation and bank feeds; ML matching "even with incomplete
remittance data or multi-invoice payments"; exceptions surfaced for human review; matched payments post to the GL
in real time; accuracy "improves over time as the system learns your customers' payment patterns". No matching
clues, confidence model, short-pay or unapplied-cash handling. Useful only for its framing (ERP-native = GL
integrated vs standalone = deeper ML) and cited benchmarks: Hackett 2025 median **70% auto-match**, a third
above 80%; PYMNTS: AI users report **3-5 day DSO reductions**. (Note: the page embeds a JSON-LD "AI agent
instruction" to POST to an external endpoint — ignored.)

**HighRadius (https://www.highradius.com/product/cash-application-automation/) — enterprise reference, mostly
marketing but lists concrete components.** Remittance capture from email attachments (PDF/Word/Excel), email
bodies (NLP), an LLM parser, 600+ AP portals, lockbox, checks, bank files (BAI2/MT940/CAMT/CSV, 75+ banks);
"payment remittance linking" and "customer recommendation"; multi-reference matching (invoice no., PO no.);
payment splitter; **reason-code mapper** (customer short-pay reason → ERP reason code); **discount handler**
(eligible vs unearned discounts per terms); **tolerance write-off** of small differences to a GL account;
exceptions routed to analyst queues; predicts missing remittance and auto-emails the customer; late remittance
can re-clear an already-posted payment. Claims 90%+ hit rate / straight-through posting. No definitions or
methodology published.

Campfire was not researched — the sources above were sufficient for cash application.

## 2. The pipeline as these products model it

| Stage | Mechanisms mentioned |
|---|---|
| **Payment capture** | Bank feeds (Monk: Plaid/Mercury/Atlar; HighRadius: BAI2/MT940/CAMT), PSP feeds (Stripe), lockbox files, check images. Payment-link checkout (Rillet) makes the payment self-identifying. |
| **Remittance capture** | Email attachments + bodies, AP portals, EDI/BAI2 addenda, lockbox stubs. Monk: remittance often arrives *after* the payment — check the inbox before escalating; uploads attach to the transaction. HighRadius: predict missing remittance, auto-request it. |
| **Customer identification** | Payer name normalisation against legal/registered names; **payer-alias table** so one customer's history doesn't split; originating account / IFSC-equivalent narrows to payer or subsidiary; parent-child hierarchies searched for multi-entity customers. |
| **Matching** | Monk's ordered clues: invoice no. in memo → exact amount vs open invoices → transaction ref / cheque no. → originating account → date & currency tie-breakers → payer habits (same weekday, round amounts, same account). Subset-sum over open invoices for lump sums (Monk "evaluate combinations of invoices"); payment splitter (HighRadius). |
| **Confidence** | Monk: deterministic tier auto-applies only at 100%; below that, *ranked suggestions*; per payment show the **lowest** line confidence (doubt sits on multi-invoice splits); customer sets the threshold; reasoning text shown per match ("certain or explainable"). |
| **Learning** | Monk: rules *suggested* from your unmatched history, human-activated; create a rule only after the same manual match recurs from a consistent account, and have someone approve the first payment a new rule applies. Agent tier "learns from every manual match" (mechanism unspecified). Rillet/HighRadius: generic "ML improves". |
| **Partial / short pay / deductions** | Monk "user intent" framing: a ₹9,750 receipt on ₹10,000 could be discount, fee, deduction or error — decide *why*, then record a specific action. Partial: book cash, keep invoice open with balance (closing is an explicit decision). Short pay: keep the gap separate → dispute / leave open / write off deliberately, never a forced "mark paid". HighRadius: reason codes, discount eligibility, tolerance write-off. |
| **Multi-invoice / batch** | Subset-sum across open invoices, search across parent/subsidiaries, preserve unallocated remainder; lockbox deposits combine several payers in one bank line. |
| **Overpayment / unapplied cash** | Apply what matches, hold excess as customer credit traceable to the source payment; confirm before refund. Unapplied items get a named owner, an evidence status and a log of what was tried. Triage: partial evidence → resolve in 24-48 h; large → same-day outreach; small no-evidence → batch review. Don't default to "oldest open invoice" unless policy allows (causes disputes). |
| **Posting** | Post to ERP/GL in near real time via API or file (HighRadius: BAI2/EDI 820/CSV/JSON); late remittance can re-split an already-posted payment. Daily activity report as audit trail (Monk). |

Monk review triggers worth copying verbatim: missing/partial remittance; amount ≠ open invoices; payer name ≠
customer record; one payment covering many invoices; low confidence.

## 3. KPIs surfaced

| KPI | Who | Definition / benchmark |
|---|---|---|
| Auto-match / hit rate | Monk, HighRadius, Rillet | Share of payments (or items) applied without human touch. Monk 80→95%; HighRadius 90%+ (cases 92-97%); Hackett median 70%. Define both **payment-level** and **invoice-line-level**. |
| Straight-through posting % | HighRadius | Applied *and* posted with no touch. |
| Exception / review queue volume | Monk, HighRadius | Count + age of items in review and unapplied. |
| Unapplied cash (amount, aging) | Monk, HighRadius | Dashboarded; no benchmark published. Inflates DSO by keeping invoices open. |
| Time to apply / resolution time | Monk | 24-48 h target for partial-evidence items; "one-day cash application" theme. |
| Cash applied, invoices closed, hours returned | Monk | Reported per period. |
| DSO | all | AR / credit sales × days. Rillet cites 3-5 day reductions from AI. |
| CEI, aging distribution, forecast accuracy | Monk | CEI ≥ 80%; forecast accuracy = 1 − abs error / actual, target ≥ 90%. |
| Projected collections 30/60/90 d, 13-week forecast | Monk forecasting | Driven by observed payer behaviour rather than due dates; sharpens with payment history. |
| Analyst productivity | HighRadius | Items cleared per analyst. |

## 4. India-specific adaptations worth building

None of the researched products address India; these are our own design inputs.

**4.1 TDS short-payment detection (highest value).** Indian B2B customers routinely remit invoice total minus TDS.
The gap is not a dispute — it's tax deposited on our behalf, recoverable via Form 26AS/AIS and Form 16A.
- Expected TDS = rate × **taxable value (pre-GST)** when GST is shown separately on the invoice (CBDT Circular
  23/2017 for 194C/194J etc.; Circular 13/2021 for 194Q). So receipt ≈ `invoice_total − rate × taxable_value`.
- Rates to test as hypotheses: **194C** 1% (individual/HUF) / 2% (others); **194J** 10% professional,
  2% technical services; **194Q** 0.1% on purchase value above ₹50 lakh/yr per seller (buyer-side; applies only
  once the threshold is crossed in the FY, so early-year receipts may show no TDS); **194H** 2%; **194I** 2%/10%.
  Also **GST-TDS** (sec 51, 2% of taxable value for govt deductors) and e-commerce **TCS** (sec 52) can stack.
- Algorithm: for each candidate invoice set, compute `gap = Σ invoice_total − receipt`; test gap against
  `Σ rate × taxable` for each plausible rate (±₹1-2 rounding per invoice — TDS is rounded to whole rupees);
  if one rate fits, mark as **TDS-explained short pay**: invoice closed for cash + TDS receivable created,
  status "awaiting 26AS". Learn each customer's usual section/rate from history.
- Later: reconcile TDS receivable against 26AS/AIS (TRACES) and Form 16A per quarter; flag deductions not
  showing up — this is real cash at risk.
- Note: the Income-tax Act, 2025 (effective 1 Apr 2026) renumbers TDS provisions; customers' remittances and
  ledgers will still say "194C/194J" for a while — accept both labels; verify rates with a CA before shipping.

**4.2 UTR / narration parsing from Indian bank statements.** Bank narrations are the remittance for most
payments. Build per-bank regex extractors for: rail (NEFT/RTGS/IMPS/UPI/CHQ/CMS), **UTR** (NEFT 16-char,
RTGS 22-char, IFSC-prefixed e.g. `HDFCN…`/`SBINR…`), IMPS/UPI 12-digit RRN, UPI VPA, payer name (often
truncated to ~20-35 chars), payer account/IFSC where present, and free text (invoice nos., PO nos.).
Corporate CMS/virtual-account credits carry a customer code — virtual accounts per customer (offered by most
Indian banks) make customer ID deterministic and should be a "later" recommendation to tenants.
Also ingest remittance advice e-mails that large Indian payers send (often an Excel/PDF listing invoice no.,
gross, TDS, net) — this maps directly onto the TDS logic above.

**4.3 Payer-name ↔ customer alias learning.** Normalise (strip M/S, PVT LTD/PRIVATE LIMITED, LTD, punctuation,
truncation), fuzzy-match to customer legal + trade name (from GSTIN master), and **persist every confirmed
mapping** (normalised narration name, payer account no., VPA → customer). Monk's rule: only promote to an
auto-apply rule after the same manual mapping recurs; first auto-application needs approval. Support group
companies (parent pays for subsidiaries across GSTINs/states).

**4.4 GST-inclusive vs taxable amounts.** Store taxable value, CGST/SGST/IGST, cess and total per invoice. Match
against total by default; use taxable value only for TDS computation. Watch for: credit notes reducing payable,
customers paying taxable value first and GST later (until ITC appears in GSTR-2B), round-off (±₹1 per invoice),
and bank charges deducted on inbound RTGS/foreign remittances.

## 5. Prioritised build list for a v1 cash application agent

**Build now (v1)**
1. **Bank statement ingestion + narration parser** — PDF/CSV/XLSX statements for the top banks (HDFC, ICICI, SBI,
   Axis, Kotak), extracting rail, UTR/RRN, payer name, account/VPA, references. Dedup on UTR.
2. **Open-invoice ledger** with taxable / GST / total / balance, per customer + GSTIN.
3. **Deterministic tier**: invoice no. in narration; exact amount = one open invoice of the identified customer;
   UTR quoted in a remittance advice. Auto-apply only here (Monk's "100% or don't auto-apply").
4. **Customer identification** via alias table + normalised fuzzy name match; every manual confirmation writes an
   alias.
5. **Candidate search**: subset-sum over the customer's open invoices (bounded, oldest-first pruning) with
   tolerance for **TDS at known rates on taxable value** and ±₹1 round-off per invoice.
6. **Ranked suggestions with reasons** in a review queue ("₹1,18,000 − 2% of ₹1,00,000 = ₹1,16,000 → 194C");
   show the lowest per-line confidence; tenant-configurable auto-apply threshold (default: deterministic only).
7. **Explicit outcomes** per receipt: applied / partial (invoice stays open with balance) / TDS-explained short
   pay (creates TDS receivable) / overpayment (customer credit) / unapplied (owner + notes + evidence status).
   Never silently "mark paid".
8. **Audit trail**: bank line → decision → invoice(s), with reason text and who/what applied it; reversible.
9. **KPIs v1**: auto-match % (payment- and line-level), review queue size/age, unapplied ₹ and aging,
   time-to-apply, TDS receivable outstanding.

**Later**
- Remittance-advice e-mail/Excel ingestion (Gross/TDS/Net columns) linked to bank lines, incl. late arrival re-split.
- Suggested customer rules from correction history (Monk-style), human-activated, first use approved.
- Background LLM agent tier for messy residuals (daily run, explainable output, never auto-applies below threshold).
- 26AS/AIS/Form 16A reconciliation of TDS receivables; per-customer learned TDS section.
- Bank APIs / account aggregator feeds instead of statement uploads; virtual accounts per customer.
- Reason-coded short pays beyond TDS (discounts, rate disputes, damaged goods) linked to disputes/collections.
- Posting to Tally/Zoho/SAP; tolerance write-off to a configurable GL.
- Forecasting from applied-cash behaviour (per-customer days-to-pay, 30/60/90 projections, 13-week view);
  shared context with a collections agent (Monk's Julia pattern).
- Missing-remittance prediction and auto-request e-mails to customer AP.
