"""GRN ingest — the RECEIPT leg (RECON_IMPLEMENTATION_PLAN.md §7).

Bata's goods receipt is **an entry inside Microsoft Dynamics**, not a document:
no copy is issued, and the vendor never provides one (call of 16 Nov 2026). It
reaches us as a structured extract, so there is no OCR and no parser — which
makes it the cheapest and most reliable input in the pipeline.

**Why the mapping is declared.** Bata's extract has not arrived yet, so any
column names written into this module would be a guess. Instead a mapping is
*declared* — per tenant, as data — and inference is only the fallback. When the
real file lands, supporting it costs a mapping entry, not a rewrite. That is the
same bet the vocabulary makes: client variation is configuration.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal

from rapidfuzz import fuzz

from .num import parse_inr

# Canonical field → header spellings seen or expected. Deliberately generic:
# these are a starting point for inference, never a contract.
ALIASES: dict[str, list[str]] = {
    "grn_number":   ["grn number", "grn no", "grn", "receipt no", "gr number", "document no"],
    "grn_date":     ["grn date", "posting date", "receipt date", "document date", "date"],
    "po_number":    ["po number", "po no", "purchase order", "po", "order no"],
    "po_line_no":   ["po line", "line no", "item no", "line", "sr no", "s no"],
    "item_code":    ["item code", "material code", "material", "sku", "fa code", "asset code"],
    "description":  ["description", "item name", "item description", "particulars", "material description"],
    "unit":         ["unit", "uom", "unit of measure"],
    "qty_received": ["received qty", "qty received", "grn qty", "quantity", "qty", "accepted qty"],
    "rate":         ["rate", "unit price", "unit rate", "price"],
    "amount":       ["amount", "value", "line amount", "net amount", "total"],
    "msd_voucher":  ["voucher", "voucher no", "msd voucher", "journal no"],
}

# Without these a row cannot take part in reconciliation: nothing to join on, or
# nothing to compare. Everything else is optional enrichment.
REQUIRED = ("po_number", "qty_received")

_MATCH_FLOOR = 0.80


@dataclass
class Mapping:
    """canonical field → column name in the source file."""
    columns: dict[str, str]
    source: str = "declared"          # declared | inferred
    weakest: float = 1.0
    # Declared fields whose column is absent from this file — a renamed column
    # in the client's export, surfaced rather than silently skipped.
    missing_columns: dict[str, str] = field(default_factory=dict)

    def missing(self) -> list[str]:
        return [f for f in REQUIRED if f not in self.columns]


@dataclass
class GrnLine:
    po_number: str
    qty_received: Decimal
    grn_number: str | None = None
    grn_date: object | None = None
    po_line_no: str | None = None
    item_code: str | None = None
    description: str | None = None
    unit: str | None = None
    rate: Decimal | None = None
    amount: Decimal | None = None
    msd_voucher: str | None = None
    row_no: int = 0
    warnings: list[str] = field(default_factory=list)


def _norm(s: object) -> str:
    return re.sub(r"[^a-z0-9 ]+", " ", re.sub(r"\s+", " ", str(s or "").lower())).strip()


def infer_mapping(columns: list[str]) -> Mapping:
    """Best-effort header matching, used only when nothing is declared."""
    used: set[str] = set()
    out: dict[str, str] = {}
    weakest = 1.0
    for field_name, names in ALIASES.items():
        best, score = None, 0.0
        for c in columns:
            if c in used:
                continue
            cl = _norm(c)
            s = max(fuzz.ratio(cl, n) for n in names) / 100
            if cl in names or any(cl.startswith(n) for n in names):
                s = max(s, 0.95)
            if s > score:
                best, score = c, s
        if best is not None and score >= _MATCH_FLOOR:
            out[field_name] = best
            used.add(best)
            weakest = min(weakest, score)
    return Mapping(columns=out, source="inferred", weakest=weakest)


def resolve_mapping(columns: list[str], declared: dict[str, str] | None = None) -> Mapping:
    """A declared mapping wins outright; otherwise infer.

    A declared mapping naming a column the file does not have is reported rather
    than quietly ignored — a renamed column in the client's export must surface
    as a mapping error, not as a load that silently drops a field.
    """
    if not declared:
        return infer_mapping(columns)
    return Mapping(
        columns={f: c for f, c in declared.items() if c in columns},
        source="declared",
        missing_columns={f: c for f, c in declared.items() if c not in columns})


def parse_rows(rows: list[dict], mapping: Mapping) -> tuple[list[GrnLine], list[str]]:
    """Map raw spreadsheet rows to GRN lines. Returns (lines, problems).

    A row missing a required field is skipped **and reported**; a GRN loader that
    silently drops receipt lines would understate what was received, which is
    exactly the direction that causes an overpayment to look acceptable.
    """
    problems: list[str] = []
    if mapping.missing():
        return [], [f"mapping is missing required field(s): {', '.join(mapping.missing())}"]
    cols = mapping.columns
    out: list[GrnLine] = []
    for i, raw in enumerate(rows, start=1):
        def val(f: str):
            c = cols.get(f)
            return raw.get(c) if c else None

        po = str(val("po_number") or "").strip()
        qty = parse_inr(val("qty_received"))
        if not po:
            problems.append(f"row {i}: no PO number")
            continue
        if qty is None:
            problems.append(f"row {i}: no received quantity")
            continue
        out.append(GrnLine(
            po_number=po, qty_received=qty,
            grn_number=(str(val("grn_number")).strip() if val("grn_number") else None),
            grn_date=val("grn_date"),
            po_line_no=(str(val("po_line_no")).strip() if val("po_line_no") else None),
            item_code=(str(val("item_code")).strip() if val("item_code") else None),
            description=(str(val("description")).strip() if val("description") else None),
            unit=(str(val("unit")).strip() if val("unit") else None),
            rate=parse_inr(val("rate")), amount=parse_inr(val("amount")), row_no=i,
            msd_voucher=(str(val("msd_voucher")).strip() if val("msd_voucher") else None)))
    return out, problems


@dataclass
class LoadReport:
    """What a load actually did — never just a count.

    An extract that half-loaded in silence is worse than one that failed: the
    receipt would be understated, and an understated receipt makes an
    overpayment look acceptable. So every sheet considered, every column left
    unmapped and every skipped row is reported back.
    """
    sheet: str = ""
    mapping_source: str = ""
    mapped: dict[str, str] = field(default_factory=dict)
    unmapped_columns: list[str] = field(default_factory=list)
    declared_but_absent: dict[str, str] = field(default_factory=dict)
    rows_read: int = 0
    lines: list = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    rejected_sheets: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return bool(self.lines) and not self.declared_but_absent


def load_extract(sheets: list, declared: dict[str, str] | None = None) -> LoadReport:
    """Turn a parsed spreadsheet into GRN lines.

    `sheets` is what `core.vendor_doc_tables.parse_spreadsheet` returns:
    `[(sheet_meta, [(row_no, {column: value}), ...]), ...]`.

    An MSD export often carries several sheets — a cover sheet, a parameters
    tab, the data. The sheet that can actually be mapped wins; the others are
    named in `rejected_sheets` so a wrong choice is visible rather than silent.
    """
    best: LoadReport | None = None
    rejected: list[str] = []
    for meta, rows in sheets or []:
        name = str(meta.get("sheet_name") or "")
        # `parse_spreadsheet` describes columns as {"name", "letter"} while the
        # row dicts are keyed by the bare name. Normalise here so the mapping
        # and the row lookup agree; a plain list of names is accepted too.
        columns = [c.get("name") if isinstance(c, dict) else c for c in (meta.get("columns") or [])]
        columns = [str(c) for c in columns if c not in (None, "")]
        if not columns or not rows:
            rejected.append(f"{name}: no header or no rows")
            continue
        mapping = resolve_mapping(columns, declared)
        if mapping.missing():
            rejected.append(f"{name}: no column for {', '.join(mapping.missing())}")
            continue
        data = [r for _, r in rows]
        lines, problems = parse_rows(data, mapping)
        report = LoadReport(
            sheet=name, mapping_source=mapping.source, mapped=dict(mapping.columns),
            unmapped_columns=[c for c in columns if c not in set(mapping.columns.values())],
            declared_but_absent=dict(mapping.missing_columns),
            rows_read=len(data), lines=lines, problems=problems)
        # Prefer the sheet that yields the most usable lines.
        if best is None or len(report.lines) > len(best.lines):
            if best is not None:
                rejected.append(f"{best.sheet}: fewer usable rows ({len(best.lines)})")
            best = report
        else:
            rejected.append(f"{name}: fewer usable rows ({len(lines)})")
    if best is None:
        return LoadReport(problems=["no sheet could be mapped to a GRN"], rejected_sheets=rejected)
    best.rejected_sheets = rejected
    return best


@dataclass(frozen=True)
class Disagreement:
    """One place the GRN and the audit report do not agree."""
    kind: str                 # QTY_DIFFERS | RECEIVED_NOT_CERTIFIED | CERTIFIED_NOT_RECEIVED
    key: str                  # what the two rows were matched on
    label: str
    certified: Decimal | None = None
    received: Decimal | None = None
    basis: str = ""           # ITEM_CODE | DESCRIPTION


def _key_of(code: object, text: object) -> tuple[str, str]:
    """(matching key, basis) for a GRN line or an audit row."""
    c = _norm(code)
    if c and c not in ("na", "n a", "nil", "-"):
        return c, "ITEM_CODE"
    return _norm(text), "DESCRIPTION"


def compare_with_audit(lines: list[GrnLine], evidence_rows: list, *,
                       qty_tol: Decimal = Decimal("0.01")) -> list[Disagreement]:
    """Does the GRN say what the auditor certified?

    Bata creates the GRN **from** the auditor-certified quantity (R3/R8), so the
    two should agree by construction. A disagreement is therefore a finding
    about how the GRN was raised — not about the vendor's invoice, and it must
    not be reported as though the vendor did something wrong.

    Matching is by item code where both sides print one, else by normalised
    description. Rows that match nothing are reported in their own right:
    a GRN line with no certified quantity behind it is the one that matters,
    because it means stock was received against no verification.
    """
    audit: dict[str, tuple[Decimal | None, str, str]] = {}
    for r in evidence_rows or []:
        k, basis = _key_of(getattr(r, "asset_code", None), getattr(r, "item", None))
        if not k:
            continue
        q = getattr(r, "audit_qty", None)
        audit[k] = (getattr(q, "value", None) if q is not None else None,
                    basis, str(getattr(r, "item", "") or k))

    out: list[Disagreement] = []
    seen: set[str] = set()
    for l in lines:
        k, basis = _key_of(l.item_code, l.description)
        if not k:
            continue
        seen.add(k)
        if k not in audit:
            out.append(Disagreement(kind="RECEIVED_NOT_CERTIFIED", key=k,
                                    label=l.description or l.item_code or k,
                                    received=l.qty_received, basis=basis))
            continue
        certified, _, label = audit[k]
        if certified is None:
            continue   # the auditor left it blank; that is its own finding elsewhere
        if abs(certified - l.qty_received) > qty_tol:
            out.append(Disagreement(kind="QTY_DIFFERS", key=k, label=label,
                                    certified=certified, received=l.qty_received, basis=basis))
    for k, (certified, basis, label) in audit.items():
        if k not in seen and certified is not None and certified > 0:
            out.append(Disagreement(kind="CERTIFIED_NOT_RECEIVED", key=k, label=label,
                                    certified=certified, basis=basis))
    return out


def receipt_total(lines: list[GrnLine]) -> Decimal | None:
    """The value of what was received, for the ±₹100 check (R7).

    Uses the printed amount where the extract gives one and falls back to
    qty × rate. Returns None when neither is available for any line: an absent
    total must make the variance check abstain, never compare against zero.
    """
    total, seen = Decimal("0"), False
    for l in lines:
        if l.amount is not None:
            total += l.amount
            seen = True
        elif l.rate is not None:
            total += l.qty_received * l.rate
            seen = True
    return total if seen else None
