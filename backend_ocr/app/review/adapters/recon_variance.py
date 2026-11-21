"""recon_variance.py — invoice vs PO vs on-ground evidence (docs/bata-recon/).

One finding per recon case that still has open BLOCKER/REVIEW lines or failed
header checks. The recon engine has already done the work (recon_line_results);
this adapter only mirrors open cases into Review Hub, like billing_discrepancies
mirrors the Nova recon service. An acknowledged case, or one with nothing open,
stops being yielded and the AUTO_RESOLVE sweep closes its finding.
"""
from __future__ import annotations

from decimal import Decimal
from typing import AsyncIterator

import asyncpg

from .. import links
from ..routing import data_audience
from ..types import FindingDraft, condition_hash, jsonb, table_evidence
from .base import FindingAdapter

_SQL = """
SELECT rc.id, rc.supplier_id, rc.bill_id, rc.invoice_no, rc.money_at_risk, rc.under_billed, rc.counts,
       rc.result_hash, po.po_number || '-' || po.revision AS po_number, s.name AS vendor_name,
       (SELECT json_agg(x) FROM (
           SELECT r.result->>'description' AS d, r.severity, r.statuses, r.result->>'delta' AS delta
             FROM recon_line_results r
            WHERE r.case_id = rc.id AND r.reviewed_by IS NULL AND r.severity IN ('BLOCKER','REVIEW')
            ORDER BY CASE r.severity WHEN 'BLOCKER' THEN 0 ELSE 1 END, abs((r.result->>'delta')::numeric) DESC
            LIMIT 8) x) AS top_lines,
       (SELECT json_agg(json_build_object('label', h.label, 'detail', h.detail, 'severity', h.severity))
          FROM recon_header_checks h WHERE h.case_id = rc.id AND NOT h.passed
           AND h.severity IN ('BLOCKER','REVIEW')) AS failed_checks
  FROM recon_cases rc
  LEFT JOIN purchase_orders po ON po.id = rc.po_id
  LEFT JOIN dim_suppliers s ON s.supplier_id = rc.supplier_id AND s.tenant_id = rc.tenant_id
 WHERE rc.tenant_id = $1::uuid AND rc.status = 'NEEDS_REVIEW' AND rc.bill_id IS NOT NULL
 ORDER BY rc.money_at_risk DESC
 LIMIT $2
"""


class ReconVarianceAdapter(FindingAdapter):
    detector = "recon_variance"
    family = "reconciliation"
    source_service = "recon"

    async def scan(self, conn: asyncpg.Connection, tenant_id: str, limit: int) -> AsyncIterator[FindingDraft]:
        if not await conn.fetchval("SELECT to_regclass('recon_cases') IS NOT NULL"):
            return
        for c in await conn.fetch(_SQL, tenant_id, limit):
            counts = jsonb(c["counts"], {}) or {}
            blockers, reviews = int(counts.get("BLOCKER", 0)), int(counts.get("REVIEW", 0))
            lines = jsonb(c["top_lines"], []) or []
            checks = jsonb(c["failed_checks"], []) or []
            if not lines and not checks:
                continue
            risk: Decimal = c["money_at_risk"] or Decimal(0)
            under: Decimal = c["under_billed"] or Decimal(0)
            inv = c["invoice_no"] or "Invoice"
            po = c["po_number"] or "its PO"
            if blockers:
                title = f"{inv}: {blockers} line(s) billed beyond PO or site report" + (f", ₹{risk:,.2f} at risk" if risk else "")
            else:
                title = f"{inv}: {reviews} difference(s) vs {po} and the site report to check"
            detail_bits = [f"Reconciled against {po}."]
            if under:
                detail_bits.append(f"The vendor billed ₹{under:,.2f} less than the site report supports.")
            rows = [[l["d"], l["severity"].title(), ", ".join(s.replace("_", " ").lower() for s in (l["statuses"] or [])
                                                             if s not in ("MATCHED", "UNDER_USED", "AUDITOR_REMARK")),
                     l.get("delta")] for l in lines]
            rows += [[h["label"], h["severity"].title(), h.get("detail") or "", None] for h in checks[:4]]
            aud = data_audience("edit")
            yield FindingDraft(
                tenant_id=tenant_id, finding_type="recon_variance", family=self.family, subject_type="bill",
                subject_id=str(c["bill_id"]), severity="HIGH" if blockers else "MEDIUM", title=title,
                detail=" ".join(detail_bits),
                deep_link=links.vendor_recon(str(c["supplier_id"]), str(c["id"])),
                condition_hash=condition_hash("recon_variance", c["id"], c["result_hash"]),
                detector=self.detector, source_service=self.source_service, verification="VERIFIED",
                money_at_risk=risk if risk else None, money_at_risk_inr=risk if risk else None,
                entities=(("bill", str(c["bill_id"]), "subject", inv),
                          ("vendor", str(c["supplier_id"]), "counterparty", c["vendor_name"])),
                evidence=table_evidence(["Line or check", "Severity", "What differs", "Δ ₹"], rows,
                                        note="From the recon case; open it to see each line against the PO and report."),
                audience_roles=aud.roles, required_capability=aud.capability, key_qualifier=str(c["id"]),
            )
