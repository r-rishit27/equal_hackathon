"""Recon vocabulary — the machine form of docs/RECON_VOCABULARY.md.

docs/reconciliation/RECON_VOCABULARY.md is the dictionary people read; this module is the same dictionary for the code
and the database. tests/recon/test_vocab.py fails if a code here is missing from the document.

Three jobs:
  1. CODES / ALIASES: every allowed code by kind, and raw label → code, seeded into `vocab_codes` and
     `vocab_aliases` by `sync()`.
  2. Mapping from Recon's internal enums (DocClass, SegmentKind, AuditVerdict, extractor layouts, units,
     severities) to vocabulary codes — the only place that mapping is written.
  3. `generated_sql()`: the SQL expressions behind the generated vocabulary columns on Recon's tables
     (recon/schema.py), built from (2), so the database and the code can never disagree.

Change rules (vocabulary §0): one concept, one code; after v1 the code list is append-only — deprecate,
never delete. A change to a mapping in (2) must bump MAPPING_VERSION: `sync()` then rebuilds the
generated columns.
"""
from __future__ import annotations

import re

VOCAB_VERSION = "v1"
MAPPING_VERSION = "m3"   # bump when a *_MAP below changes; sync() rebuilds the generated columns


def _codes(block: str, tier: str = "N") -> list[tuple[str, str, str, str | None]]:
    """'CODE | label [| tier [| parent]]' per line → (code, label, tier, parent)."""
    out = []
    for line in block.strip().splitlines():
        parts = [p.strip() for p in line.split("|")]
        code, label = parts[0], parts[1]
        t = parts[2] if len(parts) > 2 and parts[2] else tier
        parent = parts[3] if len(parts) > 3 and parts[3] else None
        out.append((code, label, t, parent))
    return out


# ── 1. Codes (vocabulary section in brackets) ─────────────────────────────────
CODES: dict[str, list[tuple[str, str, str, str | None]]] = {
    "recon_leg": _codes("""
        COMMITMENT | What we agreed to buy, at what rate
        DISPATCH | What the supplier says they sent
        RECEIPT | What actually arrived or got built
        QUALITY | Whether it was acceptable
        BILLING | What the vendor is charging
        PAYMENT | What we paid"""),                                                        # §1
    "match_type": _codes("""
        TWO_WAY | Commitment ↔ billing
        THREE_WAY | Commitment ↔ receipt ↔ billing
        FOUR_WAY | Three-way plus quality
        ERS | Evaluated receipt settlement (no invoice)"""),
    "receipt_granularity": _codes("""
        ITEM_QTY | Quantity per line item
        PACKAGE | Number of packages, weight
        CONSIGNMENT | That a consignment for given invoices arrived
        VALUE | Declared value only"""),
    "doc_role": _codes("""
        PURCHASE_REQUISITION | Internal request to buy | X | COMMITMENT
        PURCHASE_ORDER | Buyer's binding order | N | COMMITMENT
        WORK_ORDER | Binding order for works or services | X | COMMITMENT
        PO_AMENDMENT | Change to an existing commitment | X | COMMITMENT
        RATE_CONTRACT | Agreed rates without fixed quantity | X | COMMITMENT
        BOQ | Bill of quantities | X | COMMITMENT
        QUOTATION | Vendor offer before commitment | L | COMMITMENT
        DELIVERY_CHALLAN | Supplier's dispatch document | X | DISPATCH
        PACKING_LIST | Contents of each package | L | DISPATCH
        ASN | Advance shipping notice | L | DISPATCH
        LORRY_RECEIPT | Carrier's consignment note | X | DISPATCH
        EWAY_BILL | GST movement document | X | DISPATCH
        GOODS_RECEIPT_NOTE | Buyer's record of what was received | X | RECEIPT
        PROOF_OF_DELIVERY | Delivery acknowledged by the receiver | N | RECEIPT
        PHYSICAL_VERIFICATION_REPORT | Third-party report of what exists on site | N | RECEIPT
        SITE_VERIFICATION_SHEET | Signed field sheet with measurements | N | RECEIPT
        MEASUREMENT_SHEET | Vendor's claimed measurements | N | RECEIPT
        MEASUREMENT_BOOK | Client engineer's measurement record | L | RECEIPT
        SERVICE_ENTRY_SHEET | Buyer's acceptance of services | L | RECEIPT
        INSTALLATION_REPORT | Equipment installed | L | RECEIPT
        COMPLETION_CERTIFICATE | Work completed | X | RECEIPT
        INSPECTION_REPORT | QC acceptance or rejection | L | QUALITY
        TEST_CERTIFICATE | Manufacturer or lab test | L | QUALITY
        COMMISSIONING_CERTIFICATE | System tested and running | X | QUALITY
        HANDOVER_CERTIFICATE | Site handed over | L | QUALITY
        WARRANTY_CERTIFICATE | Warranty proof | L | QUALITY
        TAX_INVOICE | GST tax invoice (incl. e-invoice) | N | BILLING
        PROFORMA_INVOICE | Pre-bill or workings | N | BILLING
        BILL_OF_SUPPLY | Invoice with no GST charged | L | BILLING
        CREDIT_NOTE | Reduces an invoice | X | BILLING
        DEBIT_NOTE | Increases an invoice | X | BILLING
        FREIGHT_INVOICE | Carrier's bill for transport | L | BILLING
        PAYMENT_ADVICE | Remittance details | X | PAYMENT
        BANK_STATEMENT | Bank ledger | X | PAYMENT
        APPROVAL_COMMUNICATION | Email, memo or letter carrying a decision | N
        PHOTO_EVIDENCE | Site or work photo | X
        DRAWING | Layout, as-built or single-line drawing | X"""),                           # §2
    "doc_subrole": _codes("""
        ADVANCE_INVOICE | Advance invoice
        RA_BILL | Running account bill
        MAIN_BILL | Main bill
        SUPPLEMENTARY_BILL | Extra or additional work
        FINAL_BILL | Final bill
        RETENTION_RELEASE | Retention release"""),
    "copy_type": _codes("""
        ORIGINAL_FOR_RECIPIENT | Original for recipient
        DUPLICATE_FOR_TRANSPORTER | Duplicate for transporter
        TRIPLICATE_FOR_SUPPLIER | Triplicate for supplier
        ACCOUNTING_COPY | Accounting copy
        CONSIGNOR_COPY | Consignor copy
        CONSIGNEE_COPY | Consignee copy
        DRIVER_COPY | Driver copy
        OFFICE_COPY | Office copy""", "X"),
    "pv_format": _codes("""
        AUDITOR_ANNEXURE | Auditor's A/B/C table with signed field sheets
        WITNESSED_VENDOR_SHEET | Vendor's sheet with Vendor/Audit Qty, signed as witness
        SPREADSHEET_TABLE | Report supplied as a spreadsheet | X"""),
    "communication_intent": _codes("""
        APPROVAL | Approval
        INSTRUCTION | Instruction
        SCOPE_EXCLUSION | Scope exclusion
        CONFIRMATION | Confirmation
        DISPUTE | Dispute"""),
    "drawing_type": _codes("""
        LAYOUT | Layout
        AS_BUILT | As-built
        SLD | Single-line diagram
        LINE_DIAGRAM | Line diagram
        SHOP_DRAWING | Shop drawing""", "X"),
    "party_role": _codes("""
        BUYER | Contracting buyer
        BILL_TO | Invoice addressee
        SHIP_TO | Delivery or consignee location
        SUPPLIER | Seller or contractor
        CONSIGNOR | Party handing goods to the carrier
        CARRIER | Transporter
        AUDITOR | Third-party verifier
        CONSULTANT | Technical advisor
        SITE | Store or project location"""),                                              # §3
    "person_role": _codes("""
        STORE_MANAGER | Store manager
        PROJECT_MANAGER | Project manager
        REGIONAL_MANAGER | Regional manager
        VENDOR_REPRESENTATIVE | Vendor representative
        AUDIT_TEAM_MEMBER | Audit team member
        CONSULTANT | Consultant
        PROCESS_OWNER | Process owner
        RECEIVER | Person signing a POD
        AUTHORISED_SIGNATORY | Authorised signatory
        APPROVER | Approver named in a decision""", "X"),
    "signoff_capacity": _codes("""
        PREPARER | Preparer
        VERIFIER | Verifier
        WITNESS | Signed in the capacity of witness
        RECEIVER | Receiver
        APPROVER | Approver
        AUTHORISED_SIGNATORY | Authorised signatory"""),
    "assurance_level_stated": _codes("""
        NO_ASSURANCE | Auditor expresses no assurance
        LIMITED | Limited assurance
        REASONABLE | Reasonable assurance"""),
    "qty_role": _codes("""
        QTY_ORDERED | Buyer committed
        QTY_CLAIMED | Vendor claims executed or supplied
        QTY_VERIFIED | Independent verifier measured or counted
        QTY_CERTIFIED | Client authority approved for payment | L
        QTY_MOUNTED | Mounted at verification
        QTY_UNMOUNTED | Not mounted at verification
        QTY_DAMAGED | Damaged at verification
        QTY_DISPATCHED | Supplier says shipped | L
        QTY_DELIVERED | Carrier delivered, receiver acknowledged
        QTY_RECEIVED | Buyer counted into stock or site | X
        QTY_ACCEPTED | Accepted after inspection | L
        QTY_REJECTED | Rejected after inspection | L
        QTY_INVOICED | Billed in this invoice
        QTY_PREV_BILLED | Billed in earlier RA bills | X
        QTY_CUM_BILLED | Billed up to date | X
        QTY_PAYABLE | Computed by policy, never extracted"""),                               # §4
    "measure_basis": _codes("""
        ITEM | Per item
        PACKAGE | Boxes, cartons, bundles
        WEIGHT_ACTUAL | Actual weight
        WEIGHT_CHARGED | Charged weight
        VOLUME | Volume
        VALUE | Declared value
        PERCENT_BASE | Base a percentage applies to"""),
    "evidence_layer": _codes("""
        TYPED_BODY | Typed body of the document
        TYPED_ANNEXURE | Auditor's typed annexure table
        SIGNED_SITE_SHEET | Signed field sheet (Mounted/Unmounted/Damaged)
        WITNESSED_SHEET | Vendor sheet with handwritten audit values, witnessed"""),          # gap, §4.4
    "value_change_kind": _codes("""
        HANDWRITTEN_CORRECTION | Value overwritten by hand on the page
        REVIEWER_CORRECTION | Value corrected by a reviewer in Reckon.ai"""),                   # gap, §4.4
    "rate_role": _codes("""
        RATE_LIST | Rate-card rate before discount
        RATE_NET | Rate after negotiated discount
        RATE_PO | Rate on the PO line
        RATE_INVOICED | Rate on the invoice line"""),                                       # §5
    "pricing_basis": _codes("""
        UNIT_RATE | Quantity × rate
        PERCENT_OF_BASE | Percentage of a stated base
        LUMPSUM | One fixed amount
        SLAB | Price by a range of a site attribute | X
        DISTANCE_TIER | Price by distance band | X
        ZONE | Price by region | X
        THRESHOLD_ITEM | Applies only above a measured threshold | X"""),
    "line_origin": _codes("""
        CONTRACT_LINE | On the commitment document
        ADDITIONAL_WORK | Not on the commitment; new work
        SUBSTITUTE | Replaces a commitment item | X
        CHARGE | Non-item cost
        ADJUSTMENT | Discount, round-off, advance adjustment"""),
    "charge_type": _codes("""
        PACKING_FORWARDING | Packing and forwarding
        FREIGHT | Transport, cartage
        LOADING_UNLOADING | Loading and unloading
        OUTSTATION | Outstation or travel allowance
        SCAFFOLDING | Scaffolding
        DEBRIS_DISPOSAL | Malba / debris disposal
        INSURANCE | Insurance
        MOBILISATION | Mobilisation
        HANDLING | Handling"""),
    "line_nature": _codes("""
        SUPPLY | Supply only
        SUPPLY_AND_INSTALL | Supply and install
        INSTALL_ONLY | Fixing or installation only
        SERVICE | Programming, integration, commissioning
        CIVIL_WORK | Core cutting, dismantling""", "X"),
    "uom_family": _codes("""
        COUNT | Count
        AREA | Area
        LENGTH | Length
        MASS | Mass
        LUMPSUM | Lumpsum
        PERCENT | Percent
        DISTANCE | Distance
        CAPACITY | Capacity (attribute units)"""),                                           # §6
    "uom": _codes("""
        EA | Each | N | COUNT
        SET | Set | N | COUNT
        PKG | Package | N | COUNT
        SQFT | Square feet | N | AREA
        SQM | Square metres | N | AREA
        RFT | Running feet | N | LENGTH
        RMT | Running metres | N | LENGTH
        KG | Kilogram | N | MASS
        LS | Lumpsum | N | LUMPSUM
        PCT | Percent | N | PERCENT
        KM | Kilometre | N | DISTANCE
        TR | Tonne of refrigeration | N | CAPACITY
        KW | Kilowatt | N | CAPACITY
        KVA | Kilovolt-ampere | N | CAPACITY
        HP | Horsepower | N | CAPACITY"""),
    "work_package": _codes("""
        CIVIL | Civil
        FALSE_CEILING | False ceiling | X | CIVIL
        PARTITION_PANELLING | Partition and panelling | X | CIVIL
        FLOORING | Flooring | X | CIVIL
        PAINTING | Painting | X | CIVIL
        FACADE | Facade | X | CIVIL
        JOINERY | Joinery | X | CIVIL
        ELECTRICAL | Electrical
        LT_PANEL | LT panel | X | ELECTRICAL
        WIRING_POINTS | Wiring points | X | ELECTRICAL
        CABLING | Cabling | X | ELECTRICAL
        EARTHING | Earthing | X | ELECTRICAL
        LIGHTING | Lighting
        SIGNAGE | Signage
        HVAC | HVAC
        HVAC_HIGH_SIDE | HVAC high side (per tenant) | X | HVAC
        HVAC_LOW_SIDE | HVAC low side (per tenant) | X | HVAC
        AHU_DUCTING | AHU and ducting | X | HVAC
        FIRE | Fire
        FIRE_SPRINKLER | Fire sprinkler | X | FIRE
        FIRE_ALARM | Fire alarm | X | FIRE
        FURNITURE_FIXTURE | Furniture and fixtures
        RACKING | Racking | X | FURNITURE_FIXTURE
        IT_NETWORK | IT network
        PLUMBING | Plumbing
        SITE_SERVICES | Site services""", "X"),                                               # §7
    "po_tax_treatment": _codes("""
        GST | GST PO
        NON_GST | Non-GST PO""", "X"),
    "verification_status": _codes("""
        VERIFIED | A verified quantity is given
        NOT_EXECUTED | Work not present
        NOT_IN_SCOPE | Deliberately not verified
        NOT_VERIFIABLE | Could not be checked
        DEFECTIVE_EXCLUDED | Present but defective, excluded
        INSTALLED_THEN_REMOVED | Installed, later removed on instruction
        PARTIALLY_INSTALLED | Some units mounted, some not"""),                             # §9
    "scope_exclusion_source": _codes("""
        AUDITOR_SCOPE | Auditor's own scope or limitation
        CLIENT_INSTRUCTION | Excluded on the client's instruction
        CERTIFICATE_PENDING | Waiting for a certificate
        NOT_APPLICABLE | Not applicable (charges)"""),
    "measurement_technique": _codes("""
        COUNT | Counted
        AREA_MEASURED | Area measured
        LENGTH_MEASURED | Length measured
        VISUAL_CHECK | Visual check
        ESTIMATE | Estimated
        FORMULA | Consultant formula
        DOCUMENT_REVIEW | Document review
        NONE | Not measured"""),
    "visibility": _codes("""
        VISIBLE | Visible
        CONCEALED | Concealed
        PARTIALLY_CONCEALED | Partly concealed"""),
    "basis_source": _codes("""
        AUDITOR_INDEPENDENT | Auditor's own count
        VENDOR_DIRECTED | Counted on the vendor's directions
        STORE_MANAGER_CONFIRMED | Store manager confirmed
        PROJECT_MANAGER_CONFIRMED | Project manager confirmed
        CONSULTANT_GUIDELINE | Consultant's formula or guideline
        BEST_JUDGEMENT | Best judgement
        PHOTO | Photo
        DRAWING | Drawing"""),
    "spec_verification_status": _codes("""
        SPEC_CONFIRMED | Spec confirmed
        SPEC_DEVIATION | Spec differs from the PO
        SPEC_NOT_VERIFIABLE | Spec could not be checked
        SPEC_NOT_ASSESSED | Spec excluded by disclaimer"""),
    "old_asset_check": _codes("""
        YES | Old item reused
        NO | No old item
        UNANSWERED | Question not answered""", "X"),
    "assurance_exclusion": _codes("""
        QUALITY_NOT_VERIFIED | Quality and workmanship not assessed
        MATERIAL_SPEC_NOT_VERIFIED | Thickness, brand, grade not verified
        CONCEALED_WORK_NOT_VERIFIED | Concealed work not verified
        DISMANTLING_NOT_VERIFIED | Removal of old structures unverified
        OLD_ASSET_REUSE_RISK | Possible reuse of old material
        OLD_FRAMEWORK_REMOVAL_UNVERIFIED | Old signage framework removal unverified
        DUPLICATE_CLAIM_RISK | Same work possibly claimed twice
        BEST_JUDGEMENT_ALLOWANCE | Allowances made on judgement
        DRAWINGS_NOT_PROVIDED | Drawings or photos not shared
        NOT_ENGINEERING_CERTIFICATION | Not an engineering certificate
        TITLE_NOT_VERIFIED | Ownership not verified
        CLIENT_DISCRETION_ALLOWANCE | Allowance at the client's discretion""", "X"),           # §10
    "payable_condition": _codes("""
        PHOTO_REQUIRED | Photo evidence needed
        CERTIFICATE_REQUIRED | Commissioning or integration certificate needed
        EMAIL_APPROVAL_REQUIRED | Named approver's written approval needed
        DRAWING_REQUIRED | Drawing needed
        CLIENT_TEAM_CONCURRENCE_REQUIRED | Process owner must concur
        SPEC_REFERENCE | Must meet the referenced spec
        MAKE_RESTRICTED | Only approved makes
        CAP_LIMIT | Quantity or size ceiling
        RECEIPT_REQUIRED_FOR_ITC | GST input credit needs goods received"""),              # §11
    "tax_component": _codes("""
        IGST | IGST
        CGST | CGST
        SGST | SGST
        UTGST | UTGST
        CESS | Cess"""),                                                                    # §12
    "supply_type": _codes("""
        INTER_STATE | Inter-state supply (IGST)
        INTRA_STATE | Intra-state supply (CGST + SGST)
        NO_TAX | No GST charged"""),
    "code_type": _codes("""
        HSN | Goods
        SAC | Services"""),
    "payment_trigger": _codes("""
        ADVANCE | Advance
        ON_DELIVERY | On delivery
        ON_INSTALLATION | On installation
        ON_AUDIT | On the PV report
        ON_INVOICE_IMMEDIATE | Immediately on invoice
        NET_DAYS | Net n days
        RETENTION_RELEASE | Retention release""", "X"),                                      # §13
    "advance_type": _codes("""
        MOBILISATION_ADVANCE | Mobilisation advance
        SECURED_ADVANCE | Secured advance against materials
        SUPPLY_ADVANCE | PO percentage advance""", "X"),
    "price_basis": _codes("""
        FIRM | Prices firm
        VARIABLE | Price variation or escalation""", "X"),
    "partial_delivery_policy": _codes("""
        WITH_WRITTEN_CONSENT | Only with written consent
        ALLOWED | Allowed
        NOT_ALLOWED | Not allowed""", "X"),
    "freight_payment_mode": _codes("""
        PAID | Consignor pays at booking
        TO_PAY | Consignee pays on delivery
        CREDIT_ACCOUNT | Billed later to a contract customer""", "X"),                        # §14
    "delivery_mode": _codes("""
        DOOR_DELIVERY | Door delivery
        GODOWN_DELIVERY | Collected at the carrier's warehouse
        DOD | Draft on delivery
        COD | Cash on delivery
        DACC | Delivery against document copy""", "L"),
    "extraction_artifact": _codes("""
        SPREADSHEET_OVERFLOW | ##### in a cell
        SPREADSHEET_FORMULA_ERROR | #NAME? in a cell
        SCIENTIFIC_NOTATION | Number shown as 9.84E+09
        OCR_CHAR_CONFUSION | Characters misread (O/0, I/1, B/8)
        TRUNCATED_VALUE | Value cut off
        LABEL_VALUE_SHIFT | Values under the wrong labels
        PRINTED_VARIANCE_WRONG | Printed variance does not recompute
        HANDWRITTEN_CORRECTION | Value overwritten by hand
        QTY_UNIT_INCOHERENT | Quantity and unit don't fit
        UOM_MIXED_IN_WORKING | Units mixed in a working
        TYPO_IN_LABEL | Typo in a label"""),                                              # §16
    "date_role": _codes("""
        ISSUE_DATE | Date a PO or order was issued
        INVOICE_DATE | Invoice date
        ACK_DATE | e-invoice acknowledgement date
        AUDIT_DATE | Date of the site audit
        VERIFICATION_DATE | Date a quantity was verified
        DELIVERY_DATE | Promised delivery date
        SHIP_DATE | Date shipped
        PICKUP_DATE | Date picked up by the carrier
        RECEIVED_DATE | Date received
        SERVICE_MONTH | Month the service relates to"""),                                   # gap, §18
    "recon_outcome": _codes("""
        PASS | Passed
        WARN | Passed with a note
        HOLD | Needs a person before payment
        FAIL | Failed
        NA | Not applicable"""),                                                           # gap, §17a
    "recon_line_status": _codes("""
        MATCHED | Matches on every source
        RATE_HIGHER | Billed rate above the PO rate
        RATE_LOWER | Billed rate below the PO rate
        OVER_PO | Billed more than ordered
        OVER_VERIFIED | Billed more than verified on site
        UNDER_BILLED | Billed less than verified
        UNDER_USED | Verified less than ordered
        OVER_EXECUTED_CAPPED | More done than ordered; capped at the PO
        NOT_DONE | Not done on site
        NOT_VERIFIABLE | Could not be verified
        NOT_IN_PO | Billed but not in the PO
        ADDITIONAL_ON_SITE | Extra work found on site
        DESCRIPTION_CONFLICT | Descriptions disagree
        UOM_CONFLICT | Units disagree
        DAMAGED_UNMOUNTED | Damaged or not mounted on site
        AUDITOR_REMARK | Auditor left a remark
        PCT_CHARGE_MISMATCH | Percentage charge does not recompute
        ARITHMETIC | Quantity × rate ≠ amount
        NO_EVIDENCE | No site evidence for the line
        UNCHECKED_READING | Handwritten value not yet checked
        REPORT_ONLY | Report row that fits no line of this PO"""),                          # gap, §17a
    "recon_check_code": _codes("""
        PO_REFERENCE | PO number on invoice
        WITHIN_PO_VALUE | Within PO value
        SINGLE_PO | One PO per invoice
        RECEIPT_VARIANCE | Invoice within receipt value
        GRN_VS_AUDIT | GRN matches the audit report
        PAYMENT_ARITHMETIC | Payment advice adds up
        PAYMENT_REFERENCE | Payment advice names this invoice
        PAYMENT_SETTLED_IN_FULL | Invoice settled in full
        PAYMENT_TERMS | Payment terms
        TAX_REGIME | GST type and amount
        INVOICE_ARITHMETIC | Invoice arithmetic
        HEADER_VS_ANNEXURE | Invoice = its detail page
        HANDWRITTEN_CORRECTIONS | Handwritten changes on invoice
        DUPLICATE_INVOICE | Not billed before
        VENDOR_IDENTITY | Same vendor GSTIN everywhere
        BUYER_GSTIN | Billed to the PO's buyer GSTIN
        STORE_CONSISTENCY | Same store on every document
        DATE_ORDER | Dates in order
        POD_MATCHES | Delivery proof matches invoice
        DELIVERY_TIMELINESS | Delivered on time
        APPROVALS | Approval memo
        POD_INVOICE_REF_MATCH | POD names the invoice | X
        POD_VALUE_MATCH | POD value matches the invoice | X
        POD_CONSIGNEE_MATCHES_SITE | POD consignee is the store | X
        POD_SIGNED_AND_STAMPED | POD signed and stamped | X
        POD_RECEIVER_STAMP_ADDRESS_MATCH | Receiver's stamp matches the store | X
        POD_RECEIVED_DATE | POD received date in range | X
        EWAY_PRESENT_IF_REQUIRED | e-way bill present when required | X
        EWAY_INVOICE_LINK | e-way bill names the invoice | X"""),                           # gap, §17a + §14
    "match_method": _codes("""
        EXACT_KEY | Same item code or exact description
        ALIAS | A learned alias for this vendor
        RATE_SPEC | Description, rate and spec score
        SEQUENCE | Same position in both documents
        SEMANTIC | Model judged them the same item
        HUMAN | A person matched them"""),                                                 # gap, §17a
}

# ── Seed aliases: (kind, raw label, code, context_doc_role or None) ──────────────
_UOM_ALIASES: dict[str, list[str]] = {
    "EA": ["Nos", "No", "No.", "Each", "Pcs", "Pc", "Unit", "Units"],
    "SET": ["Set", "Sets", "Kit", "Kits"],
    "PKG": ["Pkg", "Pkgs", "Package", "Packages", "Carton", "Cartons", "Box", "Boxes"],
    "SQFT": ["SF", "Sft", "SQFT", "Sq ft", "Sq. ft", "Square feet"],
    "SQM": ["SM", "Sqm", "Sqmt", "Sq mtrs", "Sq m", "m2", "m²"],
    "RFT": ["Rft", "Running ft", "Running feet", "Ft", "Fit", "'"],
    "RMT": ["M", "Rmt", "Mtr", "Mtrs", "Metre", "Meter", "Running metre"],
    "KG": ["Kg", "Kgs", "Act Wt"],
    "LS": ["LS", "Lot", "Job", "Lumpsum", "Lump sum", "NA"],
    "PCT": ["%", "Pct", "Percent"],
    "KM": ["KM", "Kms"],
    "TR": ["TR", "Ton", "Tons"], "KW": ["KW"], "KVA": ["KVA"], "HP": ["HP"],
}
ALIASES: list[tuple[str, str, str, str | None]] = [
    *(("uom", a, c, None) for c, names in _UOM_ALIASES.items() for a in names),
    ("qty_role", "Qty as per PO", "QTY_ORDERED", None), ("qty_role", "PO Qty", "QTY_ORDERED", None),
    ("qty_role", "Qty as per PO/PPS sheet", "QTY_ORDERED", None),
    ("qty_role", "QTY", "QTY_ORDERED", "PHYSICAL_VERIFICATION_REPORT"),
    ("qty_role", "QTY", "QTY_INVOICED", "TAX_INVOICE"),
    ("qty_role", "Given/ Vendor Qty (B)", "QTY_CLAIMED", None), ("qty_role", "Vendor Qty", "QTY_CLAIMED", None),
    ("qty_role", "Given Qty", "QTY_CLAIMED", None),
    ("qty_role", "Qty as per measurement sheet/vendor invoice", "QTY_CLAIMED", None),
    ("qty_role", "Verified Qty (C)", "QTY_VERIFIED", None), ("qty_role", "Actual Measured Qty", "QTY_VERIFIED", None),
    ("qty_role", "Total Measured Area", "QTY_VERIFIED", None), ("qty_role", "Total Area", "QTY_VERIFIED", None),
    ("qty_role", "Audit Qty", "QTY_VERIFIED", "PHYSICAL_VERIFICATION_REPORT"),
    ("qty_role", "Audit Qty", "QTY_INVOICED", "PROFORMA_INVOICE"),
    ("qty_role", "Mounted", "QTY_MOUNTED", None), ("qty_role", "Unmounted", "QTY_UNMOUNTED", None),
    ("qty_role", "Damaged", "QTY_DAMAGED", None), ("qty_role", "Pkg", "QTY_DELIVERED", "PROOF_OF_DELIVERY"),
    ("rate_role", "RATE", "RATE_LIST", "PHYSICAL_VERIFICATION_REPORT"),
    ("rate_role", "RATE AFTER 5%", "RATE_NET", None), ("rate_role", "Unit Pr.", "RATE_PO", "PURCHASE_ORDER"),
    ("rate_role", "Rate", "RATE_INVOICED", "TAX_INVOICE"),
    ("doc_role", "PO", "PURCHASE_ORDER", None), ("doc_role", "PPO", "PURCHASE_ORDER", None),
    ("doc_role", "Purchase Order", "PURCHASE_ORDER", None), ("doc_role", "Buyer's Order", "PURCHASE_ORDER", None),
    ("doc_role", "Work Order", "WORK_ORDER", None), ("doc_role", "PR", "PURCHASE_REQUISITION", None),
    ("doc_role", "Tax Invoice", "TAX_INVOICE", None), ("doc_role", "e-Invoice", "TAX_INVOICE", None),
    ("doc_role", "Proforma Invoice", "PROFORMA_INVOICE", None), ("doc_role", "Performa Invoice", "PROFORMA_INVOICE", None),
    ("doc_role", "POD", "PROOF_OF_DELIVERY", None), ("doc_role", "ePOD", "PROOF_OF_DELIVERY", None),
    ("doc_role", "PV Report", "PHYSICAL_VERIFICATION_REPORT", None),
    ("doc_role", "Report of Site Visit & Physical Verification", "PHYSICAL_VERIFICATION_REPORT", None),
    ("doc_role", "Audit Report", "PHYSICAL_VERIFICATION_REPORT", None),
    ("doc_role", "JMR", "SITE_VERIFICATION_SHEET", None),
    ("doc_role", "Memorandum", "APPROVAL_COMMUNICATION", None),
    ("doc_role", "LR", "LORRY_RECEIPT", None), ("doc_role", "Bilty", "LORRY_RECEIPT", None),
    ("doc_role", "Waybill", "LORRY_RECEIPT", None), ("doc_role", "E-Way Bill", "EWAY_BILL", None),
    ("doc_role", "Delivery Challan", "DELIVERY_CHALLAN", None), ("doc_role", "DC", "DELIVERY_CHALLAN", None),
    ("doc_role", "MRN", "GOODS_RECEIPT_NOTE", None),
    ("line_origin", "Additional work", "ADDITIONAL_WORK", None), ("line_origin", "Add.", "ADDITIONAL_WORK", None),
    ("line_origin", "Not in PO/ Additional", "ADDITIONAL_WORK", None), ("line_origin", "extra item", "ADDITIONAL_WORK", None),
    ("line_origin", "Round Off", "ADJUSTMENT", "TAX_INVOICE"),
    ("charge_type", "Packing and forwarding", "PACKING_FORWARDING", None), ("charge_type", "P&F", "PACKING_FORWARDING", None),
    ("charge_type", "Transportation", "FREIGHT", None), ("charge_type", "Freight", "FREIGHT", None),
    ("charge_type", "Cartage", "FREIGHT", None), ("charge_type", "Loading", "LOADING_UNLOADING", None),
    ("charge_type", "Unloading", "LOADING_UNLOADING", None), ("charge_type", "Outstation", "OUTSTATION", None),
    ("charge_type", "Malba", "DEBRIS_DISPOSAL", None), ("charge_type", "Debris", "DEBRIS_DISPOSAL", None),
    ("charge_type", "Scaffolding", "SCAFFOLDING", None), ("charge_type", "Insurance", "INSURANCE", None),
    ("charge_type", "Mobilisation", "MOBILISATION", None), ("charge_type", "Handling", "HANDLING", None),
    ("verification_status", "work is not done", "NOT_EXECUTED", None),
    ("verification_status", "not covered in audit", "NOT_IN_SCOPE", None),
    ("verification_status", "out of audit", "NOT_IN_SCOPE", None),
    ("verification_status", "could not be checked", "NOT_VERIFIABLE", None),
    ("verification_status", "defective items are not considered", "DEFECTIVE_EXCLUDED", None),
    ("signoff_capacity", "signed in the capacity of witness", "WITNESS", None),
    ("assurance_level_stated", "do not express any assurance", "NO_ASSURANCE", None),
    ("assurance_level_stated", "does not provide any formal assurance", "NO_ASSURANCE", None),
]


def alias_norm(text: str) -> str:
    """The form aliases are matched in: lower case, punctuation and runs of space collapsed."""
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9%²']+", " ", (text or "").lower())).strip()


# ── 2. Recon's internal codes → vocabulary codes ─────────────────────────────────
# Page classes (recon_doc_pages.doc_class). TERMS_CONDITIONS and OTHER are page types, not documents.
DOC_CLASS_ROLE = {
    "PURCHASE_ORDER": "PURCHASE_ORDER", "TAX_INVOICE": "TAX_INVOICE", "INVOICE_ANNEXURE": "TAX_INVOICE",
    "PV_NARRATIVE": "PHYSICAL_VERIFICATION_REPORT", "PV_ANNEXURE_TYPED": "PHYSICAL_VERIFICATION_REPORT",
    "PV_SHEET_SCANNED": "PHYSICAL_VERIFICATION_REPORT", "PV_FIELD_SHEET": "SITE_VERIFICATION_SHEET",
    "POD": "PROOF_OF_DELIVERY", "APPROVAL_MEMO": "APPROVAL_COMMUNICATION", "DELIVERY_CHALLAN": "DELIVERY_CHALLAN",
    "GRN": "GOODS_RECEIPT_NOTE", "MEASUREMENT_SHEET": "MEASUREMENT_SHEET",
}
# Document parts (recon_doc_segments.kind). OTHER / IGNORED have no role.
SEGMENT_KIND_ROLE = {
    "PURCHASE_ORDER": "PURCHASE_ORDER", "TAX_INVOICE": "TAX_INVOICE", "PV_SECTION": "PHYSICAL_VERIFICATION_REPORT",
    "POD": "PROOF_OF_DELIVERY", "APPROVAL_MEMO": "APPROVAL_COMMUNICATION",
    "PAYMENT_ADVICE": "PAYMENT_ADVICE",
}
# Which leg each part fills, and how much a receipt can prove (vocabulary §1).
SEGMENT_KIND_LEG = {"PURCHASE_ORDER": "COMMITMENT", "TAX_INVOICE": "BILLING", "PV_SECTION": "RECEIPT",
                    "POD": "RECEIPT", "PAYMENT_ADVICE": "PAYMENT"}
SEGMENT_KIND_GRANULARITY = {"PV_SECTION": "ITEM_QTY", "POD": "CONSIGNMENT"}

# Which document each header check is ABOUT, so opening one shows that
# document's own comparison with the invoice rather than the whole case.
# A reviewer who opened the site report did not ask about the payment advice.
#
# The invoice is the spine: checks about the bill itself, and the ones that
# compare every document at once (same vendor, same store, dates in order),
# belong to it. Anything unmapped lands there too, so a new check is visible
# somewhere rather than nowhere.
CHECK_DOCUMENT = {
    "po_reference": "po", "within_po_value": "po", "single_po": "po", "payment_terms": "po",
    "pod_matches": "pod", "pod_invoice_ref_match": "pod", "delivery_timeliness": "pod",
    "receipt_variance": "pod", "grn_vs_audit": "pod",
    "payment_arithmetic": "payment", "payment_reference": "payment",
    "payment_settled_in_full": "payment",
    "approvals": "memo",
}
# Extractor layouts (extracted_json.layout) → pv_format, and the evidence layer their audit values come from.
LAYOUT_PV_FORMAT = {"jpc_typed": "AUDITOR_ANNEXURE", "matolia_scan": "WITNESSED_VENDOR_SHEET",
                    "generic": "SPREADSHEET_TABLE"}
LAYOUT_EVIDENCE_LAYER = {"jpc_typed": "TYPED_ANNEXURE", "matolia_scan": "WITNESSED_SHEET",
                         "generic": "TYPED_BODY"}
# Auditor verdicts (recon_evidence_rows.verdict) → verification_status. ADDITIONAL is VERIFIED work whose
# line_origin is ADDITIONAL_WORK (vocabulary §19: no ADDITIONAL_VERIFIED code).
VERDICT_STATUS = {"VERIFIED": "VERIFIED", "NOT_DONE": "NOT_EXECUTED", "NOT_COUNTABLE": "NOT_VERIFIABLE",
                  "NOT_COVERED": "NOT_IN_SCOPE", "ADDITIONAL": "VERIFIED"}
# A remark that puts the line out of scope (vocabulary §17: "not covered in audit", "out of audit", "as per Bata
# instructions not in scope", "certificate needed"). Recon's classifier may file these rows as NOT_COUNTABLE or
# ADDITIONAL — billing follows the classifier; the vocabulary code follows what the auditor wrote.
OUT_OF_SCOPE_REMARK = r"not in scope|out of (audit|scope)|not covered|certificate needed"
OUT_OF_SCOPE_VERDICTS = ("NOT_COVERED", "NOT_COUNTABLE", "ADDITIONAL")
# Why a line was out of scope, read from the auditor's remark (vocabulary §17).
SCOPE_SOURCE_PATTERNS = [("CLIENT_INSTRUCTION", r"instruction"), ("CERTIFICATE_PENDING", r"certificate")]
SCOPE_SOURCE_DEFAULT = "AUDITOR_SCOPE"
# Severity of a result → outcome.
SEVERITY_OUTCOME = {"OK": "PASS", "INFO": "WARN", "REVIEW": "HOLD", "BLOCKER": "FAIL"}
# Engine match methods → match_method.
MATCH_METHOD = {"EXACT": "EXACT_KEY", "ALIAS": "ALIAS", "SCORE": "RATE_SPEC", "LLM": "SEMANTIC", "HUMAN": "HUMAN"}
# Charge lines → charge_type by description, in order (vocabulary §17).
CHARGE_PATTERNS = [("PACKING_FORWARDING", r"packing|p\s*&\s*f|forwarding"), ("FREIGHT", r"transport|freight|cartage"),
                   ("LOADING_UNLOADING", r"loading"), ("OUTSTATION", r"outst?ation"),
                   ("SCAFFOLDING", r"scaffold"), ("DEBRIS_DISPOSAL", r"malba|debris"),
                   ("INSURANCE", r"insurance"), ("MOBILISATION", r"mobili[sz]ation"), ("HANDLING", r"handling")]
# Evidence-row columns → qty_role / rate_role (what the API and exports label each column with).
COLUMN_QTY_ROLE = {"po_qty": "QTY_ORDERED", "vendor_qty": "QTY_CLAIMED", "audit_qty": "QTY_VERIFIED",
                   "mounted": "QTY_MOUNTED", "unmounted": "QTY_UNMOUNTED", "damaged": "QTY_DAMAGED",
                   "qty": "QTY_INVOICED", "billed_qty": "QTY_INVOICED", "verified_qty": "QTY_VERIFIED",
                   "expected_qty": "QTY_PAYABLE"}
COLUMN_RATE_ROLE = {"rate": "RATE_LIST", "rate_after_discount": "RATE_NET", "po_rate": "RATE_PO",
                    "unit_price": "RATE_PO", "billed_rate": "RATE_INVOICED"}


def uom_code(unit: str | None) -> str | None:
    """A printed unit → canonical uom code, or None when it isn't a unit we know (flag UOM_UNPARSEABLE)."""
    n = _unit_key(unit)
    return _UOM_INDEX.get(n) if n else None


def _unit_key(unit: str | None) -> str:
    return re.sub(r"[^a-z0-9%²']", "", (unit or "").lower())


_UOM_INDEX: dict[str, str] = {}
for _k, _a, _c, _ctx in ALIASES:
    if _k == "uom":
        _UOM_INDEX.setdefault(_unit_key(_a), _c)
_UOM_FAMILY = {c: p for c, _l, _t, p in CODES["uom"]}


def uom_family(code: str | None) -> str | None:
    return _UOM_FAMILY.get(code) if code else None


def _out_of_scope(verdict: str | None, remark: str | None) -> bool:
    return verdict == "NOT_COVERED" or (verdict in OUT_OF_SCOPE_VERDICTS
                                        and bool(re.search(OUT_OF_SCOPE_REMARK, remark or "", re.I)))


def verification_status(verdict: str | None, remark: str | None = None) -> str | None:
    if _out_of_scope(verdict, remark):
        return "NOT_IN_SCOPE"
    return VERDICT_STATUS.get(verdict or "")


def scope_exclusion_source(verdict: str | None, remark: str | None) -> str | None:
    if not _out_of_scope(verdict, remark):
        return None
    for code, pat in SCOPE_SOURCE_PATTERNS:
        if re.search(pat, remark or "", re.I):
            return code
    return SCOPE_SOURCE_DEFAULT


def charge_type(description: str | None) -> str | None:
    for code, pat in CHARGE_PATTERNS:
        if re.search(pat, description or "", re.I):
            return code
    return None


_STRUCK = re.compile(r"~~\s*([\d.,]+)\s*~~\s*([\d.,]+)|\[\s*([\d.,]+)\s*\]\s*([\d.,]+)")


def value_history_from_raw(raw: str | None) -> list[dict]:
    """A handwritten overwrite in a raw cell ('~~18~~ 15' or '[548] 602') → [{was, now, kind}]."""
    out = []
    for m in _STRUCK.finditer(raw or ""):
        was, now = (m.group(1), m.group(2)) if m.group(1) else (m.group(3), m.group(4))
        try:
            out.append({"was": float(was.replace(",", "")), "now": float(now.replace(",", "")),
                        "kind": "HANDWRITTEN_CORRECTION"})
        except ValueError:
            continue
    return out


def auto_verdict(row_type: str | None, verdict: str | None, remark: str | None, audit_qty) -> str:
    """What the auditor's row says, as Recon's screens show it (rules.VerdictClassifier, default config)."""
    from decimal import Decimal

    from .rules import VerdictClassifier
    from .types import AuditVerdict, EvidenceRow, Sourced
    row = EvidenceRow(key="", item="", row_type=row_type or "po", remark=remark,
                      verdict=AuditVerdict(verdict) if verdict else None,
                      audit_qty=Sourced(value=Decimal(str(audit_qty))) if audit_qty is not None else None)
    return VerdictClassifier().classify(row).value


def backfill_auto_verdicts(cur) -> int:
    """Classify evidence rows saved before auto_verdict existed (psycopg2 cursor). Returns rows updated."""
    cur.execute("SELECT to_regclass('recon_evidence_rows') IS NOT NULL")
    if not cur.fetchone()[0]:
        return 0
    cur.execute("SELECT id, row_type, verdict, remark, audit_qty FROM recon_evidence_rows WHERE auto_verdict IS NULL")
    rows = cur.fetchall()
    for rid, row_type, verdict, remark, audit in rows:
        cur.execute("UPDATE recon_evidence_rows SET auto_verdict = %s WHERE id = %s",
                    (auto_verdict(row_type, verdict, remark, audit), rid))
    return len(rows)


def code_known(kind: str, code: str | None) -> bool:
    return code is None or any(c == code for c, *_ in CODES.get(kind, []))


# ── 3. SQL for the generated vocabulary columns ───────────────────────────────────
def _lit(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def _case_map(expr: str, mapping: dict[str, str]) -> str:
    whens = " ".join(f"WHEN {_lit(k)} THEN {_lit(v)}" for k, v in sorted(mapping.items()))
    return f"(CASE {expr} {whens} ELSE NULL END)"


def _case_regex(expr: str, patterns: list[tuple[str, str]], default: str | None = None) -> str:
    whens = " ".join(f"WHEN {expr} ~* {_lit(p)} THEN {_lit(c)}" for c, p in patterns)
    return f"(CASE {whens} ELSE {_lit(default) if default else 'NULL'} END)"


_SQL_OUT_OF_SCOPE = (
    "(coalesce(verdict, auto_verdict) = 'NOT_COVERED' OR (coalesce(verdict, auto_verdict) IN ("
    + ", ".join(_lit(v) for v in OUT_OF_SCOPE_VERDICTS) + f") AND coalesce(remark, '') ~* {_lit(OUT_OF_SCOPE_REMARK)}))")
_SQL_UNIT_KEY = "regexp_replace(lower(coalesce(unit, '')), '[^a-z0-9%²'']', '', 'g')"


def generated_sql() -> dict[tuple[str, str], str]:
    """(table, column) → SQL expression for a STORED generated column. All are immutable expressions over the
    row's own values, so every write path (extraction, read-again, reviewer correction, kind override) keeps
    them right without code."""
    uom_map = dict(_UOM_INDEX)
    fam_map = {k: _UOM_FAMILY[v] for k, v in uom_map.items()}
    return {
        ("recon_doc_pages", "doc_role"): _case_map("doc_class", DOC_CLASS_ROLE),
        ("recon_doc_segments", "doc_role"): _case_map("kind", SEGMENT_KIND_ROLE),
        ("recon_doc_segments", "recon_leg"): _case_map("kind", SEGMENT_KIND_LEG),
        ("recon_doc_segments", "receipt_granularity"): _case_map("kind", SEGMENT_KIND_GRANULARITY),
        ("recon_doc_segments", "pv_format"): _case_map("(extracted_json ->> 'layout')", LAYOUT_PV_FORMAT),
        ("recon_doc_segments", "evidence_layer"): _case_map("(extracted_json ->> 'layout')", LAYOUT_EVIDENCE_LAYER),
        # verdict = a reviewer's verdict; auto_verdict = rules.VerdictClassifier's, saved with the row
        ("recon_evidence_rows", "verification_status"):
            f"(CASE WHEN {_SQL_OUT_OF_SCOPE} THEN 'NOT_IN_SCOPE' "
            f"ELSE {_case_map('coalesce(verdict, auto_verdict)', VERDICT_STATUS)} END)",
        ("recon_evidence_rows", "scope_exclusion_source"):
            f"(CASE WHEN {_SQL_OUT_OF_SCOPE} THEN "
            f"{_case_regex('coalesce(remark, ' + _lit('') + ')', SCOPE_SOURCE_PATTERNS, SCOPE_SOURCE_DEFAULT)} "
            f"ELSE NULL END)",
        ("recon_evidence_rows", "line_origin"):
            "(CASE WHEN row_type = 'additional' OR coalesce(verdict, auto_verdict) = 'ADDITIONAL' THEN 'ADDITIONAL_WORK' "
            "ELSE 'CONTRACT_LINE' END)",
        ("recon_evidence_rows", "uom"): _case_map(_SQL_UNIT_KEY, uom_map),
        ("recon_evidence_rows", "uom_family"): _case_map(_SQL_UNIT_KEY, fam_map),
        ("recon_invoice_lines", "line_origin"): "(CASE WHEN is_charge THEN 'CHARGE' ELSE 'CONTRACT_LINE' END)",
        ("recon_invoice_lines", "charge_type"):
            f"(CASE WHEN is_charge THEN {_case_regex('description', CHARGE_PATTERNS)} ELSE NULL END)",
        ("recon_invoice_lines", "pricing_basis"):
            "(CASE WHEN is_charge AND charge_pct IS NOT NULL THEN 'PERCENT_OF_BASE' "
            "WHEN is_charge THEN 'LUMPSUM' ELSE 'UNIT_RATE' END)",
        ("recon_invoice_lines", "uom"): _case_map(_SQL_UNIT_KEY, uom_map),
        ("recon_invoice_lines", "uom_family"): _case_map(_SQL_UNIT_KEY, fam_map),
        ("recon_line_results", "outcome"): _case_map("severity", SEVERITY_OUTCOME),
        ("recon_header_checks", "check_code"): "upper(code)",
        ("recon_header_checks", "outcome"):
            f"(CASE WHEN passed THEN 'PASS' ELSE {_case_map('severity', SEVERITY_OUTCOME)} END)",
    }


# Which vocabulary kind each generated column holds (for the foreign keys sync() adds).
GENERATED_KIND = {
    ("recon_doc_pages", "doc_role"): "doc_role", ("recon_doc_segments", "doc_role"): "doc_role",
    ("recon_doc_segments", "recon_leg"): "recon_leg", ("recon_doc_segments", "receipt_granularity"): "receipt_granularity",
    ("recon_doc_segments", "pv_format"): "pv_format", ("recon_doc_segments", "evidence_layer"): "evidence_layer",
    ("recon_evidence_rows", "verification_status"): "verification_status",
    ("recon_evidence_rows", "scope_exclusion_source"): "scope_exclusion_source",
    ("recon_evidence_rows", "line_origin"): "line_origin", ("recon_evidence_rows", "uom"): "uom",
    ("recon_evidence_rows", "uom_family"): "uom_family",
    ("recon_invoice_lines", "line_origin"): "line_origin", ("recon_invoice_lines", "charge_type"): "charge_type",
    ("recon_invoice_lines", "pricing_basis"): "pricing_basis", ("recon_invoice_lines", "uom"): "uom",
    ("recon_invoice_lines", "uom_family"): "uom_family",
    ("recon_line_results", "outcome"): "recon_outcome",
    ("recon_header_checks", "check_code"): "recon_check_code", ("recon_header_checks", "outcome"): "recon_outcome",
}


# ── Database sync: seed codes and aliases, (re)build generated columns ───────────
VOCAB_DDL: tuple[str, ...] = (
    """CREATE TABLE IF NOT EXISTS vocab_codes (
        kind          TEXT NOT NULL,
        code          TEXT NOT NULL,
        label         TEXT NOT NULL,
        parent_code   TEXT,
        tier          CHAR(1) NOT NULL DEFAULT 'L' CHECK (tier IN ('N','X','L')),
        version_added TEXT NOT NULL,
        deprecated    BOOLEAN NOT NULL DEFAULT false,
        replaced_by   TEXT,
        PRIMARY KEY (kind, code)
    )""",
    # Learned aliases are tenant-scoped (scope_tenant_id set). A NULL tenant (global) alias is seeded from
    # this module only — never written from a tenant's correction (docs/bata-recon/infra_brainstorm/ANALYSIS.md V3).
    """CREATE TABLE IF NOT EXISTS vocab_aliases (
        alias_id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        kind              TEXT NOT NULL,
        code              TEXT NOT NULL,
        alias_text        TEXT NOT NULL,
        alias_norm        TEXT NOT NULL,
        scope_tenant_id   UUID,
        scope_supplier_id UUID,
        context_doc_role  TEXT,
        source            TEXT NOT NULL DEFAULT 'SEED' CHECK (source IN ('SEED','HUMAN','LEARNED')),
        confirmed_by      VARCHAR(100),
        created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
        FOREIGN KEY (kind, code) REFERENCES vocab_codes (kind, code),
        CHECK (source = 'SEED' OR scope_tenant_id IS NOT NULL)
    )""",
    """CREATE UNIQUE INDEX IF NOT EXISTS vocab_aliases_uniq ON vocab_aliases
        (kind, alias_norm, COALESCE(context_doc_role, ''),
         COALESCE(scope_tenant_id, '00000000-0000-0000-0000-000000000000'::uuid),
         COALESCE(scope_supplier_id, '00000000-0000-0000-0000-000000000000'::uuid))""",
    """CREATE TABLE IF NOT EXISTS vocab_meta (
        key   TEXT PRIMARY KEY,
        value TEXT NOT NULL,
        at    TIMESTAMPTZ NOT NULL DEFAULT now()
    )""",
    # Handwritten overwrites and reviewer corrections, kept per row: [{was, now, kind, by?, at?}].
    "ALTER TABLE recon_evidence_rows ADD COLUMN IF NOT EXISTS value_history JSONB",
)


def _rows_codes() -> list[tuple]:
    return [(kind, code, label, parent, tier, VOCAB_VERSION)
            for kind, items in CODES.items() for code, label, tier, parent in items]


def _rows_aliases() -> list[tuple]:
    seen, out = set(), []
    for kind, text, code, ctx in ALIASES:
        key = (kind, alias_norm(text), ctx or "")
        if key in seen or not alias_norm(text):
            continue
        seen.add(key)
        out.append((kind, code, text, alias_norm(text), ctx))
    return out


def sync(cur) -> dict:
    """Bring the database in line with this module (psycopg2 cursor; idempotent; safe to run on every start).

    1. vocab tables; 2. upsert every code (never delete — codes dropped here are only marked deprecated);
    3. upsert SEED aliases; 4. (re)build the generated vocabulary columns when MAPPING_VERSION changed;
    5. foreign keys from those columns to vocab_codes."""
    for stmt in VOCAB_DDL:
        cur.execute(stmt)
    codes = _rows_codes()
    for row in codes:
        cur.execute(
            """INSERT INTO vocab_codes (kind, code, label, parent_code, tier, version_added)
               VALUES (%s, %s, %s, %s, %s, %s)
               ON CONFLICT (kind, code) DO UPDATE SET label = EXCLUDED.label, parent_code = EXCLUDED.parent_code,
                   tier = EXCLUDED.tier, deprecated = false""", row)
    live = {(k, c) for k, c, *_ in codes}
    cur.execute("SELECT kind, code FROM vocab_codes WHERE NOT deprecated")
    gone = [r for r in cur.fetchall() if (r[0], r[1]) not in live]
    for kind, code in gone:
        cur.execute("UPDATE vocab_codes SET deprecated = true WHERE kind = %s AND code = %s", (kind, code))
    for kind, code, text, norm_, ctx in _rows_aliases():
        cur.execute(
            """INSERT INTO vocab_aliases (kind, code, alias_text, alias_norm, context_doc_role, source)
               VALUES (%s, %s, %s, %s, %s, 'SEED')
               ON CONFLICT (kind, alias_norm, COALESCE(context_doc_role, ''),
                   COALESCE(scope_tenant_id, '00000000-0000-0000-0000-000000000000'::uuid),
                   COALESCE(scope_supplier_id, '00000000-0000-0000-0000-000000000000'::uuid))
               DO UPDATE SET code = EXCLUDED.code, alias_text = EXCLUDED.alias_text""",
            (kind, code, text, norm_, ctx))

    cur.execute("SELECT value FROM vocab_meta WHERE key = 'mapping_version'")
    row = cur.fetchone()
    rebuild = not row or row[0] != MAPPING_VERSION
    built = 0
    for (table, col), expr in generated_sql().items():
        cur.execute("SELECT 1 FROM information_schema.columns WHERE table_name = %s AND column_name = %s",
                    (table, col))
        exists = cur.fetchone() is not None
        if exists and not rebuild:
            continue
        if exists:
            cur.execute(f'ALTER TABLE {table} DROP COLUMN "{col}"')
        cur.execute(f'ALTER TABLE {table} ADD COLUMN "{col}" TEXT GENERATED ALWAYS AS ({expr}) STORED')
        built += 1
    for (table, col), kind in GENERATED_KIND.items():
        kind_col, fk = f"{col}_kind", f"fk_{table}_{col}_vocab"
        cur.execute("SELECT 1 FROM information_schema.columns WHERE table_name = %s AND column_name = %s",
                    (table, kind_col))
        if cur.fetchone() is None:
            cur.execute(f"ALTER TABLE {table} ADD COLUMN \"{kind_col}\" TEXT GENERATED ALWAYS AS ({_lit(kind)}) STORED")
        cur.execute("SELECT 1 FROM pg_constraint WHERE conname = %s", (fk,))
        if cur.fetchone() is None:
            cur.execute(f'ALTER TABLE {table} ADD CONSTRAINT {fk} FOREIGN KEY ("{kind_col}", "{col}") '
                        f"REFERENCES vocab_codes (kind, code)")
    backfilled = backfill_auto_verdicts(cur)
    cur.execute(
        """INSERT INTO vocab_meta (key, value) VALUES ('mapping_version', %s), ('vocab_version', %s)
           ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, at = now()""",
        (MAPPING_VERSION, VOCAB_VERSION))
    return {"codes": len(codes), "deprecated": len(gone), "aliases": len(_rows_aliases()), "columns_built": built,
            "verdicts_backfilled": backfilled}
