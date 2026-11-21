"""Deterministic advisory checks over a persisted invoice snapshot."""

from datetime import date
import re

GSTIN = re.compile(r"[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]")


def evaluate(bill):
    gstin = (bill["gstn"] or "").strip().upper()
    has_gstin = GSTIN.fullmatch(gstin) is not None
    has_amount = bill["total_amount"] is not None and bill["total_amount"] > 0
    due = bill["due_date"]
    overdue = due is not None and due < date.today()
    status = str(bill["status"] or "").upper()
    payment = str(bill["payment_status"] or "").upper()
    return [
        {"id": "verification", "label": "Vendor verification",
         "state": "ready" if bill["vendor_name"] else "review",
         "detail": bill["vendor_name"] or "Vendor record is missing."},
        {"id": "gst", "label": "GSTIN format", "state": "ready" if has_gstin else "review",
         "detail": "Vendor GSTIN is present in the expected format." if has_gstin
                   else "Check the vendor GSTIN or confirm that it is exempt."},
        {"id": "analytics", "label": "Invoice amount", "state": "ready" if has_amount else "review",
         "detail": f'{bill["currency_code"] or "INR"} {bill["total_amount"]}' if has_amount
                   else "Review the invoice amount."},
        {"id": "payable", "label": "Approval and payment", "state": "ready" if status == "APPROVED" else "review",
         "detail": f'{status or "Unknown approval status"} · {payment or "No payment status"}'
                   + (" · Past due date" if overdue and payment != "PAID" else "")},
    ]
