"""GRN ingest, the RECEIPT leg (plan §7).

Bata's extract has not arrived, so the point of these tests is the *mechanism*:
a declared mapping must win over inference, a renamed column must surface, and
a row that cannot be used must be reported rather than dropped.
"""
from decimal import Decimal as D

import pytest

from backend_ocr.app.recon import grn


# ── inference (the fallback) ──────────────────────────────────────────────────

def test_obvious_headers_are_inferred():
    m = grn.infer_mapping(["GRN No", "PO Number", "Item Code", "Received Qty", "Rate", "Amount"])
    assert m.source == "inferred"
    assert m.columns["po_number"] == "PO Number"
    assert m.columns["qty_received"] == "Received Qty"
    assert not m.missing()


def test_inference_tolerates_spacing_and_case():
    m = grn.infer_mapping(["po  number", "QTY RECEIVED"])
    assert m.columns["po_number"] == "po  number"
    assert m.columns["qty_received"] == "QTY RECEIVED"


def test_unrecognisable_headers_leave_required_fields_missing():
    m = grn.infer_mapping(["Col1", "Col2", "Col3"])
    assert set(m.missing()) == {"po_number", "qty_received"}


def test_a_column_is_not_claimed_by_two_fields():
    m = grn.infer_mapping(["Qty", "Rate", "Amount"])
    assert len(set(m.columns.values())) == len(m.columns)


# ── declared mapping (the point of the design) ────────────────────────────────

def test_a_declared_mapping_beats_inference():
    """The client's own column names decide, not our guesses.

    Here 'Quantity' would be inferred as the received quantity, but the extract
    actually puts it in 'Qty Passed' — a declared mapping must win outright.
    """
    cols = ["PO", "Quantity", "Qty Passed"]
    m = grn.resolve_mapping(cols, declared={"po_number": "PO", "qty_received": "Qty Passed"})
    assert m.source == "declared"
    assert m.columns["qty_received"] == "Qty Passed"


def test_a_declared_column_that_is_absent_is_reported_not_ignored():
    """A renamed column in the client's export must surface as a mapping error.

    Silently dropping it would understate what was received, and understating
    the receipt is the direction that makes an overpayment look acceptable.
    """
    m = grn.resolve_mapping(["PO", "Qty Passed"],
                            declared={"po_number": "PO", "qty_received": "Qty Passed",
                                      "amount": "Line Value"})
    assert m.missing_columns == {"amount": "Line Value"}
    assert not m.missing(), "the required fields are still satisfied"


def test_a_declared_mapping_missing_a_required_field_fails_loudly():
    m = grn.resolve_mapping(["PO", "Something"], declared={"po_number": "PO"})
    lines, problems = grn.parse_rows([{"PO": "4500087255"}], m)
    assert lines == []
    assert "qty_received" in problems[0]


# ── parsing rows ──────────────────────────────────────────────────────────────

MAP = grn.Mapping(columns={"po_number": "PO", "qty_received": "Qty", "rate": "Rate",
                           "amount": "Amount", "item_code": "Code", "grn_number": "GRN"})


def test_rows_parse_with_indian_number_formatting():
    rows = [{"PO": "4500087255", "Qty": "1,200.500", "Rate": "620", "Amount": "7,44,310.00",
             "Code": "AHU-85", "GRN": "GRN/1"}]
    lines, problems = grn.parse_rows(rows, MAP)
    assert not problems
    assert lines[0].qty_received == D("1200.500")
    assert lines[0].amount == D("744310.00")


def test_a_row_without_a_po_is_reported_not_silently_dropped():
    lines, problems = grn.parse_rows([{"PO": "", "Qty": "5"}], MAP)
    assert lines == [] and "row 1" in problems[0] and "PO" in problems[0]


def test_a_row_with_an_unreadable_quantity_is_reported():
    """'####' is a spreadsheet overflow, not a zero (vocabulary §16)."""
    lines, problems = grn.parse_rows([{"PO": "P1", "Qty": "####"}], MAP)
    assert lines == [] and "quantity" in problems[0]


def test_good_rows_survive_a_bad_neighbour():
    rows = [{"PO": "P1", "Qty": "10"}, {"PO": "", "Qty": "7"}, {"PO": "P2", "Qty": "3"}]
    lines, problems = grn.parse_rows(rows, MAP)
    assert [l.po_number for l in lines] == ["P1", "P2"]
    assert len(problems) == 1


# ── receipt_total: what the ₹100 check compares against ──────────────────────

def test_total_prefers_the_printed_amount():
    lines, _ = grn.parse_rows([{"PO": "P1", "Qty": "10", "Rate": "100", "Amount": "995"}], MAP)
    assert grn.receipt_total(lines) == D("995"), "the extract's own figure wins over qty x rate"


def test_total_falls_back_to_qty_times_rate():
    lines, _ = grn.parse_rows([{"PO": "P1", "Qty": "10", "Rate": "100"}], MAP)
    assert grn.receipt_total(lines) == D("1000")


def test_total_is_none_when_there_is_no_value_at_all():
    """None makes the variance check abstain; zero would compare against nothing.

    Comparing an invoice to a receipt total of zero would fail every invoice by
    more than ₹100 — the worst possible default.
    """
    lines, _ = grn.parse_rows([{"PO": "P1", "Qty": "10"}], MAP)
    assert grn.receipt_total(lines) is None


def test_total_sums_across_lines():
    rows = [{"PO": "P1", "Qty": "1", "Amount": "100"}, {"PO": "P1", "Qty": "1", "Amount": "250.50"}]
    lines, _ = grn.parse_rows(rows, MAP)
    assert grn.receipt_total(lines) == D("350.50")


def test_required_fields_are_the_two_that_make_a_row_usable():
    assert set(grn.REQUIRED) == {"po_number", "qty_received"}


# ── GRN vs the audit report (R3/R8) ──────────────────────────────────────────

class _Row:
    """Stand-in for types.EvidenceRow — only the fields the comparison reads."""
    def __init__(self, item, audit, asset_code=None):
        self.item, self.asset_code = item, asset_code
        self.audit_qty = type("S", (), {"value": D(audit)})() if audit is not None else None


def _grn(po="P1", qty="10", code=None, desc=None):
    return grn.GrnLine(po_number=po, qty_received=D(qty), item_code=code, description=desc)


def test_matching_quantities_produce_no_finding():
    out = grn.compare_with_audit([_grn(code="AHU-85", qty="2")],
                                 [_Row("Ductable AHU", "2", asset_code="AHU-85")])
    assert out == []


def test_item_code_matching_beats_description():
    """Descriptions differ wildly between an ERP extract and an auditor's sheet."""
    out = grn.compare_with_audit([_grn(code="AHU-85", qty="2", desc="AHU UNIT 8.5TR")],
                                 [_Row("Ductable AHU unit with ODU", "2", asset_code="AHU-85")])
    assert out == [], "the same asset code means the same line, whatever the wording"


def test_a_quantity_difference_is_reported_against_the_grn():
    out = grn.compare_with_audit([_grn(code="PIPE", qty="460")],
                                 [_Row("Piping", "441.9", asset_code="PIPE")])
    assert len(out) == 1
    d = out[0]
    assert d.kind == "QTY_DIFFERS" and d.certified == D("441.9") and d.received == D("460")


def test_a_grn_line_with_no_certified_quantity_is_the_finding_that_matters():
    """Stock received against nothing the auditor verified."""
    out = grn.compare_with_audit([_grn(code="EXTRA", qty="5")],
                                 [_Row("Piping", "10", asset_code="PIPE")])
    kinds = {d.kind for d in out}
    assert "RECEIVED_NOT_CERTIFIED" in kinds


def test_a_certified_line_absent_from_the_grn_is_reported():
    out = grn.compare_with_audit([_grn(code="PIPE", qty="10")],
                                 [_Row("Piping", "10", asset_code="PIPE"),
                                  _Row("Hooter", "1", asset_code="MCP")])
    assert [d.kind for d in out] == ["CERTIFIED_NOT_RECEIVED"]
    assert out[0].certified == D("1")


def test_a_blank_audit_quantity_is_not_a_disagreement():
    """The auditor left it blank; that is handled by the verdict rules, not here."""
    assert grn.compare_with_audit([_grn(code="PIPE", qty="10")],
                                  [_Row("Piping", None, asset_code="PIPE")]) == []


def test_zero_certified_and_absent_from_grn_is_not_reported():
    """Nothing was certified and nothing was received — they agree."""
    assert grn.compare_with_audit([], [_Row("Not done", "0", asset_code="X")]) == []


def test_description_matching_is_used_when_no_codes_are_printed():
    out = grn.compare_with_audit([_grn(desc="Core  Cutting", qty="4")],
                                 [_Row("core cutting", "4")])
    assert out == []


def test_tolerance_is_respected():
    out = grn.compare_with_audit([_grn(code="P", qty="10.005")], [_Row("x", "10", asset_code="P")],
                                 qty_tol=D("0.01"))
    assert out == []


# ── load_extract: choosing a sheet and reporting what happened ───────────────

def _sheet(name, columns, rows):
    return ({"sheet_name": name, "columns": columns}, list(enumerate(rows, start=2)))


DATA = [{"PO": "4500087255", "Qty": "2", "Amount": "2,96,000.00"},
        {"PO": "4500087255", "Qty": "441.9", "Amount": "2,73,978.00"}]


def test_a_single_mappable_sheet_loads():
    r = grn.load_extract([_sheet("GRN", ["PO", "Qty", "Amount"], DATA)])
    assert r.ok and len(r.lines) == 2 and r.sheet == "GRN"
    assert r.rows_read == 2 and not r.problems


def test_the_data_sheet_wins_over_a_cover_sheet():
    """MSD exports carry parameter and cover tabs; the mappable one must win."""
    sheets = [_sheet("Parameters", ["Setting", "Value"], [{"Setting": "Company", "Value": "Bata"}]),
              _sheet("GRN Lines", ["PO", "Qty", "Amount"], DATA)]
    r = grn.load_extract(sheets)
    assert r.sheet == "GRN Lines" and len(r.lines) == 2
    assert any("Parameters" in s for s in r.rejected_sheets), "the skipped tab must be named"


def test_the_sheet_with_more_usable_rows_wins():
    sheets = [_sheet("Partial", ["PO", "Qty"], [{"PO": "P1", "Qty": "1"}]),
              _sheet("Full", ["PO", "Qty"], [{"PO": "P1", "Qty": "1"}, {"PO": "P2", "Qty": "2"}])]
    assert grn.load_extract(sheets).sheet == "Full"


def test_nothing_mappable_is_reported_not_silently_empty():
    r = grn.load_extract([_sheet("Notes", ["A", "B"], [{"A": "x", "B": "y"}])])
    assert not r.ok and r.lines == []
    assert "no sheet could be mapped" in r.problems[0]
    assert r.rejected_sheets


def test_unmapped_columns_are_reported():
    r = grn.load_extract([_sheet("GRN", ["PO", "Qty", "Cost Centre", "Notes"],
                                 [{"PO": "P1", "Qty": "1", "Cost Centre": "C", "Notes": "n"}])])
    assert set(r.unmapped_columns) >= {"Cost Centre", "Notes"}, \
        "columns we ignored must be visible, in case one of them mattered"


def test_a_declared_mapping_is_used_and_its_source_reported():
    r = grn.load_extract([_sheet("GRN", ["Purchase Order", "Qty Passed"],
                                 [{"Purchase Order": "P1", "Qty Passed": "9"}])],
                         declared={"po_number": "Purchase Order", "qty_received": "Qty Passed"})
    assert r.mapping_source == "declared" and r.lines[0].qty_received == D("9")


def test_a_renamed_declared_column_makes_the_load_not_ok():
    """The client renamed a column: the load must not pass as clean."""
    r = grn.load_extract([_sheet("GRN", ["PO", "Qty"], [{"PO": "P1", "Qty": "1"}])],
                         declared={"po_number": "PO", "qty_received": "Qty", "amount": "Line Value"})
    assert r.lines, "the usable rows still load"
    assert not r.ok, "but the load is flagged, because a declared column is missing"
    assert r.declared_but_absent == {"amount": "Line Value"}


def test_skipped_rows_are_counted_in_the_report():
    rows = DATA + [{"PO": "", "Qty": "5"}]
    r = grn.load_extract([_sheet("GRN", ["PO", "Qty", "Amount"], rows)])
    assert len(r.lines) == 2 and len(r.problems) == 1 and r.rows_read == 3


def test_an_empty_file_is_handled():
    assert grn.load_extract([]).lines == []


def test_load_extract_accepts_the_real_parser_output():
    """Guards a contract mismatch that synthetic fixtures hid.

    `core.vendor_doc_tables.parse_spreadsheet` describes columns as
    {"name", "letter"} dicts while keying row dicts by the bare name. Tests that
    passed a plain list of strings passed happily while the real path raised
    `unhashable type: 'dict'`.
    """
    openpyxl = pytest.importorskip("openpyxl")
    import io
    from backend_ocr.app.recon.core_tables import parse_spreadsheet_safe

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Parameters"
    ws.append(["Setting", "Value"])
    ws.append(["Company", "Bata India"])
    data = wb.create_sheet("GRN Lines")
    data.append(["GRN No", "PO Number", "Item Code", "Received Qty", "Rate", "Amount", "Cost Centre"])
    data.append(["GRN/2026/8812", "4500087255", "AHU-85", 2, 148000, 296000, "CHR-LF"])
    data.append(["GRN/2026/8812", "4500087255", "PIPE-25", 441.9, 620, 273978, "CHR-LF"])
    data.append(["GRN/2026/8812", "", "ORPHAN", 5, 10, 50, "CHR-LF"])
    buf = io.BytesIO()
    wb.save(buf)

    r = grn.load_extract(parse_spreadsheet_safe("grn_export.xlsx", buf.getvalue()))
    assert r.sheet == "GRN Lines" and r.ok
    assert len(r.lines) == 2 and r.rows_read == 3
    assert r.unmapped_columns == ["Cost Centre"]
    assert "row 3" in r.problems[0]
    assert grn.receipt_total(r.lines) == D("569978")


def test_an_unreadable_file_comes_back_empty_not_raising():
    from backend_ocr.app.recon.core_tables import parse_spreadsheet_safe
    assert parse_spreadsheet_safe("broken.xlsx", b"not a spreadsheet") == []


# ── storage refs must be readable by whoever reads the database ──────────────

def test_a_local_path_is_refused_when_the_database_is_shared(monkeypatch):
    """A laptop pointed at dev must not store documents on its own disk.

    The ref it would write is an absolute path on that machine, so the deployed
    API and the recon worker both get None from it — surfacing much later as
    "the file could not be loaded from storage", with nothing pointing back at
    the cause.
    """
    from backend_ocr.app.core import object_store

    monkeypatch.setattr(object_store, "enabled", lambda: False)
    monkeypatch.setattr(object_store, "shared_database", lambda: True)
    with pytest.raises(object_store.LocalRefOnSharedDatabase) as e:
        object_store.save("vendor-docs/t/s/d", b"bytes")
    assert "S3_BUCKET" in str(e.value)


def test_a_local_path_is_fine_against_a_local_database(monkeypatch, tmp_path):
    from backend_ocr.app.core import object_store

    monkeypatch.setattr(object_store, "enabled", lambda: False)
    monkeypatch.setattr(object_store, "shared_database", lambda: False)
    monkeypatch.setattr(object_store, "LOCAL_ROOT", tmp_path)
    ref = object_store.save("vendor-docs/t/s/d", b"bytes")
    assert object_store.load(ref) == b"bytes"


@pytest.mark.parametrize("url,shared", [
    ("postgresql://u:p@localhost:5432/db", False),
    ("postgresql://u:p@127.0.0.1:5432/db", False),
    ("postgresql://u:p@3.110.208.167:5432/onsumm_db?sslmode=require", True),
    ("postgresql://u:p@db.internal.example:5432/db", True),
])
def test_shared_database_detection(monkeypatch, url, shared):
    import backend_ocr.app.config as cfg
    from backend_ocr.app.core import object_store
    monkeypatch.setattr(cfg, "DB_URL", url)
    assert object_store.shared_database() is shared


# ── telling a storage problem from a parsing problem ─────────────────────────

def test_an_s3_ref_is_readable(monkeypatch):
    from backend_ocr.app.core import object_store
    assert object_store.unreadable_here("s3://bucket/key") is None


def test_a_bill_upload_ref_is_not_object_storage_business(monkeypatch):
    """`bill-upload:<id>` resolves from the database, not from storage.

    Treating it as a file path marked two perfectly good invoices unreadable.
    """
    from backend_ocr.app.core import object_store
    monkeypatch.setattr(object_store, "shared_database", lambda: True)
    assert object_store.unreadable_here("bill-upload:4b036da6-2c6c") is None


def test_a_local_path_is_unreadable_on_a_shared_database_even_if_present(tmp_path, monkeypatch):
    """The question is whether the SYSTEM can read it, not this machine.

    The bytes being on this laptop is irrelevant: the deployed API and the
    worker cannot see this filesystem, and they are the ones that must read it.
    """
    from backend_ocr.app.core import object_store
    f = tmp_path / "doc.pdf"
    f.write_bytes(b"here all along")
    monkeypatch.setattr(object_store, "shared_database", lambda: True)
    why = object_store.unreadable_here(str(f))
    assert why and "another machine" in why


def test_a_local_path_present_on_a_local_database_is_fine(tmp_path, monkeypatch):
    from backend_ocr.app.core import object_store
    f = tmp_path / "doc.pdf"
    f.write_bytes(b"x")
    monkeypatch.setattr(object_store, "shared_database", lambda: False)
    assert object_store.unreadable_here(str(f)) is None


def test_a_missing_local_file_on_a_local_database_says_so(tmp_path, monkeypatch):
    from backend_ocr.app.core import object_store
    monkeypatch.setattr(object_store, "shared_database", lambda: False)
    assert "no longer on disk" in object_store.unreadable_here(str(tmp_path / "gone.pdf"))


def test_no_ref_at_all_is_reported():
    from backend_ocr.app.core import object_store
    assert "No file was stored" in object_store.unreadable_here(None)


# ── the fourth way at line level: what the GRN says arrived ─────────────────

def test_a_grn_line_fills_the_received_quantity():
    """The Dynamics extract is per line, so it answers at item level."""
    from backend_ocr.app.recon.assemble import reconcile
    from backend_ocr.app.recon.types import (
        ExtractedInvoice, ExtractedPO, InvoiceLine, MatchPair, POLine, ReconInput, Sourced)

    po_line = POLine(sno=1, description="Ductable AHU 8.5 TR", unit="EA", qty=D("6"),
                     unit_price=D("95400"), amount=D("572400"))
    inv_line = InvoiceLine(key="rl:1", sno=1, description="Ductable AHU 8.5 TR", unit="EA",
                           qty=Sourced(value=D("6")), rate=Sourced(value=D("95400")),
                           amount=Sourced(value=D("572400")))
    g = grn.GrnLine(po_number="P1", qty_received=D("5"), po_line_no="1",
                    description="AHU UNIT 8.5TR")
    res = reconcile(ReconInput(
        po=ExtractedPO(po_number="P1", lines=[po_line], total=D("572400")),
        invoice=ExtractedInvoice(invoice_no="I-1", annexure_lines=[inv_line], taxable=D("572400")),
        receipt_lines=[g],
        invoice_matches=[MatchPair(po_key=po_line.key, other_key="rl:1", score=1.0, method="EXACT")]))
    assert res.lines[0].received_qty == D("5"), "matched on the PO line number the extract carries"


def test_received_is_none_when_no_grn_covers_the_line():
    """Absent receipt is reported by its own check, never as a zero here."""
    from backend_ocr.app.recon.assemble import reconcile
    from backend_ocr.app.recon.types import (
        ExtractedInvoice, ExtractedPO, InvoiceLine, MatchPair, POLine, ReconInput, Sourced)

    po_line = POLine(sno=1, description="Piping", unit="RFT", qty=D("10"),
                     unit_price=D("620"), amount=D("6200"))
    inv_line = InvoiceLine(key="rl:1", sno=1, description="Piping", unit="RFT",
                           qty=Sourced(value=D("10")), rate=Sourced(value=D("620")),
                           amount=Sourced(value=D("6200")))
    res = reconcile(ReconInput(
        po=ExtractedPO(po_number="P1", lines=[po_line], total=D("6200")),
        invoice=ExtractedInvoice(invoice_no="I-1", annexure_lines=[inv_line], taxable=D("6200")),
        receipt_lines=[grn.GrnLine(po_number="P1", qty_received=D("4"), description="Something else")],
        invoice_matches=[MatchPair(po_key=po_line.key, other_key="rl:1", score=1.0, method="EXACT")]))
    assert res.lines[0].received_qty is None
