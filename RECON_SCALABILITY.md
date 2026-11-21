# Why one JSONB row per document scales to the next client

**Status:** 2026-11-14 · companion to `RECON_VOCABULARY.md` (the dictionary) and `RECON_SCHEMA_V1.md` (the storage)

> ⚠ **Historical, as of 18 November 2026.** This page argues for the single-JSONB-row shape,
> which was tested as **Plan B in the architecture bake-off and lost** (48.4 vs 89.2 for the
> hybrid), on decision durability and operational risk rather than on storage. The storage
> arithmetic below is correct but was found immaterial at Bata's volume. Build from
> `RECON_IMPLEMENTATION_PLAN.md`. Keep this page for the vocabulary-carries-the-variation
> argument in §3 and the leg argument in §6, which the hybrid design retains.

Bata is client one. The design question is what client two costs. This page argues that the cost is **a mapping, not a migration** — and names the two cases where that is not true.

---

## 1. The approach in one paragraph

The parser's job ends at classification: it decides the `doc_role`, then dumps what it read as **key–value pairs** — a `header` object and a `lines` array whose entries carry their own `quantities` — into **one JSONB row per document** in `recon_extractions`. Nothing about a document's shape is encoded in columns. Columns exist only so the linker can *find* the row (`doc_number`, `po_number_ref`, `site_code`, `invoice_refs`, the money totals). The meaning of every key and code comes from the vocabulary, enforced in the database. Matching happens later, in the graph, built from these rows.

---

## 2. What a new client actually costs

| What the new client brings | Where it lands | Migration? |
|---|---|---|
| Their own column headings ("Measured Qty", "Qty passed") | `vocab_aliases` row, scoped to their `tenant_id` | **No** — a data insert |
| A field we have never extracted (e.g. `bin_location`) | a new key in `header` or `lines[]` | **No** — JSONB takes it |
| A document type we have never seen (GRN instead of PV) | existing `doc_role` + a new extractor | **No** — the RECEIPT leg is a slot, not a table |
| A concept with no code yet (`QTY_CERTIFIED` going live) | `vocab_codes` row, append-only | **No** — reseed, no DDL |
| A different ERP (SAP instead of Dynamics) | posting adapter | **No** — nothing in storage changes |
| A **new link key** — they join on something we don't index | a column on `recon_extractions` | **Yes**, one `ALTER TABLE` |
| A reader that must filter lines in SQL, not the graph | `lines` becomes a table again | **Yes**, and §5.4 of the schema is the test |

Six of eight are configuration. That ratio is the whole argument.

---

## 3. Why the vocabulary carries the variation, not the schema

`vocab_aliases` is scoped by `(tenant_id, supplier_id, context_doc_role)`. So:

- Bata's auditor writes **"Given/ Vendor Qty (B)"** → `QTY_CLAIMED`
- The next client's auditor writes **"Contractor Claim"** → `QTY_CLAIMED`
- Both reach the identical rule, which only knows `QTY_CLAIMED`

The rules never learn a client's wording. **Onboarding is translation, and translation is rows.** Every human correction in the Review Hub writes a `source='HUMAN'` alias, so each client makes the next one cheaper: the global alias set grows while the per-client set shrinks.

The ambiguity register (V§18) is what makes this safe to share. A bare `QTY` means ordered in a PV sheet and invoiced on an invoice, so the alias is resolved by `context_doc_role` rather than globally — one client's shorthand cannot silently repoint another's.

---

## 4. Why one row per document is the right grain

A parser output is a document. So one row is **one unit of everything**:

| Operation | Rev 1 (3 tables) | Rev 2 (1 table) |
|---|---|---|
| Extract | insert across 3 tables in one transaction | 1 insert |
| Re-extract after a parser fix | delete-cascade `n+m` rows, re-insert | supersede 1 row, insert 1 |
| Replay a verdict | reassemble from 3 tables | read 1 row |
| Hand a document to the graph loader | 3 queries | 1 query |

No cascade, no cross-table transaction, no partial extraction visible to a reader. That is what makes it safe to onboard several tenants in parallel on the same table: the unit of concurrency is a row, and rows don't interfere.

---

## 5. The memory arithmetic

Take one real document shape: a PV report with 60 lines, each carrying ordered / claimed / verified quantities, some also mounted / unmounted / damaged — call it 3 quantities per line.

|  | Rev 1 | Rev 2 |
|---|---|---|
| Heap rows | 1 + 60 + 180 = **241** | **1** |
| Index tuples (per the DDL's indexes) | 6 + 300 + 180 = **486** | **6** |
| Fixed per-row overhead (23-byte header → 24 aligned, + 4-byte line pointer) | 241 × 28 = **6.6 KB** | **28 B** |

At 10,000 documents that is **64 MB of pure tuple overhead** before a single extracted value is stored, plus the index trees over it. Rev 2 pays 273 KB.

Two further effects compound it:

- **Compression applies.** A `lines` array past ~2 KB goes to TOAST and is compressed as one object. The equivalent 240 narrow rows cannot compress across rows, and each repeats `tenant_id`, `document_id` and its codes.
- **The graph stays small by construction.** It holds work in progress, not history: once every invoice under an audit report is reconciled and posted, the transactional cluster is pruned and the hub keeps the settled position. Graph growth tracks **decisions made**, not documents ever processed — while `recon_extractions` keeps the full history cheaply, and can rebuild the graph at any time.

---

## 6. The same engine, a different receipt document

`recon_leg` (V§1) is why one template serves clients whose paperwork differs. The engine compares **legs**, and a template declares which document fills each one:

```
COMMITMENT   PO, work order, rate contract, BOQ
RECEIPT      PV report  │  POD  │  GRN  │  SES  │  measurement book
QUALITY      inspection report, test certificate, commissioning certificate
BILLING      tax invoice, proforma, credit note
```

"PO vs PV vs invoice" (Bata fit-out) and "PO vs POD vs invoice" (Bata goods) are **already the same engine with a different document in the receipt slot**. A client who runs GRNs is the third instance of a path that is exercised twice on day one — not a new branch.

The guard that keeps this honest is `receipt_granularity`. A POD proves `PACKAGE`, never `ITEM_QTY`, so the rules will not use it as item-level evidence and will not fail an invoice because a POD has no line items. Granularity travels with the document, so adding a weaker receipt type cannot quietly weaken an existing check.

---

## 7. What this does *not* buy, stated plainly

1. **No SQL filtering on line attributes.** "Every line above ₹1L across all vendors" is `jsonb_array_elements`, not a `WHERE` clause, and the planner has no per-key statistics inside `lines` so it cannot estimate selectivity. Accepted, because the readers that would want this are in the graph. If an analytics reader appears, the answer is a materialised view, not reverting the table.
2. **Codes rest on a trigger, not a foreign key.** The trigger (§3.3) validates every code in `lines` against `vocab_codes` and is stricter than rev 1 — it rejects deprecated codes too. But it is one function, so it is a thing to keep fast and to keep tested.
3. **Deprecating a code is now a breaking change.** Because the trigger rejects deprecated codes, removing one must ship together with the extractor that stops emitting it.
4. **A genuinely new link key is still DDL.** One `ALTER TABLE ADD COLUMN` with a default of null is cheap on Postgres 18, but it is a migration and should be counted as one.

---

## 8. The onboarding checklist this produces

For client two, in order:

1. Collect five real documents per `doc_role` they use.
2. Add their column headings to `vocab_aliases`, scoped to their tenant. **No code.**
3. Add any genuinely new concept to `RECON_VOCABULARY.md`, reseed `vocab_codes`. **No DDL.**
4. Point an existing extractor at their layout, or write one if the layout is structurally new. It writes one row.
5. Declare their template: which `doc_role` fills which leg, and the `receipt_granularity` each proves.
6. Set their tolerance bands and approval routes in settings; the rule compiler emits a new signed version.
7. Run in `--dry-run`, then on the mirror, then live.

Steps 2, 3, 5 and 6 are data. Step 4 is the only code, and only when a layout is new rather than merely differently worded.

---

## 9. The claim, and its limit

**Claim:** the marginal client costs a mapping, because the shape of their documents lives in JSONB, the words they use live in the vocabulary, and the documents they happen to own are a leg assignment.

**Limit:** this holds while reconciliation reads the graph. The moment a required reader needs to filter or join line attributes in SQL, the one-table shape stops paying and §5.4 of the schema is the test for reverting it. That test exists so the decision is made on evidence rather than preference.

**Not yet measured.** Every figure above is arithmetic from the DDL, not a benchmark. The honest next step is to extract the five Bata documents into both shapes and compare real `pg_total_relation_size`, insert latency and trigger cost before this is quoted to a client.

---

## 10. Worked examples — the same row, five document types

This is the argument above, shown rather than asserted. Every example below is **one row of
`recon_extractions`**. The columns never change; only the key–value payload does. Scenario:
Bata store 8255, PO `4500087255` on Universal Refrigeration, verified by a CA firm, billed
as `UR/26-27/0417`, delivered on a Safexpress waybill.

### 10.1 The part that is identical for every document

```
tenant_id · channel · content_sha256 · doc_role · doc_number · doc_date
supplier_gstin · site_code · po_number_ref · invoice_refs[] · total_amount
header(jsonb) · lines(jsonb) · vocab_version · extractor · status
```

Eleven link/provenance columns plus two JSONB columns. A PO, an audit report, an invoice and
a carrier's POD all land in exactly this. **No new client adds a column to this list** unless
they join on a key we have never indexed (§2, row 6).

> Every code in the examples below is a code `RECON_VOCABULARY.md` already defines, with one
> exception: the `date_role` values (`ISSUE_DATE`, `AUDIT_DATE`, `RECEIVED_DATE` …) are used by
> §5.2 of the schema but are not yet enumerated as a vocab kind. That kind needs adding before
> the seeder runs — a vocabulary gap, not a schema one, which is the point.

### 10.2 `PURCHASE_ORDER` — commitment

```json
{ "doc_role": "PURCHASE_ORDER", "doc_number": "4500087255", "doc_date": "2026-07-14",
  "site_code": "8255", "po_number_ref": "4500087255", "total_amount": 722561.20,
  "header": { "date_role": "ISSUE_DATE", "pr_number": "PPR000037245", "vendor_code": "V0102887",
              "payment_terms_raw": "60%Advance_40%_IMM", "price_basis": "FIRM",
              "inspection_window_days": 15, "partial_delivery_policy": "WITH_WRITTEN_CONSENT",
              "ld_penalty": [{"from_day":1,"to_day":7,"pct":10,"base":"PO_VALUE"}] },
  "lines": [
    { "line_seq": 1, "line_origin": "CONTRACT_LINE", "work_package": "HVAC_LOW_SIDE",
      "line_nature": "SUPPLY_AND_INSTALL", "description_raw": "Ductable AHU 8.5 TR with ODU and grill",
      "uom_raw": "Nos", "uom": "EA", "uom_family": "COUNT",
      "rate": 148000.0, "rate_role": "RATE_PO", "pricing_basis": "UNIT_RATE", "amount": 296000.0,
      "item_spec": { "capacity": {"value": 8.5, "unit": "TR"}, "includes": ["ODU","grill"] },
      "quantities": [ { "qty_role": "QTY_ORDERED", "value": 2, "uom": "EA",
                        "measure_basis": "ITEM", "evidence_layer": "TYPED_ANNEXURE" } ] } ],
  "extractor": "po_v1" }
```

### 10.3 `PHYSICAL_VERIFICATION_REPORT` — receipt, three quantities on one line

```json
{ "doc_role": "PHYSICAL_VERIFICATION_REPORT", "doc_number": "JPC/BATA/8255/PV-112",
  "doc_date": "2026-09-18", "site_code": "8255", "po_number_ref": "4500087255",
  "total_amount": null, "role_alias_raw": "Audit Report",
  "header": { "date_role": "AUDIT_DATE", "pv_format": "AUDITOR_ANNEXURE",
              "auditor_name": "J P C & Associates", "auditor_frn": "012345N",
              "quantity_legend": {"A":"QTY_ORDERED","B":"QTY_CLAIMED","C":"QTY_VERIFIED"},
              "assurance_level_stated": "NO_ASSURANCE",
              "site": {"core_selling_area_sqft": 1703, "distance_km": 352} },
  "lines": [
    { "line_seq": 2, "line_no_raw": "20", "line_origin": "CONTRACT_LINE",
      "work_package": "HVAC_LOW_SIDE", "description_raw": "Insulated refrigerant piping 25 mm",
      "uom": "RFT", "uom_family": "LENGTH",
      "verification": { "status": "VERIFIED", "measurement_technique": "LENGTH_MEASURED",
                        "visibility": "PARTIALLY_CONCEALED", "basis_source": "AUDITOR_INDEPENDENT" },
      "quantities": [
        { "qty_role": "QTY_ORDERED",  "value": 460,   "uom": "RFT", "evidence_layer": "TYPED_ANNEXURE" },
        { "qty_role": "QTY_CLAIMED",  "value": 452,   "uom": "RFT", "evidence_layer": "TYPED_ANNEXURE" },
        { "qty_role": "QTY_VERIFIED", "value": 441.9, "uom": "RFT", "evidence_layer": "TYPED_ANNEXURE",
          "value_raw": "[420] 441.9",
          "value_history": [{"was":420,"now":441.9,"kind":"HANDWRITTEN_CORRECTION"}],
          "measurement_working": {"expression_raw":"23+13+10+395.9","parsed_value":441.9,"unit":"RFT"} } ] } ],
  "assurance_exclusions": ["QUALITY_NOT_VERIFIED","CONCEALED_WORK_NOT_VERIFIED"],
  "extractor": "pv_jpc_v1" }
```

The auditor's **A/B/C column letters** resolve through `header.quantity_legend` and never reach
a rule. The 10.1 RFT short is derived, not stored (V§19).

### 10.4 `TAX_INVOICE` — billing

```json
{ "doc_role": "TAX_INVOICE", "doc_subrole": "MAIN_BILL", "doc_number": "UR/26-27/0417",
  "doc_date": "2026-09-22", "site_code": "8255", "po_number_ref": "4500087255",
  "taxable_amount": 634890.50, "tax_amount": 114280.29, "total_amount": 749170.79,
  "header": { "date_role": "INVOICE_DATE", "is_e_invoice": true, "irn": "a1f3…9c",
              "ack_no": "112618043712345", "place_of_supply": "27", "supply_type": "INTER_STATE",
              "tax_components": [{"component":"IGST","rate":18,"amount":114280.29}],
              "billing_basis": "AUDIT_QTY", "round_off": 0.21, "reverse_charge": false },
  "lines": [
    { "line_seq": 2, "line_origin": "CONTRACT_LINE", "work_package": "HVAC_LOW_SIDE",
      "description_raw": "Insulated refrigerant piping 25 mm", "hsn_sac": "7411",
      "uom": "RFT", "uom_family": "LENGTH",
      "rate": 620.0, "rate_role": "RATE_INVOICED", "pricing_basis": "UNIT_RATE",
      "amount": 273978.0, "tax_rate_pct": 18.0,
      "quantities": [ { "qty_role": "QTY_INVOICED", "value": 441.9, "uom": "RFT",
                        "measure_basis": "ITEM", "evidence_layer": "TYPED_ANNEXURE" } ] } ],
  "stg_bill_id": "…", "invoice_id": "…", "extractor": "invoice_v2" }
```

Only this row sets `stg_bill_id` / `invoice_id` — the bridge to the existing bill path. Nothing
about that bridge is in the table's shape; it is two nullable columns.

### 10.5 `PROOF_OF_DELIVERY` — a receipt that proves packages, not items

```json
{ "doc_role": "PROOF_OF_DELIVERY", "doc_number": "266J/KMA/8115224", "doc_date": "2026-09-21",
  "site_code": "8255", "po_number_ref": null,
  "invoice_refs": ["UR/26-27/0417"], "total_amount": 675432.00, "role_alias_raw": "GRN",
  "header": { "date_role": "RECEIVED_DATE", "carrier": "Safexpress",
              "destination_branch": "GTY- Mysuru-11", "ship_date": "2026-09-16",
              "package_count": 18, "actual_weight_kg": 696, "eway_bill_no": "412182718839",
              "declared_invoice_value": 675432.00, "invoice_count": 1,
              "freight_payment_mode": "CREDIT_ACCOUNT", "receiver_name": "Store Manager",
              "received_date": "2026-09-21",
              "receiver_stamp_text": "#10 Temple Road, Vontikoppal" },
  "lines": [
    { "line_seq": 1, "line_origin": "CONTRACT_LINE", "description_raw": "Consignment, 18 packages",
      "uom": "PKG", "uom_family": "COUNT",
      "quantities": [ { "qty_role": "QTY_DELIVERED", "value": 18, "uom": "PKG",
                        "measure_basis": "PACKAGE", "evidence_layer": "TYPED_ANNEXURE" } ] } ],
  "extractor": "pod_v1" }
```

Three scalability points sit in this one row: `po_number_ref` is **null** and the link runs
through `invoice_refs[]` instead; the client's own word for the document (`"GRN"`) is kept in
`role_alias_raw` without changing `doc_role`; and `measure_basis: PACKAGE` is what stops a rule
using 18 packages as item-level evidence (§6).

### 10.6 Documents with no lines at all

```json
{ "doc_role": "APPROVAL_COMMUNICATION", "channel": "EMAIL_ATTACHMENT",
  "doc_date": "2026-09-10", "site_code": "8255", "po_number_ref": "4500087255",
  "header": { "communication_intent": "APPROVAL", "approver_name": "Gagan",
              "person_role": "CONSULTANT", "subject": "8255 AC LS additional core cutting",
              "quoted_text": "Approved, please proceed with the 4 cuts." },
  "lines": [], "extractor": "email_v1" }
```

`lines: []` is a legitimate row, and `line_count` is `0` by generation. An approval email, a
completion certificate and a commissioning certificate are all this shape. **No table was added
to hold evidence that has no line items** — which is exactly how the QUALITY leg will arrive
later without a migration.

### 10.7 Client two, in the same table

A client who issues GRNs instead of PV reports, calls the claimed column "Contractor Claim" and
adds a bin location we have never extracted:

```json
{ "doc_role": "GOODS_RECEIPT_NOTE", "doc_number": "GRN/2027/44812", "doc_date": "2027-02-03",
  "site_code": "DEL-WH-02", "po_number_ref": "PO-99120",
  "header": { "date_role": "RECEIPT_DATE", "receiver_name": "K. Menon",
              "bin_location": "A-14-03" },
  "lines": [
    { "line_seq": 1, "line_origin": "CONTRACT_LINE", "description_raw": "MS angle 50x50x5",
      "uom": "KG", "uom_family": "MASS",
      "quantities": [
        { "qty_role": "QTY_CLAIMED",  "value": 1200, "uom": "KG", "measure_basis": "ITEM",
          "evidence_layer": "TYPED_ANNEXURE" },
        { "qty_role": "QTY_RECEIVED", "value": 1188, "uom": "KG", "measure_basis": "ITEM",
          "evidence_layer": "TYPED_ANNEXURE" },
        { "qty_role": "QTY_REJECTED", "value": 12,   "uom": "KG", "measure_basis": "ITEM",
          "evidence_layer": "TYPED_ANNEXURE" } ] } ],
  "extractor": "grn_v1" }
```

What this cost: one `vocab_aliases` row (`"Contractor Claim"` → `QTY_CLAIMED`, scoped to their
tenant), one `bin_location` key that no DDL knows about, one template declaring
`GOODS_RECEIPT_NOTE` fills RECEIPT at `ITEM_QTY`, and one extractor. **Zero schema changes, and
the rules are the same rules** — they still only ever see `QTY_CLAIMED` and `QTY_RECEIVED`.

### 10.8 What the five rows have in common

| | PO | PV report | Invoice | POD | Approval | GRN (client 2) |
|---|---|---|---|---|---|---|
| Columns used | same | same | same | same | same | same |
| `header` keys | 14 | 9 | 12 | 13 | 5 | 3 |
| Lines | 3 | 60 | 14 | 1 synthetic | 0 | 1 |
| `qty_role`s present | 1 | 6 | 1 | 1 | — | 3 |
| New tables needed | — | — | — | — | — | **—** |

The header-key counts differ by a factor of four and the quantity roles by a factor of six.
Nothing in the storage notices. That is the whole claim of this document, in one table:
**the document's shape is data, not schema** — so onboarding is a mapping exercise, and the
only migration left is the one named in §2.
