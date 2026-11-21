# Cash Application — User Flows

Persona: **AR accountant** (daily), **finance controller** (approves write-offs,
settings, reversals). Screens live under the **Receivables** side of the sidebar switch.

---

## F0. Navigation — Payables ⇄ Receivables

```mermaid
flowchart LR
  S[Sidebar ledger switch] -->|Payables| P[Dashboard · Review · Bills · Upload Invoices · Vendors · Payment Hub · ...]
  S -->|Receivables| R[Cash Application · Invoices · Upload Invoices · Customers]
  R --> CA[/receivables/cash-application/]
  R --> IV[/receivables/invoices/]
  R --> UP[/receivables/upload/]
  R --> CU[/receivables/customers/]
```

The switch shows only when the tenant is licensed for `receivables`. The mode follows the
URL, so a shared link opens on the right side.

## F1. Upload sales invoices (reuses the payable Upload page)

```mermaid
flowchart TD
  A[Receivables → Upload Invoices] --> B[Drop PDFs / photos]
  B --> C[OCR with ledger=receivable<br/>buyer = customer, PO captured]
  C --> D{Is it an invoice?}
  D -- no --> D1[Skipped, shown as 'not an invoice']
  D -- yes --> E[Review screen: PDF + customer, GSTIN, invoice no., dates, PO, taxable, tax, total]
  E --> F{Customer exists?<br/>GSTIN, then name}
  F -- yes --> G[Linked]
  F -- no --> H[Created from the invoice]
  G --> I[Save → invoice open]
  H --> I
  I --> J[Agent re-tries this customer's unmatched payments]
  I --> K{More in queue?}
  K -- yes --> E
  K -- no --> L[Invoices list]
```

Duplicate invoice number for the same customer → save is refused with "already exists",
offering to open it.

## F2. Daily: import the bank statement

```mermaid
flowchart TD
  A[Cash Application → Import statement] --> B[Choose CSV/XLSX + bank account]
  B --> C[Parsed: credits only; UTR, rail, payer read from narration]
  C --> D[Dedupe on fingerprint / UTR]
  D --> E[Toast: 42 imported · 3 already imported · 2 set aside as not receipts]
  E --> F[Agent matches in background — list updates live]
  F --> G[Auto-applied tab: exact matches, nothing to do]
  F --> H[Needs review tab: suggestion + reasons]
  F --> I[Unmatched tab: no idea yet]
```

## F3. Review a suggestion (the core loop)

```mermaid
flowchart TD
  A[Needs review → open payment] --> B[Workbench:<br/>payment facts · customer · agent suggestion · clues · confidence · flags]
  B --> C{Agree?}
  C -- yes --> D[Accept] --> Z[Applied · alias + TDS habit learned]
  C -- partly --> E[Edit allocations:<br/>tick invoices, amounts, TDS, deduction + reason]
  E --> F{Allocated = payment?}
  F -- yes --> Z
  F -- less --> G[Apply; remainder stays on account] --> Z2[Partially applied]
  C -- try another --> H[Pick an alternative suggestion] --> B
  C -- wrong customer --> I[Change customer → re-match] --> B
  C -- can't decide --> J[Flag exception: dispute · duplicate · FX · ask customer] --> K[Exceptions tab, owner + age]
```

## F4. Add remittance advice

```mermaid
flowchart TD
  A[Add remittance] --> B{Paste email text or upload PDF/image}
  B --> C[Read: payer, reference/UTR, date, total, lines]
  C --> D{Matching payment found?}
  D -- by UTR --> E[Linked]
  D -- by amount ±₹1 and date ±10d, unique --> E
  D -- no --> F[Kept as unlinked — auto-links when the payment is imported]
  E --> G[Agent re-matches that payment using the lines]
  G --> H{Exact?}
  H -- yes --> I[Auto-applied]
  H -- no --> J[Needs review with remittance shown beside it]
```

## F5. Record a payment by hand (cheque, cash, a credit not in a statement yet)

```mermaid
flowchart TD
  A[Record payment] --> B[Date · amount · method · reference · payer · optional customer]
  B --> C{Same UTR or same amount+payer+date exists?}
  C -- yes --> D[Warn: possible duplicate — create anyway / open existing]
  C -- no --> E[Created → agent matches]
```

## F6. Unapply / reverse

```mermaid
flowchart TD
  A[Applied payment → Unapply] --> B[Reason required]
  B --> C[Applications marked reversed; invoices reopened]
  C --> D[Payment → unmatched; re-match queued]
  A2[Statement shows CHQ RETURN / reversal] --> E[Agent flags the original payment: possible bounce]
  E --> F[Human confirms → payment reversed, invoices reopened, customer note]
```

## F7. Customers

```mermaid
flowchart LR
  A[Customers list:<br/>outstanding · overdue · unapplied credit · last payment] --> B[Customer detail]
  B --> C[Payer names (aliases): add / remove]
  B --> D[Usual TDS rate (learned, editable)]
  B --> E[Open invoices · payments · on-account credit]
```

## F8. Controller: settings and KPIs

```mermaid
flowchart LR
  A[Cash Application header KPIs] --> B[Match rate · exception rate · applied cash % · time to apply · unapplied aging · DSO]
  C[Settings] --> D[Auto-apply on/off · threshold · rupee tolerance]
  C --> E[Write-off tolerance (off by default)]
  C --> F[Trust learned TDS rate for auto-apply (off by default)]
```
