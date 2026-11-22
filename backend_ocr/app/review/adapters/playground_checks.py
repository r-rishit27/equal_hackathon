"""playground_checks — what a playground run found that a person has to settle.

Two findings, both computed by the run itself (domain/playground/checks.py)
and only mirrored here:

* **A newer contract changes a term the flow calculates with.** The run held
  the old value and kept going; this is the either/or — use the contract's
  value, or keep the one the flow has been using. Both answers go to
  POST /api/vendors/{id}/flow/terms/{field}/decide, which owns the write. Once
  answered the term has no `pending` left, so this stops asserting it and the
  sweep closes the finding.

* **The sheet a run produced disagrees with the vendor's bill.** Only the
  latest run per bill counts: re-running after a fix (a decided term, a
  corrected rate card) writes a newer run that matches, and the finding closes
  on its own — which is what "solved when we press Run" means.
"""
from __future__ import annotations

from decimal import Decimal

from .. import links
from ..routing import data_audience
from ..types import FindingDraft, action, condition_hash, diff_evidence, jsonb
from .base import FindingAdapter


def _label(field: str) -> str:
    return field.replace("_", " ")


def _show(value, unit: str | None) -> str:
    v = str(value)
    u = (unit or "").strip()
    # "5" with a unit of "% of the total invoice amount…" reads as "5%".
    return f"{v}%" if u.startswith("%") else (f"{v} {u}".strip() if u and len(u) <= 12 else v)


def _inr(v) -> str:
    """₹25,52,128.29 — Indian grouping, as every amount in the app reads."""
    try:
        d = Decimal(str(v)).quantize(Decimal("0.01"))
    except Exception:
        return str(v)
    sign, whole, paise = ("-" if d < 0 else ""), *f"{abs(d):.2f}".split(".")
    head, tail = whole[:-3], whole[-3:]
    while len(head) > 2:
        tail = f"{head[-2:]},{tail}"
        head = head[:-2]
    return f"{sign}₹{head + ',' + tail if head else tail}.{paise}"


class PlaygroundChecksAdapter(FindingAdapter):
    detector = "adapter:playground_checks"
    family = "reconciliation"
    source_service = "playground"

    async def scan(self, conn, tenant_id: str, limit: int):
        aud = data_audience(capability="edit")
        async for f in self._term_changes(conn, tenant_id, limit, aud):
            yield f
        async for f in self._bill_mismatches(conn, tenant_id, limit, aud):
            yield f

    async def _term_changes(self, conn, tenant_id: str, limit: int, aud):
        rows = await conn.fetch(
            """
            SELECT f.supplier_id, f.terms, s.name AS vendor_name
              FROM vendor_flows f
              LEFT JOIN dim_suppliers s ON s.supplier_id = f.supplier_id AND s.tenant_id = f.tenant_id
             WHERE f.tenant_id = $1::uuid
               AND EXISTS (SELECT 1 FROM jsonb_each(f.terms) t WHERE t.value ? 'pending')
             ORDER BY f.updated_at DESC
             LIMIT $2
            """,
            tenant_id, limit,
        )
        # The Gmail thread each email-raised question came from, so the card
        # can link straight to that conversation.
        email_ids = [str(h["pending"]["doc_id"]) for r in rows
                     for h in (jsonb(r["terms"], default={}) or {}).values()
                     if isinstance(h, dict) and isinstance(h.get("pending"), dict)
                     and h["pending"].get("source") == "email" and h["pending"].get("doc_id")]
        threads: dict[str, str] = {}
        if email_ids:
            for m in await conn.fetch(
                """SELECT message_id::text AS id, thread_id FROM poc_email_messages
                    WHERE tenant_id = $1::uuid AND message_id::text = ANY($2::text[])
                      AND thread_id IS NOT NULL""",
                tenant_id, email_ids,
            ):
                threads[m["id"]] = m["thread_id"]

        for r in rows:
            sid = str(r["supplier_id"])
            vendor = r["vendor_name"] or "this vendor"
            for field, held in (jsonb(r["terms"], default={}) or {}).items():
                if not isinstance(held, dict) or not isinstance(held.get("pending"), dict):
                    continue
                p = held["pending"]
                old = _show(held.get("value"), held.get("unit"))
                new = _show(p.get("value"), p.get("unit") or held.get("unit"))
                label = _label(field)
                endpoint = f"/api/vendors/{sid}/flow/terms/{field}/decide"
                by_email = p.get("source") == "email"
                yield FindingDraft(
                    tenant_id=tenant_id,
                    finding_type="playground_term_changed",
                    family=self.family,
                    subject_type="vendor",
                    subject_id=sid,
                    severity="HIGH",
                    # Ultra-minimal: the title is the whole question, the two
                    # buttons are the answers, and "View email" is the proof.
                    # No paragraph or table restating the same two numbers.
                    title=f"{vendor}: {label} {old} → {new}",
                    deep_link=links.vendor(sid, tab="playground"),
                    condition_hash=condition_hash("playground_term_changed", field,
                                                  held.get("value"), p.get("value"), p.get("doc_id")),
                    detector=self.detector,
                    source_service=self.source_service,
                    # Both values are stored exactly; the newer one came from a
                    # model's read of a contract or an email, whose sentence is
                    # quoted beside it so a person can judge it at a glance.
                    verification="VERIFIED",
                    key_qualifier=field,
                    actions=[
                        action("keep_new", "Accept change", kind="safe",
                               endpoint=endpoint, method="POST", body={"choice": "contract"},
                               confirm={"title": f"Calculate {vendor}'s {label} at {new}",
                                        "change": {"label": label.capitalize(), "from": old, "to": new}},
                               success={"status": "ok"}),
                        action("keep_current", "Keep current", kind="safe", emphasis="secondary",
                               endpoint=endpoint, method="POST", body={"choice": "keep"},
                               confirm={"title": f"Keep calculating {vendor}'s {label} at {old}",
                                        "change": {"label": label.capitalize(), "from": old, "to": old}},
                               success={"status": "ok"}),
                    ] + ([action("open_email",
                                 # WhatsApp text rides the same queue (thread "wa:<phone>").
                                 "Open WhatsApp" if threads[str(p["doc_id"])].startswith("wa:") else "Open email",
                                 kind="navigate",
                                 href=links.vendor_thread(sid, threads[str(p["doc_id"])]))]
                         if by_email and threads.get(str(p.get("doc_id"))) else []),
                    audience_roles=aud.roles,
                    required_capability="edit",
                    # The email that raised it travels as evidence, which is
                    # what gives the drawer its "View email" preview.
                    entities=(("vendor", sid, "subject", r["vendor_name"]),) + (
                        (("email", str(p["doc_id"]), "evidence", p.get("file_name")),)
                        if by_email and p.get("doc_id") else ()),
                )

    async def _bill_mismatches(self, conn, tenant_id: str, limit: int, aud):
        rows = await conn.fetch(
            """
            SELECT DISTINCT ON (r.invoice_id)
                   r.invoice_id, r.supplier_id, r.checks, r.started_at,
                   s.name AS vendor_name, fi.due_date
              FROM vendor_flow_runs r
              JOIN fact_invoices fi ON fi.invoice_id = r.invoice_id AND fi.tenant_id = r.tenant_id
              LEFT JOIN dim_suppliers s ON s.supplier_id = r.supplier_id AND s.tenant_id = r.tenant_id
             WHERE r.tenant_id = $1::uuid AND r.invoice_id IS NOT NULL
               AND COALESCE(fi.soft_status, 'active') = 'active'
             ORDER BY r.invoice_id, r.started_at DESC
             LIMIT $2
            """,
            tenant_id, limit,
        )
        for r in rows:
            rec = (jsonb(r["checks"], default={}) or {}).get("recon") or {}
            if rec.get("status") not in ("close", "off"):
                continue  # the latest run agrees with the bill
            inv = str(r["invoice_id"])
            diff = Decimal(str(rec.get("difference") or 0))
            # difference = calculated − billed, so a positive one is a bill that is lower.
            bill_is = "lower" if diff > 0 else "higher"
            terms = "; ".join(f"{_label(t['field'])} {_show(t['value'], t.get('unit'))}"
                              for t in rec.get("terms") or [])
            yield FindingDraft(
                tenant_id=tenant_id,
                finding_type="playground_bill_mismatch",
                family=self.family,
                subject_type="bill",
                subject_id=inv,
                severity="HIGH" if rec["status"] == "off" else "MEDIUM",
                title=f"Calculated {rec.get('total_name') or 'invoice amount'} doesn't match bill "
                      f"{rec.get('invoice_number') or ''}".strip(),
                detail=(
                    f"The playground worked out {_inr(rec.get('sheet_total'))}; the bill is "
                    f"{_inr(rec.get('before_tax'))} before GST — the bill is {_inr(abs(diff))} {bill_is}"
                    f"{' (' + str(rec.get('difference_pct')) + '%)' if rec.get('difference_pct') is not None else ''}."
                ),
                deep_link=links.bill(inv, focus="playground"),
                condition_hash=condition_hash("playground_bill_mismatch", rec.get("sheet_total"),
                                              rec.get("before_tax")),
                detector=self.detector,
                source_service=self.source_service,
                money_at_risk=abs(diff),
                money_at_risk_inr=abs(diff),
                due_at=r["due_date"],
                evidence=diff_evidence(
                    "Calculated", "On the bill",
                    [("Amount before GST", _inr(rec.get("sheet_total")), _inr(rec.get("before_tax"))),
                     ("From", f"{rec.get('report_name') or 'playground run'} · {rec.get('total_name')}",
                      f"{rec.get('invoice_number') or '—'}"
                      + (f" · {rec['service_month']}" if rec.get("service_month") else "")),
                     ("Contract terms used", terms or "—", "—")],
                ),
                actions=[
                    action("open_bill", "Review the bill", kind="navigate",
                           href=links.bill(inv, focus="playground")),
                    action("open_playground", "Open the playground", kind="navigate",
                           emphasis="secondary",
                           href=links.vendor(str(r["supplier_id"]), tab="playground")),
                ],
                audience_roles=aud.roles,
                required_capability="edit",
                entities=tuple(
                    e for e in [
                        ("bill", inv, "subject", rec.get("invoice_number")),
                        ("vendor", str(r["supplier_id"]), "counterparty", r["vendor_name"])
                        if r["vendor_name"] else None,
                    ] if e
                ),
            )
