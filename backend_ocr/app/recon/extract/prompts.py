"""Every recon prompt in one place. Bump PROMPT_VERSION when a prompt changes:
it is stored with each extraction so a re-read can be targeted."""

PROMPT_VERSION = "p3"

_NUMBERS = ("Copy every number exactly as printed — keep Indian grouping (1,26,312.00), do not round, do not "
            "correct arithmetic, do not fill in values that are not printed (use null). ")

INVOICE_HEADER = (
    "You read the first page of a vendor tax invoice issued in India. " + _NUMBERS +
    """Return JSON:
{"invoice_no": "...", "invoice_date": "...", "irn": "...|null", "vendor": {"name": "...", "gstin": "..."},
 "buyer_gstin": "...", "place_of_supply": "state name or code", "po_ref": "PO number as printed|null",
 "payment_terms": "...|null",
 "header_lines": [{"sno": 1, "description": "...", "hsn": "...", "unit": "...", "qty": "...", "rate": "...",
                   "amount": "..."}],
 "taxable": "...", "cgst": "...", "sgst": "...", "igst": "...", "tax_rate": "total GST % e.g. 18",
 "round_off": "...", "total": "...",
 "corrections": [{"field": "invoice_no|date|amount|other", "printed": "...", "handwritten": "..."}]}
`corrections`: any printed value that has been struck through or overwritten by hand.""")

INVOICE_ANNEXURE = (
    "You read the detail page(s) of a vendor invoice: a table of items with quantity, unit, rate and amount. "
    + _NUMBERS +
    """Return JSON:
{"invoice_no": "...|null", "po_ref": "...|null",
 "lines": [{"sno": 1, "description": "...", "unit": "...", "qty": "...", "rate": "...", "amount": "...",
            "hsn": "...|null", "after_subtotal": false}],
 "printed_subtotal": "the first 'Sub Total' printed after the item rows|null",
 "corrections": [{"field": "...", "printed": "...", "handwritten": "..."}]}
Return every printed row in order, including rows with quantity 0 and rows that look unrelated to the PO.
`after_subtotal`: true for rows printed below the first Sub Total (packing, transport, installation, etc.).
Do not include tax rows (CGST/SGST/IGST) or total rows as lines.""")

SHEET_ROWS = (
    "You read one page of an auditor's site-verification sheet for a Bata store: a printed spreadsheet, scanned, "
    "with handwritten values in some cells. Read the item table ROW BY ROW. For each printed row return every cell "
    "of THAT row together, left to right: vendor_qty ('Vendor Qty', handwritten or typed), audit_qty ('Audit Qty'), "
    "remark ('Remarks' column only), asset_code, item (ITEM NAME), unit, po_qty (QTY), rate (RATE), "
    "rate_after_discount (the 'AFTER 5% DISC' column), amount (the row's own 'TOTAL' column, "
    "exactly as printed — never computed). " + _NUMBERS +
    """Never take a value from a neighbouring row. A blank cell is null; '####' is null.
Return EVERY row top to bottom, including rows with 0 and rows under an 'Additional / Not in PO' heading
(in_additional_block true). Total / G Total / Amount in words lines are not rows; stamps, signatures and the footer
below the table are not rows, and their text is never a remark.
If a number is struck through, return the value that is NOT struck through and put the whole cell in audit_qty_raw.
If you cannot read a handwritten cell with confidence set legible=false.
Return JSON:
{"section_title": "the bold title above the table, e.g. 'FURNITURE PO'",
 "vendor": {"name": "the name in the 'MATERIAL Vendor' row", "gstin": "the GSTIN beside 'GST NO.' on the right — never the 'BATA GST NO.'"},
 "store_sn": "Shop No|null", "site_name": "...|null", "verification_date": "...|null",
 "rows": [{"row": 1, "vendor_qty": "as written|null", "audit_qty": "as written|null",
           "audit_qty_raw": "the cell exactly, e.g. '348+102=450'", "remark": null, "asset_code": null,
           "item": "...", "unit": "...|null", "po_qty": "...", "rate": "...|null", "rate_after_discount": "...|null",
           "amount": "the printed TOTAL for this row|null",
           "in_additional_block": false, "legible": true}]}""")

FIELD_SHEET = (
    "You read a signed site-verification field sheet. Each item row has boxes 'Mounted', 'Unmounted', 'Damaged', "
    "'Total' filled by hand (a dash means 0) and a notes column. " + _NUMBERS +
    """Return JSON: {"vendor": "...", "work": "...", "rows": [{"sno": 9, "item": "...", "qty_as_per_po": "...",
"vendor_qty": "...", "mounted": "...", "unmounted": "...", "damaged": "...", "total": "...", "note": "...|null"}]}""")

POD = (
    "You read a proof-of-delivery / courier waybill / lorry receipt photo. " + _NUMBERS +
    """Return JSON:
{"waybill_no": "...", "carrier": "...", "ship_date": "...", "consignor": {"name": "...", "gstin": "..."},
 "consignee": {"name": "...", "gstin": "..."}, "invoice_nos": ["..."], "total_invoice_value": "...",
 "packages": "...", "weight": "...",
 "receipt": {"stamp_text": "text of the receiving stamp|null", "receiver": "handwritten name|null",
             "date": "handwritten receipt date|null"}}""")

MEMO = (
    "You read an internal approval memo. " +
    """Return JSON: {"memo_ref": "...", "subject": "...", "from": "...", "to": ["..."], "date": "...",
"vendor_name": "...|null", "body": "...",
"approvals": [{"approver": "...", "status": "...", "date": "...", "remark": "...|null"}]}""")

GENERIC = (
    "You read one document that a finance team attached while reconciling a vendor's invoice against a purchase "
    "order. Say what it is and pull out anything that states quantities of items delivered, installed or verified. "
    + _NUMBERS +
    """Return JSON: {"label": "short document type, e.g. 'Delivery challan', 'Measurement sheet'",
"summary": "one sentence", "key_values": {"name": "value"},
"rows": [{"item": "...", "unit": "...|null", "qty": "...", "remark": "...|null"}]}
`rows` only when the document lists items with quantities; otherwise []""")

ADJUDICATE = (
    "You match one line from a vendor document to the purchase-order line it refers to. Vendors and auditors "
    "word items differently (prefixes like 'Supply & Installation of', dropped brand names, spelling mistakes, "
    "truncated text). Sizes and types that differ (600 vs 1200, Type D vs Type E) usually mean a different item — "
    "pick it only if the rate and everything else clearly agree, and then name the conflict in `reason`. "
    """Return JSON: {"po_line_id": "id of the matching PO line or null if none fits", "confidence": 0-1,
"reason": "one short sentence"}""")
