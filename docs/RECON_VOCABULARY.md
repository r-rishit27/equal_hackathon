# Reckon.ai Recon Vocabulary (v1)

**Status:** Adopted for Recon · v1 · 2026-11-16. Author: Vibhanshu (v1-draft, 2026-11-14); adopted into Recon with the corrections and additions logged in §19 and §21.
**This file is the single source of truth for codes.** Its machine form is `backend_ocr/app/recon/vocab.py` (seeded into `vocab_codes` / `vocab_aliases`); `tests/recon/test_vocab.py` fails if the two disagree. How Recon stores and uses each code: §21.

> ### Basic principle: the vocabulary is the dictionary; the schema is derived from it
> - **The vocabulary (this file) is a dictionary.** It defines every word Reckon.ai understands in reconciliation: what each code means, which raw labels and phrases map to it, and how ambiguous words are resolved. It holds no data.
> - **The schema is derived from the vocabulary.** Recon's tables carry generated code columns (`doc_role`, `recon_leg`, `verification_status`, `line_origin`, `uom`, …) with foreign keys into `vocab_codes` (§21). The vocabulary decides which values those columns may hold.
> - **Change flows one way: vocabulary first, then schema.** A new concept is added here first. In most cases nothing else changes, because it's just a new allowed value or JSON key. A column is added to the schema only when a rule must join, filter or calculate on that value, and it is still named and defined by the vocabulary.
> - **Nothing exists in the schema that isn't in the vocabulary.** No code, column or JSON key appears in the database without a vocabulary entry.

**Grounded in 5 real documents**
| Tag | Document |
|---|---|
| `BT-PO` | Bata PO `PPO00024046-1` → Anjle MEP (HVAC + fire), Thane store 8255 |
| `BT-PV` | J P Chawla & Co. LLP PV report, Bhumi World Thane 8255, 21-09-2026 (typed annexures + signed site sheets) |
| `BT-INV` | Anjle tax/e-invoice `AMP/26-27/070` + proforma ("as per Audit, Main bill") |
| `BM-PV` | Matolia Rai & Associates "Report of Site Visit & Physical Verification", PM Rao Road Mangalore 9621, 11-07-2026 (cover + disclaimers + witnessed vendor measurement sheets per PO family) |
| `POD` | Safexpress waybill/POD `1000 4128 4608` (Bosch Home Comfort → Bata Mysuru), signed and stamped by receiver on 21-09-2026 |
| `IND` | Industry and regulatory practice (SAP P2P, GST, Indian works contracts and logistics). Sources are listed in §20. |

**Entry format:** `CODE`: meaning · *aliases* · seen in · tier.
**Tiers** (from the architecture decision): **N** = used now by the Bata template; **X** = next, when a rule needs it; **L** = later, defined only.

---

## 0. Deduplication rules (how this vocabulary stays clean)

1. **One concept, one code.** Synonyms are **aliases** of a code, never new codes.
2. **Orthogonal facets, not combined codes.** If a value mixes two ideas (e.g. "measured *on vendor's direction*"), split it into facets (`measurement_technique` + `basis_source`) instead of minting `AREA_MEASURED_VENDOR_DIRECTED`.
3. **Extract what a document states; derive comparisons.** "Short", "excess", "balance" are computed by the engine, so they are **not** extraction codes.
4. **Context-dependent labels live in the Ambiguity Register (§18).** The bare label `QTY` means ordered in one document and invoiced in another, so it is resolved by `doc_role` + sibling columns, never by a global alias.
5. **A physical paper can change role.** A Lorry Receipt becomes a POD once the receiver signs it. Role is decided by **evidence present**, not by the title.
6. **Append-only after v1 freeze.** Before freeze (now), merges and renames are allowed and logged in §19.

---

## 1. Recon legs and evidence slots (the core idea)

Every reconciliation compares **legs**. A template declares which leg each document fills, so "PO vs PV vs invoice" and "PO vs POD vs invoice" are the same engine with a different document in the **receipt slot**.

| `recon_leg` | Question it answers | Documents that can fill it (§2) |
|---|---|---|
| `COMMITMENT` | What did we agree to buy, at what rate? | PURCHASE_ORDER, WORK_ORDER, RATE_CONTRACT, BOQ, PO_AMENDMENT, QUOTATION (weak) |
| `DISPATCH` | What does the supplier say they sent? | DELIVERY_CHALLAN, PACKING_LIST, ASN, LORRY_RECEIPT, EWAY_BILL |
| `RECEIPT` | What actually arrived or got built? | GOODS_RECEIPT_NOTE, PROOF_OF_DELIVERY, PHYSICAL_VERIFICATION_REPORT, SITE_VERIFICATION_SHEET, SERVICE_ENTRY_SHEET, MEASUREMENT_BOOK, INSTALLATION_REPORT, COMPLETION_CERTIFICATE |
| `QUALITY` | Was it acceptable? (the 4th way) | INSPECTION_REPORT, TEST_CERTIFICATE, COMMISSIONING_CERTIFICATE, HANDOVER_CERTIFICATE |
| `BILLING` | What is the vendor charging? | TAX_INVOICE, PROFORMA_INVOICE, CREDIT_NOTE, DEBIT_NOTE, BILL_OF_SUPPLY |
| `PAYMENT` | What did we pay? | PAYMENT_ADVICE, BANK_STATEMENT |

`match_type`: **N**
- `TWO_WAY`: COMMITMENT ↔ BILLING
- `THREE_WAY`: + RECEIPT
- `FOUR_WAY`: + QUALITY
- `ERS`: COMMITMENT + RECEIPT with no invoice (Evaluated Receipt Settlement; the buyer self-bills from the PO and the receipt) *(IND, SAP)*

`receipt_granularity` (how much a receipt document can prove): **N**
| Code | Meaning | Typical document |
|---|---|---|
| `ITEM_QTY` | Quantity per line item | GRN, PV report, site sheet, SES, MB |
| `PACKAGE` | Number of packages / boxes, weight | POD, LR (`Pkg/Act Wt 18/696`) |
| `CONSIGNMENT` | That a consignment for invoice(s) X arrived | POD with `Invoice List` |
| `VALUE` | Declared value only | POD `Total Inv. Value`, e-way bill |

> **Why this matters:** a POD can never confirm "60 metal shelves". It confirms "18 packages for invoice 266J/KMA/8115224 worth ₹6,75,432 reached Mysuru on 21-09-2026". The engine must not use a POD as item-level receipt, and must not fail an invoice merely because the POD has no line items.

---

## 2. `doc_role`

### 2.1 Commitment leg
| Code | Meaning | Aliases | Seen | Tier |
|---|---|---|---|---|
| `PURCHASE_REQUISITION` | Internal request to buy, before the PO | PR, indent, purchase requisition, PPR | BT-PO (`PPR000037245`) | X |
| `PURCHASE_ORDER` | Buyer's binding order for goods/services | PO, PPO, Buyer's Order, purchase order | BT-PO, BM-PV (PO families) | N |
| `WORK_ORDER` | Binding order for works/services | WO, LOA (letter of award), LOI (letter of intent; `commitment_strength=INTENT`) | IND | X |
| `PO_AMENDMENT` | Change to an existing commitment | PO revision, amendment, change order, variation order, deviation order, `-1` suffix | BT-PO (`-1`) | X |
| `RATE_CONTRACT` | Agreed rates without fixed qty | rate card, ARC, annual rate contract, price agreement, SOR (schedule of rates) | BT/BM (rates repeat across stores) | X |
| `BOQ` | Itemised quantity × rate estimate | bill of quantities, estimate, PPS sheet *(Bata; expansion unconfirmed)* | BT-PV ("Qty as per PO/PPS sheet") | X |
| `QUOTATION` | Vendor offer before commitment | quote, proposal, offer | IND | L |

### 2.2 Dispatch leg
| Code | Meaning | Aliases | Seen | Tier |
|---|---|---|---|---|
| `DELIVERY_CHALLAN` | Supplier's dispatch document (a GST-prescribed document when goods move without an invoice) | DC, challan, delivery note, dispatch note | IND | X |
| `PACKING_LIST` | Contents of each package | packing slip | IND | L |
| `ASN` | Advance shipping notice (electronic dispatch notice) | advance ship notice, dispatch advice | IND | L |
| `LORRY_RECEIPT` | Carrier's consignment note issued at booking | LR, consignment note, bilty, docket, waybill, CN, GR *(transport sense, see §18)*, AWB (air), BL (sea) | POD ("Waybill No.") | X |
| `EWAY_BILL` | GST movement document for goods above the threshold | e-way bill, EWB, "E- Waybill" | POD (`412182718839`) | X |

### 2.3 Receipt leg
| Code | Meaning | Aliases | Seen | Tier |
|---|---|---|---|---|
| `GOODS_RECEIPT_NOTE` | **Buyer's internal** record of what was received and counted | GRN, GR *(ERP sense)*, MRN (material receipt note), MIR, inward note, gate inward, receiving report, SAP MIGO GR | IND | X |
| `PROOF_OF_DELIVERY` | **Carrier/supplier** document **signed or stamped by the receiver** acknowledging delivery | POD, ePOD, signed LR/consignee copy, signed DC, delivery acknowledgment; *client usage sometimes calls this "GRN"* (§18) | POD | **N** |
| `PHYSICAL_VERIFICATION_REPORT` | Third-party (CA firm) report that executed work/assets exist, with measured quantities | PV report, site audit, site visit & physical verification, FA verification, audit report | BT-PV, BM-PV | N |
| `SITE_VERIFICATION_SHEET` | Signed field sheet with measurements, jointly signed | audit verification sheet, JMR (joint measurement record), witnessed measurement sheet | BT-PV (signed sheets), BM-PV ("signed in the capacity of witness") | N |
| `MEASUREMENT_SHEET` | **Vendor's** claimed measurements submitted for billing/audit | vendor measurement sheet, measurement statement, abstract of measurement | BT-PV ("B = measurement sheet/vendor invoice"), BM-PV ("Vendor Qty") | N |
| `MEASUREMENT_BOOK` | **Client engineer's** official record of measured work (certifies for payment) | MB, M-book | IND (CPWD) | L |
| `SERVICE_ENTRY_SHEET` | Buyer's acceptance of services performed | SES, service receipt, service acceptance | IND (SAP) | L |
| `INSTALLATION_REPORT` | Confirms equipment installed | installation certificate, I&C report | IND | L |
| `COMPLETION_CERTIFICATE` | Work completed | CC, work completion certificate | IND | X |

### 2.4 Quality leg
| Code | Meaning | Aliases | Seen | Tier |
|---|---|---|---|---|
| `INSPECTION_REPORT` | QC acceptance/rejection | QC report, inspection certificate, IR | IND; PO T&C "100% physical inspection" | L |
| `TEST_CERTIFICATE` | Manufacturer or lab test | MTC, test report, TC | IND | L |
| `COMMISSIONING_CERTIFICATE` | System tested and running; integration done | T&C certificate, commissioning report, integration certificate | BT-PV ("certificate needed" for FAS/panel programming) | X |
| `HANDOVER_CERTIFICATE` | Site handed over to client | handover note, snag-closure, punch-list closure | IND | L |
| `WARRANTY_CERTIFICATE` | Warranty proof | guarantee card | BT ("3 Year Warranty") | L |

### 2.5 Billing leg
| Code | Meaning | Aliases | Seen | Tier |
|---|---|---|---|---|
| `TAX_INVOICE` | GST tax invoice. **An e-invoice is a TAX_INVOICE with `is_e_invoice=true`** (IRN, Ack No., QR), not a separate role. | invoice, bill, tax invoice, e-invoice, GST invoice | BT-INV | N |
| `PROFORMA_INVOICE` | Pre-bill or workings; not a tax document | performa/proforma invoice, PI, bill workings, computation sheet | BT-INV (embedded) | N |
| `BILL_OF_SUPPLY` | Invoice for exempt goods or a composition dealer (no GST charged) | bill of supply | IND | L |
| `CREDIT_NOTE` | Reduces an invoice | CN | IND | X |
| `DEBIT_NOTE` | Increases an invoice, or buyer's claim on the supplier | DN | IND | X |
| `FREIGHT_INVOICE` | Carrier's bill for transport | freight bill, transport bill | POD ("Freight Amt.") | L |

### 2.6 Payment and supporting
| Code | Meaning | Aliases | Tier |
|---|---|---|---|
| `PAYMENT_ADVICE` | Remittance details | remittance advice, payment intimation, UTR advice | X |
| `BANK_STATEMENT` | Bank ledger | e-statement, account statement | X |
| `APPROVAL_COMMUNICATION` | Email/chat/letter/**internal approval memo** carrying a decision (Bata's "Memorandum" approval flow is one). Facet `communication_intent` = `APPROVAL`, `INSTRUCTION`, `SCOPE_EXCLUSION`, `CONFIRMATION`, `DISPUTE` | approval mail, instruction, "as per Bata instructions", "approval from mr gagan on mail", "MD sir instructions dated …" | N |
| `PHOTO_EVIDENCE` | Site or work photo | photograph, site photo, geo-tagged photo | X |
| `DRAWING` | Facet `drawing_type` = `LAYOUT`, `AS_BUILT`, `SLD` (single-line diagram), `LINE_DIAGRAM`, `SHOP_DRAWING` | dwg, drawing, SLD, line drawing | X |

`doc_subrole` (billing stage) **N**: `ADVANCE_INVOICE`, `RA_BILL` (+`ra_sequence`, running account bill), `MAIN_BILL`, `SUPPLEMENTARY_BILL` (extra/additional work), `FINAL_BILL`, `RETENTION_RELEASE`.

`copy_type` **X**: `ORIGINAL_FOR_RECIPIENT`, `DUPLICATE_FOR_TRANSPORTER`, `TRIPLICATE_FOR_SUPPLIER`, `ACCOUNTING_COPY` (BM-PV sheets), `CONSIGNOR_COPY`, `CONSIGNEE_COPY`, `DRIVER_COPY`, `OFFICE_COPY`. Used to detect **duplicate submissions** of the same document.

`pv_format` (shape of a PV report) **N**
| Code | Shape | Seen |
|---|---|---|
| `AUDITOR_ANNEXURE` | Auditor builds an A/B/C table (PO / vendor / verified), with printed variances and remarks, plus signed field sheets | BT-PV |
| `WITNESSED_VENDOR_SHEET` | The vendor's own measurement sheet, with "Vendor Qty / Audit Qty / Remarks" columns added, signed by the auditor "in the capacity of witness" | BM-PV |
| `SPREADSHEET_TABLE` | A report supplied as a spreadsheet; columns read from its headings (tier X) | Recon spreadsheet uploads |

---

## 3. Parties, people and sign-off

`party_role` (organisations) **N**
| Code | Meaning | Aliases | Seen |
|---|---|---|---|
| `BUYER` | Contracting buyer entity | company, client | all |
| `BILL_TO` | Invoice addressee | Buyer (Bill to) | BT-INV |
| `SHIP_TO` | Delivery/consignee location | Consignee (Ship to), consignee, delivery address | BT-INV, POD |
| `SUPPLIER` | Seller/contractor | vendor, MATERIAL Vendor, contractor, consignor *(when supplier ships itself)* | all |
| `CONSIGNOR` | Party handing goods to the carrier (usually = SUPPLIER; kept separate because a distributor can ship for the supplier) | consignor, shipper, sender | POD (Bosch Home Comfort) |
| `CARRIER` | Transporter | transporter, courier, logistics partner | POD (Safexpress) |
| `AUDITOR` | Third-party verifier | CA firm, chartered accountants, prepared by | BT-PV, BM-PV |
| `CONSULTANT` | Technical advisor whose formula/guidelines are applied | electrical consultant, PMC | BM-PV ("Shri Gagan Ji, electrical consultant") |
| `SITE` | Store / project location (an entity, §15) | store, shop, site | all |

`person_role` **X**: `STORE_MANAGER`, `PROJECT_MANAGER`, `REGIONAL_MANAGER` (RM), `VENDOR_REPRESENTATIVE`, `AUDIT_TEAM_MEMBER`, `CONSULTANT`, `PROCESS_OWNER` (e.g. "SIS/Projects team"), `RECEIVER` (person signing a POD), `AUTHORISED_SIGNATORY`, `APPROVER` (named in approval mails: "mr gagan", "Inderpreet sir", "MD sir").

`signoff_capacity` **N**: `PREPARER`, `VERIFIER`, `WITNESS` ("signed in the capacity of witness"), `RECEIVER`, `APPROVER`, `AUTHORISED_SIGNATORY`. Combined with `signature_present`, `seal_present`, `seal_text`, `digital_signature`.

`assurance_level_stated` (what the auditor says they guarantee) **N**: `NO_ASSURANCE` ("we do not express any assurance", BM-PV; "does not provide any formal assurance", BT-PV), `LIMITED`, `REASONABLE`.

---

## 4. Quantities

### 4.1 `qty_role` (extractable quantities only)
| Code | Meaning (who says so) | Aliases / column labels | Seen | Tier |
|---|---|---|---|---|
| `QTY_ORDERED` | Buyer committed (PO/BOQ/WO) | Qty as per PO (A), Qty as per PO/PPS sheet, PO Qty, `QTY` *(in a PV sheet next to Vendor/Audit Qty, §18)* | BT-PV, BM-PV, BT-PO | N |
| `QTY_CLAIMED` | Vendor claims executed/supplied | Given/ Vendor Qty (B), Qty as per measurement sheet/vendor invoice, **Vendor Qty** | BT-PV, BM-PV | N |
| `QTY_VERIFIED` | Independent verifier measured or counted | Verified Qty (C), Actual Measured Qty, Total Area, Total Measured Area, **Audit Qty**, Mounted…Total | BT-PV, BM-PV | N |
| `QTY_CERTIFIED` | Client authority approves for payment (engineer-in-charge, MB, PMC). *Distinct from VERIFIED: a different actor and a later stage.* | certified qty, passed qty, MB qty | IND | L |
| `QTY_MOUNTED` / `QTY_UNMOUNTED` / `QTY_DAMAGED` | Breakdown of a count at verification or receipt | Mounted [ ] Unmounted [ ] Damaged [ ]; defective | BT-PV | N |
| `QTY_DISPATCHED` | Supplier says shipped | DC qty, ASN qty, packing-list qty | IND | L |
| `QTY_DELIVERED` | Carrier delivered and receiver acknowledged (**usually PACKAGE basis**, §4.2) | Pkg (in `Pkg/Act Wt`), no. of packages, articles | POD (18) | N |
| `QTY_RECEIVED` | Buyer counted into stock or site | GRN qty, received qty, MIGO qty | IND | X |
| `QTY_ACCEPTED` / `QTY_REJECTED` | After inspection | accepted / rejected qty | IND | L |
| `QTY_INVOICED` | Billed in this invoice | Qty (invoice), Audit Qty-M (proforma, `billing_basis=AUDIT_QTY`) | BT-INV | N |
| `QTY_PREV_BILLED` / `QTY_CUM_BILLED` | RA billing history | previous bill qty, up-to-date qty | IND | X |
| `QTY_PAYABLE` | **Computed by policy**, never extracted | — | — | N |

**Derived, not roles (so no codes):** short = ordered − received; balance/open = ordered − cumulative billed; excess = verified − ordered; transit loss. The engine computes them.

### 4.2 `measure_basis` (what a quantity counts) **N**
`ITEM` (default), `PACKAGE` (boxes/cartons/bundles), `WEIGHT_ACTUAL` ("Act Wt"), `WEIGHT_CHARGED` (volumetric/charged weight), `VOLUME`, `VALUE` (declared ₹), `PERCENT_BASE` (the base amount a % line applies to).

### 4.3 Dimensions of a measurement (`measurement_working`)
Keep the expression verbatim plus the parsed result:
- `23'+13'+10'` → 46 ft
- `54 ft X 17ft =918` → 918 sqft (BM-PV)
- `6-41 x 38 x 21` → 6 packages of 41×38×21 (POD `DIM`)

Package dimension strings are `count-L x W x H` (unit implied cm/in, so the unit must be confirmed per carrier).

### 4.4 Evidence layer and value history *(added at adoption)*
`evidence_layer` **N**: which layer of a receipt document a quantity was read from. Two layers of the same report are kept apart, never merged.
| Code | Meaning | Seen |
|---|---|---|
| `TYPED_BODY` | Typed body of the document (the default) | POs, invoices, spreadsheets |
| `TYPED_ANNEXURE` | The auditor's typed annexure table (A/B/C) | BT-PV |
| `SIGNED_SITE_SHEET` | The signed field sheet (Mounted / Unmounted / Damaged / Total) | BT-PV |
| `WITNESSED_SHEET` | The vendor's sheet with handwritten Vendor / Audit Qty, witnessed by the auditor | BM-PV |

`value_change_kind` **N**: why a value has history (`value_history` = `[{field, was, now, kind, by?, at?}]`).
- `HANDWRITTEN_CORRECTION`: overwritten by hand on the page (`~~18~~ 15`, `[548] 602`).
- `REVIEWER_CORRECTION`: corrected by a reviewer in Reckon.ai; the machine reading is kept.

---

## 5. Rates, pricing and charges

`rate_role` **N**
| Code | Meaning | Aliases | Seen |
|---|---|---|---|
| `RATE_LIST` | Rate-card / list rate before negotiation | RATE, rate card rate, SOR rate | BM-PV ("RATE") |
| `RATE_NET` | After negotiated discount | **RATE AFTER 5%**, net rate, discounted rate | BM-PV |
| `RATE_PO` | Rate on the PO line | Unit Pr., Rate | BT-PO |
| `RATE_INVOICED` | Rate on the invoice line | Rate | BT-INV |

`discount_pct` is extracted where printed (BM-PV: 5%). Check: `RATE_NET ≈ RATE_LIST × (1 − discount_pct)`, rounded.

`pricing_basis` **N/X**
| Code | Meaning | Example | Seen |
|---|---|---|---|
| `UNIT_RATE` | qty × rate | most lines | all |
| `PERCENT_OF_BASE` | % of a stated base (another subtotal) | "Packing and forwarding Charges 3%", "Furniture Packing Charges Fixed 5%" | BM-PV, BT |
| `LUMPSUM` | One fixed amount | "Panel programming and integration with mall" | BT |
| `SLAB` | Price chosen by a range of a site attribute | "Furniture Fixing 1501–2000 sft" (selling area), "Furniture Fixing upto 1000 Sft" | BM-PV, BT |
| `DISTANCE_TIER` | Price by distance band | "Outstation Charges upto 500 KM" vs site `distance_km=352` | BM-PV |
| `ZONE` | Price by region | "Transportation with Loading Unloading — For South" | BM-PV |
| `THRESHOLD_ITEM` | Applies only above a measured threshold | "Cost of Angle Structure more than 25ft" (+ remark "Length is 52 ft") | BM-PV |

`line_origin` **N**
| Code | Meaning | Aliases | Seen |
|---|---|---|---|
| `CONTRACT_LINE` | On the commitment document | PO line, BOQ item, agreement item | all |
| `ADDITIONAL_WORK` | Not on the commitment; new work | Additional work, Add., **Not in PO/ Additional**, extra item, NT item (non-tendered), variation item | BT-PV, BM-PV |
| `SUBSTITUTE` | Replaces or modifies a commitment item | substituted item, in lieu of, alternate make | IND (CPWD) |
| `CHARGE` | Non-item cost (type in `charge_type`) | — | all |
| `ADJUSTMENT` | Discount, round-off, advance adjustment | Round Off, Less: Advance | BT-INV |

> Quantity beyond the PO on a **contract line** is a *deviation* (engine-computed), **not** `ADDITIONAL_WORK`.

`charge_type` (only when `line_origin=CHARGE`) **N**: `PACKING_FORWARDING` (P&F), `FREIGHT` (transport, cartage), `LOADING_UNLOADING`, `OUTSTATION` (outstation/travel allowance), `SCAFFOLDING`, `DEBRIS_DISPOSAL` (malba disposal, debris removal), `INSURANCE`, `MOBILISATION`, `HANDLING`.

`line_nature` **X**: `SUPPLY`, `SUPPLY_AND_INSTALL`, `INSTALL_ONLY` (fixing charges: "LED light fixing charges", "Board fitting of logo", "Furniture fixing"), `SERVICE` (programming, integration, commissioning), `CIVIL_WORK` (core cutting, dismantling).

---

## 6. Units of measure (`uom`)

`uom` **N** (each canonical unit belongs to one `uom_family`: `COUNT`, `AREA`, `LENGTH`, `MASS`, `LUMPSUM`, `PERCENT`, `DISTANCE`, `CAPACITY`)

| Canonical | Family | Aliases seen | Notes |
|---|---|---|---|
| `EA` | COUNT | Nos, No, NO, No., no, EACH, Pcs, Unit | |
| `SET` | COUNT | Set, "1set 2nos" | A set can contain n pieces; keep `pieces_per_set` (BM-PV: "Cash desk 1set 2nos") |
| `PKG` | COUNT | Pkg, packages, cartons, boxes | POD |
| `SQFT` | AREA | SF, sf, sft, SFT, Sft, SQFT, Sq ft | |
| `SQM` | AREA | SM, Sqmt, Sq mtrs., m² | 1 SQM = 10.7639 SQFT |
| `RFT` | LENGTH | Rft, rft, RFT, running ft, `'`, Fit (OCR of "Ft": "8 Fit") | |
| `RMT` | LENGTH | M, m, Rmt, RMT, rmt, mtr | 1 RMT = 3.28084 RFT |
| `KG` | MASS | kg, Act Wt | |
| `LS` | LUMPSUM | NA, Lot, Job, LS | |
| `PCT` | PERCENT | % | For `PERCENT_OF_BASE` lines |
| `KM` | DISTANCE | KM | Distance tiers only |
| `TR`, `KW`, `KVA`, `HP` | CAPACITY | TR, Ton | Attribute units, not billing units |

**Garbage units** (flag `UOM_UNPARSEABLE`, keep raw): "For Soutl" (truncated zone text in the unit column).

---

## 7. Trade / work package (`work_package`) and client PO families

`work_package` **X** (hierarchical; children roll up to the parent):
`CIVIL` › `FALSE_CEILING`, `PARTITION_PANELLING`, `FLOORING`, `PAINTING`, `FACADE`, `JOINERY`
`ELECTRICAL` › `LT_PANEL`, `WIRING_POINTS`, `CABLING`, `EARTHING`
`LIGHTING`
`SIGNAGE`
`HVAC` › `HVAC_HIGH_SIDE`, `HVAC_LOW_SIDE`, `AHU_DUCTING`
`FIRE` › `FIRE_SPRINKLER`, `FIRE_ALARM` (FAS)
`FURNITURE_FIXTURE` › `RACKING`
`IT_NETWORK`, `PLUMBING`, `SITE_SERVICES`

> **HVAC high side / low side.** In industry tenders, "high side" usually means central plant (chillers, cooling towers, pumps) and "low side" the distribution (AHU, ducting, piping, terminals). The usage is conventional, not standardised. **Bata's usage (BM-PV) is per PO:** `AC HS PO` = AC equipment supply (Blue Star cassette AC + ODU), `AC LS PO` = installation, stands, core cutting, refrigerant and drain piping, cabling. So the mapping is **per tenant** via `po_family_alias`, not global.

`po_family_alias` (tenant-scoped map from a PO/section title to `work_package`) **N**
| Raw title (seen) | → work_package |
|---|---|
| "FAMILY- INTERIOR + ELECTRICAL + RACKS PO" | `CIVIL` + `ELECTRICAL` + `RACKING` (multi) |
| "FURNITURE PO" | `FURNITURE_FIXTURE` |
| "SIGNAGE PO" / "Signage" | `SIGNAGE` |
| "AC HS PO" | `HVAC_HIGH_SIDE` |
| "AC LS PO" | `HVAC_LOW_SIDE` |
| "LIGHTS PO" / "LED Lights" | `LIGHTING` |
| "Civil and Electric PO GST" / "… Non GST" | `CIVIL` + `ELECTRICAL`; plus `po_tax_treatment` = `GST` / `NON_GST` |
| "AHU" (BT) | `HVAC` (AHU + ducting + fire in one PO; lines classified individually) |

`po_tax_treatment` **X**: `GST`, `NON_GST`. Bata splits one vendor's work into GST and Non-GST POs; check that the invoice tax matches the PO's treatment.

---

## 8. Item specification attributes (`item_spec`)

One registry. Each attribute has a type and units. Two attributes from the earlier draft were replaced to remove overlap (§19).

| Attribute | Type | Examples (seen) | Tier |
|---|---|---|---|
| `make[]` | list | Waves/Zeco, Siemens/Honeywell, Blue Star, Polycab/Finolex, "Make MS" ⚠ *(MS here = mild steel material, see §18)* | N |
| `model_code` | str | FX-01, FX-16, FN-01, "Type D" (LT panel) | X |
| `capacity` | quantity | 8.5 TR, 7 TR (observed), 4 TR (cassette AC), "Upto 8 TR" | **N** |
| `material` | enum+str | MDF, laminate, HPL, ACP, GI, MS (mild steel), CRC (cold-rolled sheet), SS, copper, aluminium, PVC, gypsum, ply 19mm, veneer | X |
| `finish_colour` | str | silver, grey powder coated, red, white body, high gloss | L |
| `dimensions` | {l,w,h,unit} | 34×12 in, 600×600 mm, 900×300×2400, 7'×3', 1200×450×100 mm | X |
| `height` / `length` | quantity | 8 ft height, 1200mm, 6.5 Fit, 30 inch ht (letter) | X |
| `thickness` | quantity | 10 mm, 6 mm, 12 mm MDF, 19 mm ply | X |
| `gauge` | int | 22, 24, 14 (rack angle), 20 (shelf), 8 SWG | X |
| `diameter` | quantity | 15 mm, 25 mm, 40 mm, 2 in | X |
| `conductor` | {cores, csa_sqmm, material, armoured} | 4×4 sq mm Cu armoured; 4×25 sq mm Al armoured | X |
| `electrical` | {current_a, poles, curve, voltage_v, power_w, power_kva} | 25 A TPN, 32 A DP, MCCB 100 A, SP MCB C-16, C-25 | X |
| `lighting` | {power_w, color_temp_k, fixture_type} | 30 W concealed zoom 3000K; 40 W track 3000K; 8 W 4000K globe | X |
| `language` | enum | `ENGLISH`, `REGIONAL` (signage remarks "Regional", "English") | L |
| `includes[]` / `excludes[]` | list | with LED / **without LED**, without footboard, ODU and grill | **N** (catches "Without LED") |
| `concealment` | enum | `ABOVE_CEILING`, `IN_WALL`, `VISIBLE` | X |
| `warranty_years` | int | 3 | L |
| `spec_fingerprint` | hash | normalised spec for matching | N |

---

## 9. Verification (what the auditor did and found)

Three orthogonal facets plus one outcome replace the earlier mixed `verification_method` list (§19).

`verification_status` (what the auditor **states** about the line) **N**
| Code | Meaning | Phrases | Seen |
|---|---|---|---|
| `VERIFIED` | A verified quantity is given (any value, compared later by the engine) | numeric C / Audit Qty | both |
| `NOT_EXECUTED` | Work not present | "The work is not done/performed.", Audit Qty 0 with Vendor Qty 0 | BT-PV, BM-PV |
| `NOT_IN_SCOPE` | Deliberately not verified (reason in `scope_exclusion_source`) | "Not covered in audit", "Out of Audit", **"As per Bata instructions not in scope"** | both |
| `NOT_VERIFIABLE` | Verifier could not check the line or an attribute | "Tonnage could not be checked" (attribute), concealed works "not verified" | BM-PV |
| `DEFECTIVE_EXCLUDED` | Present but defective, excluded | "Defective items are not considered in verified quantity" | BT-PV |
| `INSTALLED_THEN_REMOVED` | Supplied and installed, later removed on an instruction | "vendor had supplied and installed … later shifted/removed as per RM's instructions" | BM-PV |
| `PARTIALLY_INSTALLED` | Some units mounted, some not | "8/14" mounted | BT-PV |

`scope_exclusion_source` **N**: `AUDITOR_SCOPE` (auditor's own scope or limitation), `CLIENT_INSTRUCTION` ("as per Bata instructions"), `CERTIFICATE_PENDING` ("certificate needed. Out of audit"), `NOT_APPLICABLE` (charges).

`measurement_technique` **N**: `COUNT`, `AREA_MEASURED`, `LENGTH_MEASURED`, `VISUAL_CHECK`, `ESTIMATE`, `FORMULA` (consultant formula for additional points), `DOCUMENT_REVIEW`, `NONE`.

`visibility` **N**: `VISIBLE`, `CONCEALED` ("fitted under wall/false ceiling", "concealed in ceiling"), `PARTIALLY_CONCEALED` ("2 visible, 2 above ceiling").

`basis_source` (whose word the number rests on) **N**: `AUDITOR_INDEPENDENT`, `VENDOR_DIRECTED` ("on the directions of vendor"), `STORE_MANAGER_CONFIRMED` (verbal), `PROJECT_MANAGER_CONFIRMED`, `CONSULTANT_GUIDELINE` ("formulae/guidelines suggested by … electrical consultant"), `BEST_JUDGEMENT` ("best judgement basis considering the physical dimensions of the store"), `PHOTO`, `DRAWING`.

`spec_verification_status` (per attribute, e.g. capacity) **N**: `SPEC_CONFIRMED`, `SPEC_DEVIATION` ("7 TR AHU" against 8.5 TR; "Without LED"), `SPEC_NOT_VERIFIABLE` ("Tonnage could not be checked"), `SPEC_NOT_ASSESSED` (excluded by disclaimer: quality, thickness, brand).

`old_asset_check` **X**: `YES`, `NO`, `UNANSWERED` ("Is there any old item/asset? (YES/NO)"; BM-PV disclaimer on old MDF reuse).

**Derived `assurance_level`** (engine, not extracted): HIGH = COUNT/MEASURED + VISIBLE + AUDITOR_INDEPENDENT; MEDIUM = VENDOR_DIRECTED, or PARTIALLY_CONCEALED; LOW = CONCEALED + BEST_JUDGEMENT/STORE_MANAGER_CONFIRMED, or NOT_VERIFIABLE. This drives risk weighting and the routing of exceptions.

---

## 10. Report-level disclaimers (`assurance_exclusion`)

Extracted once per PV report, then **inherited** by every line in the affected `work_package` or matching lines. **X**
| Code | Meaning | Source text (paraphrased) | Seen |
|---|---|---|---|
| `QUALITY_NOT_VERIFIED` | Quality, workmanship, defects not assessed | "Invisible defects, quality … not verified"; "no opinion … regarding quality" | both |
| `MATERIAL_SPEC_NOT_VERIFIED` | Thickness, brand, grade not verified | "thickness, and brand of material (MDF, laminate, metal) not verified"; MDF disclaimer | BM-PV |
| `CONCEALED_WORK_NOT_VERIFIED` | Concealed civil, electrical, AC, AHU, fire not verified | standard disclaimer 2; electrical disclaimer | both |
| `DISMANTLING_NOT_VERIFIED` | Removal of old structures unverified without photos | disclaimer 3; civil disclaimer | BM-PV |
| `OLD_ASSET_REUSE_RISK` | Possible reuse of old MDF/channels/frames | civil and MDF disclaimers | BM-PV |
| `OLD_FRAMEWORK_REMOVAL_UNVERIFIED` | Signage old framework removal relies on verbal confirmation | signage disclaimer | BM-PV |
| `DUPLICATE_CLAIM_RISK` | Same work possibly claimed by the same or another vendor | disclaimer 5 | BM-PV |
| `BEST_JUDGEMENT_ALLOWANCE` | Allowances made on judgement or consultant guidelines | disclaimers 4, 3, 5 | BM-PV |
| `DRAWINGS_NOT_PROVIDED` | SLD, line diagrams or photos not shared | electrical and AC LS disclaimers | BM-PV |
| `NOT_ENGINEERING_CERTIFICATION` | Not a QS, structural or engineering certificate | disclaimer 3.2 | BT-PV |
| `TITLE_NOT_VERIFIED` | Ownership/title out of scope | disclaimer 3.2 | BT-PV |
| `CLIENT_DISCRETION_ALLOWANCE` | "Allowance … at the sole discretion of Bata" | civil and MDF disclaimers | BM-PV |

These do **not** change quantities. They lower `assurance_level` and can add `payable_condition`s (§11).

---

## 11. Payable conditions (`payable_condition`)

Gates that must be satisfied before the related amount is released. Extracted from PO line text, report text or disclaimers. **N/X**
| Code | Meaning | Phrases (seen) |
|---|---|---|
| `PHOTO_REQUIRED` | Photo evidence needed | "subject to availability of Photo", "PCC … Only after Photograph", "Photos … to be shared with Audit Team" (BM-PV, AC LS) |
| `CERTIFICATE_REQUIRED` | Commissioning or integration certificate needed | "certificate needed" |
| `EMAIL_APPROVAL_REQUIRED` | Named approver's written approval | "after approval from mr gagan on mail" |
| `DRAWING_REQUIRED` | SLD, line diagram or as-built drawing | "Electrical SLD and line diagrams have not been shared" |
| `CLIENT_TEAM_CONCURRENCE_REQUIRED` | Process owner must concur before processing | "vendor's bills must be processed only after obtaining concurrence of SIS/Projects team" |
| `SPEC_REFERENCE` | Must meet the referenced spec | "Please refer TnC & Specs", "as dwg", "as per mall requirement" |
| `MAKE_RESTRICTED` | Only approved makes | "Make A / B / C" |
| `CAP_LIMIT` | Quantity or size ceiling | "upto 1000 Sft", "Upto 8 TR", "Avg Max 8 Mtr len", "upto 500 KM" |
| `RECEIPT_REQUIRED_FOR_ITC` | GST input credit needs goods received (CGST s.16(2)(b)) | IND, satisfied by a GRN/POD on goods |

---

## 12. Tax, e-invoice, e-way bill and statutory

`tax_component` (reuses DB enum `tax_type`) **N**: `IGST`, `CGST`, `SGST`, `UTGST` (to add), `CESS`.
`supply_type` **N**: `INTER_STATE` / `INTRA_STATE` (and `NO_TAX` when no GST is charged), derived from supplier GSTIN state code vs place of supply (BT: 07→27 ⇒ IGST; BM: 29→29 ⇒ CGST+SGST; POD: 24→29, inter-state).
`code_type` **N**: `HSN` (goods) / `SAC` (services; starts with `99`).
`reverse_charge` **X**: bool ("Reverse Charge (Y/N)", "GST on Reverse Charge").
`tax_group` **X**: PO tax-code shorthand, e.g. `INEInput18` → {INPUT, 18%}.

e-invoice fields **X**: `irn`, `ack_no`, `ack_date`, `signed_qr`, `is_e_invoice`.
e-way bill fields **X**: `eway_bill_no` ("E- Waybill"), `eway_valid_upto`, `vehicle_no`. **Rule:** goods consignments above the state/central threshold need one (POD value ₹6,75,432 → required). Check `eway.invoice_ref = invoice_number`.
`tds_section` **X**: `194C` (contractor works, typical for fit-out), `194J` (professional/technical, e.g. consultants or audit fees), `194Q` (purchase of goods, threshold-based), `194I` (rent). Reuses `dim_tds_sections`.
Identity checks **N**: GSTIN format + checksum; GSTIN chars 3–12 = PAN; GSTIN chars 1–2 = state code.

---

## 13. Commercial terms (PO / contract)

`payment_trigger` **X**: `ADVANCE`, `ON_DELIVERY`, `ON_INSTALLATION`, `ON_AUDIT` (PV report), `ON_INVOICE_IMMEDIATE` ("IMM"), `NET_DAYS(n)`, `RETENTION_RELEASE`. Example: `60%Advance_40%_IMM`.
`advance_type` **X**: `MOBILISATION_ADVANCE`, `SECURED_ADVANCE` (against materials at site), `SUPPLY_ADVANCE` (PO % advance). It must be netted on billing ("Less: Advance").
`retention` **L**: `retention_pct`, `retention_release_trigger` (e.g. end of DLP).
`dlp` **L**: defect liability period (months), linked to retention and warranty.
`ld_penalty` **X**: tiers `{from_day, to_day, pct, base}` (BT-PO: 10% days 1–7, 20% days 8–14, then 10%/day), `deemed_termination_days` (21).
`price_basis` **X**: `FIRM` ("Prices … shall remain firm"), `VARIABLE` (PVC / escalation).
`inspection_window_days` **X**: 15 working days (BT-PO).
`partial_delivery_policy` **X**: `WITH_WRITTEN_CONSENT`, `ALLOWED`, `NOT_ALLOWED`.
`bank_guarantee` **L**: PBG (performance), ABG (advance).

---

## 14. Logistics (POD / LR / e-way)

Consignment fields **N**:
- `waybill_no` (aliases: Waybill No., LR No., docket no., CN no., AWB no., *GR no.*)
- `booking_branch`, `pickup_datetime`, `ship_date`, `destination_branch` ("GTY- Mysuru-11"; `GTY` prefix meaning unconfirmed)
- `invoice_refs[]` ("Invoice List")
- `declared_invoice_value` ("Total Inv. Value")
- `invoice_count` ("Total Nos Of Inv.")
- `package_count` / `actual_weight_kg` ("Pkg/Act Wt 18/696")
- `charged_weight_kg`, `package_dimensions[]` ("DIM")
- `receiver_name`, `received_date`, `receiver_stamp_text`

`freight_payment_mode` **X**
| Code | Meaning | Aliases |
|---|---|---|
| `PAID` | Consignor pays at booking | Paid, prepaid |
| `TO_PAY` | Consignee pays on delivery | To Pay, collect, freight collect |
| `CREDIT_ACCOUNT` | Billed later to a contract customer | Credit (seen in POD "Freight Amt. Credit"), TBB *(To Be Billed; practitioner usage, unverified)* |

`delivery_mode` **L**
| Code | Meaning | Aliases |
|---|---|---|
| `DOOR_DELIVERY` | Delivered to the consignee's door | door delivery |
| `GODOWN_DELIVERY` | Collected at the carrier's warehouse | godown delivery |
| `DOD` | Released only after payment by draft/cheque | Draft on Delivery |
| `COD` | Released only after cash payment | Cash on Delivery |
| `DACC` | Released only against presentation of a document copy | Delivery Against Consignee/Consignor Copy (*sources disagree on which copy*) |

POD checks (`recon_check_code`, §17a; tier X until the POD rules run) **N**:
- `POD_INVOICE_REF_MATCH`
- `POD_VALUE_MATCH`
- `POD_CONSIGNEE_MATCHES_SITE`
- `POD_SIGNED_AND_STAMPED`
- `POD_RECEIVER_STAMP_ADDRESS_MATCH`. The POD consignee is "#2951 Temple Road, Vontikoppal", but the receiver's stamp reads "#10 Temple Road, Vontikoppal" (Livin' Corner store), so this flags it.
- `POD_RECEIVED_DATE` (transit 16→21 Sep; must be ≤ invoice payment and ≥ ship date)
- `EWAY_PRESENT_IF_REQUIRED`
- `EWAY_INVOICE_LINK`

---

## 15. Site / store attributes (`SiteRef`)

| Attribute | Aliases | Seen | Use | Tier |
|---|---|---|---|---|
| `site_code` | Store No., Shop No., SN, store code | 8255 (BT), 9621 (BM) | **link key** | N |
| `site_name_aliases[]` | Store/Site name, Destination | "PM Rao Road Mangalore", "HP Bhumi World Thane" | link key | N |
| `brand` | HP (Hush Puppies), Bata, Livin' Corner | BT, POD stamp | | X |
| `concept` | Concept | "FSC Red 2 Silver", "Red Concept Furniture" | standard-design expectations | L |
| `core_selling_area_sqft` | Core selling Area, selling area | 1703 | **SLAB checks**; sanity cap for ceiling/painting area | X |
| `distance_km` | Distance | 352 | **DISTANCE_TIER checks** (outstation) | X |
| `project_manager`, `store_manager`, `regional_manager` | Project Manager, RM | Satish | routing | X |
| `unit_no`, `address`, `pincode`, `state_code` | Unit No., Shop Add | Unit 31; 575001 | supply-type, POD address check | N |

---

## 16. Extraction artifacts (`extraction_artifact`)

Flags the parser sets so the engine never trusts a corrupted value. **N**
| Code | Example (seen) | Handling |
|---|---|---|
| `SPREADSHEET_OVERFLOW` | `#####` in TOTAL/RATE columns (BM-PV) | Value is null; recompute qty × rate |
| `SPREADSHEET_FORMULA_ERROR` | `#NAME?` in "Amount in words" (BM-PV) | Ignore the field |
| `SCIENTIFIC_NOTATION` | Phone `9.84E+09` (BM-PV) | Precision lost; don't use as an identifier |
| `OCR_CHAR_CONFUSION` | GSTIN `…1ZO`/`…1Z0`; PAN `AABC81043Q` for `AABCB1043Q`; `29AABCB104301ZI` for `29AABCB1043Q1ZI` (Bata Karnataka; check digit verified); `984503B247` | Validate with the checksum or master; auto-correct only when exactly one candidate is valid |
| `TRUNCATED_VALUE` | `9AAACB4487D1ZC` (leading `2` lost); "…HAMPANAKATTE,MANG"; PO descriptions cut at ~60 chars | Complete from master/other docs; flag |
| `LABEL_VALUE_SHIFT` | Universal Refrigeration header: values shifted one row under the wrong labels (Address → name, Site name → phone) | Re-align by value type (GSTIN regex, phone, address) |
| `PRINTED_VARIANCE_WRONG` | Printed (C−A) ≠ recomputed | Trust the recomputed value |
| `HANDWRITTEN_CORRECTION` | `[548] 602`, `~~20~~ 41.9` | Keep `value_history` |
| `QTY_UNIT_INCOHERENT` | Unit `NA` with qty 700 (scaffolding) | Flag |
| `UOM_MIXED_IN_WORKING` | feet sum → "14m" | Flag |
| `TYPO_IN_LABEL` | "Outsatation Chagres", "Pipining", "Stainner", "Sienems", "SINGED IN THE CAPACITY" | Normalise via the alias dictionary |

---

## 17. Phrase → code dictionary (seed for the extractor and normaliser)

| Phrase (case-insensitive, fuzzy) | → field = code |
|---|---|
| "work is not done/performed" | verification_status = `NOT_EXECUTED` |
| "not covered in audit" / "out of audit" | verification_status = `NOT_IN_SCOPE`, scope_exclusion_source = `AUDITOR_SCOPE` |
| "as per Bata instructions not in scope" | `NOT_IN_SCOPE` + `CLIENT_INSTRUCTION` |
| "certificate needed" | `NOT_IN_SCOPE` + `CERTIFICATE_PENDING`; condition `CERTIFICATE_REQUIRED` |
| "could not be checked" (+ attribute word, e.g. tonnage) | spec_verification_status = `SPEC_NOT_VERIFIABLE` on that attribute |
| "without <component>" | item_spec.excludes += component; possible `SPEC_DEVIATION` vs PO |
| "removed/shifted as per <role>'s instructions" | `INSTALLED_THEN_REMOVED`; basis_source = `STORE_MANAGER_CONFIRMED` |
| "defective … not considered" | `DEFECTIVE_EXCLUDED` |
| "measurement of total area" | measurement_technique = `AREA_MEASURED` |
| "on the directions of vendor" / "vendor's direction" | basis_source = `VENDOR_DIRECTED` |
| "fitted under wall/false ceiling" / "concealed in ceiling" | visibility = `CONCEALED` |
| "on estimation" | measurement_technique = `ESTIMATE` |
| "above (the false) ceiling" | visibility = `PARTIALLY_CONCEALED`/`CONCEALED` |
| "best judgement basis" | basis_source = `BEST_JUDGEMENT` |
| "formulae/guidelines suggested by" | measurement_technique = `FORMULA`, basis_source = `CONSULTANT_GUIDELINE` |
| "subject to availability of photo" / "only after photograph" | condition `PHOTO_REQUIRED` |
| "after approval from … on mail" | condition `EMAIL_APPROVAL_REQUIRED` (+ approver) |
| "concurrence of … team" | condition `CLIENT_TEAM_CONCURRENCE_REQUIRED` |
| "upto N <unit>" / "avg max N" / "more than N ft" | `CAP_LIMIT` / `THRESHOLD_ITEM` |
| "Additional work" / "Add." / "Not in PO/ Additional" / "extra item" | line_origin = `ADDITIONAL_WORK` |
| "Packing and forwarding" / "P&F" | `CHARGE` + `PACKING_FORWARDING` |
| "Transportation" / "Freight" / "cartage" | `CHARGE` + `FREIGHT` |
| "Loading" / "Unloading" | `CHARGE` + `LOADING_UNLOADING` |
| "Outstation" | `CHARGE` + `OUTSTATION` (pricing `DISTANCE_TIER`) |
| "Malba" / "debris" | `CHARGE` + `DEBRIS_DISPOSAL` |
| "Scaffolding" | `CHARGE` + `SCAFFOLDING` |
| "RATE AFTER n%" | rate_role = `RATE_NET`, discount_pct = n |
| "n%" in the rate column of a charge line | pricing_basis = `PERCENT_OF_BASE` |
| "Main Bill" / "Supplementary" / "RA Bill n" / "Final Bill" | doc_subrole |
| "as per Audit" / "Audit Qty" (on an invoice) | billing_basis = `AUDIT_QTY` |
| "signed in the capacity of witness" | signoff_capacity = `WITNESS` |
| "do not express any assurance" / "does not provide any formal assurance" | assurance_level_stated = `NO_ASSURANCE` |
| "Accounting Copy" / "Original for Recipient" | copy_type |
| "Is there any old item/asset?" | old_asset_check |
| "Make X/Y/Z" | item_spec.make[] (unless X = a material code, §18) |

---

## 18. Ambiguity register (same word, different meaning)

| Term | Meanings | Resolution rule |
|---|---|---|
| **GR / GRN** | (a) ERP *Goods Receipt* (buyer's receipt, SAP); (b) transport *GR* = consignment note/LR (North-India usage); (c) **client usage: "GRN" for a signed POD** | Classify by **evidence**: a carrier name + waybill no. + receiver signature ⇒ `PROOF_OF_DELIVERY`; buyer letterhead + item-level received qty ⇒ `GOODS_RECEIPT_NOTE`; carrier doc without a receiver signature ⇒ `LORRY_RECEIPT`. Store the tenant's word as `alias` on the resulting role. |
| **POD vs DC vs LR vs e-way bill** | DC = supplier's dispatch claim; LR = carrier's booking; e-way = GST movement permit; POD = receiver's acknowledgment | Only a **receiver-signed/stamped** document is receipt evidence. DC, LR and e-way bill are `DISPATCH` leg. |
| **QTY** (bare) | Ordered (PV sheet next to Vendor/Audit Qty, BM-PV), invoiced (invoice), received (GRN) | Resolve by `doc_role` and sibling columns: in a PV/measurement sheet with Vendor/Audit columns ⇒ `QTY_ORDERED`; on an invoice ⇒ `QTY_INVOICED`. |
| **Audit Qty** | BM-PV: verified quantity; BT-INV proforma "Audit Qty-M": the quantity the vendor *billed* on audit basis | In a PV ⇒ `QTY_VERIFIED`; on an invoice/proforma ⇒ `QTY_INVOICED` with `billing_basis=AUDIT_QTY`. |
| **RATE** | List rate (BM-PV, next to "RATE AFTER 5%"), PO rate, invoice rate | By document, and by the presence of a "RATE AFTER" column. |
| **Credit** | POD freight mode (credit account) vs credit note vs ledger credit | In the POD freight field ⇒ `CREDIT_ACCOUNT`. |
| **Consignee** | Ship-to on an invoice; delivery party on a POD | Both map to `SHIP_TO`. |
| **MS** | Mild steel (material, "Make MS", "M S Pipe") vs M/s (Messrs) vs "MS AIRFLOW" (a brand) | `MS` next to Pipe/Rod/legs/"Make" with no brand ⇒ material; "M S Airflow" ⇒ make. |
| **NA** | Unit "not applicable" (lumpsum charges) vs a missing value | As unit ⇒ `LS`; as a person/vendor ⇒ null. |
| **Additional** | Additional *work* (no PO) vs additional *points* (a contract line "Add point …") | Only section headers or FA-code cells saying "Additional work"/"Not in PO" set `ADDITIONAL_WORK`. |
| **HS / LS** | AC high side / low side (BM-PV) vs LS = lumpsum | `AC HS`/`AC LS` in a PO-family title ⇒ HVAC; "LS" in the unit column ⇒ lumpsum. |
| **DACC** | Delivery Against Consignee Copy vs Consignor's Copy | Keep code `DACC`; don't depend on the expansion. |
| **Distance** | Store distance from vendor/base for outstation slabs (BM-PV) vs transit distance | Site attribute `distance_km`. |
| **Main bill** | Invoice billing stage vs "main supply" cable | Only in invoice remarks/title ⇒ doc_subrole. |
| **Date** | Audit date, verification date, PO date, delivery date, ship date, received date, invoice date, service month | Always role-qualified with a `date_role` (§18a); a bare `date` field is not allowed. |

---

### 18a. `date_role` *(added at adoption)* **N**
`ISSUE_DATE` (PO / order issued), `INVOICE_DATE`, `ACK_DATE` (e-invoice acknowledgement), `AUDIT_DATE`, `VERIFICATION_DATE`, `DELIVERY_DATE` (promised), `SHIP_DATE`, `PICKUP_DATE`, `RECEIVED_DATE`, `SERVICE_MONTH`.

---

## 17a. Engine outcomes *(added at adoption)*
The vocabulary names these kinds; Recon's engine is their source. Codes only grow.

`recon_outcome` **N**: `PASS`, `WARN`, `HOLD` (needs a person before payment), `FAIL`, `NA`. From the engine's severity: OK→`PASS`, INFO→`WARN`, REVIEW→`HOLD`, BLOCKER→`FAIL`.

`recon_line_status` **N** (a line can carry several):
| Code | Meaning |
|---|---|
| `MATCHED` | Matches on every source |
| `RATE_HIGHER` / `RATE_LOWER` | Billed rate above / below the PO rate |
| `OVER_PO` | Billed more than ordered |
| `OVER_VERIFIED` | Billed more than verified on site |
| `UNDER_BILLED` | Billed less than verified |
| `UNDER_USED` | Verified less than ordered |
| `OVER_EXECUTED_CAPPED` | More done than ordered; payable capped at the PO |
| `NOT_DONE` | Not done on site |
| `NOT_VERIFIABLE` | Could not be verified |
| `NOT_IN_PO` | Billed but not in the PO |
| `ADDITIONAL_ON_SITE` | Extra work found on site |
| `DESCRIPTION_CONFLICT` / `UOM_CONFLICT` | Descriptions / units disagree |
| `DAMAGED_UNMOUNTED` | Damaged or not mounted on site |
| `AUDITOR_REMARK` | Auditor left a remark |
| `PCT_CHARGE_MISMATCH` | A percentage charge does not recompute |
| `ARITHMETIC` | Quantity × rate ≠ amount |
| `NO_EVIDENCE` | No site evidence for the line |
| `UNCHECKED_READING` | Handwritten value not yet checked |
| `REPORT_ONLY` | Report row that fits no line of this PO |

`recon_check_code` **N** (header checks; the engine writes them in lower case, the vocabulary in upper): `PO_REFERENCE` *(raised only when the invoice quotes a PO number and it is the wrong one; printing none is not a finding — Bata, 20 Nov 2026)*, `WITHIN_PO_VALUE`, `SINGLE_PO` *(one invoice may never be processed against two POs — Bata, 16 Nov 2026)*, `RECEIPT_VARIANCE` *(invoice over the GRN by more than ₹100 per invoice → costing team)*, `GRN_VS_AUDIT` *(the GRN is raised from the certified quantity, so a difference is a finding about the GRN, not the invoice)*, `PAYMENT_ARITHMETIC`, `PAYMENT_REFERENCE`, `PAYMENT_SETTLED_IN_FULL` *(the PAYMENT leg, from a remittance advice)*, `PAYMENT_TERMS`, `TAX_REGIME`, `INVOICE_ARITHMETIC`, `HEADER_VS_ANNEXURE`, `HANDWRITTEN_CORRECTIONS`, `DUPLICATE_INVOICE`, `VENDOR_IDENTITY`, `BUYER_GSTIN`, `STORE_CONSISTENCY`, `DATE_ORDER`, `POD_MATCHES`, `DELIVERY_TIMELINESS`, `APPROVALS`; and, tier X, the POD and e-way checks of §14: `POD_INVOICE_REF_MATCH`, `POD_VALUE_MATCH`, `POD_CONSIGNEE_MATCHES_SITE`, `POD_SIGNED_AND_STAMPED`, `POD_RECEIVER_STAMP_ADDRESS_MATCH`, `POD_RECEIVED_DATE`, `EWAY_PRESENT_IF_REQUIRED`, `EWAY_INVOICE_LINK`.

`match_method` **N** (how a PO line was paired with an invoice line or a report row): `EXACT_KEY`, `ALIAS` (a learned alias for this vendor), `RATE_SPEC` (description, rate and spec score), `SEQUENCE`, `SEMANTIC` (model judged them the same item), `HUMAN`.

---

## 19. Change log vs the earlier draft (dedup decisions)

| Change | Reason |
|---|---|
| `E_INVOICE` role **removed** → `TAX_INVOICE` + `is_e_invoice` | Same document; e-invoice is an attribute. |
| `MEASUREMENT_SHEET` aliases "MB", "JMR" **moved** | MB = client's `MEASUREMENT_BOOK`; JMR = joint ⇒ `SITE_VERIFICATION_SHEET`. The vendor sheet stays `MEASUREMENT_SHEET`. |
| `verification_status` `VERIFIED_FULL/SHORT/EXCESS` **merged** → `VERIFIED` | Short/excess are engine comparisons, not auditor statements. |
| `ADDITIONAL_VERIFIED` **removed** | = `line_origin=ADDITIONAL_WORK` + `VERIFIED`. |
| `verification_method` **split** into `measurement_technique` × `visibility` × `basis_source` | The old list mixed three ideas (e.g. CONCEALED_ESTIMATED, VENDOR_DIRECTED). |
| `ItemSpec.rating` **replaced** by `electrical{}` + `lighting{}` | "8W 4000K" and "25 A TPN" were different things in one field. |
| `payable_condition` gained `DRAWING_REQUIRED`, `CLIENT_TEAM_CONCURRENCE_REQUIRED`, `RECEIPT_REQUIRED_FOR_ITC` | New evidence from BM-PV and GST. |
| `NOT_IN_SCOPE` **kept single**, with new facet `scope_exclusion_source` | Avoids `NOT_IN_SCOPE_CLIENT` / `NOT_IN_SCOPE_AUDITOR` codes. |
| `QTY_SHORT`, `QTY_BALANCE` **not added** | Derived. |
| `QTY_CERTIFIED` **added, separate from** `QTY_VERIFIED` | Different actor (client authority) and stage. |
| `LORRY_RECEIPT` and `PROOF_OF_DELIVERY` **both kept** | Same paper, different evidence state (receiver signature); decided by rule §0.5. |
| `HVAC` split into `HVAC_HIGH_SIDE` / `HVAC_LOW_SIDE` / `AHU_DUCTING` as children | BM-PV PO families; parent kept for roll-up. |
| `PO_AMENDMENT` absorbs change order / variation order | Same function: change of commitment. |

| **Adoption into Recon, 2026-11-16** | |
| Example GSTIN `…1043Q1ZJ` **corrected** to `29AABCB1043Q1ZI` | `…1ZJ` fails the GSTIN check digit; Bata Karnataka is `…1ZI`. |
| Dead link "§8.4 of the schema" **replaced** with `recon_check_code` (§17a) | The schema file it pointed to was not part of the vocabulary set. |
| `date_role` **added** (§18a) | Used by the schema proposals, never enumerated. |
| `evidence_layer`, `value_change_kind` **added** (§4.4) | Used by both schema proposals; never enumerated. |
| `recon_outcome`, `recon_line_status`, `recon_check_code`, `match_method` **added** (§17a) | Named by the schema; seeded from Recon's engine. |
| `pv_format` gained `SPREADSHEET_TABLE`; `supply_type` gained `NO_TAX` | Recon accepts spreadsheet reports; some bills carry no GST. |
| "Memorandum" **added** as an alias of `APPROVAL_COMMUNICATION` | Bata's internal approval memo. |
| `link_method` **not adopted yet** | Recon records only who linked (auto / person), not how; add codes when it records the method. |

### Open items (need client or tenant confirmation)
- **PPS sheet** (BT-PV legend) — expansion unknown; treated as BOQ-like.
- **SIS** ("SIS Project site", "SIS/Projects team") — Bata internal team/process name; stored as `process_owner` text.
- **FSC** in concept "FSC Red 2 Silver" — store format code; stored as text.
- **GTY**, **SCH** on the POD — carrier codes; stored raw.
- **TBB** — practitioner usage only.
- **DACC** — expansion disputed between sources.
- Whether Bata's "GRN" always means a signed POD, or sometimes a store-level inward entry.

---

## 20. Sources (industry terms)
- SAP: [GR/IR clearing account](https://help.sap.com/saphelp_46c/helpdata/en/96/8b328343ce11d189ee0000e81ddfac/content.htm), [Evaluated Receipt Settlement](https://help.sap.com/saphelp_46c/helpdata/en/fd/45c1759d6411d189b60000e829fbbd/content.htm), [Invoice verification for services / SES](https://help.sap.com/doc/ea1dbf53d25ab64ce10000000a174cb4/3.6/en-US/f81cbf53d25ab64ce10000000a174cb4.html)
- PO vs GRN vs DC vs invoice, ITC receipt condition: [Terra Insight](https://www.terra-insight.com/insights/purchase-order-grn-delivery-challan-invoice-what-each-document-proves), [open.money delivery notes](https://open.money/blog/?p=24817)
- Lorry receipt / consignment note fields and copies: [Tata Nexarc](https://blog.tatanexarc.com/logistics/lorry-receipt-a-guide-to-types-features-rules-format-and-usage), [Fleetx — bilty](https://blog.fleetx.io/what-is-bilty-a-simple-explanation-for-transporters-shippers/)
- DOD / DACC: [Safexpress blog](https://safexpresslogistics.blogspot.com/2025/10/how-safexpress-ensures-safe-and.html), [TCI Express booking terms](https://www.tciexpress.in/pdf/BOOKING-TERMS-AND-CONDITIONS.pdf)
- HVAC high side / low side usage: [TIFR Hyderabad tender](https://www.tifrh.res.in/webdata/documents/events/tenders/2024/aug/240479.pdf), [IIT Hyderabad notice](https://www.iith.ac.in/assets/files/tenders/Tendernotice_1-3.pdf)
- Extra / substituted items, works billing: [CPWD Works Manual 2022 (NDMC)](https://www.ndmc.gov.in/departments/Departments/Finance/nodal_cell/CPWD%20Works%20Manual%202022.pdf), [InfraLens RA bill](https://infralens.in/pmc/billing/running-account-ra-bill)
- 3-way match practice: [Lleverage](https://www.lleverage.ai/blog/three-way-matching-automation), [Peakflo](https://peakflo.co/blog/three-way-matching-exceptions-ai-solutions)


---

## 21. How Recon uses this vocabulary *(added at adoption)*

**Machine form.** `backend_ocr/app/recon/vocab.py` holds every code in this file (`CODES`), the seed aliases (`ALIASES`) and the only mapping from Recon's internal codes to vocabulary codes. On every migration `vocab.sync()`:
1. upserts every code into `vocab_codes`. A code removed from this file is marked `deprecated`, never deleted;
2. upserts the seed aliases into `vocab_aliases`;
3. (re)builds the generated code columns below when the mapping version changes;
4. adds the foreign keys from those columns to `vocab_codes`.

**Generated code columns** are computed by Postgres from each row's own values, so extraction, read-again, reviewer corrections and kind overrides keep them right without application code:

| Table | Column → kind | From |
|---|---|---|
| `recon_doc_pages` | `doc_role` | page class |
| `recon_doc_segments` | `doc_role`, `recon_leg`, `receipt_granularity` | part kind |
| `recon_doc_segments` | `pv_format`, `evidence_layer` | the extractor's layout |
| `recon_evidence_rows` | `verification_status`, `scope_exclusion_source` | the effective verdict (a reviewer's `verdict`, else `auto_verdict`, which is Recon's classifier saved with the row) and the auditor's remark. A §17 out-of-scope remark ("as per Bata instructions not in scope", "out of audit", "not covered in audit") gives `NOT_IN_SCOPE`, whichever bucket the classifier used for billing |
| `recon_evidence_rows` | `line_origin` | row type (PO line / additional) |
| `recon_evidence_rows` | `uom`, `uom_family` | printed unit |
| `recon_invoice_lines` | `line_origin`, `charge_type`, `pricing_basis`, `uom`, `uom_family` | charge flag, description, % |
| `recon_line_results` | `outcome` → `recon_outcome` | severity |
| `recon_header_checks` | `check_code` → `recon_check_code`, `outcome` | check code, pass/severity |

Plus two plain columns:
- `recon_evidence_rows.value_history` (§4.4), written on save (handwritten overwrites) and on every reviewer correction;
- `recon_evidence_rows.auto_verdict`, the classifier's reading of the row, written on save and re-classified when a reviewer corrects a quantity or remark.

**Aliases are tenant-scoped once learned.** A `HUMAN` or `LEARNED` alias must carry a tenant (a CHECK constraint). Global aliases come only from this file. One client's reviewer can never repoint another client's labels.

**API.** Every document part in Recon's API carries `vocab: {doc_role, recon_leg, receipt_granularity, pv_format, evidence_layer}`. Every table column with a quantity or rate carries `code` (e.g. a sheet's "Vendor Qty" column is `QTY_CLAIMED`).

**Changing a code.** Add it here and in `vocab.py`; `tests/recon/test_vocab.py` checks they agree. To change a *mapping*, bump `MAPPING_VERSION` in `vocab.py`; the next migration rebuilds the generated columns.
