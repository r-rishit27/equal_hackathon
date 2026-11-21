"""What a run checks besides doing its job: the contract terms it calculated
with, and whether the sheet it produced agrees with the vendor's bill.

**Terms are held, not followed.** A flow reads `contract["routing_fee"]` from
the latest contract on the vendor. Following that blindly means the day a new
contract is filed with a different fee, the next run silently recalculates —
and mails — every number on a different basis, with nobody having decided
that. So the first run records the value it used (on `vendor_flows.terms`),
and every later run compares the latest contract against it:

* same value            → carry on;
* different value       → keep calculating with the held value, and put the
                          change in front of a person (Review Hub, via the
                          `playground_checks` adapter) as an either/or;
* they chose the contract → the held value becomes the contract's;
* they kept the old one   → remembered *against that contract and value*, so
                          the same contract does not ask again, but a newer
                          one still does.

Only terms the flow's formulas actually reference are held — a changed
termination notice has no bearing on a calculated fee and asking about it
would be noise.

**The sheet is reconciled against the bill.** The total the sheet calls its
invoice amount is compared to the vendor's latest bill before GST (the sheet
carries no tax, so that is like for like), and the result is stored on the run
so the bill can show it and Review Hub can raise a mismatch.
"""
from __future__ import annotations

import datetime as _dt
import json
import re
from typing import Any

from .formula import _num

# A computed figure is fractional (a bill rate over 21 working days); a bill is
# in whole rupees or paise. A rupee either way is rounding, not a difference.
MATCH_TOLERANCE_INR = 1.0
# Beyond rounding but within this share of the bill reads "close", not "off" —
# the same 2% the Nova reconciliation treats as materially the same.
CLOSE_TOLERANCE_PCT = 2.0

# Steps are stored as JSON text, so the quotes may arrive escaped (\").
_CONTRACT_REF = re.compile(r"""contract\s*\[\s*\\?["']([^"'\\]+)\\?["']\s*\]""")
# Which sheet total is the amount the vendor should be invoicing. Named rather
# than guessed by position: comparing "Provision fees" against a bill would be
# a confident, wrong finding.
_INVOICE_TOTAL = re.compile(r"invoice|payable|bill", re.I)


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


def _same(a: Any, b: Any) -> bool:
    na, nb = _num(a), _num(b)
    if na is not None and nb is not None:
        return abs(na - nb) < 1e-9
    return str(a).strip().lower() == str(b).strip().lower()


def referenced_terms(nodes: list[dict]) -> set[str]:
    """Contract fields any Formula node reads, by name."""
    out: set[str] = set()
    for n in nodes:
        if n.get("kind") != "formula":
            continue
        cfg = n.get("config") or {}
        for key in ("steps", "aggregates"):
            out.update(_CONTRACT_REF.findall(str(cfg.get(key) or "")))
    return out


# ── terms ───────────────────────────────────────────────────────────────────

def load_terms(cur, flow_id: str) -> dict:
    cur.execute("SELECT terms FROM vendor_flows WHERE flow_id=%s", (flow_id,))
    r = cur.fetchone()
    return dict(r[0] or {}) if r else {}


def save_terms(cur, flow_id: str, terms: dict) -> None:
    cur.execute("UPDATE vendor_flows SET terms=%s WHERE flow_id=%s", (json.dumps(terms), flow_id))


def settle_terms(terms: dict, contract_val: dict, wanted: set[str]) -> list[dict]:
    """Decide which value each referenced contract term runs with.

    Mutates `contract_val["fields"]` so the formula sees the held value, and
    `terms` so the caller can store what was decided. Returns one note per
    term for the run record.
    """
    fields = contract_val.get("fields") or {}
    doc = contract_val.get("doc") or {}
    notes: list[dict] = []

    for field in sorted(wanted):
        if field not in fields:
            continue
        latest = fields[field]
        unit = fields.get(f"{field}_unit") or ""
        held = terms.get(field)

        if held is None:
            # First run with this term: what the contract says is what the flow
            # was built on.
            terms[field] = {"value": latest, "unit": unit, "doc_id": doc.get("doc_id"),
                            "file_name": doc.get("file_name"), "since": _now(),
                            "how": "from the contract"}
            notes.append({"field": field, "value": latest, "unit": unit,
                          "file_name": doc.get("file_name"), "status": "held"})
            continue

        if _same(held.get("value"), latest):
            # Agrees — including a newer contract that restates the same fee.
            held["doc_id"], held["file_name"] = doc.get("doc_id"), doc.get("file_name")
            pending = held.get("pending") or {}
            if pending.get("source") == "email":
                # The contract agreeing with the held value does not answer a
                # vendor's email saying it has changed — that is still open.
                notes.append({"field": field, "value": held["value"], "unit": held.get("unit") or unit,
                              "file_name": doc.get("file_name"), "status": "changed",
                              "contract_value": pending.get("value"),
                              "contract_file": pending.get("file_name")})
                continue
            held.pop("pending", None)
            notes.append({"field": field, "value": held["value"], "unit": unit,
                          "file_name": doc.get("file_name"), "status": "held"})
            continue

        kept = held.get("kept_against") or {}
        if kept.get("doc_id") == doc.get("doc_id") and _same(kept.get("value"), latest):
            # Someone already looked at this exact contract and kept the old value.
            fields[field] = held["value"]
            held.pop("pending", None)
            notes.append({"field": field, "value": held["value"], "unit": held.get("unit") or unit,
                          "file_name": held.get("file_name"), "status": "kept",
                          "contract_value": latest, "contract_file": doc.get("file_name")})
            continue

        # The contract moved and nobody has decided. Calculate on the value the
        # flow has been using, and ask.
        fields[field] = held["value"]
        pending = held.get("pending") or {}
        if not (pending.get("doc_id") == doc.get("doc_id") and _same(pending.get("value"), latest)):
            held["pending"] = {"value": latest, "unit": unit, "doc_id": doc.get("doc_id"),
                               "file_name": doc.get("file_name"), "seen_at": _now()}
        notes.append({"field": field, "value": held["value"], "unit": held.get("unit") or unit,
                      "file_name": held.get("file_name"), "status": "changed",
                      "contract_value": latest, "contract_file": doc.get("file_name")})
    return notes


def propose_change(terms: dict, field: str, value: Any, unit: str | None, source: dict) -> bool:
    """A change to a held term stated somewhere other than a contract — today,
    a vendor's email read by the communication agent.

    Recorded as the term's open question, exactly like a newer contract, so
    the same Review Hub either/or and the same next-run behaviour apply. Only
    a term the flow already holds can change; one it has never used has no
    "from" to compare against. Returns True when something was recorded.

    `source`: {"id", "label", "quote"} — the email's message id, a readable
    name for it, and the sentence the value came from.
    """
    held = terms.get(field)
    if not held or value in (None, ""):
        return False
    if _same(held.get("value"), value):
        return False                       # the email restates what is in force
    kept = held.get("kept_against") or {}
    if kept.get("doc_id") == source.get("id"):
        return False                       # this very email was already answered
    pending = held.get("pending") or {}
    if pending.get("doc_id") == source.get("id") and _same(pending.get("value"), value):
        return False
    held["pending"] = {"value": str(value), "unit": unit or held.get("unit") or "",
                       "doc_id": source.get("id"), "file_name": source.get("label"),
                       "source": "email", "quote": source.get("quote"), "seen_at": _now()}
    return True


def decide_term(terms: dict, field: str, choice: str, actor: str | None) -> dict:
    """Apply a person's answer to a pending term change. Returns the term."""
    held = terms.get(field)
    if not held or not held.get("pending"):
        raise LookupError("there is no open question about this term")
    p = held.pop("pending")
    if choice == "contract" and p.get("source") == "email":
        # The vendor amended a contract term by email. Remember which contract
        # value it overrides, so the next run does not ask about that same
        # contract again (settle_terms' kept_against branch), and keep where
        # it came from so the contract's own panel can say why it changed.
        held["kept_against"] = {"doc_id": held.get("doc_id"), "value": held.get("value"),
                                "file_name": held.get("file_name")}
        held.update({"value": p["value"], "doc_id": p.get("doc_id"), "file_name": p.get("file_name"),
                     "source": "email", "quote": p.get("quote"), "since": _now(),
                     "how": "vendor email value chosen"})
    elif choice == "contract":
        held.update({"value": p["value"], "unit": p.get("unit") or held.get("unit"),
                     "doc_id": p.get("doc_id"), "file_name": p.get("file_name"),
                     "since": _now(), "how": "contract value chosen"})
        held.pop("kept_against", None)
        held.pop("source", None)
        held.pop("quote", None)
    elif choice == "keep":
        held["kept_against"] = {"doc_id": p.get("doc_id"), "value": p["value"],
                                "file_name": p.get("file_name")}
        held["how"] = "kept over a newer contract"
    else:
        raise ValueError("choice must be 'contract' or 'keep'")
    held["decided_by"], held["decided_at"] = actor, _now()
    return held


# ── the sheet against the bill ──────────────────────────────────────────────

def _invoice_total(values: dict[str, dict], order: list[str]) -> tuple[str, float] | None:
    """The last calculated total named as the invoice amount."""
    for nid in reversed(order):
        totals = (values.get(nid) or {}).get("totals") or {}
        for name, v in totals.items():
            n = _num(v)
            if n is not None and _INVOICE_TOTAL.search(str(name)):
                return str(name).strip(), n
    return None


def _latest_bill(cur, tenant: str, supplier: str) -> dict | None:
    cur.execute(
        """SELECT fi.invoice_id, fi.invoice_number, fi.invoice_date, fi.total_amount,
                  COALESCE(sb.taxable_amount, sb.subtotal, fi.subtotal,
                           fi.total_amount - COALESCE(fi.tax_amount, 0)) AS before_tax,
                  sb.service_month
             FROM fact_invoices fi
             LEFT JOIN stg_bills sb ON sb.stg_bill_id = fi.stg_bill_id
            WHERE fi.tenant_id=%s AND fi.supplier_id=%s
              AND COALESCE(fi.soft_status, 'active') = 'active'
            ORDER BY fi.invoice_date DESC NULLS LAST, fi.created_at DESC
            LIMIT 1""",
        (tenant, supplier),
    )
    r = cur.fetchone()
    if not r:
        return None
    return {"invoice_id": str(r[0]), "invoice_number": r[1],
            "invoice_date": r[2].isoformat() if r[2] else None,
            "bill_total": float(r[3]) if r[3] is not None else None,
            "before_tax": float(r[4]) if r[4] is not None else None,
            "service_month": r[5]}


def reconcile(cur, tenant: str, supplier: str, values: dict[str, dict], order: list[str],
              terms_used: list[dict], produced: list[dict]) -> dict | None:
    """Compare the sheet's invoice-amount total with the vendor's latest bill.

    None when there is nothing to compare — no total named as an invoice
    amount, or no bill on the vendor yet. That is not a mismatch.
    """
    found = _invoice_total(values, order)
    if not found:
        return None
    bill = _latest_bill(cur, tenant, supplier)
    if not bill or bill["before_tax"] is None:
        return None

    total_name, sheet = found
    billed = bill["before_tax"]
    diff = round(sheet - billed, 2)
    pct = round(abs(diff) / billed * 100, 2) if billed else None
    status = ("match" if abs(diff) <= MATCH_TOLERANCE_INR
              else "close" if pct is not None and pct <= CLOSE_TOLERANCE_PCT
              else "off")
    report = next((o["name"] for o in produced if o.get("kind") in ("report", "spreadsheet")), None)
    return {"status": status, "total_name": total_name, "sheet_total": round(sheet, 2),
            **bill, "difference": diff, "difference_pct": pct,
            "tolerance_inr": MATCH_TOLERANCE_INR, "close_pct": CLOSE_TOLERANCE_PCT,
            "terms": terms_used, "report_name": report, "checked_at": _now()}
