"""Spreadsheets filed against a vendor, read cell by cell into the database.

Every .xlsx / .xlsm / .csv uploaded to a vendor's Documents (any type, and
attachments filed from the vendor inbox too) is parsed in full: one
`vendor_doc_tables` row per sheet, one `vendor_doc_rows` row per data row.
That makes any number in the file usable later in a calculation or a custom
report, e.g.

    SELECT r.row_number, r.data->>'Resource', (r.data->>'Rate')::numeric
      FROM vendor_doc_rows r
      JOIN vendor_documents d ON d.id = r.doc_id AND d.deleted_at IS NULL
     WHERE r.tenant_id = :tenant AND r.supplier_id = :vendor
       AND jsonb_typeof(r.data->'Rate') = 'number';

`data` is keyed by the sheet's header names; `columns` on the sheet row keeps
their order and Excel letters, and `row_number` is the row in the sheet, so
every value can be traced back to its cell (e.g. Rate in column D, row 7 = D7).

Values keep their type: numbers stay JSON numbers, dates become ISO strings,
and text that is cleanly a number ("1,08,000", "₹ 5,000.50", "(1,200)") is
stored as that number. Identifiers are left as text: anything with a leading
zero ("0105") or longer than 15 digits (account numbers).

Parsing runs off the request after the upload is saved; the document's
`data_status` goes PENDING -> PARSED (or FAILED with `data_error`). A file that
can't be read is still a stored document, just without rows.
"""
from __future__ import annotations

import csv
import datetime as _dt
import io
import json
import logging
import re
import threading

from psycopg2.extras import execute_values

from ..config import get_conn, put_conn

log = logging.getLogger(__name__)

SPREADSHEET_EXTS = (".xlsx", ".xlsm", ".csv")
# A runaway export shouldn't fill the database; past this the sheet is marked truncated.
MAX_ROWS_PER_DOC = 200_000
MAX_COLS = 500
_HEADER_SCAN_ROWS = 20

_NUM_RE = re.compile(r"^\(?-?\d{1,3}(?:,\d{2,3})*(?:\.\d+)?\)?$|^\(?-?\d+(?:\.\d+)?\)?$")
_CURRENCY = ("₹", "rs.", "rs", "inr", "$", "usd", "€", "£")


def is_spreadsheet(file_name: str | None) -> bool:
    return (file_name or "").lower().endswith(SPREADSHEET_EXTS)


def _col_letter(i: int) -> str:
    """0 -> A, 25 -> Z, 26 -> AA."""
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def _coerce_text(s: str):
    """Text that is cleanly a number becomes that number; anything else stays text."""
    t = s.strip()
    if not t:
        return None
    low = t.lower()
    for c in _CURRENCY:
        if low.startswith(c):
            t = t[len(c):].strip()
            break
    t = t.replace(" ", "")
    if not _NUM_RE.match(t):
        return s.strip()
    neg = t.startswith("(") and t.endswith(")")
    digits = t.strip("()").replace(",", "")
    bare = digits.lstrip("-")
    # Identifiers, not amounts: account numbers, pincodes with leading zeros, etc.
    if (len(bare) > 1 and bare.startswith("0") and not bare.startswith("0.")) or len(bare.split(".")[0]) > 15:
        return s.strip()
    try:
        n = float(digits) if "." in digits else int(digits)
    except ValueError:
        return s.strip()
    return -n if neg else n


def _value(v):
    """A cell as a JSON value."""
    if v is None:
        return None
    if isinstance(v, bool):
        return v
    if isinstance(v, int):
        return v
    if isinstance(v, float):
        if v != v or v in (float("inf"), float("-inf")):
            return None
        return int(v) if v.is_integer() and abs(v) < 2**53 else v
    if isinstance(v, (_dt.datetime, _dt.date, _dt.time)):
        if isinstance(v, _dt.datetime) and v.time() == _dt.time(0):
            return v.date().isoformat()
        return v.isoformat()
    if isinstance(v, _dt.timedelta):
        return v.total_seconds()
    if isinstance(v, str):
        return _coerce_text(v)
    return str(v)


def _pick_header(rows: list[list]) -> int:
    """Index of the header row among the first rows: the first row that is mostly
    filled and mostly text. Title rows above a table ("Vendor resource list Sep'26")
    have one or two cells and are skipped."""
    counts = [sum(1 for c in r if c not in (None, "")) for r in rows]
    if not counts or max(counts) == 0:
        return 0
    widest = max(counts)
    for i, r in enumerate(rows):
        filled = [c for c in r if c not in (None, "")]
        # At least two cells (unless the sheet really is one column wide): a
        # single-cell row is a title, and on a narrow table "half the widest"
        # is one cell, which let those titles through as headings.
        need = max(2 if widest > 1 else 1, widest * 0.6)
        if len(filled) >= need and sum(isinstance(c, str) for c in filled) >= len(filled) * 0.6:
            return i
    return next(i for i, n in enumerate(counts) if n)


def _header_names(raw: list) -> list[str]:
    """Clean, unique column names; blank headers get their Excel letter."""
    names, seen = [], {}
    for i, h in enumerate(raw):
        n = " ".join(str(_value(h) if not isinstance(h, str) else h).split()) if h not in (None, "") else ""
        n = n[:120] or f"Column {_col_letter(i)}"
        if n in seen:
            seen[n] += 1
            n = f"{n} ({seen[n]})"
        else:
            seen[n] = 1
        names.append(n)
    return names


def _sheet_table(name: str, index: int, rows_iter, budget: int) -> tuple[dict, list[tuple[int, dict]]]:
    """One sheet -> (sheet meta, [(row_number, data), ...]). rows_iter yields raw cell lists."""
    head: list[list] = []
    it = iter(rows_iter)
    for r in it:
        head.append(list(r)[:MAX_COLS])
        if len(head) >= _HEADER_SCAN_ROWS:
            break
    if not any(c not in (None, "") for r in head for c in r):
        return {"sheet_name": name, "sheet_index": index, "header_row": None, "columns": [], "row_count": 0, "truncated": False}, []
    h = _pick_header(head)
    width = max(len(r) for r in head)
    names = _header_names(head[h] + [None] * (width - len(head[h])))
    out: list[tuple[int, dict]] = []
    truncated = False

    def take(row_number: int, raw: list):
        nonlocal names, truncated
        raw = list(raw)[:MAX_COLS]
        if len(raw) > len(names):  # a data row wider than the header
            names = names + [f"Column {_col_letter(i)}" for i in range(len(names), len(raw))]
        data = {}
        for i, c in enumerate(raw):
            v = _value(c)
            if v is not None:
                data[names[i]] = v
        if data:
            out.append((row_number, data))

    for i, r in enumerate(head[h + 1:], start=h + 2):
        take(i, r)
    n = len(head) + 1
    for r in it:
        if len(out) >= budget:
            truncated = True
            break
        take(n, r)
        n += 1
    letters = [{"name": nm, "letter": _col_letter(i)} for i, nm in enumerate(names)]
    return ({"sheet_name": name, "sheet_index": index, "header_row": h + 1, "columns": letters,
             "row_count": len(out), "truncated": truncated}, out)


def parse_spreadsheet(file_name: str, contents: bytes) -> list[tuple[dict, list[tuple[int, dict]]]]:
    """Every sheet of an .xlsx/.xlsm/.csv as (sheet meta, rows)."""
    budget = MAX_ROWS_PER_DOC
    tables = []
    if file_name.lower().endswith(".csv"):
        try:
            text = contents.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = contents.decode("latin-1")
        try:
            dialect = csv.Sniffer().sniff(text[:8192], delimiters=",;\t|")
        except csv.Error:
            dialect = csv.excel
        tables.append(_sheet_table("Sheet1", 0, csv.reader(io.StringIO(text), dialect), budget))
        return tables
    import openpyxl
    # data_only: a formula cell gives the value Excel last calculated, not the formula.
    wb = openpyxl.load_workbook(io.BytesIO(contents), read_only=True, data_only=True)
    try:
        for idx, ws in enumerate(wb.worksheets):
            meta, rows = _sheet_table(ws.title, idx, ws.iter_rows(values_only=True), budget)
            budget -= len(rows)
            tables.append((meta, rows))
            if budget <= 0:
                meta["truncated"] = True
                break
    finally:
        wb.close()
    return tables


def store_tables(doc_id: str, tenant_id: str, supplier_id: str, file_name: str, contents: bytes) -> int:
    """Parse the file and replace this document's rows. Returns rows stored.
    Records PARSED / FAILED on the document; never raises."""
    try:
        tables = parse_spreadsheet(file_name, contents)
    except Exception as e:  # a corrupt or password-protected workbook
        log.warning("vendor doc %s: spreadsheet not readable: %s", doc_id, e)
        _set_status(doc_id, "FAILED", f"Couldn't read this file: {type(e).__name__}")
        return 0
    conn = get_conn()
    total = 0
    try:
        with conn.cursor() as cur:
            # Lock the document so a delete can't land mid-write; a document
            # already deleted (while this was parsing) keeps no values.
            cur.execute("SELECT 1 FROM vendor_documents WHERE id=%s AND deleted_at IS NULL FOR UPDATE", (doc_id,))
            if cur.fetchone() is None:
                conn.rollback()
                put_conn(conn)
                return 0
            cur.execute("DELETE FROM vendor_doc_tables WHERE doc_id=%s", (doc_id,))
            for meta, rows in tables:
                cur.execute(
                    """INSERT INTO vendor_doc_tables (doc_id, tenant_id, supplier_id, sheet_name, sheet_index,
                                                      header_row, columns, row_count, truncated)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                    (doc_id, tenant_id, supplier_id, meta["sheet_name"][:255], meta["sheet_index"],
                     meta["header_row"], json.dumps(meta["columns"]), meta["row_count"], meta["truncated"]))
                table_id = cur.fetchone()[0]
                if rows:
                    execute_values(
                        cur,
                        "INSERT INTO vendor_doc_rows (table_id, doc_id, tenant_id, supplier_id, row_number, data) VALUES %s",
                        [(table_id, doc_id, tenant_id, supplier_id, n, json.dumps(d, ensure_ascii=False)) for n, d in rows],
                        page_size=1000)
                total += len(rows)
            cur.execute("UPDATE vendor_documents SET data_status='PARSED', data_error=NULL WHERE id=%s", (doc_id,))
        conn.commit()
    except Exception as e:
        conn.rollback()
        log.exception("vendor doc %s: storing spreadsheet rows failed", doc_id)
        put_conn(conn)
        _set_status(doc_id, "FAILED", f"Couldn't store this file's rows: {type(e).__name__}")
        return 0
    put_conn(conn)
    return total


def _set_status(doc_id: str, status: str, error: str | None) -> None:
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("UPDATE vendor_documents SET data_status=%s, data_error=%s WHERE id=%s", (status, error, doc_id))
        conn.commit()
    except Exception:
        conn.rollback()
        log.exception("vendor doc %s: couldn't record data_status", doc_id)
    finally:
        put_conn(conn)


def store_tables_in_background(doc_id: str, tenant_id: str, supplier_id: str, file_name: str, contents: bytes) -> None:
    """Parse after the upload has answered; a big workbook shouldn't hold the request."""
    threading.Thread(target=store_tables, args=(doc_id, tenant_id, supplier_id, file_name, contents),
                     name=f"vdoc-parse-{doc_id[:8]}", daemon=True).start()
