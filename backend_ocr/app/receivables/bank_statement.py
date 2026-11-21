"""Bank statement → incoming payments (credits only).

Indian bank exports differ in everything but substance: a few preamble rows,
then a header row with some spelling of date / narration / reference / debit /
credit (or one amount column plus a Dr/Cr flag). The header is found by scoring
rows, not by position, so HDFC, ICICI, SBI, Axis and Kotak CSV/XLSX exports all
read without per-bank configuration.

The narration carries what matching needs — the rail (NEFT/RTGS/IMPS/UPI/
cheque), the UTR, and the payer's name, e.g.

    NEFT-HDFCN52026111512345678-ACME TRADING PVT LTD-INV 1045
    RTGS/UTIBR52026111500012345/ACME TRADING/
    IMPS/P2A/631512345678/ACMETRADIN/HDFC
    UPI/631512345678/ACME TRADING/acme@okhdfc/Payment
    BY CLG CHQ NO 004512 ACME TRADING

The payer name read here is a best guess; aliases learned from confirmed
matches (ar_customers.payer_aliases) are what make it reliable over time.
"""
from __future__ import annotations

import csv
import hashlib
import io
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

_DATE_FORMATS = ("%d/%m/%Y", "%d-%m-%Y", "%d/%m/%y", "%d-%m-%y", "%d.%m.%Y", "%Y-%m-%d",
                 "%d %b %Y", "%d-%b-%Y", "%d-%b-%y", "%d %b %y", "%d %B %Y", "%d/%b/%Y")

_METHODS = ("NEFT", "RTGS", "IMPS", "UPI", "NACH", "ACH", "CHQ", "CLG", "CHEQUE", "INFT", "MMT", "FT", "TRF")
_NOISE = {"BY", "TO", "FROM", "TRANSFER", "TRF", "P2A", "P2P", "PAYMENT", "PAY", "CR", "CREDIT", "INB",
          "NET", "BANKING", "MOB", "REF", "NO", "CLG", "CHQ", "CHEQUE", "DEPOSIT", "INWARD", "OUTWARD",
          "FUND", "FUNDS", "RECEIVED", "ONLINE", "BANK", "IB", "INFT", "NEFT", "RTGS", "IMPS", "UPI", "MMT",
          "NACH", "ACH", "FT"}
_IFSC = re.compile(r"^[A-Z]{4}0[A-Z0-9]{6}$")
_UTR = re.compile(r"\b([A-Z]{4}[RNH0-9][0-9A-Z]{10,20}|[0-9]{12,22})\b")


class StatementError(ValueError):
    pass


# ── Cells ──────────────────────────────────────────────────────────────────────

def parse_date(v) -> date | None:
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    s = str(v).strip().split(" ")[0] if re.match(r"^\d{4}-\d{2}-\d{2} ", str(v)) else str(v).strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def parse_amount(v) -> Decimal | None:
    if v is None:
        return None
    if isinstance(v, (int, float, Decimal)):
        return Decimal(str(v)).quantize(Decimal("0.01")) if v else None
    s = re.sub(r"[₹,\s]|INR|CR|Cr", "", str(v))
    s = s.strip("()")
    if not s or s in ("-", "--"):
        return None
    try:
        d = Decimal(s)
    except InvalidOperation:
        return None
    return abs(d).quantize(Decimal("0.01")) if d else None


# ── Narration ─────────────────────────────────────────────────────────────────

def parse_narration(text: str | None) -> dict:
    """{method, utr, payer_name} read from one narration line."""
    t = (text or "").upper()
    method = next((m for m in _METHODS if re.search(rf"(?<![A-Z]){m}(?![A-Z])", t)), None)
    if method in ("CLG", "CHEQUE"):
        method = "CHQ"
    if method in ("INFT", "MMT", "FT", "TRF"):
        method = "TRANSFER"
    utr = None
    m = _UTR.search(t)
    if m:
        utr = m.group(1)

    payer = None
    for tok in re.split(r"[/\-:|]+|\s{2,}", t):
        tok = tok.strip(" .,")
        if not tok or "@" in tok or _IFSC.match(tok) or (utr and utr in tok):
            continue
        words = [w for w in re.split(r"\s+", tok) if w and w not in _NOISE and not w.isdigit()]
        letters = sum(c.isalpha() for c in "".join(words))
        if letters < 4 or not words:
            continue
        # "INV 1045", "PO4500012345", "BILL NO" are references, not names — but only
        # the bare keyword or keyword+digits: POTHYS, POLICE, POWER are payers.
        if re.fullmatch(r"(INV|INVOICE|BILL|PO)\d*", words[0]):
            continue
        if len(words) == 1 and re.search(r"\d", words[0]):
            continue
        payer = " ".join(words)
        break
    return {"method": method, "utr": utr, "payer_name": payer}


# ── Rows ──────────────────────────────────────────────────────────────────────

def _rows(data: bytes, filename: str) -> list[list]:
    name = filename.lower()
    if name.endswith((".xlsx", ".xlsm")):
        from openpyxl import load_workbook
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        ws = wb.worksheets[0]
        return [list(r) for r in ws.iter_rows(values_only=True)]
    if name.endswith(".xls"):
        raise StatementError("Old .xls statements aren't supported — save it as .xlsx or .csv")
    text = data.decode("utf-8-sig", errors="replace")
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    return [r for r in csv.reader(io.StringIO(text), dialect)]


def _norm_head(v) -> str:
    return re.sub(r"[^a-z/ ]", "", str(v or "").lower()).strip()


def _find_columns(rows: list[list]) -> tuple[int, dict]:
    """(header row index, {role: column index}) for the best-looking header row."""
    best = (-1, {}, 0)
    for ri, row in enumerate(rows[:40]):
        heads = [_norm_head(c) for c in row]
        cols: dict[str, int] = {}
        for ci, h in enumerate(heads):
            if not h:
                continue
            if "value date" in h:
                cols.setdefault("value_date", ci)
            elif "date" in h:
                cols.setdefault("date", ci)
            elif any(k in h for k in ("narration", "description", "particular", "remark", "details")):
                cols.setdefault("narration", ci)
            elif any(k in h for k in ("ref", "chq", "cheque", "utr", "instrument")):
                cols.setdefault("reference", ci)
            elif any(k in h for k in ("credit", "deposit")) or h in ("cr", "cr amount", "cr amt"):
                cols.setdefault("credit", ci)
            elif any(k in h for k in ("debit", "withdrawal")) or h in ("dr", "dr amount", "dr amt"):
                cols.setdefault("debit", ci)
            elif h in ("dr/cr", "cr/dr", "type", "drcr", "crdr", "txn type", "transaction type"):
                cols.setdefault("drcr", ci)
            elif "amount" in h:
                cols.setdefault("amount", ci)
        if "date" not in cols and "value_date" in cols:
            cols["date"] = cols["value_date"]
        score = sum(k in cols for k in ("date", "narration", "credit", "reference")) + \
            (1 if "amount" in cols and "drcr" in cols else 0)
        if "date" in cols and ("credit" in cols or "amount" in cols) and score > best[2]:
            best = (ri, cols, score)
    if best[0] < 0:
        raise StatementError("Couldn't find the header row — expected columns like Date, Narration "
                             "and Credit / Deposit")
    return best[0], best[1]


def fingerprint(received_on: date, amount: Decimal, utr: str | None, narration: str | None,
                reference: str | None, occurrence: int = 1) -> str:
    """Identity of a statement line. `occurrence` numbers identical lines within one
    file (two equal transfers from one customer on one day are both real, edge case
    E3), so re-importing the same or an overlapping statement still dedupes (E2)."""
    key = (f"{received_on.isoformat()}|{amount}|{utr or ''}|{(reference or '').strip()}|"
           f"{(narration or '').strip().upper()}|{occurrence}")
    return hashlib.sha256(key.encode()).hexdigest()[:32]


def table_records(data: bytes, filename: str) -> list[dict]:
    """Raw lines of a CSV / XLSX statement: {date, narration, reference, credit, debit}."""
    rows = _rows(data, filename)
    hi, cols = _find_columns(rows)
    out: list[dict] = []
    for row in rows[hi + 1:]:
        cell = lambda k: row[cols[k]] if k in cols and cols[k] < len(row) else None  # noqa: E731
        d = parse_date(cell("date"))
        if not d:
            continue
        credit = debit = None
        if "credit" in cols:
            credit = parse_amount(cell("credit"))
            debit = parse_amount(cell("debit")) if "debit" in cols else None
        elif "amount" in cols:
            flag = str(cell("drcr") or "").strip().upper()
            raw = cell("amount")
            if flag.startswith("C") or (not flag and str(raw or "").upper().endswith("CR")):
                credit = parse_amount(raw)
            elif flag.startswith("D") or str(raw or "").upper().endswith("DR"):
                debit = parse_amount(raw)
        out.append({"date": d, "narration": str(cell("narration") or "").strip() or None,
                    "reference": str(cell("reference") or "").strip() or None,
                    "credit": credit, "debit": debit})
    return out


def finalize(records: list[dict]) -> dict:
    """Raw lines (from a table or a PDF) → payment-ready credits, bounce debits, and
    every line numbered as read, so the statement can be shown back exactly.

    {"credits": [...], "bounces": [...], "lines": [...]} — credits and bounces carry
    `line`, the index into `lines`.
    """
    from .detectors import is_bounce
    credits: list[dict] = []
    bounces: list[dict] = []
    lines: list[dict] = []
    seen: dict[tuple, int] = {}
    for rec in records:
        d = rec["date"]
        credit, debit = rec.get("credit"), rec.get("debit")
        narration = rec.get("narration") or None
        reference = rec.get("reference") or None
        if reference and re.fullmatch(r"0+", reference):
            reference = None
        n = len(lines)
        lines.append({"line": n, "date": d.isoformat(), "narration": narration, "reference": reference,
                      "credit": str(credit) if credit else None, "debit": str(debit) if debit else None,
                      "outcome": "ignored"})
        meta = parse_narration(" ".join(filter(None, [narration, reference])))
        utr = meta["utr"] or (reference if reference and len(reference) >= 10 else None)
        if credit:
            key = (d, credit, utr, reference, (narration or "").upper())
            seen[key] = seen.get(key, 0) + 1
            credits.append({
                "line": n,
                "received_on": d,
                "amount": credit,
                "narration": narration,
                "reference": reference,
                "method": meta["method"],
                "utr": utr,
                "payer_name": meta["payer_name"],
                "fingerprint": fingerprint(d, credit, utr, narration, reference, seen[key]),
            })
        elif debit and is_bounce(narration):
            bounces.append({"line": n, "date": d, "amount": debit, "narration": narration,
                            "reference": reference, "utr": utr})
    return {"credits": credits, "bounces": bounces, "lines": lines}


def parse_statement(data: bytes, filename: str) -> dict:
    """A CSV / XLSX statement → {"credits", "bounces", "lines"} (see finalize)."""
    return finalize(table_records(data, filename))
