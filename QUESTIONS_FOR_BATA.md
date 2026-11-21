# CAPEX Four-Way Match — Business Questions for the Bata Team

**Prepared by:** Onsumm · **Issued:** 16 November 2026 · **Answered:** 16 November 2026
**Source of answers:** call "Bata X Onsumm: Data Clarification", 16 Nov 2026, 11:00 — Harminder Singh (Bata), Vibhanshu Ahluwalia and Rishit Rastogi (Onsumm)
**Status:** 5 of 6 questions closed · Q6 (Dynamics posting) and the mailbox point still open

---

## Purpose

We are configuring the CAPEX four-way reconciliation — purchase order, physical
verification (audit) report, goods receipt and vendor invoice — for Bata's store fit-out
and goods spend. Six business decisions sat with Bata rather than with us. This document
now records both the questions and Bata's answers, and what each answer changes in the
build.

---

## Summary of answers

| # | Question | Bata's answer |
|---|---|---|
| 1 | Approval limits and acceptable variance | **₹100 absolute.** Invoice over GRN by ≤ ₹100 is booked; above that it goes to the costing team as an exception |
| 2 | Additional work not covered by the PO | **A PO is never amended.** Invoice booked in full, credit note booked for the excess lines, a **new PO** and a new invoice for the balance |
| 3 | Authority of the audit quantity | **The auditor's certified quantity is final.** The GRN is created from it; the vendor's claim does not prevail |
| 4 | Advances, retention and part-billing | 60% advance against the PO, parked in the vendor ledger, settled at invoice booking. **Not required for matching** |
| 5 | Goods receipts and the term "GRN" | **The GRN lives inside MSD only.** The vendor's POD is a separate document and is not the GRN |
| 6 | Posting in Microsoft Dynamics | **Not covered on the call — still open** |

**Two further rules confirmed, which we had not asked:**

- **The PO is the cap, not a match leg.** The match is **GRN ↔ invoice ↔ audit report**. The PO
  sets the maximum quantity and the fixed rate; a GRN can be lower than the PO but never higher.
- **One PO may carry several invoices. One invoice may never span two POs** — Bata has
  prohibited that explicitly.

---

## 1. Approval limits and acceptable variance

**Question.** What is the approval matrix for a billing variance — the rupee or percentage
bands, and who signs at each band? Is the band applied per line item, or per invoice?

> **Bata response (16 Nov 2026).** The comparison is **invoice value against GRN value**.
> If the invoice exceeds the GRN by **less than ₹100, it is booked automatically**. Above
> ₹100 it goes for exceptional approval by the **costing team**. There is no percentage
> band — asked directly about a percentage, Harminder's answer was "₹100, whichever is
> lower". The threshold is absolute.
>
> In the additional-line-items scenario this exception is expected and routine: the invoice
> is booked at its full value while the GRN is lower, so it breaches ₹100 by design. The
> costing team approves it once the offsetting credit note is shown.

**What this changes in the build.** One absolute threshold replaces the tolerance matrix we
had planned, which is considerably simpler. The rule is: `invoice_total − grn_total > 100`
→ exception, route to costing team; otherwise pass.

**Confirmed 18 November 2026: the ₹100 threshold is per invoice, not per line.** Built and
tested that way (`RuleConfig.variance_scope = "invoice"`).

**Confirmed 19 November 2026: an invoice *below* the GRN value also raises an exception.**
The threshold is therefore symmetric — a difference of more than ₹100 in either direction
needs a person. Over-billing routes to the costing team as money at risk; under-billing is
flagged as a GRN or vendor-billing problem, since more was received than is being charged
for.

---

## 2. Additional work not covered by the purchase order

**Question.** Where a vendor bills work that is not on the purchase order, is a written
approval on email sufficient for payment, or is a PO amendment mandatory?

> **Bata response (16 Nov 2026).** **A PO cannot be amended once it is approved.** Email
> approval does not make an out-of-PO line payable on that PO.
>
> The correct process is: book the invoice at its **full value**; obtain a **credit note
> from the vendor** for the line items in excess of the PO; book the credit note against
> that invoice so the invoice is settled; then raise a **new PO** for the balance line
> items, against which the vendor issues a **new invoice**.
>
> Processing one invoice against two POs is **prohibited**, and vendors have been told so.
>
> Worked example given on the call: scaffolding of about ₹11,800 was billed although the PO
> excluded it. A credit note for ₹11,800 is booked against the invoice; the remainder is
> paid; the scaffolding, if payable at all, goes through a fresh PO and invoice.

**What this changes in the build.** Larger than it looks:

- `PO_AMENDMENT` is **not a real document for Bata**. An amendment arrives as a *new PO*.
- `CREDIT_NOTE` moves from "later" into v1 — it is the standard resolution path, not an
  edge case.
- An out-of-PO line is an exception whose prescribed action is **"obtain a credit note from
  the vendor"**, and the exception stays open until the credit note arrives. This is a
  concrete workflow, not just a flag.
- An email approval is still worth capturing as evidence, but it no longer authorises
  payment on the original PO. We will keep it as context on the exception, not as a
  condition that clears it.

---

## 3. Authority of the audit quantity

**Question.** When the auditor's verified quantity is lower than the vendor's claim, is the
audit quantity final?

> **Bata response (16 Nov 2026).** **Yes — final.** "Whatever quantity the auditor
> certifies, that is final for us, and with that quantity only the GRN is created." The
> vendor's claimed quantity does not prevail.
>
> The PO remains the maximum. A GRN may be **lower** than the PO quantity; it can never
> exceed it.
>
> Worked example given on the call: an acoustic insulation line ordered at 10 sqm, claimed
> at 10, measured by audit at 11.1. The vendor may **not** bill 11.1 against that PO; the
> excess 1.1 requires a separate invoice against a new PO.

**What this changes in the build.** The payable quantity is the **audit-certified
quantity, capped at the PO quantity**. No override facility is required, which removes a
screen and an approval path we had assumed. Excess over the PO is never payable on that PO
— it is a new-PO case, which is the same workflow as Q2.

---

## 4. Advances, retention and part-billing

**Question.** Is the advance ledger maintained in Dynamics and readable per PO? Can one PO
be billed across several invoices? Is retention or LD applied at invoice stage?

> **Bata response (16 Nov 2026).** For store renovation and new-store CAPEX there is an
> advance in essentially every case: **60% of the total PO value**, paid against the PO
> number and **parked in the vendor ledger**. When the invoice is booked it is settled
> against that advance and the balance is released to the vendor.
>
> Asked where we could read the advance ledger, Harminder's response was that **matching
> does not require it** — the advance is a payment matter, not a matching input. Onsumm
> confirmed on the call that the payment side is out of scope for now.
>
> **One PO can carry multiple invoices. One invoice cannot carry multiple POs.**

**What this changes in the build.** The advance, retention and LD fields come **out of v1**.
The payable waterfall no longer needs an `advance_ledger` input, which removes the two
pending inputs the design was carrying. Cumulative billing against a PO cap is still
required, because one PO may be billed several times.

---

## 5. Goods receipts and the term "GRN"

**Question.** Does "GRN" mean the signed carrier delivery proof, or a separate inward entry
in Dynamics?

> **Bata response (16 Nov 2026).** The GRN is **an entry inside MSD (Microsoft Dynamics)**.
> No GRN copy is issued, and the vendor never provides one. The document we had been shown
> and treating as a GRN — the Bosch delivery paper — is a **POD provided by the vendor, a
> separate document**.
>
> A GRN can only be created against a PO, which is why the PO quantity can never be
> exceeded at receipt.
>
> Harminder will share **Excel extracts of GRN line items for two or three samples** so we
> can demonstrate the four-way match without MSD access.

**What this changes in the build.** This is the single biggest change:

- The receipt leg for Bata is the **GRN**, not the physical verification report. The audit
  report is the **upstream authority** that determines the GRN quantity; the GRN is the
  system-of-record receipt that the invoice is matched against.
- The GRN arrives as a **structured MSD extract, not a scanned document**. No OCR, no
  parser — a direct ingest. That is cheaper and more reliable than everything else in the
  pipeline.
- The POD remains useful as delivery evidence for goods, but it is **not** the receipt leg
  and must not be treated as one.
- GRN support moves from "not in v1" to **core v1 scope**.

---

## 6. Posting in Microsoft Dynamics — **OPEN**

**Question.** Once an invoice is approved, should the system post the voucher to Dynamics
directly, or hand the approved invoice to the Bata finance team to post? If direct, we need
API access and confirmation that Dynamics rejects a duplicate submission of the same
invoice.

> **Bata response.** Not covered on the 16 Nov call.

**Why it still matters.** It defines where our responsibility ends and is what guarantees no
invoice is posted twice on a retry. It also determines whether we need MSD write access or
only read access for the GRN extract.

---

## One operational point — **OPEN**

Please confirm the mailbox to which vendors and auditors send purchase orders, audit
reports, delivery proofs and invoices, and the typical senders.

> **Bata response.** Not covered on the 16 Nov call.

---

## Action items from the 16 November call

| Owner | Item |
|---|---|
| Harminder Singh (Bata) | Share Excel extracts of **GRN line items** for 2–3 samples |
| Harminder Singh (Bata) | Share a **sample credit note** linked to its invoice |
| Harminder Singh (Bata) | Check with the team on **AR open transactions** / receivable invoices for receipt matching |
| Vibhanshu Ahluwalia (Onsumm) | Send the invoice showing the **additional line items**, so the matching credit note can be arranged |
| Onsumm | Reconfigure to **GRN ↔ invoice ↔ audit report** with the PO as cap, and the ₹100 threshold |

---

## What we still need, in one line

Dynamics posting ownership, the document mailbox, the GRN Excel samples, one credit note
sample, and confirmation that the ₹100 threshold is per invoice rather than per line.
