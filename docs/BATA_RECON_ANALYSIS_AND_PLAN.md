# Bata — PO ↔ Invoice ↔ On-ground Reconciliation: Analysis & Plan

> **2026-11-16:** Recon's codes now follow `docs/RECON_VOCABULARY.md` (Vibhanshu's vocabulary, adopted). See `docs/bata-recon/VOCABULARY_ADOPTION.md`.

| | |
|---|---|
| **Client** | Bata India Ltd (prospect) |
| **Problem** | Reconcile vendor invoices against purchase orders and on-ground (physical verification) reports, line by line |
| **Build target** | `uat2` branch — new **Recon** section in Vendor card → Documents |
| **Sample data** | `ACHS by Bosch/`, `AHU by Anjile/`, `Civil po by Inner Sapce/`, `Red Furniture by  Inner Space/` (repo root, untracked) |
| **Status** | Analysis complete · plan proposed · no code yet |
| **Date** | 2026-11-12 |

---

## 0. TL;DR

1. **Bata already has a billing rule, and the samples follow it exactly:**
   **`billable qty = min(PO qty, verified qty)`**, billed at the **PO rate**. Items the audit
   could not count ("Not covered in audit", "Out of audit", "As per Bata instruction not in scope")
   are billed at **PO qty**. Items marked "not done" are billed at **0**. Extra items found on site
   ("Additional / Not in PO") are **not billed**.
   Checked against the numbers:
   - Inner Space Civil: ₹9,56,733.55 recomputed = invoice, **to the paisa**.
   - Anjile AHU: recomputed ₹6,36,740.50 vs invoiced ₹6,34,890.50. The ₹1,850 gap is one
     verified item the vendor did not bill (MCP Hooter).
   - Inner Space Red Furniture: goods subtotal ₹5,45,985.90 recomputed = invoice.

   The approval memo says the same thing in words: *"process … as per the Audit Report & with
   Non-Countable items"*. So our engine's job is to **apply this rule and show every place an
   invoice departs from it**. We don't need to invent a matching policy.
2. **The on-ground report is the hard document, not the invoice.** There are two different
   auditors with two different formats:
   - **JPC**: typed PDF with a text layer, plus signed scanned field sheets.
   - **Matolia Rai**: scanned Excel print-outs with **handwritten** audit quantities and remarks.

   Each report is **store-level** and covers **several vendors and several POs**. One upload
   therefore has to be split and routed.
3. **The join key across everything is the store number.** It appears in:
   - the PO's requisition name: `… PO SN 1859`;
   - the report header: `Store No. & Name: New Town Yelanka Bangalore_1859`;
   - the memo subject.

   After the store number, the next keys are the PO number (`PPO000xxxxx-1`) and the vendor GSTIN.
4. **Line names differ across all three documents. The unit rate is the best anchor**, because the
   invoice copies the PO rate. Matching should run in this order:
   1. rate + unit + tokens, deterministic;
   2. LLM adjudication, only for leftovers;
   3. a human confirms;
   4. the alias is remembered per vendor.
5. **Bosch is the simple shape:** PO ↔ Invoice ↔ POD, single line, clean 2-way match. The POD
   proves delivery: it carries the invoice no., the total including GST, and a receipt stamp with
   a date. That covers the GRN step.
6. **The repo has no PO entity today** (per `docs/agents/RECON_AGENT.md` on uat2: *"no PO table
   exists yet"*). We add `purchase_orders`, evidence documents, and recon cases.

---

## 1. Dataset inventory

| Set | File | Type | Pages | Text layer? | Notes |
|---|---|---|---|---|---|
| **Bosch (ACHS)** | `Show purchase order.pdf` | PO | 2 | ✅ | PPO00030541-1, 1 line, p2 = T&Cs |
| | `26GJKMWSI15224.pdf` | Tax invoice | 2 | ✅ | 1 line, IGST 18%, p2 = conditions of sale |
| | `POD- SI15224.png` | POD / waybill (Safexpress) | 1 | ❌ image | Stamp + handwritten receipt date |
| | `MEMO.pdf` | Bata approval memo | 2 | ❌ (vector, no text) | "Machine installed" |
| **Anjile (AHU)** | `Show purchase order.pdf` | PO | 11 | ✅ | PPO00024046-1, 39 lines |
| | `Final Tax Invoice … as per Audit Main bill.pdf` | e-Invoice + annexure | 3 | ✅ | p1 = 2 lump-sum lines; p2–3 = 36-line "Performa Invoice" annexure |
| | `Outlet mall HP Thane (8255) PV Report.pdf` | Physical verification report (JPC) | 36 | p1–17 ✅, p18–36 ❌ scanned | Store-level, 4 annexures, several vendors |
| | `MEMO-.pdf` | Memo | 2 | ❌ | |
| **Inner Space — Civil** | `PPO00024378-1.pdf` | PO | 11 | ✅ | 36 lines, ₹11,72,575.45 |
| | `NEW TOWN YALHANKA- PPO00024378-1 Main Invoice.pdf` | Tax invoice + "Details of invoice" | 2 | ❌ scanned | p1 = 1 line "Gst Local Sales"; p2 = 35-line detail |
| | `1_New Town Yelanka Bangalore 1859 S.pdf` | Site visit & PV report (Matolia Rai) | 11 | ❌ scanned | **Handwritten** audit qty, 6 vendors/POs |
| | `Memorandum-Create - Bata.pdf` | Memo | 2 | ✅ | "as per Audit Report & with Non-Countable items" |
| **Inner Space — Red Furniture** | `Show purchase order.pdf` | PO | 8 | ✅ | PPO00023557-1, 25 lines, ₹6,26,693.90 |
| | `PM Rao Road Mangalore- PPO00023557-1 Main Invoice.pdf` | Tax invoice + detail | 2 | ❌ scanned | Handwritten invoice-no correction |
| | `1_ Report PM Rao Road Mangalore_9621 S.pdf` | Site visit & PV report (Matolia Rai) | 10 | ❌ scanned | Handwritten, 6 vendors/POs |
| | `Memorandum-Create - Bata.pdf` | Memo | 2 | ✅ | |

**What this means:** 9 of 17 files have no usable text layer. Vision/OCR is required. Per our
OCR memory, we still use the text layer first wherever it exists: it is exact, and vision misreads
GSTINs.

---

## 2. Document types: anatomy and complexity

### 2.1 Purchase Order (Bata ERP print, "Show purchase order") — complexity: **Low–Medium**

- **Header:**
  - PO number `PPO000xxxxx-1` (the `-1` is the revision);
  - PO date;
  - vendor name, GSTIN and vendor account (`V000…`);
  - terms of payment (`60%Advance_40%_IMM`);
  - purchase requisition `PPR…`;
  - **Purchase requisition name**, which carries the store and concept, e.g.
    `Temple Road Mysore New FSC Red 2 Gold PO SN 9648`.
- **Lines:** S.No, Description, Delivery date, Qty, Unit (`NO`, `SM`, `RFT`, `RMT`, `m`, `SF`),
  Unit price, Amount, plus delivery and billing address blocks repeated on every line.
- **Totals:** Sales subtotal, discount, charges, **Tax = 0.00**, Total. **POs are always pre-tax.**
- **Gotchas:**
  - The description column is narrow. Words wrap and get cut off mid-word: `PANAL PROGRAMMI / NG
    AND INTEGRATIO / N WITH MALL`, `Transportatio n`.
  - Some descriptions are truncated so badly they say nothing. Anjile line 34 is just
    `Supply & Installation` at ₹1,500. Only the rate identifies it as the "15 mm Air Punch Valve".
  - Every page repeats the full header, so extraction has to drop repeated headers.
  - The HSN/SAC column holds garbage (`INEInput18`). Ignore it.
  - The last pages are T&Cs. They matter for one rule: the late-delivery penalty (10% in the first
    7 days, 20% in the next 7, then 10%/day).

### 2.2 Tax invoice — complexity: **Medium**. Three vendor shapes

| Vendor | Shape | Where the line items are |
|---|---|---|
| Bosch | Structured ERP invoice with text layer | On the invoice itself (item code, qty, rate, gross, discount, net, GST type/% and amount, HSN) |
| Anjile | Tally e-invoice with **2 lump-sum lines** (HVAC ₹3,95,567.50 + Sprinkler/FAS ₹2,39,323.00) | **Annexure "Performa Invoice" (pages 2–3)**: 36 lines, columns "Audit Qty-M" and "Audit Amount", per-line GST |
| Inner Space | Scanned e-invoice with **1 line** "Gst Local Sales @18%" | **Page 2 "DETAILS OF INVOICE — As per PO"**: Qty, UoM, Unit rate, Amount, subtotals, then extra charges, CGST/SGST |

- **Rule:** the invoice is the header page **plus** its detail annexure. Reconcile against the
  annexure, then tie the annexure total back to the taxable value on the header page.
- **Gotchas found in the samples:**
  - The annexure document number differs from the tax invoice number (`AMP/26-27/000` vs
    `AMP/26-27/070`).
  - The invoice number has a handwritten correction (`IS-HO-26-27-108` → `109`).
  - Serial numbers have gaps (Anjile goes 35 → 39; Red Furniture skips 25–26).
  - Lines for items that are not in the PO appear with **qty 0** and their own rates.
  - HSN typo `993463` vs `995463`.
  - UoM written differently from the PO (`Sqmt` vs `SM`; aluminium cable `SF` vs PO `m`).

### 2.3 On-ground / Physical Verification report — complexity: **High**. The core difficulty

There are two auditors and two formats. **Both are store-level and cover several vendors.**

**A. J P Chawla & Co. LLP (Anjile / Thane 8255)**
- Pages 1–6: narrative covering scope, methodology, personnel present (with vendor
  representatives named per work type), and conclusion.
- Pages 7–17: **typed annexures** with a text layer. One annexure per work type: Civil & Electric,
  Lighting, Signage, AHU. Columns:
  - Sr, Vendor, Work, FA Code, Item Name, Unit;
  - **A = Qty as per PO**;
  - **B = Given/Vendor Qty**;
  - **C = Verified Qty**;
  - **C−A**, **C−B**;
  - Remarks (long free text, e.g. "Verification is done through measurement…").
- Rows past the PO list are tagged **"Additional work"**: items found on site but not in the PO.
- Pages 18–36: **scanned field sheets**, signed by the auditor, the vendor rep and the store
  manager. They carry **handwritten** `Mounted / Unmounted / Damaged / Total` per item and
  handwritten notes ("2 – store, 2 – above ceiling", "Actuator").
- ✅ **We can skip handwriting for JPC.** `PyMuPDF find_tables()` extracted the full AHU annexure
  cleanly in testing. The field sheets are **corroboration**: secondary, and useful for the
  "damaged / unmounted" signal.

**B. Matolia Rai & Associates (Inner Space / Bangalore 1859, Mangalore 9621)**
- Pages 1–2: "Report of Site Visit & Physical Verification" with disclaimers (concealed work and
  electrical are on a "best judgement basis"; dismantling is not verified without photos).
- Pages 3+: **scanned Excel print-outs, one sheet per PO type**, titled e.g. `FAMILY- INTERIOR +
  ELECTRICAL + RACKS PO`, `FURNITURE PO`, `SIGNAGE PO`, `AC HS PO`, `AC LS PO`, `LIGHTS PO`.
  - Each sheet has its own vendor block (name, GSTIN, contact). On one report: **Inner Space,
    Voltas, Atspire, Blue Star, Universal Refrigeration, VDM Enterprises**.
  - Columns: **Vendor Qty | Audit Qty | Remarks** (Audit Qty and Remarks are **often
    handwritten**), Assets Code (`CWIP000044080…`), Item Name, Unit, **QTY (= PO qty)**, Rate,
    **Rate after 5% discount**, Total.
  - Many cells print as `####` (Excel overflow), so totals are unreadable. **We recompute totals
    and never read them.**
  - The footer has a "**Not in PO / Additional**" block with vendor/audit qty and remarks.
  - The printed "Rate" is the pre-discount rate. The PO rate equals "Rate after 5%". Use the
    after-discount column, or derive it.
  - **The PO number is not printed.** Sheets are identified by vendor GSTIN + store + section
    title + item overlap with the PO.
- **Handwriting:** digits written in cells ("1665", "146", "94"), sometimes struck through or
  written as `348+102=450`, and remark sentences. Scans are slightly rotated, have stamps over the
  table, and one page is a faint photocopy.

### 2.4 POD / Waybill (Bosch, Safexpress) — complexity: **Medium** (photo + stamp + handwriting)

- **Printed:**
  - waybill no.;
  - pick-up/ship date;
  - consignor/consignee with GSTINs;
  - **Invoice List: 26GJ/KMW/SI15224**;
  - **Total Inv. Value 6,75,432.00**: this is the invoice gross **including GST**, not the PO
    value;
  - number of invoices;
  - packages/weight 18/696;
  - E-waybill no.
- **Handwritten/stamp:** consignee store stamp ("Bata Shoe Store, Temple Road, Mysore"),
  receiver name, **receipt date 21/9/26**.
- **Recon value:** evidence of goods receipt. It acts as the GRN.
  - Invoice no. must match.
  - Total value must equal the invoice gross.
  - Receipt date must be on or before the PO delivery date (29-09-2026). Otherwise the
    late-delivery penalty clause applies.

### 2.5 Bata Internal Memo — complexity: **Low**. Not a recon input

- Memo ref, From/To, Subject (contains store/SN and vendor), body, approver table (Approver,
  Status, Date, Remark).
- Use it as the **approval trail and rule source**, not for line recon. Example remarks:
  "Machine installed"; "ok to proceed as per audit".
- We **classify it, extract it, and attach it** to the case.

### 2.6 Complexity summary

| Doc | Structure | Reading difficulty | Linking difficulty | Recon role |
|---|---|---|---|---|
| PO | Fixed ERP template | Low (text layer); wrapped/truncated descriptions | Low (PO no.) | **Baseline**: qty cap, rate |
| Invoice | 3 shapes, header + annexure | Medium (2 of 4 scanned) | Low (PO no. printed on all) | **Claim** |
| PV report (JPC) | Typed annexures + scanned sheets | Low (typed) / High (sheets) | Medium (store, vendor, multi-PO) | **Verified qty** |
| PV report (Matolia) | Scanned Excel, handwritten | **High** | **High** (no PO no., multi-vendor) | **Verified qty** |
| POD | Courier form photo | Medium | Low (invoice no. on it) | **Delivery proof** |
| Memo | Web print | Low | Medium (store/SN in subject) | **Approval trail** |

---

## 3. How the documents link together

| Key | PO | Invoice | PV report | POD | Memo |
|---|---|---|---|---|---|
| PO number `PPO000…-1` | ✅ | ✅ (all 4) | ❌ (section title only) | ❌ | ❌ |
| **Store no.** (SN 1859 / 9621 / 8255 / 9648) | ✅ in PR name | ⚠ sometimes in address (`01859`, `01369`) | ✅ header | ❌ | ✅ subject |
| Vendor GSTIN | ✅ | ✅ | ✅ (Matolia per sheet) / name only (JPC) | ✅ | ❌ (name only) |
| Bata GSTIN (state) | ✅ | ✅ | ✅ (Matolia) | ✅ | ❌ |
| Invoice number | ❌ | ✅ | ❌ | ✅ | ❌ |
| Amount | pre-tax total | taxable + tax | (unreadable totals) | **gross incl. tax** | ❌ |
| Dates | PO date, delivery date | invoice date | date of verification | ship/receipt date | approval dates |

**Linking order for a newly uploaded document** (it is attached to a vendor, so the candidates are
that vendor's invoices from the last N months):

1. **Exact reference:** a PO no. or invoice no. found in the document. This links outright.
2. **Store + vendor:** the store SN and vendor GSTIN/name match the PO/invoice store. This narrows
   to one or two candidates.
3. **Amount:** POD total = invoice gross; annexure total = invoice taxable value.
4. **Line overlap:** the share of the document's lines that match PO lines by rate + name. This is
   how a Matolia sheet ("FURNITURE PO") finds PPO00023557-1.
5. **Date window:** PO date ≤ audit date ≤ invoice date (true for every sample).

- Auto-link when the top score is high **and** clearly ahead of the runner-up.
- Otherwise show the top 3 candidates and let the user pick.
- Sections of a store-level report that belong to **other vendors** are kept as unlinked evidence
  for that store. Later they can be routed to those vendors' cards.

---

## 4. The billing rule, proven on the samples

```
for each PO line:
    if audit says "not covered / out of audit / not in scope (as per Bata instruction)":
        expected_qty = PO qty                       # non-countable → billed at PO
        flag  = INFO  "Not verified on ground"
    elif audit says "not done/performed" or verified == 0:
        expected_qty = 0
    else:
        expected_qty = min(PO qty, verified qty)    # cap at PO, never above
    expected_amt = expected_qty × PO rate
extras ("Additional / Not in PO") → expected 0 (needs PO amendment to be billable)
percentage charges (packing 3% / 5%) → % × goods subtotal, capped at the PO amount
```

| Set | Recomputed | Invoiced | Δ | Explanation |
|---|---|---|---|---|
| Inner Space Civil (goods) | 9,49,608.55 | 9,49,608.55 | **0.00** | Exact |
| Inner Space Civil (+ Malba 3 × 2,375, "not in scope" → PO qty) | 9,56,733.55 | 9,56,733.55 | **0.00** | Exact |
| Anjile AHU | 6,36,740.50 | 6,34,890.50 | **−1,850.00** | MCP Hooter verified 1 × 1,850, **not billed** (vendor under-billed) |
| Inner Space Red Furniture (goods) | 5,45,985.90 | 5,45,985.90 | **0.00** | Exact (subtotal; see footing issue below) |
| Red Furniture packing | 5% × 5,45,986 = 27,299.30 | 27,299.30 | 0.00 | PO has ₹28,078 "fixed". The invoice applies 5% instead |
| Bosch | 6 × 95,400 = 5,72,400 | 5,72,400 | 0.00 | + IGST 18% 1,03,032 = 6,75,432 = POD value |

Capping examples that show the rule is **min(PO, verified)**:

| Item | PO | Verified | Billed |
|---|---|---|---|
| Gypsum false ceiling | 1531 | 1665 | 1531 |
| Orient tiles | 1531 | 1683 | 1531 |
| Plastic emulsion | 1605 | 1705 | 1605 |
| Add point | 142 | 146 | 142 |
| Butterfly valve | 3 | 4 | 3 |
| Acoustic insulation | 10 | 11.1 | 10 |
| Drain pipe | 12 | 13 | 12 |

---

## 5. Discrepancies found in the sample (what the system must surface)

**Severity:** 🔴 blocker (money at risk) · 🟠 review · 🔵 info (expected under the rules, but shown)

### Bosch — PPO00030541-1 ↔ 26GJ/KMW/SI15224
- ✅ Qty 6 = 6. Rate 95,400 = 95,400. Taxable 5,72,400 = PO total. IGST is correct: vendor state 24
  (GJ) ≠ place of supply 29 (KA).
- ✅ POD: invoice no. matches, total value 6,75,432 = invoice gross, received 21-09-26 ≤ PO delivery
  date 29-09-26 (no late penalty).
- 🟠 **Payment terms mismatch:** PO says `60% Advance / 40% IMM`; invoice says `100% – 30 days`.
- 🔵 Description variance: PO "4 TR Cassette Unit Inverter AC (Hitachi)" vs invoice "SPLIT AC -
  4.0TR CLASS HITACHI INVERTER CASSETTE - R32 - RAG348HIEOQ (W/O CONN. KIT)". Matched by 4 TR =
  4.0TR, cassette, inverter, Hitachi, and the identical rate.
- 🔵 Invoice says "W/O CONN. KIT" (without connection kit). This is worth surfacing in case the PO
  intended the kit.
- 🔵 Memo: 3/3 approved, "Machine installed". This is the installation confirmation, since there
  is no PV report for Bosch.

### Anjile — PPO00024046-1 ↔ AMP/26-27/070 ↔ JPC PV report (Annexure-4)
- 🟠 **Under-billing:** MCP Hooter (verified 1 × ₹1,850) is missing from the invoice.
- 🔵 **Under-use vs PO** (billed = verified < PO). There are 13 lines; the largest are:

  | Item | PO | Billed |
  |---|---|---|
  | 24 G duct | 70 | 30.8 |
  | Nitrile insulation | 80 | 41.9 |
  | 22 G duct | 15 | 11.1 |
  | Chilled water pipe | 85 | 76 |
  | Grill | 3 | 1.8 |
  | Flex duct | 35 | 30 |
  | 4 sqmm wire | 20 | 9.5 |
  | 1.5 sqmm wire | 20 | 10 |
  | Battery | 2 | 1 |
  | Control module | 4 | 2 |

- 🔵 **Not done → not billed (correct):** Input Module ×3, Fault Isolator ×1.
- 🔵 **Non-countable billed at PO:** Scaffolding, Panel programming & mall integration, FAS
  integration & programming.
- 🔵 **Over-execution capped at PO:**
  - Butterfly valve 4 → 3;
  - Acoustic insulation 11.1 → 10;
  - Acoustic lining 11.1 → 10;
  - Drain pipe 13 → 12.
- 🟠 **Additional work found on site (not in PO, not billed):**
  - fire-panel-to-mall integration wire (verified 25 m of 60 claimed);
  - pressure gauge with ball valve;
  - braided flexible drop (9 of 10);
  - upright sprinkler (2);
  - MCP looping wire (50 m).

  If the vendor bills these later, they need a PO amendment.
- 🟠 **Vendor over-claims seen in the audit (column B > C):** smoke detector wire 85 claimed vs 64
  verified; drain pipe 15 vs 13. The invoice billed the verified quantities.
- 🔵 HSN `993463` on 2 lines (should be `995463`). The serial numbering jumps 35 → 39.
- 🔵 The header page has 2 lump sums. HVAC + Sprinkler = 6,34,890.50 = annexure total ✅.

### Inner Space Civil — PPO00024378-1 ↔ IS-HO-26-27-120 ↔ Matolia report (1859)
- ✅ The recomputed total equals the invoice exactly. Every rate equals the PO rate.
- 🟠 **Description conflict:** invoice "Integrated Main LT Panel **Type D**" vs PO/report "**TYPE
  E**". The rate is the same (74,100). Was a different item supplied?
- 🟠 **UoM conflict:** aluminium armoured cable is billed in `SF`; the PO says `m`. The size reads
  "3 Point 5 x **355** SQMM" vs PO "3point5x**35**SqMM".
- 🟠 **Lines not in the PO on the invoice** (qty 0 today):
  - "8 Way TPN Distribution Board" @ 6,270 (the report says "8 way **SPN**", audit 1, listed under
    Additional);
  - "Floor Chipping" (report: 80 sft "not in scope").

  If qty ever becomes > 0, this is a 🔴 blocker.
- 🔵 Dismantling (furniture, false ceiling, lights): PO ₹30,096. Audit 0, billed 0. The report
  disclaimer says dismantling is not verified without photos.
- 🔵 PVC conduit: "Not allowed separately". Audit 0, billed 0.
- 🔵 MCCB 100 A: vendor claimed 1, audit blank, billed 0.
- 🔵 Malba disposal: vendor claimed 5, "As per Bata instruction not in scope", billed 3 = PO qty
  (non-countable).
- 🔵 Invoice reference "PPO00024378-1 dt. **10-Sep-26**", but the PO date is **24-03-2026**. The
  invoice quotes its own date as the PO date.
- 🔵 Report header "Store selling area 1531". This equals the PO qty for tiles and false ceiling:
  the PO qty is derived from store area.

### Inner Space Red Furniture — PPO00023557-1 ↔ IS-HO-26-27-109 ↔ Matolia report (9621)
- 🟠 **Footing error:** line 12 prints rate 2,105.00 / amount 1,26,300.00, but the subtotal
  (5,45,985.90) uses the PO rate 2,105.20 (= 1,26,312). The printed lines add up to 5,45,973.90.
  The net effect is nil, but the printed document is internally inconsistent.
- 🟠 **Packing charge basis:** PO has "Furniture Packing Charges Fixed" ₹28,078. The invoice bills
  5% of goods = ₹27,299.30 (lower, so favourable). The rule needs to be confirmed with Bata.
- 🟠 **Handwritten invoice-number correction** (108 → 109) on a digitally generated invoice. Check
  for a duplicate claim under 108.
- 🟠 **Size conflict on the same line:** PO "Metal Shelf CRC sheet with PC led" (no size) vs report
  "… **1200**" vs invoice "… **600**". The rate (2,105.20) ties them together.
- 🟠 **Audit remark that must be visible:** for that shelf (vendor 54, audit 60), *"LED strips not
  fitted/glowing … vendor had supplied and installed … later shifted/removed as per RM's
  instructions"*. It is billed 60 × with-LED rate.
- 🔵 Under-use:
  - Hanging bar 1200: PO 60, billed 54;
  - Impulse buy: PO 2, billed 1;
  - Metal shelf 600: PO 21, billed 13 (vendor claimed 16);
  - See-through channel 8 ft: PO 2, billed 0.
- 🟠 Invoice lines not in the PO (qty 0): Metal shelf 1200 @ 1,159; Metal shelf with PC led 600 @
  1,121; See-through channel **10 ft** @ 1,948. These come from the report's "Not in PO /
  Additional" block (verified 2, 6, 4).

---

## 6. Line-item name variance: what we have to map

Observed across PO ↔ Invoice ↔ Report:

| Pattern | Example |
|---|---|
| Action prefixes added/removed | PO "Balancing Valve Make Cassetle Advance" ↔ invoice "Supply & Installation of Balancing valve"; "Providing and fixing of …" |
| Brand/make suffix dropped | PO "8 point 5 TR AHU Make Waves Zeco" ↔ invoice "Supply Of 8.5TR AHU CS Type" |
| Number words / formatting | "8 point 5" ↔ "8.5"; "1point5 sqmm" ↔ "1.5 sqmm"; "4 TR" ↔ "4.0TR" |
| Spelling errors (vendor and Bata both) | Sienems, Stainner, Interartion, Progamming, Acousting/Accousting, Scafolding, Dismenlitng, Isolater, Thermostate, PANAL |
| Truncation / column wrap | "Transportatio n", "INTEGRATIO N", PO line that is only "Supply & Installation" |
| Size/variant tokens conflict | "600" vs "1200", "Type D" vs "Type E", "8 ft" vs "10 feet", "SPN" vs "TPN" |
| UoM aliases | NO/No/Nos/No./EACH; SM/Sqmt/Sq mtrs; RFT/Rft/rft; RMT/rmt/Rmt/m; SF/SFT/Sft |
| Category vs item | invoice header "Supply Installation of HVAC Work" (lump sum) ↔ 20+ PO lines |
| Rate shown differently | Matolia "Rate" (pre-5%) vs "Rate after 5%" (= PO rate) |

**Matching strategy (per PO, one-to-one):**

1. **Normalise.**
   - Lowercase.
   - Strip the action prefixes ("supply & installation of", "providing and fixing (of)",
     "supply of").
   - Strip "make X" brand tails.
   - Spell out number words (`point` → `.`).
   - Map UoM aliases to canonical units.
   - Correct spelling through a domain dictionary that grows over time.
   - Extract **numeric/variant tokens** (sizes, gauge, TR, sqmm, type letter, ft) as a separate
     set.
2. **Score each candidate pair:**
   - **rate**: equal within ₹0.5 / 0.1%. This is the strongest single signal: invoices copy PO
     rates, and the auditor's "rate after 5%" equals the PO rate;
   - **unit**: same canonical unit;
   - **name**: token-set similarity after normalisation;
   - **variant tokens**: agree, missing, or **conflict** (a conflict sets a flag; it does not
     reject the pair);
   - **position**: invoice and audit sheets mostly keep PO order or alphabetical order.

   Rates repeat inside one PO (4,200 ×2, 7,500 ×2, 2,200 ×3, 17.1 ×3, 76 ×2), so rate alone is
   never enough.
3. **Assign** with the Hungarian algorithm over the score matrix, so every line is matched at most
   once.
4. **LLM adjudication, only for lines below the threshold.** Send the unmatched line with the
   top-5 candidates and their rates/units. The model returns `{match_id | none, confidence,
   reason}`. A **numeric guardrail** follows: we accept the match only if rate/unit stay
   consistent.
5. **Human confirmation** in the UI for the remaining low-confidence pairs. Confirmed pairs are
   saved as **per-vendor aliases** (`vendor_id, alias_text → canonical PO item text`), so the next
   invoice from Inner Space matches without help.

---

## 7. Reconciliation checks (engine output)

### 7.1 Header and document checks

| Check | Rule | Severity |
|---|---|---|
| PO reference | PO no. on invoice = linked PO | 🔴 if different |
| Vendor identity | Vendor GSTIN same on PO, invoice, report sheet, POD | 🔴 |
| Buyer / store | Bata GSTIN state = store state; store SN consistent | 🟠 |
| Tax type | Vendor state code ≠ place of supply → IGST, else CGST + SGST; rate × taxable = tax | 🔴 on wrong tax |
| Arithmetic | qty × rate = amount per line; Σ lines = subtotal; subtotal + tax = total; amount in words | 🟠 |
| Header ↔ annexure | Annexure total = header taxable value | 🔴 |
| Over PO value | Taxable value ≤ PO total (and **cumulative across invoices on the same PO** ≤ PO total) | 🔴 |
| Dates | PO date ≤ audit/POD date ≤ invoice date; POD receipt vs PO delivery date (late penalty clause) | 🟠 |
| Payment terms | Invoice terms vs PO terms | 🟠 |
| POD | Invoice no. listed; Total inv. value = invoice gross; receipt stamp and date present | 🔴 if value mismatch |
| Duplicate / tampering | Handwritten correction on invoice no.; same invoice no. already billed | 🟠 |
| Approvals | Memo found and all approvers approved; remarks shown | 🔵 |

### 7.2 Line checks (per matched PO line)

| Status | Condition | Severity |
|---|---|---|
| `rate_higher` | Billed rate > PO rate | 🔴 |
| `rate_lower` | Billed rate < PO rate | 🔵 |
| `over_po` | Billed qty > PO qty | 🔴 (needs amendment) |
| `over_verified` | Billed qty > verified qty (countable items) | 🔴 **overbilling** |
| `under_billed` | Billed qty < min(PO, verified) | 🟠 (vendor may re-bill) |
| `under_used` | Billed qty < PO qty | 🔵 **always flagged** (per Bata: "underused is OK, still flag") |
| `over_executed_capped` | Verified > PO, billed = PO | 🔵 |
| `not_done` | Audit: not done, billed 0 | 🔵 · 🔴 if billed > 0 |
| `not_verifiable` | Audit: not covered / out of scope, billed at PO | 🔵 "not verified on ground" |
| `not_in_po` | Invoice line with no PO match | 🔴 if qty > 0, 🔵 if 0 |
| `additional_on_site` | Report "Additional / Not in PO" | 🟠 info for PO amendment |
| `description_conflict` | Variant tokens disagree (Type D/E, 600/1200, SPN/TPN) | 🟠 |
| `uom_conflict` | Canonical units differ | 🟠 |
| `damaged_unmounted` | Field sheet shows Damaged/Unmounted > 0 | 🟠 |
| `auditor_remark` | Non-trivial remark text | 🔵 (always shown next to the line) |
| `pct_charge_mismatch` | Packing/forwarding % recomputed ≠ billed | 🟠 |

Each line also gets an **expected amount** (from §4) and a **Δ = billed − expected**. Summed, Δ is
the money at risk for the invoice.

---

## 8. Document intelligence pipeline

```
upload (PDF / image / XLSX / CSV) in Vendor → Documents → Recon
   │
   ├─ 1. Page split + text-layer probe (PyMuPDF). Text layer ⇒ use it; else render 200 dpi → vision
   ├─ 2. Page classification (per page, not per file):
   │      purchase_order | tax_invoice | invoice_annexure | pv_report_narrative |
   │      pv_report_annexure | pv_field_sheet | pod | approval_memo | terms_conditions |
   │      delivery_challan | grn | measurement_sheet | other:<llm-proposed-label>
   ├─ 3. Segmentation: group consecutive pages → logical documents; split PV reports by
   │      (vendor GSTIN/name, PO section title); drop repeated PO headers and T&C pages
   ├─ 4. Typed extraction per class → JSON schema (below), with per-field confidence + page/bbox
   ├─ 5. Linking (§3) → PO + invoice candidates → auto-link or ask
   ├─ 6. Line matching (§6)
   └─ 7. Recon engine (§4, §7) → recon case with header checks + line results
```

**Extraction schemas (core fields)**

- `purchase_order`: po_number, revision, po_date, vendor {name, gstin, account}, buyer_gstin,
  store_sn, store_name, payment_terms, requisition {no, name}, lines[{sno, description, unit, qty,
  unit_price, amount, delivery_date}], subtotal, tax, total, penalty_terms.
- `tax_invoice` (+ `invoice_annexure`): invoice_no, date, irn, vendor_gstin, buyer_gstin,
  place_of_supply, po_ref, header_lines[], annexure_lines[{sno, description, hsn, unit, qty, rate,
  amount, tax_rate, tax_amt}], subtotal, charges[{label, basis_pct?, amount}], cgst, sgst, igst,
  total, corrections[] (handwritten edits detected).
- `pv_report_section`: auditor, store_sn, verification_date, vendor {name, gstin}, section_title
  (e.g. "FURNITURE PO"), rows[{sno, asset_code, item, unit, po_qty, vendor_qty, audit_qty,
  remark, mounted, unmounted, damaged, rate, rate_after_discount, row_type:
  po|additional}], signatures {auditor, vendor, store_manager}.
- `pod`: waybill_no, carrier, invoice_nos[], total_invoice_value, packages, weight, ship_date,
  receipt {stamp_text, receiver, date}.
- `approval_memo`: memo_ref, subject, store_sn, vendor, from, to[], approvals[{approver, status,
  date, remark}].
- `other`: llm_label, summary, key_values{}, lines[] (if tabular). If it has qty-bearing lines, it
  can join recon as an extra evidence source.

**Reading handwriting reliably (Matolia sheets).** These are the riskiest numbers in the system.

1. **Read with the PO as the prompt.** We already know the PO lines, so we hand the vision model
   the printed row list and ask it to fill in only `vendor_qty`, `audit_qty` and `remark` per row.
   It does not have to read the whole table blind.
2. **Read twice.** Do two independent reads (two models, or two crops at different DPI). Where
   they disagree, mark the cell low-confidence.
3. **Check the result against the invoice.** If `invoice qty == min(PO, read audit qty)`, that is
   strong confirmation. If not, it is either a real discrepancy or a misread, so show the **cell
   crop** next to the number for one-click human confirmation.
4. **Treat struck-through or arithmetic cells as needing review.** Cells like `348+102=450` are
   always flagged for a human.

---

## 9. Data model (new)

```
purchase_orders        id, tenant_id, vendor_id, po_number, revision, po_date, store_sn,
                       store_name, buyer_gstin, payment_terms, subtotal, total,
                       source_document_id, raw_json
purchase_order_lines   id, po_id, sno, description, norm_key, unit, qty, unit_price, amount,
                       delivery_date
vendor_documents (+)   EXISTING table, new columns: doc_class, llm_label, store_sn,
                       extracted_json, confidence, recon_status(parsed|needs_review|linked),
                       linked_bill_id            -- see §13; no separate recon_documents table
recon_evidence_rows    id, vendor_document_id, section_title, row_type, item, unit, po_qty,
                       vendor_qty, audit_qty, remark, mounted, unmounted, damaged,
                       confidence, page, bbox
recon_cases            id, tenant_id, vendor_id, bill_id, po_id, status, summary_json,
                       money_at_risk, created_by, updated_at
recon_case_documents   case_id, vendor_document_id, role(po|invoice|pv_report|pod|memo|other)
recon_line_results     id, case_id, po_line_id, invoice_line_ref, evidence_row_id,
                       match_score, match_method(rate|token|llm|human), po_qty, verified_qty,
                       billed_qty, po_rate, billed_rate, expected_amt, billed_amt, delta,
                       statuses[], severity
vendor_item_aliases    tenant_id, vendor_id, alias_norm, po_item_norm, confirmed_by, created_at
```

Documents stay private: S3 only, with 5-minute signed links issued after the tenant check. This is
the existing hard rule, and it applies to recon uploads too.

---

## 10. UX: Vendor card → Documents → **Recon**

- **Upload zone:** multi-file drag-and-drop (PDF/image/xlsx). Each file shows its detected type
  (editable chip), store, and linked invoice ("Linked to IS-HO-26-27-120 · 92%"). Where no link was
  confident, it shows "Choose invoice" with the top 3.
- **Recon cases list** (one per invoice): invoice no., PO no., store, documents present (PO ✓ /
  Report ✓ / POD — / Memo ✓), status, **money at risk**, flag counts by severity.
- **Case view.** Follows the approver-first layout: fixed, labelled sections, nothing hidden.
  1. **Header checks:** pass/fail rows (§7.1).
  2. **Line reconciliation table:**

     | Item (PO name) | Unit | PO qty | Verified | Billed | PO rate | Billed rate | Expected ₹ | Billed ₹ | Δ | Status |
     |---|---|---|---|---|---|---|---|---|---|---|

     - Each row expands to show the invoice and report wording, the auditor's remark, and the
       source crop.
     - Each row has a match badge (rate / name / AI / you).
     - Filters: flagged only, by status.
  3. **Additional / not in PO** items from the report and the invoice.
  4. **Approvals:** memo approver table.
  5. **Documents:** the source files, via signed links.
- **Actions:**
  - confirm or override a match (this saves an alias);
  - mark a flag reviewed with a note;
  - export the recon (xlsx/pdf).

  Buttons use the same label and style as the existing review actions (one style per action).

---

## 11. Phased plan

| Phase | Scope | Exit criterion |
|---|---|---|
| **P0: Fixtures and rule engine** | Hand-encode the 4 sample sets as golden JSON. Build the pure recon engine (§4, §7) and the matcher (§6) as testable functions | Engine reproduces the §4 table and the §5 flags from golden JSON |
| **P1: PO + invoice extraction** | PO parser (text layer); invoice header + annexure extraction (text layer, else vision); `purchase_orders` tables; 2-way recon (Bosch-shaped) | Bosch, plus the 3 others with no report, reconcile end to end from upload |
| **P2: PV report extraction** | JPC typed annexures (`find_tables`), Matolia scanned sheets (PO-prompted vision read + double read + crops), section splitting by vendor/PO | Golden audit quantities reproduced; ≥ 98% cell accuracy on Matolia, with the rest routed to review |
| **P3: Classification + linking + UI** | Page classifier, segmentation, auto-linking to invoices, Recon tab, case view, review/confirm, aliases | Upload of each raw sample folder → correct cases with no manual linking |
| **P4: POD, memo, other types** | POD and memo extraction, unknown-type generic path, cumulative-PO tracking across running bills, late-penalty check | All 17 sample files classified and attached |
| **P5: Store-level routing** | Report sections for other vendors routed to their vendor cards; Excel upload of reports/POs | |

---

## 12. Open questions for Bata

1. **Packing/forwarding:** is it a fixed amount (PO says "Fixed" ₹28,078) or a percentage of goods
   (invoice 5%, report shows 3%/5%)? Which wins?
2. **Non-countable items:** is the definitive list everything the auditor marks as "not covered /
   out of audit / not in scope"? Or does Bata keep a master list (scaffolding, malba, packing,
   transport, programming)?
3. **Over-execution** (verified > PO): is it always capped? Or is a PO amendment raised and a
   supplementary invoice expected?
4. **Additional items found on site:** does Bata issue a new PO, or amend the existing one
   (`-2` revision)?
5. Can one PO be billed by **several invoices** (running bills)? If so, we track cumulative billed
   vs PO.
6. **Tolerance** for rate rounding (₹2,105.00 vs ₹2,105.20): exact match, or ± ₹1 / 0.1%?
7. Can we get the PO and report data **as Excel/ERP export** (D365?) rather than PDFs? That would
   remove most of the reading risk.
8. Should the recon **block** the approval, or advise only (L1)? Recommend: advise only, with 🔴
   lines needing an explicit acknowledgement.

---

## 13. Codebase reuse (uat2)

This section was surveyed read-only on `uat2`. Line numbers are as of commit `9c5b43e`.

| Need | Exists on uat2 | Plan |
|---|---|---|
| Upload and storage | `routers/vendor_documents.py`: `store_vendor_document()` (:132) → `object_store` (S3 `onsumm-assets[-dev]`), table `vendor_documents` (migrations.py:705). `DOC_TYPES = ("contract","other")` (:41) | **Reuse.** Add `doc_type='recon'` (or recon labels) and the columns `doc_class`, `extracted_json`, `linked_bill_id`, `store_sn`, `recon_status`. In §9, `recon_documents` **becomes these extra columns** rather than a new table |
| Spreadsheet → rows | `core/vendor_doc_tables.py`: `parse_spreadsheet` (:190), `store_tables_in_background` (:282), tables `vendor_doc_tables` / `vendor_doc_rows` (jsonb), Indian-number coercion `_value` / `_coerce_text` | **Reuse** for Excel PO and report uploads. Add a column-role mapper on top (item / unit / qty / rate / audit qty) |
| Classification | `routers/vendor_doc_classify.py`: `extract()` (:44, first 3 pages, text → PNG fallback), TypeSafe Jev `ask_jev` → OpenAI `gpt-4o-mini` vision `ask_model` → regex `guess()`. Kinds `contract / existing / new / bill`. **"Purchase order" currently lands in contract criteria** | **Extend.** Add the kinds `purchase_order`, `pv_report`, `pod`, `approval_memo`, `invoice_annexure`. Take PO out of contract criteria. The new piece is **per-page** classification for multi-section files |
| OCR / vision | `utils/ocr_engine.py`: `OCR_TO_USE=auto`, `process_pdf_async` (:857), `transcribe_scanned_pdf` (:596), `_call_vision` (:203), `OPENAI_OCR_MODEL=gpt-4o`, **`MAX_PDF_PAGES=20`** | **Reuse.** Raise or bypass the page limit for PV reports (the JPC report is 36 pages). Render page by page so we don't repeat the 88-page OOM incident. Add the PO-prompted cell read for handwriting |
| Bills and lines | `stg_bills`, `fact_invoices`, `stg_bill_line_items` (product_name, quantity, unit, unit_price, line_total, tax…), loaded as in `contract_bill_variance._load_bill_lines` (:253) | **Reuse** as the invoice side. Header-only bills (Inner Space, Anjile) need annexure lines extracted, stored as recon evidence and tied to the bill |
| Fuzzy line matching | `routers/item_mapping.py` rapidfuzz `token_set_ratio` (:110–120); `services/nova_reconciliation/app/aliases.py` `_score` / `resolve_dynamic` | **Reuse** as the name-score component of §6. Add the rate/unit/variant-token scoring and Hungarian assignment |
| Tolerances / arithmetic | `review/adapters/_variance.py` (`within_tolerance`, `DEFAULT_TOLERANCE_PCT=2.0`); `ocr_engine._reconcile_line_amounts` (:299) | **Reuse** for qty × rate = amount and the rate checks. Rate tolerance for PO recon should be ~0.1%, not 2% |
| Recon roll-up pattern | `nova_reconciliation/app/algorithm.py`: `rate_check` (:158), `qty_cost_check` (:198), `_rollup` (:240) | Use as the **pattern** for the line/summary result shape |
| Review surface | `review/adapters/contract_bill_variance.py` (contract rate vs bill line as a review finding) | Add a sibling `po_bill_variance` adapter so recon flags reach Review Hub and approvals |
| PO entity | **None.** `docs/agents/RECON_AGENT.md` §9 proposes `fact_purchase_orders` / `fact_po_line_items` | Build on that proposal and adopt its naming. The LLM-match + numeric-guardrail functions it cites **do not exist** yet |
| Frontend | `components/vendor/VendorDocuments.tsx`: folders `recent / bills / contracts / t:<label>`, `UploadDialog` (:639, classify → upload), `ParsedDataModal.tsx` (`SheetViewer`, bill view) | Add a **Recon** folder/section and a case view. Reuse `UploadDialog`, `BigDrop` and `TypeChips` |
| LLM providers | OpenAI (`gpt-4o`, `gpt-4o-mini`) + TypeSafe Jev. No Anthropic SDK in the backend | Use the existing OpenAI vision path for the double read. A second model for the cross-check is optional |

**Constraints to respect** (from past incidents and memory):
- Documents are never public: only 5-minute signed links.
- Use the text layer first.
- Render page by page to avoid OOM on the t2.micro box.
- Run `scripts/run_api_migrations.py` after pulling `uat2`.
