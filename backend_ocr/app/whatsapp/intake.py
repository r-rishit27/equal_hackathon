"""Channel-neutral bill intake: classify → OCR → duplicate/correction → draft.

Reuses the Email Agent's classifiers and OCR (routers/agent.py) so both
channels make the same decisions. What is new here, and what the email path
does not yet do (see docs/whatsapp-agent/07-e2e-plan.md, task B5/B6):

  * a deterministic duplicate engine across ALL channels — pending drafts and
    posted bills, matched on vendor + normalised invoice number, or on file hash;
  * a scoped advisory lock so two arrivals of the same invoice cannot both
    create a draft (edge case E3);
  * idempotent draft insert keyed by the source item (edge case F1/F3).
"""
from __future__ import annotations

import os
import re
import uuid
from dataclasses import dataclass, field
from datetime import date

from psycopg2.extras import Json

CONFIDENCE_FLOOR = float(os.getenv("WA_CLASSIFY_CONFIDENCE_FLOOR", "0.6"))
_REUSED_NUMBER_DAYS = 180


class RetryableIntakeError(Exception):
    def __init__(self, code: str, msg: str = ""):
        super().__init__(msg or code)
        self.code = code


@dataclass
class Provenance:
    tenant_id: str
    channel: str                 # whatsapp | email | upload
    source_ref: str              # e.g. "<MessageSid>:<media index>"
    idempotency_key: str
    supplier_id: str | None
    contact_id: str | None
    sender_masked: str | None
    conversation_key: str | None
    caption: str = ""


@dataclass
class IntakeResult:
    decision: str                # DRAFTED | DUPLICATE | CORRECTION | NOT_A_BILL | CONTRACT | LOW_CONFIDENCE | UNREADABLE
    draft_id: str | None = None
    related_draft_id: str | None = None
    related_bill_id: str | None = None
    diff: dict = field(default_factory=dict)
    reason: str = ""


# ── Document text + classification ───────────────────────────────────────────

def pdf_text(path: str, max_pages: int = 2, max_chars: int = 4000) -> tuple[str, bool]:
    """(first pages' text, encrypted?)"""
    import fitz  # pymupdf
    try:
        doc = fitz.open(path)
    except Exception as e:
        raise ValueError(f"PDF_CORRUPT: {e}") from e
    try:
        if doc.needs_pass:
            return "", True
        parts = []
        for i in range(min(max_pages, doc.page_count)):
            parts.append(doc.load_page(i).get_text())
        return "\n".join(parts)[:max_chars], False
    finally:
        doc.close()


def classify(caption: str, text: str) -> tuple[str, float, str]:
    """('bill'|'contract'|'other'|'low', confidence, reason). Raises
    RetryableIntakeError when the model is unavailable — a classifier failure
    is never treated as 'bill' and never silently dropped (PRD FR-10)."""
    from ..routers.agent import classify_email_document, classify_email_is_bill

    subject = caption or "(vendor sent this PDF on WhatsApp with no message)"
    body = f"{caption}\n\n--- Text extracted from the attached PDF ---\n{text}" if text else caption

    doc = classify_email_document(subject, body)
    if _is_error(doc.get("reason")):
        raise RetryableIntakeError("CLASSIFIER_UNAVAILABLE", doc.get("reason", ""))
    if doc["kind"] == "contract" and doc["confidence"] >= CONFIDENCE_FLOOR:
        return "contract", doc["confidence"], doc["reason"]

    cls = classify_email_is_bill(subject, body)
    if _is_error(cls.get("reason")):
        raise RetryableIntakeError("CLASSIFIER_UNAVAILABLE", cls.get("reason", ""))
    if cls["is_bill"]:
        return "bill", cls["confidence"], cls["reason"]
    if cls["confidence"] < CONFIDENCE_FLOOR:
        return "low", cls["confidence"], cls["reason"]
    return "other", cls["confidence"], cls["reason"]


def _is_error(reason: str | None) -> bool:
    r = (reason or "").lower()
    return r.startswith("classifier error") or "not configured" in r


# ── Duplicate / correction engine ────────────────────────────────────────────

def norm_invoice_number(n) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(n or "").upper())


def _num(v):
    try:
        return round(float(v), 2) if v is not None and v != "" else None
    except (TypeError, ValueError):
        return None


def _date(v):
    try:
        return date.fromisoformat(str(v)[:10]) if v else None
    except ValueError:
        return None


def _summary(payload: dict) -> dict:
    payload = payload or {}
    return {
        "invoice_number": payload.get("invoice_number"),
        "invoice_date": payload.get("invoice_date"),
        "total_amount": _num(payload.get("total_amount")),
        "tax_amount": _num(payload.get("tax_amount") or payload.get("total_tax")),
        "subtotal": _num(payload.get("subtotal") or payload.get("sub_total")),
    }


def _diff(old: dict, new: dict) -> dict:
    out = {}
    for k in ("total_amount", "tax_amount", "subtotal", "invoice_date"):
        a, b = old.get(k), new.get(k)
        if a is not None and b is not None and str(a) != str(b):
            if k != "invoice_date" and abs(float(a) - float(b)) < 0.01:
                continue
            out[k] = {"from": a, "to": b}
    return out


def _candidates(cur, tenant_id: str, supplier_id: str, inv_norm: str) -> list[dict]:
    """Prior records of this invoice from ANY channel: drafts and posted bills."""
    cur.execute("""
        SELECT 'draft' AS kind, id::text AS id, status, source_channel, ocr_payload, created_at
        FROM agent_draft_bills
        WHERE tenant_id=%s AND supplier_id=%s AND status IN ('pending','submitted')
          AND regexp_replace(upper(coalesce(ocr_payload->>'invoice_number','')), '[^A-Z0-9]', '', 'g') = %s
        ORDER BY created_at DESC LIMIT 5
    """, (tenant_id, supplier_id, inv_norm))
    rows = [dict(r) for r in cur.fetchall()]
    cur.execute("""
        SELECT 'bill' AS kind, invoice_id::text AS id, status::text AS status, NULL AS source_channel,
               invoice_number, invoice_date, total_amount
        FROM fact_invoices
        WHERE tenant_id=%s AND supplier_id=%s
          AND regexp_replace(upper(coalesce(invoice_number,'')), '[^A-Z0-9]', '', 'g') = %s
        LIMIT 5
    """, (tenant_id, supplier_id, inv_norm))
    for r in cur.fetchall():
        r = dict(r)
        r["ocr_payload"] = {"invoice_number": r.pop("invoice_number"),
                            "invoice_date": str(r.pop("invoice_date")) if r.get("invoice_date") else None,
                            "total_amount": r.pop("total_amount")}
        rows.append(r)
    return rows


def decide_and_draft(cur, prov: Provenance, source_file: str, sha256: str, ocr: dict) -> IntakeResult:
    """Run inside the caller's transaction (the caller also fences its job
    update in the same transaction, then commits)."""
    if prov.idempotency_key:
        cur.execute("SELECT id::text FROM agent_draft_bills WHERE tenant_id=%s AND idempotency_key=%s",
                    (prov.tenant_id, prov.idempotency_key))
        row = cur.fetchone()
        if row:
            return IntakeResult("DRAFTED", draft_id=row["id"], reason="Already drafted for this message")

    new = _summary(ocr)
    inv_norm = norm_invoice_number(new["invoice_number"])
    lock_key = f"{prov.tenant_id}|{prov.supplier_id}|{inv_norm or sha256}"
    cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (lock_key,))

    # Exact file replay (any channel) — checked under the lock.
    cur.execute("""
        SELECT id::text, source_channel FROM agent_draft_bills
        WHERE tenant_id=%s AND content_sha256=%s AND status IN ('pending','submitted')
        ORDER BY created_at LIMIT 1
    """, (prov.tenant_id, sha256))
    same_file = cur.fetchone()
    if same_file:
        return IntakeResult("DUPLICATE", related_draft_id=same_file["id"],
                            reason=f"Same PDF already received via {same_file['source_channel']}")

    analysis, suggestion, related_invoice = "new", None, None
    related_draft_id = related_bill_id = None
    diff: dict = {}
    if prov.supplier_id and inv_norm:
        new_date = _date(new["invoice_date"])
        for cand in _candidates(cur, prov.tenant_id, prov.supplier_id, inv_norm):
            old = _summary(cand["ocr_payload"])
            old_date = _date(old["invoice_date"])
            if new_date and old_date and abs((new_date - old_date).days) > _REUSED_NUMBER_DAYS:
                continue  # number reused in a later period (edge case E7)
            d = _diff(old, new)
            where = (f"posted bill ({cand['status']})" if cand["kind"] == "bill"
                     else f"{cand['source_channel'] or 'email'} draft ({cand['status']})")
            if not d:
                return IntakeResult(
                    "DUPLICATE",
                    related_draft_id=cand["id"] if cand["kind"] == "draft" else None,
                    related_bill_id=cand["id"] if cand["kind"] == "bill" else None,
                    reason=f"Invoice {new['invoice_number']} already exists as a {where}")
            analysis, diff = "correction", d
            related_invoice = new["invoice_number"]
            related_draft_id = cand["id"] if cand["kind"] == "draft" else None
            related_bill_id = cand["id"] if cand["kind"] == "bill" else None
            changes = ", ".join(f"{k.replace('_', ' ')} {v['from']} → {v['to']}" for k, v in d.items())
            suggestion = (f"Revised version of invoice {new['invoice_number']} ({changes}); earlier copy is a {where}. "
                          + ("The posted bill was NOT changed — follow the normal cancel/credit-note process if this "
                             "revision is correct." if cand["kind"] == "bill"
                             else "Discard whichever draft is wrong."))
            break

    cur.execute("""
        INSERT INTO agent_draft_bills
            (tenant_id, supplier_id, contact_id, thread_id, from_email, subject, source_file, ocr_payload,
             analysis, suggestion, related_invoice, source_channel, source_ref, sender_masked,
             content_sha256, idempotency_key, related_draft_id, diff)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (tenant_id, idempotency_key) WHERE idempotency_key IS NOT NULL DO NOTHING
        RETURNING id::text
    """, (prov.tenant_id, prov.supplier_id, prov.contact_id, prov.conversation_key,
          f"WhatsApp {prov.sender_masked or ''}".strip(), (prov.caption or "Invoice received on WhatsApp")[:500],
          source_file, Json(ocr), analysis, suggestion, related_invoice, prov.channel, prov.source_ref,
          prov.sender_masked, sha256, prov.idempotency_key, related_draft_id, Json(diff) if diff else None))
    row = cur.fetchone()
    if not row:
        cur.execute("SELECT id::text FROM agent_draft_bills WHERE tenant_id=%s AND idempotency_key=%s",
                    (prov.tenant_id, prov.idempotency_key))
        row = cur.fetchone()
    return IntakeResult("CORRECTION" if analysis == "correction" else "DRAFTED",
                        draft_id=row["id"], related_draft_id=related_draft_id,
                        related_bill_id=related_bill_id, diff=diff,
                        reason=suggestion or "Draft created")


def store_contract(cur, tenant_id: str, supplier_id: str, file_name: str, data: bytes) -> str:
    """Same storage + row shape as a hand-uploaded vendor document."""
    from ..core import object_store
    doc_id = str(uuid.uuid4())
    dest = object_store.save(object_store.key("vendor-docs", tenant_id, supplier_id, doc_id), data, "application/pdf")
    cur.execute("SELECT brand_id FROM dim_suppliers WHERE supplier_id=%s AND tenant_id=%s", (supplier_id, tenant_id))
    b = cur.fetchone()
    cur.execute("""
        INSERT INTO vendor_documents (id, supplier_id, tenant_id, brand_id, file_name, file_path, file_size, uploaded_by)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
    """, (doc_id, supplier_id, tenant_id, b["brand_id"] if b else None, file_name, dest, len(data), "WhatsApp Agent"))
    return doc_id
