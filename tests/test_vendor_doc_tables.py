"""Spreadsheet parsing for vendor documents (core/vendor_doc_tables.py) — no DB."""
import datetime as dt
import io

import openpyxl

from backend_ocr.app.core.vendor_doc_tables import _coerce_text, is_spreadsheet, parse_spreadsheet


def _xlsx(rows_by_sheet):
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for name, rows in rows_by_sheet.items():
        ws = wb.create_sheet(name)
        for r in rows:
            ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_is_spreadsheet():
    assert is_spreadsheet("Rates.XLSX") and is_spreadsheet("a.csv") and is_spreadsheet("m.xlsm")
    assert not is_spreadsheet("contract.pdf") and not is_spreadsheet(None)


def test_number_text_is_stored_as_number_but_identifiers_stay_text():
    assert _coerce_text("1,08,000") == 108000
    assert _coerce_text("₹ 5,000.50") == 5000.5
    assert _coerce_text("Rs. 250") == 250
    assert _coerce_text("(1,200)") == -1200
    assert _coerce_text("-42") == -42
    assert _coerce_text("0105") == "0105"                    # leading zero: an identifier
    assert _coerce_text("123456789012345678") == "123456789012345678"  # account number
    assert _coerce_text("07AVMPS4714J1Z4") == "07AVMPS4714J1Z4"
    assert _coerce_text("12%") == "12%"
    assert _coerce_text("  ") is None


def test_xlsx_title_row_skipped_header_found_and_every_sheet_read():
    data = _xlsx({
        "Resources": [
            ["Vendor resource list Sep'26"],
            [],
            ["Name", "Role", "Rate", "Start", None],
            ["Asha", "Dev", 85000, dt.datetime(2026, 9, 1), "note"],
            ["Ravi", "QA", "60,000", None, None],
        ],
        "Summary": [["Total", 145000]],
    })
    tables = parse_spreadsheet("list.xlsx", data)
    assert len(tables) == 2
    meta, rows = tables[0]
    assert meta["sheet_name"] == "Resources" and meta["header_row"] == 3
    assert [c["name"] for c in meta["columns"]] == ["Name", "Role", "Rate", "Start", "Column E"]
    assert meta["columns"][2]["letter"] == "C"
    assert rows[0] == (4, {"Name": "Asha", "Role": "Dev", "Rate": 85000, "Start": "2026-09-01", "Column E": "note"})
    assert rows[1] == (5, {"Name": "Ravi", "Role": "QA", "Rate": 60000})
    assert meta["row_count"] == 2 and not meta["truncated"]


def test_csv_with_semicolons_and_duplicate_headers():
    data = "Item;Amount;Amount\nA;1.000;2\nB;3;4\n".encode("utf-8-sig")
    (meta, rows), = parse_spreadsheet("x.csv", data)
    assert [c["name"] for c in meta["columns"]] == ["Item", "Amount", "Amount (2)"]
    assert rows[1] == (3, {"Item": "B", "Amount": 3, "Amount (2)": 4})


def test_empty_sheet():
    (meta, rows), = parse_spreadsheet("e.xlsx", _xlsx({"Blank": []}))
    assert rows == [] and meta["row_count"] == 0
