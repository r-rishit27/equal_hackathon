"""Running a playground flow.

Nodes are worked in dependency order, each one producing a value that the
nodes wired after it can read by name. A source produces rows or fields, a
Formula produces columns and totals, an output writes something into the
world — a document filed on the vendor, an email, a notification.

Two rules shape everything here:

**Nothing is evaluated.** Expressions go through `formula.evaluate`, which is a
parser over a fixed function table, not a Python interpreter. See that module.

**A run that half-worked says so.** Each node records its own outcome, and a
failure stops the branch rather than the record: the run row keeps every step
that did complete, including anything already written outside this system, so
"what did it actually do" survives a failure in the middle.
"""
from __future__ import annotations

import datetime as _dt
import json
import logging
import uuid
from typing import Any, Callable

from ...config import get_conn, put_conn
from .formula import AGGREGATES, FormulaError, evaluate

log = logging.getLogger(__name__)

MAX_ROWS = 5000


class RunError(Exception):
    """A node could not do its job. The message is shown to the user."""


# ── reading what the vendor already has ─────────────────────────────────────

def _latest_doc(cur, tenant: str, supplier: str, *, doc_type: str | None = None,
                label_like: str | None = None, parsed: bool = False) -> dict | None:
    """The most recent matching document on this vendor."""
    where = ["tenant_id=%s", "supplier_id=%s", "deleted_at IS NULL"]
    args: list[Any] = [tenant, supplier]
    if doc_type:
        where.append("doc_type=%s")
        args.append(doc_type)
    if label_like:
        where.append("COALESCE(doc_label,'') ILIKE %s")
        args.append(f"%{label_like}%")
    if parsed:
        where.append("data_status='PARSED'")
    cur.execute(
        f"""SELECT id, file_name, file_path, doc_type, doc_label, uploaded_at
              FROM vendor_documents WHERE {' AND '.join(where)}
             ORDER BY uploaded_at DESC NULLS LAST LIMIT 1""",
        tuple(args),
    )
    r = cur.fetchone()
    if not r:
        return None
    return {"doc_id": str(r[0]), "file_name": r[1], "file_path": r[2],
            "doc_type": r[3], "doc_label": r[4]}


def _unread_sheet(cur, tenant: str, supplier: str, label_like: str | None) -> dict | None:
    """A spreadsheet on this vendor whose rows were never stored."""
    from ...core.vendor_doc_tables import is_spreadsheet
    cur.execute(
        """SELECT id, file_name FROM vendor_documents
            WHERE tenant_id=%s AND supplier_id=%s AND deleted_at IS NULL
              AND COALESCE(data_status,'') <> 'PARSED'
            ORDER BY uploaded_at DESC NULLS LAST""",
        (tenant, supplier),
    )
    for doc_id, file_name in cur.fetchall():
        if is_spreadsheet(file_name or ""):
            return {"doc_id": str(doc_id), "file_name": file_name}
    return None


def _read_now(pending: dict, tenant: str, supplier: str) -> None:
    """Read a spreadsheet into rows inline, so the run can carry on.

    Inline rather than queued: the caller is waiting on this run, and handing
    them "try again in a minute" for a file already on the vendor is a worse
    answer than the second it takes to read it.
    """
    from ...core import object_store
    from ...core.vendor_doc_tables import store_tables
    from ...config import get_conn, put_conn

    conn = get_conn()
    try:
        with conn.cursor() as cur2:
            cur2.execute("SELECT file_path FROM vendor_documents WHERE id=%s", (pending["doc_id"],))
            row = cur2.fetchone()
        conn.commit()
    finally:
        put_conn(conn)
    if not row:
        return
    try:
        store_tables(pending["doc_id"], tenant, supplier, pending["file_name"],
                     object_store.load(row[0]))
    except Exception:
        log.exception("[playground] reading %s on demand failed", pending["file_name"])


def _sheet_rows(cur, doc_id: str, sheet: str | None) -> tuple[list[str], list[dict]]:
    """(column names, rows) for a parsed spreadsheet."""
    if sheet:
        cur.execute("""SELECT id, columns FROM vendor_doc_tables
                        WHERE doc_id=%s AND sheet_name ILIKE %s
                        ORDER BY sheet_index LIMIT 1""", (doc_id, sheet))
    else:
        cur.execute("""SELECT id, columns FROM vendor_doc_tables
                        WHERE doc_id=%s ORDER BY sheet_index LIMIT 1""", (doc_id,))
    t = cur.fetchone()
    if not t:
        raise RunError("that spreadsheet has not been read into the database yet")
    table_id, columns = t[0], t[1]
    names = [c["name"] for c in (columns or [])]
    cur.execute("""SELECT row_number, data FROM vendor_doc_rows
                    WHERE table_id=%s ORDER BY row_number LIMIT %s""", (table_id, MAX_ROWS))
    rows = [{"__row": n, **(d or {})} for n, d in cur.fetchall()]
    return names, rows


def _contract_fields(cur, tenant: str, supplier: str, doc: dict) -> dict:
    """A contract's read values as a flat {field: value} map.

    Only approved and still-pending claims are offered; a discarded one was
    looked at by a human and rejected, so feeding it into a calculation would
    reintroduce exactly what they threw out.
    """
    # comm_extractions is keyed by (source_type, source_id), not by doc_id —
    # it holds extractions from email threads as well as from documents.
    cur.execute("""SELECT claims FROM comm_extractions
                    WHERE tenant_id=%s AND source_type='contract' AND source_id=%s
                    ORDER BY created_at DESC LIMIT 1""", (tenant, doc["doc_id"]))
    row = cur.fetchone()
    out: dict[str, Any] = {}
    for claim in (row[0] if row and row[0] else []) or []:
        if not isinstance(claim, dict):
            continue
        if str(claim.get("status", "")).lower() == "discarded":
            continue
        field = claim.get("field") or claim.get("name") or claim.get("label")
        if not field:
            continue
        # `new_value` is what the contract says; `value` is what the vendor
        # record already held, and is null until the claim is approved. Reading
        # `value` alone meant every pending term came through empty — which is
        # most of them, since a claim sits PENDING until someone accepts it.
        val = claim.get("new_value")
        if val in (None, ""):
            val = claim.get("value")
        if val in (None, ""):
            continue
        out[str(field)] = val
        # The unit is carried alongside rather than folded into the number: a
        # routing fee of 5 "% of the total invoice amount" is 5, not 0.05, and
        # quietly dividing by 100 here would make the formula that does it
        # right look wrong.
        if claim.get("unit"):
            out[f"{field}_unit"] = claim["unit"]
    return out


# ── node executors ──────────────────────────────────────────────────────────

def _run_source(cur, ctx: dict, node: dict) -> dict:
    kind, cfg = node["kind"], node.get("config") or {}
    tenant, supplier = ctx["tenant"], ctx["supplier"]

    if kind in ("ratecard", "document"):
        label = "rate" if kind == "ratecard" else (cfg.get("folder") or None)
        doc = (_latest_doc(cur, tenant, supplier, label_like=label, parsed=True)
               or _latest_doc(cur, tenant, supplier, parsed=True))
        if not doc:
            # A spreadsheet filed before it could be read into rows — anything
            # uploaded before that feature existed — is still on the vendor and
            # looks fine in Documents. Saying "none has been filed" sends the
            # user looking for a missing file instead of an unread one, so the
            # unread case is named, and read now rather than reported.
            pending = _unread_sheet(cur, tenant, supplier, label)
            if pending:
                _read_now(pending, tenant, supplier)
                doc = _latest_doc(cur, tenant, supplier, label_like=label, parsed=True)
            if not doc:
                raise RunError(
                    f"{pending['file_name']} has not been read into rows yet — re-upload it"
                    if pending else "no spreadsheet has been filed on this vendor yet")
        names, rows = _sheet_rows(cur, doc["doc_id"], cfg.get("sheet"))
        return {"type": "table", "doc": doc, "columns": names, "rows": rows,
                "summary": f"{len(rows)} rows from {doc['file_name']}"}

    if kind == "contract":
        doc = _latest_doc(cur, tenant, supplier, doc_type="contract")
        if not doc:
            raise RunError("no contract has been filed on this vendor yet")
        fields = _contract_fields(cur, tenant, supplier, doc)
        if not fields:
            raise RunError(f"{doc['file_name']} has not been read for values yet")
        return {"type": "fields", "doc": doc, "fields": fields,
                "summary": f"{len(fields)} values from {doc['file_name']}"}

    if kind == "bills":
        # fact_invoices, not fact_bills: the bills the app shows live there, and
        # fact_bills has neither these column names nor a deleted_at.
        cur.execute("""SELECT invoice_id, invoice_number, invoice_date, total_amount,
                              outstanding_amount, status
                         FROM fact_invoices
                        WHERE tenant_id=%s AND supplier_id=%s
                          AND COALESCE(soft_status, 'active') = 'active'
                        ORDER BY invoice_date DESC NULLS LAST LIMIT %s""",
                    (tenant, supplier, MAX_ROWS))
        rows = [{"__row": i + 1, "Invoice": r[1], "Date": r[2].isoformat() if r[2] else None,
                 "Amount": float(r[3] or 0), "Outstanding": float(r[4] or 0), "Status": r[5]}
                for i, r in enumerate(cur.fetchall())]
        return {"type": "table", "columns": ["Invoice", "Date", "Amount", "Outstanding", "Status"],
                "rows": rows, "summary": f"{len(rows)} bills"}

    raise RunError(f"{kind} is not a source this can read")


def _scope_for(inputs: dict[str, dict]) -> dict:
    """What a node's expressions can see: each upstream node by its kind."""
    scope: dict[str, Any] = {}
    for name, val in inputs.items():
        if val.get("type") == "fields":
            scope[name] = val["fields"]
        elif val.get("type") == "table":
            scope[name] = val
    return scope


def _run_formula(node: dict, inputs: dict[str, dict]) -> dict:
    cfg = node.get("config") or {}
    cols = [s for s in _steps(cfg.get("steps")) if (s.get("expr") or "").strip()]
    aggs = [s for s in _steps(cfg.get("aggregates")) if (s.get("expr") or "").strip()]
    if not cols and not aggs:
        raise RunError("this Formula node has no calculations")

    table = next((v for v in inputs.values() if v.get("type") == "table"), None)
    fields = {k: v["fields"] for k, v in inputs.items() if v.get("type") == "fields"}
    if cols and table is None:
        raise RunError("no spreadsheet is connected, so there are no rows to calculate over")

    rows = [dict(r) for r in (table["rows"] if table else [])]
    names = [c["name"].strip() for c in cols if c.get("name")]
    known = list((table or {}).get("columns") or [])

    # Per-row columns, each able to use the ones named above it.
    #
    # A blank cell is dropped entirely when a sheet is read (vendor_doc_tables
    # only stores values that are present), so a row with no Bill Rate has no
    # such key at all. Every known column is laid out first, missing ones as
    # None, which keeps the two cases apart: an empty cell is empty, while a
    # column name that is simply wrong still says so.
    failures: list[str] = []
    for r in rows:
        scope: dict[str, Any] = dict(fields)
        if table is not None:
            cells = {c: r.get(c) for c in known}
            for k, v in inputs.items():
                if v is table:
                    scope[k] = cells
        row_failed = None
        for step in cols:
            nm = (step.get("name") or "").strip()
            try:
                val = evaluate(step["expr"], scope, names)
            except FormulaError as e:
                # One unusable row must not throw away the other 216. The row
                # keeps its blanks and the run reports how many fell out.
                row_failed = f"row {r.get('__row')}: {nm or 'a column'}: {e}"
                break
            if nm:
                scope[nm] = val
                r[nm] = val
        if row_failed:
            failures.append(row_failed)

    if failures and len(failures) == len(rows) and rows:
        # Every row failed the same way — that is the formula, not the data.
        raise RunError(failures[0].split(': ', 1)[-1])

    # Sheet totals: a column arrives as the whole list of its values.
    agg_scope: dict[str, Any] = dict(fields)
    for nm in names:
        agg_scope[nm] = [r.get(nm) for r in rows]
    agg_names = [a["name"].strip() for a in aggs if a.get("name")]
    totals: dict[str, Any] = {}
    for step in aggs:
        nm = (step.get("name") or "").strip()
        try:
            val = evaluate(step["expr"], agg_scope, names + agg_names)
        except FormulaError as e:
            raise RunError(f"{nm or 'a total'}: {e}") from e
        if nm:
            agg_scope[nm] = val
            totals[nm] = val

    done = len(rows) - len(failures)
    return {"type": "table", "doc": (table or {}).get("doc"),
            "columns": ((table or {}).get("columns") or []) + names,
            "added": names, "rows": rows, "totals": totals, "skipped": failures[:20],
            "writeback": cfg.get("writeback") or "", "copy_name": cfg.get("copy_name") or "",
            "summary": f"{len(names)} column(s) over {done} rows"
                       + (f", {len(totals)} total(s)" if totals else "")
                       + (f"; {len(failures)} row(s) skipped" if failures else "")}


def _steps(raw: Any) -> list[dict]:
    if not raw:
        return []
    if isinstance(raw, list):
        return [s for s in raw if isinstance(s, dict)]
    try:
        v = json.loads(raw)
        return [s for s in v if isinstance(s, dict)] if isinstance(v, list) else []
    except Exception:
        return []


def as_text(val: dict, limit: int = 4000) -> str:
    """One upstream value rendered for a prompt or a mail body."""
    if val.get("type") == "fields":
        return "\n".join(f"{k}: {v}" for k, v in val["fields"].items())[:limit]
    if val.get("type") == "table":
        out = []
        if val.get("totals"):
            out.append("Totals: " + ", ".join(f"{k} = {_fmt(v)}" for k, v in val["totals"].items()))
        cols = val.get("columns") or []
        out.append(" | ".join(str(c) for c in cols))
        for r in (val.get("rows") or [])[:50]:
            out.append(" | ".join(_fmt(r.get(c)) for c in cols))
        return "\n".join(out)[:limit]
    return str(val.get("text") or "")[:limit]


def _fmt(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, float):
        return f"{v:,.2f}" if v % 1 else f"{v:,.0f}"
    return str(v)
