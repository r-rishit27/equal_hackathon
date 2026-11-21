"""Bank statement parsing, narration parsing and detectors (edge cases E2, E3, E5, E6)."""
from __future__ import annotations

from decimal import Decimal as D

from backend_ocr.app.receivables.bank_statement import parse_narration, parse_statement
from backend_ocr.app.receivables.detectors import classify_non_receipt, is_bounce


def test_narration_neft():
    m = parse_narration("NEFT-HDFCN52026111512345678-ACME TRADING PVT LTD-INV 1045")
    assert m["method"] == "NEFT" and m["utr"] == "HDFCN52026111512345678"
    assert m["payer_name"].startswith("ACME TRADING")


def test_narration_upi():
    m = parse_narration("UPI/631512345678/ACME TRADING/acme@okhdfc/Payment")
    assert m["method"] == "UPI" and m["utr"] == "631512345678" and m["payer_name"] == "ACME TRADING"


def test_narration_imps_p2a():
    m = parse_narration("IMPS/P2A/631512345678/ACMETRADIN/HDFC")
    assert m["method"] == "IMPS" and m["payer_name"] == "ACMETRADIN"


def test_narration_cheque_no_payer():
    m = parse_narration("BY CLG 004512")
    assert m["method"] == "CHQ" and m["payer_name"] is None


CSV = b"""Statement of account
Account No,XXXX1234
Date,Narration,Chq/Ref No,Value Dt,Withdrawal Amt,Deposit Amt,Closing Balance
15/11/26,NEFT-HDFCN52026111512345678-ACME TRADING-INV 1045,HDFCN52026111512345678,15/11/26,,"1,18,000.00","5,00,000.00"
15/11/26,UPI/631512345678/BETA RETAIL/beta@ok/x,631512345678,15/11/26,,500.00,
15/11/26,UPI/631512345678/BETA RETAIL/beta@ok/x,631512345678,15/11/26,,500.00,
16/11/26,CHQ RETURN 004512 ACME,004512,16/11/26,"59,000.00",,
16/11/26,TO VENDOR PAYMENT,,16/11/26,"10,000.00",,
"""


def test_parse_statement_credits_and_bounces():
    out = parse_statement(CSV, "stmt.csv")
    credits, bounces = out["credits"], out["bounces"]
    assert [c["amount"] for c in credits] == [D("118000.00"), D("500.00"), D("500.00")]
    # E3: two identical credits are both kept, with different fingerprints
    assert credits[1]["fingerprint"] != credits[2]["fingerprint"]
    # E2: re-parsing gives identical fingerprints
    again = parse_statement(CSV, "stmt.csv")["credits"]
    assert [c["fingerprint"] for c in again] == [c["fingerprint"] for c in credits]
    # E5: only the returned cheque is a bounce; the vendor payment is ignored (E7)
    assert len(bounces) == 1 and bounces[0]["amount"] == D("59000.00")


def test_parse_statement_xlsx_amount_with_drcr(tmp_path):
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.append(["Txn Date", "Description", "Amount", "Dr/Cr"])
    ws.append(["2026-11-15", "RTGS/UTIBR52026111500012345/ACME TRADING", "118000", "CR"])
    ws.append(["2026-11-15", "ATM WDL", "2000", "DR"])
    p = tmp_path / "s.xlsx"
    wb.save(p)
    credits = parse_statement(p.read_bytes(), "s.xlsx")["credits"]
    assert len(credits) == 1 and credits[0]["method"] == "RTGS"


def test_non_receipts():                                            # E6
    assert classify_non_receipt("INT.PD:01-10-2026 TO 31-10-2026")
    assert classify_non_receipt("AUTO SWEEP FROM FD 1234")
    assert classify_non_receipt("REFUND FROM AMAZON")
    assert classify_non_receipt("NEFT-HDFCN520261115-INTERNATIONAL TRADERS") is None
    assert classify_non_receipt("NEFT-HDFCN520261115-ACME TRADING") is None


def test_bounce():
    assert is_bounce("CHQ RETURN 004512") and not is_bounce("NEFT TO VENDOR")


def test_payer_starting_with_po_is_a_name_not_a_reference():
    # Pothys's NEFT came through as "BATA INDIA LIMITED" (the beneficiary) because
    # the PO-reference rule ate POTHYS (Bata dry run, 2026-11-17).
    m = parse_narration("NEFT CR-UTIB0000047-POTHYS RETAIL PRIVATE LIMITED-BATA INDIA LIMITED-AXISCN1422960051")
    assert m["payer_name"].startswith("POTHYS RETAIL")
    assert parse_narration("NEFT CR-SBIN0000804-TAMILNADU POLICE MASTER CANTEEN-X")["payer_name"].startswith("TAMILNADU")
    assert parse_narration("NEFT/PO4500012345/ACME TRADING")["payer_name"] == "ACME TRADING"
