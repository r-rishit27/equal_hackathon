"""Read the vendor master and invoice control evidence for a CFO workflow run."""

import re

from psycopg2.extras import RealDictCursor

from ..config import get_conn, put_conn


def _control(label, passed, detail, *, blocked=False):
    return {"label": label, "state": "ready" if passed else ("blocked" if blocked else "review"), "detail": detail}


def _stage(key, label, items):
    states = {item["state"] for item in items}
    state = next((level for level in ("blocked", "review") if level in states), "ready")
    detail = {"ready": "All controls passed.", "review": "Review the outstanding controls.",
              "blocked": "Resolve the flagged controls before proceeding."}[state]
    return {"id": key, "label": label, "state": state, "detail": detail, "items": items}


def evaluate(row):
    gst = bool(row["gst_verified"])
    pan = bool(re.fullmatch(r"[A-Z]{5}[0-9]{4}[A-Z]", (row["pan"] or "").strip().upper()))
    bank = bool(row["bank_verified"])
    kyc = _stage("kyc", "Vendor identification & KYC", [
        _control("GST registration", gst, "Verified GST registration on file." if gst else "Verified GST registration required."),
        _control("Permanent Account Number (PAN)", pan, "PAN on file passes the format check." if pan else "Valid PAN required for the vendor master."),
        _control("Beneficiary bank account", bank, "Designated account verified." if bank else "Verify the designated beneficiary account."),
    ])
    setup = _stage("setup", "Vendor master setup", [
        _control("Contact details", row["contact"], "Contact channel on file." if row["contact"] else "Add a vendor email address or telephone number."),
        _control("KYC data extraction", row["extracted"], "Extracted identity evidence on file." if row["extracted"] else "No extracted identity evidence found."),
        _control("Vendor master storage", row["vendor_name"] and pan and row["gstin"] and row["bank_recorded"],
                 "Vendor master: " + (row["vendor_name"] or "Unlinked") + ". Checks stored PAN, GSTIN and beneficiary account details."),
    ])
    recon = row["recon_status"]
    approval = str(row["status"] or "").upper()
    payment = str(row["payment_status"] or "").upper()
    reconciled = recon in ("RECONCILED", "ACKNOWLEDGED")
    gates = [kyc, setup, _stage("recon", "Invoice reconciliation", [
        _control("Reconciliation case", reconciled, recon.replace("_", " ").title() if recon else "No reconciliation case linked to this invoice.")]),
        _stage("approval", "Invoice approval", [
            _control("Approval decision", approval == "APPROVED", approval.title() if approval else "Approval decision unavailable.", blocked=approval == "REJECTED")])]
    outstanding = [stage["label"] for stage in gates if stage["state"] != "ready"]
    return [*gates, _stage("payment", "Payment readiness", [
        _control("Upstream controls", not outstanding, "Review: " + ", ".join(outstanding) if outstanding else "All preceding controls recorded.", blocked=bool(outstanding)),
        _control("Disbursement status", payment in ("UNPAID", "PENDING"), payment.replace("_", " ").title() if payment else "Payment status unavailable.", blocked=payment in ("FAILED", "BLOCKED", "PAID")),
        _control("Invoice amount", (row["total_amount"] or 0) > 0, f'{row["currency_code"] or "INR"} {row["total_amount"]}' if row["total_amount"] is not None else "Invoice amount missing.", blocked=row["total_amount"] is not None and row["total_amount"] <= 0),
    ])]


def run(tenant, brand, invoice):
    conn = get_conn()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT i.status, i.payment_status, i.total_amount, i.currency_code, s.name AS vendor_name,
                       s.pan, COALESCE(g.gstin, s.gstn) AS gstin,
                       CASE WHEN g.gstin IS NULL THEN s.status::text = 'VERIFIED'
                            ELSE upper(g.status::text) IN ('VERIFIED','ACTIVE') END AS gst_verified,
                       COALESCE(b.verified, s.bank_verified, false) AS bank_verified,
                       COALESCE(b.account_number, s.bank_account) IS NOT NULL AS bank_recorded,
                       (NULLIF(trim(s.email), '') IS NOT NULL OR EXISTS (
                           SELECT 1 FROM supplier_contacts c WHERE c.tenant_id=i.tenant_id AND c.supplier_id=i.supplier_id
                             AND COALESCE(NULLIF(trim(c.email), ''), NULLIF(trim(c.phone), '')) IS NOT NULL)) AS contact,
                       EXISTS (SELECT 1 FROM comm_extractions e, jsonb_array_elements(e.claims) claim
                               WHERE e.tenant_id=i.tenant_id AND e.supplier_id=i.supplier_id
                                 AND claim->>'scope' IN ('vendor_pan','vendor_gstin','vendor_bank')) AS extracted,
                       r.status AS recon_status
                FROM fact_invoices i
                LEFT JOIN dim_suppliers s ON (s.tenant_id,s.supplier_id)=(i.tenant_id,i.supplier_id)
                LEFT JOIN supplier_gstins g ON (g.tenant_id,g.supplier_id)=(i.tenant_id,i.supplier_id) AND g.is_primary
                LEFT JOIN supplier_bank_accounts b ON (b.tenant_id,b.supplier_id)=(i.tenant_id,i.supplier_id) AND b.is_primary
                LEFT JOIN recon_cases r ON (r.tenant_id,r.bill_id)=(i.tenant_id,i.invoice_id)
                WHERE i.tenant_id=%s AND i.invoice_id=%s AND (%s::uuid IS NULL OR i.brand_id=%s::uuid)
            """, (tenant, invoice, brand, brand))
            row = cur.fetchone()
            return evaluate(row) if row else None
    finally:
        put_conn(conn)
