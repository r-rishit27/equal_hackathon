"""ReconRepository — every SQL statement recon runs (asyncpg).

Tenant scoping: every public read takes `tenant` and filters on it, even when
the id alone would be unique — a case id guessed from another tenant returns
nothing (E-SC-01). JSONB goes in as text and comes back parsed (the shared
pool has no JSON codec).
"""
from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from . import config, keys, vocab
from .clean import doc_number_ok, fit, gstin, store_no
from .rules import VerdictClassifier
from .normalize import norm
from .num import round2
from .types import (
    EvidenceRow, ExtractedDoc, ExtractedInvoice, ExtractedMemo, ExtractedOther, ExtractedPO, ExtractedPOD,
    InvoiceLine, LineResult, Party, POLine, PVSection, ReconResult, SegmentKind, Sourced, from_json, to_json,
)

# Saved with each evidence row (auto_verdict): the meaning Recon's screens show for it.
_CLASSIFY = VerdictClassifier()


def _j(v: Any) -> str | None:
    return None if v is None else json.dumps(to_json(v))


def _p(v: Any) -> Any:
    return json.loads(v) if isinstance(v, str) else v


def line_key(r) -> str:
    return f"{r.kind}|{r.po_key or ''}|{r.invoice_key or ''}|{r.evidence_key or ''}"


def result_hash(res: ReconResult) -> str:
    """Stable hash of what a human would see — decides whether an
    acknowledgement still stands after a recompute (E-CS-03)."""
    core = {"lines": [(line_key(l), l.severity.value, [s.value for s in l.statuses], str(l.delta)) for l in res.lines],
            "header": [(h.code, h.passed) for h in res.header]}
    return hashlib.sha256(json.dumps(core, sort_keys=True).encode()).hexdigest()


def input_fingerprint(*, segment_versions: list[tuple[str, str | None]], engine_version: str,
                      rule_version: str, decision_hwm: int | None, vocab_version: str | None = None) -> str:
    """Hash of everything a verdict depends on (plan §8).

    **`decision_hwm` is the point of this function.** `result_hash` covers the
    output, so a re-run after a reviewer decided something could hand back the
    previous verdict and look idempotent. Including the highest decision id in
    scope means a new decision changes the fingerprint, which forces a genuine
    recompute — the bake-off's "re-running after a decision returns the old
    stored result" failure.

    Segment versions are `(segment_id, extractor_version)` pairs, so a parser fix
    changes the fingerprint even when the document is byte-identical.
    """
    core = {
        "segments": sorted((str(sid), ver or "") for sid, ver in segment_versions),
        "engine": engine_version,
        "rules": rule_version,
        "vocab": vocab_version or "",
        "decisions": decision_hwm or 0,
    }
    return hashlib.sha256(json.dumps(core, sort_keys=True).encode()).hexdigest()


_DOC_TYPES = {
    SegmentKind.PURCHASE_ORDER.value: ExtractedPO, SegmentKind.TAX_INVOICE.value: ExtractedInvoice,
    SegmentKind.PV_SECTION.value: PVSection, SegmentKind.POD.value: ExtractedPOD,
    SegmentKind.APPROVAL_MEMO.value: ExtractedMemo, SegmentKind.OTHER.value: ExtractedOther,
}


def load_extracted(kind: str, data: Any) -> ExtractedDoc | None:
    data = _p(data)
    cls = _DOC_TYPES.get(kind)
    return from_json(cls, data) if cls and data else None


class ReconRepository:
    def __init__(self, pool) -> None:
        self.pool = pool

    # ── documents ──────────────────────────────────────────────────────────────
    async def claim_pending(self, limit: int) -> list[dict]:
        async with self.pool.acquire() as c:
            rows = await c.fetch(
                """UPDATE vendor_documents
                      SET recon_status = 'RUNNING', recon_stage = 'reading', recon_error = NULL,
                          recon_started_at = now()
                    WHERE id IN (SELECT id FROM vendor_documents
                                  WHERE recon_status = 'PENDING' AND deleted_at IS NULL
                                  ORDER BY uploaded_at LIMIT $1 FOR UPDATE SKIP LOCKED)
                RETURNING id, tenant_id, supplier_id, brand_id, file_path, file_name""", limit)
        return [dict(r) for r in rows]

    async def reset_stale(self, minutes: int = 15) -> int:
        async with self.pool.acquire() as c:
            res = await c.execute(
                """UPDATE vendor_documents SET recon_status = 'PENDING'
                    WHERE recon_status = 'RUNNING' AND deleted_at IS NULL
                      AND ($1 = 0 OR recon_started_at IS NULL OR recon_started_at < now() - make_interval(mins => $1))""",
                minutes)
        return int(res.split()[-1])

    async def get_doc(self, tenant: str, doc_id: str) -> dict | None:
        async with self.pool.acquire() as c:
            r = await c.fetchrow(
                """SELECT id, tenant_id, supplier_id, brand_id, file_path, file_name, recon_status, recon_stage,
                          recon_error, recon_progress, uploaded_at, uploaded_by, content_sha256
                     FROM vendor_documents WHERE id = $1::uuid AND tenant_id = $2::uuid AND deleted_at IS NULL""",
                doc_id, tenant)
        return dict(r) if r else None

    async def set_doc(self, doc_id: str, *, status: str | None = None, stage: str | None = None,
                      error: str | None = None, progress: dict | None = None) -> None:
        async with self.pool.acquire() as c:
            await c.execute(
                """UPDATE vendor_documents
                      SET recon_status   = COALESCE($2, recon_status),
                          recon_stage    = COALESCE($3, recon_stage),
                          recon_error    = CASE WHEN $2 IS NOT NULL THEN $4 ELSE COALESCE($4, recon_error) END,
                          recon_progress = COALESCE($5::jsonb, recon_progress)
                    WHERE id = $1::uuid""",
                doc_id, status, stage, error, json.dumps(progress) if progress is not None else None)

    async def find_duplicate(self, tenant: str, supplier: str, sha: str) -> dict | None:
        async with self.pool.acquire() as c:
            r = await c.fetchrow(
                """SELECT id, file_name, uploaded_at FROM vendor_documents
                    WHERE tenant_id = $1::uuid AND supplier_id = $2::uuid AND content_sha256 = $3
                      AND doc_type = 'recon' AND deleted_at IS NULL
                    ORDER BY uploaded_at LIMIT 1""", tenant, supplier, sha)
        return dict(r) if r else None

    async def mark_recon_upload(self, doc_id: str, sha: str) -> None:
        async with self.pool.acquire() as c:
            await c.execute("UPDATE vendor_documents SET recon_status = 'PENDING', content_sha256 = $2 "
                            "WHERE id = $1::uuid", doc_id, sha)

    async def list_docs(self, tenant: str, supplier: str, brand: str | None = None) -> list[dict]:
        async with self.pool.acquire() as c:
            rows = await c.fetch(
                """SELECT id, file_name, recon_status, recon_stage, recon_progress, recon_error, uploaded_at,
                          uploaded_by, content_sha256
                     FROM vendor_documents
                    WHERE tenant_id = $1::uuid AND supplier_id = $2::uuid AND doc_type = 'recon'
                      AND deleted_at IS NULL AND ($3::uuid IS NULL OR brand_id IS NULL OR brand_id = $3::uuid)
                    ORDER BY uploaded_at DESC""", tenant, supplier, brand)
        return [dict(r) for r in rows]

    # ── pages ──────────────────────────────────────────────────────────────────
    async def save_pages(self, doc_id: str, tenant: str, pages: list[dict]) -> None:
        async with self.pool.acquire() as c:
            async with c.transaction():
                await c.execute("DELETE FROM recon_doc_pages WHERE doc_id = $1::uuid", doc_id)
                await c.executemany(
                    """INSERT INTO recon_doc_pages (doc_id, page_index, tenant_id, text, source, ocr_confidence,
                              doc_class, class_conf, class_method, llm_label, hints)
                       VALUES ($1::uuid, $2, $3::uuid, $4, $5, $6, $7, $8, $9, $10, $11::jsonb)""",
                    [(doc_id, p["index"], tenant, p.get("text"), p.get("source", "text"), p.get("ocr_confidence"),
                      p.get("doc_class"), p.get("class_conf"), p.get("class_method"), fit(p.get("llm_label"), 80),
                      json.dumps(p.get("hints") or {})) for p in pages])

    async def load_pages(self, doc_id: str) -> list[dict]:
        async with self.pool.acquire() as c:
            rows = await c.fetch("SELECT * FROM recon_doc_pages WHERE doc_id = $1::uuid ORDER BY page_index", doc_id)
        out = []
        for r in rows:
            d = dict(r)
            d["hints"] = _p(d.get("hints")) or {}
            out.append(d)
        return out

    # ── segments ───────────────────────────────────────────────────────────────
    async def replace_segments(self, doc_id: str, tenant: str, supplier: str, segs: list[dict]) -> list[str]:
        """Drop this doc's segments (cascades their rows and case links) and insert fresh ones."""
        async with self.pool.acquire() as c:
            async with c.transaction():
                await c.execute("DELETE FROM recon_doc_segments WHERE doc_id = $1::uuid", doc_id)
                ids = []
                for s in segs:
                    ids.append(str(await c.fetchval(
                        """INSERT INTO recon_doc_segments (doc_id, tenant_id, supplier_id, kind, llm_label, pages,
                                  section_title, vendor_name, vendor_gstin, store_sn, confidence, status)
                           VALUES ($1::uuid, $2::uuid, $3::uuid, $4, $5, $6, $7, $8, $9, $10, $11, $12)
                           RETURNING id""",
                        doc_id, tenant, supplier, s["kind"], fit(s.get("llm_label"), 80), s["pages"],
                        fit(s.get("section_title"), 160), fit(s.get("vendor_name"), 200), gstin(s.get("vendor_gstin")),
                        store_no(s.get("store_sn")) or fit(s.get("store_sn"), 16), s.get("confidence"),
                        s.get("status", "PENDING"))))
        return ids

    async def remove_doc_parts(self, tenant: str, doc_id: str) -> set[str]:
        """Take a file's parts off every case (for delete or read-again). Returns the cases they were on.

        POs read from the file are retired (soft-deleted; reading it again brings them back), and cases
        that pointed at them or at its invoice lose that link. The parts and their rows go with them.
        """
        async with self.pool.acquire() as c:
            async with c.transaction():
                segs = [r["id"] for r in await c.fetch(
                    "SELECT id FROM recon_doc_segments WHERE doc_id = $1::uuid AND tenant_id = $2::uuid", doc_id, tenant)]
                if not segs:
                    return set()
                cases = {str(r["case_id"]) for r in await c.fetch(
                    "SELECT case_id FROM recon_case_segments WHERE segment_id = ANY($1::uuid[])", segs)}
                cases |= {str(r["id"]) for r in await c.fetch(
                    "SELECT id FROM recon_cases WHERE tenant_id = $1::uuid AND invoice_segment_id = ANY($2::uuid[])", tenant, segs)}
                pos = [r["id"] for r in await c.fetch(
                    "UPDATE purchase_orders SET deleted_at = now() WHERE tenant_id = $1::uuid AND segment_id = ANY($2::uuid[]) "
                    "AND deleted_at IS NULL RETURNING id", tenant, segs)]
                if pos:
                    cases |= {str(r["id"]) for r in await c.fetch(
                        "UPDATE recon_cases SET po_id = NULL WHERE tenant_id = $1::uuid AND po_id = ANY($2::uuid[]) RETURNING id",
                        tenant, pos)}
                await c.execute("DELETE FROM recon_doc_segments WHERE id = ANY($1::uuid[])", segs)
        return cases

    async def drop_if_empty(self, tenant: str, case_id: str) -> bool:
        """Delete a case left with no bill and no documents; its results and events go with it."""
        async with self.pool.acquire() as c:
            v = await c.fetchval(
                """DELETE FROM recon_cases rc WHERE rc.id = $1::uuid AND rc.tenant_id = $2::uuid AND rc.bill_id IS NULL
                      AND rc.invoice_segment_id IS NULL AND rc.po_id IS NULL
                      AND NOT EXISTS (SELECT 1 FROM recon_case_segments cs WHERE cs.case_id = rc.id)
                   RETURNING id""", case_id, tenant)
        return v is not None

    async def delete_doc(self, tenant: str, doc_id: str, actor: str) -> None:
        async with self.pool.acquire() as c:
            await c.execute("UPDATE vendor_documents SET deleted_at = now() WHERE id = $1::uuid AND tenant_id = $2::uuid",
                            doc_id, tenant)

    async def segment(self, tenant: str, seg_id: str) -> dict | None:
        async with self.pool.acquire() as c:
            r = await c.fetchrow(
                "SELECT * FROM recon_doc_segments WHERE id = $1::uuid AND tenant_id = $2::uuid", seg_id, tenant)
        return self._seg(r) if r else None

    async def segments_for_doc(self, doc_id: str) -> list[dict]:
        async with self.pool.acquire() as c:
            rows = await c.fetch(
                """SELECT s.*, cs.case_id FROM recon_doc_segments s
                     LEFT JOIN recon_case_segments cs ON cs.segment_id = s.id
                    WHERE s.doc_id = $1::uuid ORDER BY s.pages[1]""", doc_id)
        return [self._seg(r) for r in rows]

    async def unlinked_segments(self, tenant: str, supplier: str) -> list[dict]:
        async with self.pool.acquire() as c:
            rows = await c.fetch(
                """SELECT s.* FROM recon_doc_segments s
                     JOIN vendor_documents d ON d.id = s.doc_id AND d.deleted_at IS NULL
                    WHERE s.tenant_id = $1::uuid AND s.supplier_id = $2::uuid
                      AND s.status IN ('EXTRACTED','UNLINKED','NEEDS_REVIEW','WAITING')
                      AND NOT EXISTS (SELECT 1 FROM recon_case_segments cs WHERE cs.segment_id = s.id)""",
                tenant, supplier)
        return [self._seg(r) for r in rows]

    @staticmethod
    def _seg(r) -> dict:
        d = dict(r)
        for k in ("extracted_json", "link_candidates", "warnings"):
            d[k] = _p(d.get(k))
        d["id"] = str(d["id"])
        return d

    async def set_segment(self, seg_id: str, *, status: str | None = None, kind: str | None = None,
                          candidates: list | None = None, overridden_by: str | None = None) -> None:
        async with self.pool.acquire() as c:
            await c.execute(
                """UPDATE recon_doc_segments
                      SET status = COALESCE($2, status), kind = COALESCE($3, kind),
                          link_candidates = COALESCE($4::jsonb, link_candidates),
                          kind_overridden_by = COALESCE($5, kind_overridden_by)
                    WHERE id = $1::uuid""",
                seg_id, status, kind, json.dumps(candidates) if candidates is not None else None, overridden_by)

    async def save_extraction(self, tenant: str, supplier: str, seg_id: str, kind: str,
                              doc: ExtractedDoc, status: str = "EXTRACTED") -> str | None:
        """Persist an extraction and its typed rows. Returns the PO id for a PO."""
        meta = {}
        if isinstance(doc, PVSection):
            meta = {"section_title": doc.section_title, "vendor_name": doc.vendor.name,
                    "vendor_gstin": doc.vendor.gstin, "store_sn": doc.store_sn}
        elif isinstance(doc, (ExtractedPO, ExtractedInvoice)):
            meta = {"vendor_name": doc.vendor.name, "vendor_gstin": doc.vendor.gstin,
                    "store_sn": getattr(doc, "store_sn", None)}
        elif isinstance(doc, ExtractedMemo):
            meta = {"store_sn": doc.store_sn, "vendor_name": doc.vendor_name}
        po_id = None
        no_number = isinstance(doc, ExtractedPO) and not doc_number_ok(doc.po_number, doc.store_sn)
        if no_number:
            # Not a PO we can file (purchase_orders needs a number, and a store number such as "1859"
            # is not one): keep what was read, ask a person.
            msg = "No PO number could be read on this part. Check it was really a purchase order."
            if msg not in doc.warnings:
                doc.warnings.append(msg)
            status = "NEEDS_REVIEW"
        async with self.pool.acquire() as c:
            async with c.transaction():
                await c.execute(
                    """UPDATE recon_doc_segments
                          SET extracted_json = $2::jsonb, extractor_version = $3, status = $4, warnings = $5::jsonb,
                              section_title = COALESCE($6, section_title), vendor_name = COALESCE($7, vendor_name),
                              vendor_gstin = COALESCE($8, vendor_gstin), store_sn = COALESCE($9, store_sn)
                        WHERE id = $1::uuid""",
                    seg_id, _j(doc), doc.extractor_version, status, json.dumps(doc.warnings),
                    fit(meta.get("section_title"), 160), fit(meta.get("vendor_name"), 200), gstin(meta.get("vendor_gstin")),
                    store_no(meta.get("store_sn")) or fit(meta.get("store_sn"), 16))
                if isinstance(doc, ExtractedPO) and not no_number:
                    po_id = await self._upsert_po(c, tenant, supplier, doc, seg_id)
                elif isinstance(doc, ExtractedInvoice):
                    await self._save_invoice_lines(c, tenant, seg_id, doc.lines)
                elif isinstance(doc, (PVSection, ExtractedOther)):
                    await self._save_evidence_rows(c, tenant, seg_id, doc.rows)
        return po_id

    # ── purchase orders ────────────────────────────────────────────────────────
    async def _upsert_po(self, c, tenant: str, supplier: str, po: ExtractedPO, seg_id: str) -> str:
        number, _, rev = po.po_number.partition("-")
        revision = int(rev) if rev.isdigit() else po.revision
        po_id = await c.fetchval(
            """INSERT INTO purchase_orders (tenant_id, supplier_id, po_number, revision, po_date, delivery_date,
                      store_sn, store_name, buyer_gstin, vendor_gstin, payment_terms, requisition_no,
                      requisition_name, subtotal, tax, total, penalties, segment_id, deleted_at)
               VALUES ($1::uuid, $2::uuid, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16,
                       $17::jsonb, $18::uuid, NULL)
               ON CONFLICT (tenant_id, po_number, revision) DO UPDATE SET
                      supplier_id = EXCLUDED.supplier_id, po_date = EXCLUDED.po_date,
                      delivery_date = EXCLUDED.delivery_date, store_sn = EXCLUDED.store_sn,
                      store_name = EXCLUDED.store_name, buyer_gstin = EXCLUDED.buyer_gstin,
                      vendor_gstin = EXCLUDED.vendor_gstin, payment_terms = EXCLUDED.payment_terms,
                      requisition_no = EXCLUDED.requisition_no, requisition_name = EXCLUDED.requisition_name,
                      subtotal = EXCLUDED.subtotal, tax = EXCLUDED.tax, total = EXCLUDED.total,
                      penalties = EXCLUDED.penalties, segment_id = EXCLUDED.segment_id, deleted_at = NULL
               RETURNING id""",
            tenant, supplier, fit(number, 40), revision, po.po_date, po.delivery_date,
            store_no(po.store_sn) or fit(po.store_sn, 16), fit(po.store_name, 200),
            gstin(po.buyer_gstin), gstin(po.vendor.gstin), fit(po.payment_terms, 80), fit(po.requisition_no, 40),
            fit(po.requisition_name, 200),
            po.subtotal, po.tax, po.total, _j(po.penalties), seg_id)
        await c.execute("DELETE FROM purchase_order_lines WHERE po_id = $1", po_id)
        await c.executemany(
            """INSERT INTO purchase_order_lines (po_id, tenant_id, sno, description, norm, unit, qty, unit_price,
                      amount, delivery_date)
               VALUES ($1, $2::uuid, $3, $4, $5, $6, $7, $8, $9, $10)""",
            [(po_id, tenant, l.sno, l.description, norm(l.description), fit(l.unit, 16), l.qty, l.unit_price,
              l.amount if l.amount is not None else round2(l.qty * l.unit_price), l.delivery_date) for l in po.lines])
        # A later revision supersedes earlier ones (E-PO-03).
        await c.execute(
            """UPDATE purchase_orders SET superseded_by = $1
                WHERE tenant_id = $2::uuid AND po_number = $3 AND revision < $4 AND id <> $1""",
            po_id, tenant, number, revision)
        return str(po_id)

    async def supplier_pos(self, tenant: str, supplier: str) -> list[tuple[str, ExtractedPO]]:
        async with self.pool.acquire() as c:
            heads = await c.fetch(
                """SELECT * FROM purchase_orders WHERE tenant_id = $1::uuid AND supplier_id = $2::uuid
                      AND superseded_by IS NULL AND deleted_at IS NULL ORDER BY po_date DESC NULLS LAST""",
                tenant, supplier)
            out = []
            for h in heads:
                out.append((str(h["id"]), await self._po_from_rows(c, h)))
        return out

    async def load_po(self, tenant: str, po_id: str) -> ExtractedPO | None:
        async with self.pool.acquire() as c:
            h = await c.fetchrow("SELECT * FROM purchase_orders WHERE id = $1::uuid AND tenant_id = $2::uuid",
                                 po_id, tenant)
            return await self._po_from_rows(c, h) if h else None

    async def find_po(self, tenant: str, number: str) -> str | None:
        async with self.pool.acquire() as c:
            v = await c.fetchval(
                """SELECT id FROM purchase_orders WHERE tenant_id = $1::uuid AND po_number = $2
                      AND superseded_by IS NULL AND deleted_at IS NULL ORDER BY revision DESC LIMIT 1""",
                tenant, number)
        return str(v) if v else None

    async def _po_from_rows(self, c, h) -> ExtractedPO:
        lines = await c.fetch("SELECT * FROM purchase_order_lines WHERE po_id = $1 ORDER BY sno", h["id"])
        from .types import PenaltyTerm
        pens = [from_json(PenaltyTerm, p) for p in (_p(h["penalties"]) or [])]
        return ExtractedPO(
            segment_id=str(h["segment_id"]) if h["segment_id"] else None,
            po_number=f"{h['po_number']}-{h['revision']}", revision=h["revision"], po_date=h["po_date"],
            delivery_date=h["delivery_date"], vendor=Party(gstin=h["vendor_gstin"]), buyer_gstin=h["buyer_gstin"],
            store_sn=h["store_sn"], store_name=h["store_name"], payment_terms=h["payment_terms"],
            requisition_no=h["requisition_no"], requisition_name=h["requisition_name"],
            subtotal=h["subtotal"], tax=h["tax"], total=h["total"], penalties=pens,
            lines=[POLine(id=f"pol:{l['id']}", sno=l["sno"], description=l["description"], unit=l["unit"],
                          qty=l["qty"], unit_price=l["unit_price"], amount=l["amount"],
                          delivery_date=l["delivery_date"]) for l in lines])

    # ── invoice lines and evidence rows ────────────────────────────────────────
    async def _doc_of_segment(self, c, seg_id: str) -> str | None:
        return await c.fetchval("SELECT doc_id FROM recon_doc_segments WHERE id = $1::uuid", seg_id)

    # ── decisions (append-only; plan §6.2) ─────────────────────────────────────
    async def record_decision(self, c, tenant: str, *, line_uid: str | None, kind: str, payload: dict,
                              actor: str, case_id: str | None = None, actor_kind: str = "human") -> int | None:
        """Append one decision. Never updates: a changed mind is a new row.

        `supersedes` points at the previous live decision of the same kind on the
        same line, so the chain is walkable and an as-of replay can stop anywhere
        along it.
        """
        if line_uid is None and case_id is None:
            return None
        prev = await c.fetchval(
            """SELECT decision_id FROM recon_decisions
                WHERE tenant_id = $1::uuid AND line_uid = $2::uuid AND kind = $3
                ORDER BY decided_at DESC, decision_id DESC LIMIT 1""",
            tenant, line_uid, kind) if line_uid else None
        return await c.fetchval(
            """INSERT INTO recon_decisions (tenant_id, line_uid, case_id, kind, payload, supersedes,
                                            actor, actor_kind)
                    VALUES ($1::uuid, $2::uuid, $3::uuid, $4, $5::jsonb, $6, $7, $8)
               RETURNING decision_id""",
            tenant, line_uid, case_id, kind, json.dumps(payload, default=str), prev, actor, actor_kind)

    async def live_decisions(self, c, tenant: str, line_uids: list[str], *,
                             as_of: datetime | None = None) -> dict[tuple[str, str], dict]:
        """The decision in force per (line_uid, kind).

        With `as_of` this is the state as it stood then — the whole reason the log
        is append-only (plan §8).

        **`as_of` must come from the database's clock, not the caller's.**
        `decided_at` is server-generated, and dev's server runs 1.0 s ahead of
        this machine; an `as_of` taken locally silently excludes decisions made
        within the skew and returns *nothing* for that line, which reads as "no
        decision was in force" — the worst way for an audit replay to fail.
        Every caller today anchors on `recon_cases.as_of`, a server-side column,
        so the live path is safe. A future one taking `datetime.now()` would not
        be.
        """
        if not line_uids:
            return {}
        rows = await c.fetch(
            """SELECT DISTINCT ON (line_uid, kind) line_uid, kind, payload, actor, decided_at
                 FROM recon_decisions
                WHERE tenant_id = $1::uuid AND line_uid = ANY($2::uuid[])
                  AND ($3::timestamptz IS NULL OR decided_at <= $3::timestamptz)
                ORDER BY line_uid, kind, decided_at DESC, decision_id DESC""",
            tenant, line_uids, as_of)
        return {(str(r["line_uid"]), r["kind"]):
                {"payload": _p(r["payload"]), "actor": r["actor"], "decided_at": r["decided_at"]}
                for r in rows}

    async def case_decisions(self, tenant: str, case_id: str, *,
                             as_of: datetime | None = None) -> dict[str, dict]:
        """Decisions made about the case rather than about one of its lines.

        Keyed by `kind`, which for a check confirmation is the check's code —
        the engine looks it up by exactly that. Same append-only rule as the
        line log: a changed mind is a new row, and `as_of` replays the state as
        it stood then.
        """
        async with self.pool.acquire() as c:
            rows = await c.fetch(
                """SELECT DISTINCT ON (kind) kind, payload, actor, decided_at
                     FROM recon_decisions
                    WHERE tenant_id = $1::uuid AND case_id = $2::uuid AND line_uid IS NULL
                      AND ($3::timestamptz IS NULL OR decided_at <= $3::timestamptz)
                    ORDER BY kind, decided_at DESC, decision_id DESC""",
                tenant, case_id, as_of)
        out: dict[str, dict] = {}
        for r in rows:
            pay = _p(r["payload"]) or {}
            # A withdrawal is a row like any other; it simply does not confirm.
            if pay.get("withdrawn"):
                continue
            out[r["kind"]] = {**pay, "actor": r["actor"], "at": r["decided_at"]}
        return out

    async def confirm_check(self, tenant: str, case_id: str, *, code: str, shown: str,
                            actor: str, note: str | None = None, withdraw: bool = False) -> int | None:
        """Record that a person answered a check the engine could not settle.

        `shown` is what they were looking at — the engine refuses a confirmation
        whose `shown` no longer matches the document, so a re-extraction asks
        again instead of coasting on an answer given about other words.
        """
        async with self.pool.acquire() as c:
            return await self.record_decision(
                c, tenant, line_uid=None, case_id=case_id, kind=code, actor=actor,
                payload={"shown": shown, "note": note, "withdrawn": withdraw})

    async def _replay_evidence_decisions(self, c, tenant: str, seg_id: str) -> int:
        """Re-apply reviewer corrections onto freshly extracted rows (plan §6.3 step 3).

        The rows were deleted and re-inserted, so their `verdict`, `corrected_by`
        and `value_history` are gone — but the decisions that produced them are
        not, and they are keyed on `line_uid`, which survived. Only trusted keys
        replay unattended; an untrusted key keeps `needs_review` so a person
        re-confirms rather than having a decision silently moved onto it.
        """
        rows = await c.fetch(
            """SELECT id, line_uid, key_confidence, row_type, audit_qty, verdict, remark
                 FROM recon_evidence_rows
                WHERE segment_id = $1::uuid AND line_uid IS NOT NULL""", seg_id)
        if not rows:
            return 0
        live = await self.live_decisions(c, tenant, [str(r["line_uid"]) for r in rows])
        applied = 0
        for r in rows:
            d = live.get((str(r["line_uid"]), "QTY_CORRECTED"))
            if not d:
                continue
            if float(r["key_confidence"] or 0) < keys.TRUST_FLOOR:
                # A decision exists, but this row's identity is positional, so
                # moving it here could put it on the wrong line (plan §6.1). Ask
                # a person instead of guessing — and never drop the decision.
                await c.execute(
                    "UPDATE recon_evidence_rows SET needs_review = true WHERE id = $1::uuid", r["id"])
                await c.execute(
                    """INSERT INTO recon_events (tenant_id, doc_id, kind, payload, actor)
                       SELECT $1::uuid, s.doc_id, 'DECISION_RECONFIRM', $2::jsonb, 'system'
                         FROM recon_doc_segments s WHERE s.id = $3::uuid""",
                    tenant, json.dumps({"row_id": str(r["id"]), "line_uid": str(r["line_uid"]),
                                        "key_confidence": float(r["key_confidence"] or 0),
                                        "decided_by": d["actor"], "reason": "untrusted_line_key"},
                                       default=str), seg_id)
                continue
            p = d["payload"] or {}
            patch = {k: p[k] for k in ("audit_qty", "vendor_qty", "verdict", "remark") if k in p}
            if not patch:
                continue
            await c.execute(
                """UPDATE recon_evidence_rows
                      SET audit_qty = COALESCE($2::numeric, audit_qty),
                          vendor_qty = COALESCE($3::numeric, vendor_qty),
                          verdict = COALESCE($4, verdict),
                          remark = COALESCE($5, remark),
                          needs_review = false, confidence = 1.0,
                          corrected_by = $6, corrected_at = $7,
                          value_history = COALESCE(value_history, '[]'::jsonb) || $8::jsonb,
                          auto_verdict = $9
                    WHERE id = $1::uuid""",
                r["id"], patch.get("audit_qty"), patch.get("vendor_qty"), patch.get("verdict"),
                patch.get("remark"), d["actor"], d["decided_at"],
                json.dumps([{"field": "replay", "kind": "DECISION_REPLAYED", "by": d["actor"],
                             "at": (d["decided_at"] or datetime.now(timezone.utc)).isoformat()}], default=str),
                vocab.auto_verdict(r["row_type"], patch.get("verdict", r["verdict"]),
                                   patch.get("remark", r["remark"]),
                                   patch.get("audit_qty", r["audit_qty"])))
            applied += 1
        return applied

    async def _resolve_line_uid(self, c, tenant: str, doc_id: str | None, leg: str, k) -> str | None:
        """Natural key → durable line_uid for this document (keys.py §6.1).

        Same document + same printed line ⇒ same line_uid on every extraction,
        which is what lets a decision survive a re-read. Returns None when the
        segment has no document (nothing to anchor identity to).
        """
        if not doc_id:
            return None
        return await c.fetchval(
            """INSERT INTO recon_line_identity (tenant_id, doc_id, leg, natural_key, key_basis, key_confidence)
                    VALUES ($1::uuid, $2::uuid, $3, $4, $5, $6)
               ON CONFLICT (tenant_id, doc_id, leg, natural_key) DO UPDATE
                    SET last_seen_at = now(),
                        key_basis      = EXCLUDED.key_basis,
                        key_confidence = EXCLUDED.key_confidence
               RETURNING line_uid""",
            tenant, doc_id, leg, k.key, k.basis, k.confidence)

    async def _save_invoice_lines(self, c, tenant: str, seg_id: str, lines: list[InvoiceLine]) -> None:
        await c.execute("DELETE FROM recon_invoice_lines WHERE segment_id = $1::uuid", seg_id)
        doc_id = await self._doc_of_segment(c, seg_id)
        line_keys = keys.disambiguate([keys.for_invoice_line(l, ordinal=i) for i, l in enumerate(lines)])
        for i, l in enumerate(lines):
            k = line_keys[i]
            line_uid = await self._resolve_line_uid(c, tenant, doc_id, "billing", k)
            new_id = await c.fetchval(
                """INSERT INTO recon_invoice_lines (segment_id, tenant_id, sno, description, norm, hsn, unit, qty,
                          rate, amount, tax_rate, confidence, page, bbox, is_charge, charge_pct,
                          natural_key, key_basis, key_confidence, line_uid)
                   VALUES ($1::uuid, $2::uuid, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14::jsonb, $15, $16,
                           $17, $18, $19, $20::uuid)
                   RETURNING id""",
                seg_id, tenant, l.sno, l.description, norm(l.description), fit(l.hsn, 12), fit(l.unit, 16),
                l.qty.value if l.qty else None, l.rate.value if l.rate else None,
                l.amount.value if l.amount else None, l.tax_rate,
                min((s.confidence for s in (l.qty, l.rate, l.amount) if s), default=1.0),
                next((s.page for s in (l.qty, l.amount) if s and s.page is not None), None),
                json.dumps(l.qty.bbox) if l.qty and l.qty.bbox else None, l.is_charge, l.charge_pct,
                k.key, k.basis, k.confidence, line_uid)
            l.key = f"rl:{new_id}"

    async def invoice_lines(self, seg_id: str) -> list[InvoiceLine]:
        async with self.pool.acquire() as c:
            rows = await c.fetch("SELECT * FROM recon_invoice_lines WHERE segment_id = $1::uuid "
                                 "ORDER BY sno NULLS LAST, id", seg_id)
        return [InvoiceLine(
            key=f"rl:{r['id']}", sno=r["sno"], description=r["description"], hsn=r["hsn"], unit=r["unit"],
            qty=Sourced(value=r["qty"], confidence=float(r["confidence"] or 1), page=r["page"],
                        bbox=_p(r["bbox"])) if r["qty"] is not None else None,
            rate=Sourced(value=r["rate"]) if r["rate"] is not None else None,
            amount=Sourced(value=r["amount"]) if r["amount"] is not None else None,
            tax_rate=r["tax_rate"], is_charge=r["is_charge"], charge_pct=r["charge_pct"]) for r in rows]

    async def _save_evidence_rows(self, c, tenant: str, seg_id: str, rows: list[EvidenceRow]) -> None:
        await c.execute("DELETE FROM recon_evidence_rows WHERE segment_id = $1::uuid", seg_id)
        doc_id = await self._doc_of_segment(c, seg_id)
        row_keys = keys.disambiguate([keys.for_evidence_row(r, ordinal=i) for i, r in enumerate(rows)])
        for i, r in enumerate(rows):
            a = r.audit_qty
            k = row_keys[i]
            line_uid = await self._resolve_line_uid(c, tenant, doc_id, "receipt", k)
            new_id = await c.fetchval(
                """INSERT INTO recon_evidence_rows (segment_id, tenant_id, sno, asset_code, item, norm, unit, po_qty,
                          vendor_qty, audit_qty, audit_qty_raw, audit_alternatives, remark, verdict, mounted, unmounted,
                          damaged, rate, rate_after_discount, amount, row_type, confidence, needs_review, page, bbox,
                          value_history, auto_verdict, natural_key, key_basis, key_confidence, line_uid)
                   VALUES ($1::uuid, $2::uuid, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12::jsonb, $13, $14, $15, $16,
                           $17, $18, $19, $31, $20, $21, $22, $23, $24::jsonb, $25::jsonb, $26, $27, $28, $29, $30::uuid)
                   RETURNING id""",
                seg_id, tenant, r.sno, fit(r.asset_code, 80), r.item, norm(r.item), fit(r.unit, 16), r.po_qty,
                r.vendor_qty.value if r.vendor_qty else None, a.value if a else None, fit(r.audit_qty_raw, 40),
                json.dumps(a.alternatives) if a and a.alternatives else None, r.remark,
                r.verdict.value if r.verdict else None, r.mounted, r.unmounted, r.damaged, r.rate,
                r.rate_after_discount, fit(r.row_type, 12) or "po", a.confidence if a else None, r.needs_review,
                a.page if a else None, json.dumps(a.bbox) if a and a.bbox else None,
                json.dumps(hist) if (hist := [dict(h, field="audit_qty") for h in vocab.value_history_from_raw(r.audit_qty_raw)])
                else None, _CLASSIFY.classify(r).value,
                k.key, k.basis, k.confidence, line_uid, r.amount)
            r.key = f"ev:{new_id}"
        # Rows were just rebuilt; put the reviewers' decisions back on them.
        await self._replay_evidence_decisions(c, tenant, seg_id)

    async def evidence_rows(self, seg_id: str) -> list[EvidenceRow]:
        from .types import AuditVerdict
        async with self.pool.acquire() as c:
            rows = await c.fetch("SELECT * FROM recon_evidence_rows WHERE segment_id = $1::uuid "
                                 "ORDER BY sno NULLS LAST, id", seg_id)
        out = []
        for r in rows:
            audit = None
            if r["audit_qty"] is not None or r["confidence"] is not None:
                audit = Sourced(value=r["audit_qty"], confidence=float(r["confidence"] or 1.0), page=r["page"],
                                bbox=_p(r["bbox"]), raw=r["audit_qty_raw"],
                                alternatives=_p(r["audit_alternatives"]) or [])
                if r["audit_qty"] is None:
                    audit = None
            out.append(EvidenceRow(
                key=f"ev:{r['id']}", sno=r["sno"], asset_code=r["asset_code"], item=r["item"], unit=r["unit"],
                po_qty=r["po_qty"], vendor_qty=Sourced(value=r["vendor_qty"]) if r["vendor_qty"] is not None else None,
                audit_qty=audit, audit_qty_raw=r["audit_qty_raw"], remark=r["remark"],
                verdict=AuditVerdict(r["verdict"]) if r["verdict"] else None, mounted=r["mounted"],
                unmounted=r["unmounted"], damaged=r["damaged"], rate=r["rate"],
                rate_after_discount=r["rate_after_discount"], amount=r.get("amount"),
                row_type=r["row_type"],
                needs_review=r["needs_review"] and not r["corrected_by"]))
        return out

    async def correct_evidence(self, tenant: str, row_id: str, patch: dict, actor: str) -> str | None:
        """Apply a human correction; keep the machine reading in original_json. Returns segment id."""
        async with self.pool.acquire() as c:
            async with c.transaction():
                r = await c.fetchrow("SELECT * FROM recon_evidence_rows WHERE id = $1::uuid AND tenant_id = $2::uuid "
                                     "FOR UPDATE", row_id, tenant)
                if not r:
                    return None
                original = _p(r["original_json"]) or {k: (str(r[k]) if isinstance(r[k], Decimal) else r[k])
                                                       for k in ("audit_qty", "vendor_qty", "verdict", "remark")}
                # value_history (vocabulary value_change_kind): what the reviewer changed, from what, to what.
                hist = _p(r.get("value_history")) or []
                for k in ("audit_qty", "vendor_qty", "verdict"):
                    if k in patch and str(patch.get(k)) != str(r[k]):
                        was = r[k]
                        hist.append({"field": k, "was": str(was) if isinstance(was, Decimal) else was,
                                     "now": str(patch[k]) if isinstance(patch.get(k), Decimal) else patch.get(k),
                                     "kind": "REVIEWER_CORRECTION", "by": actor,
                                     "at": datetime.now(timezone.utc).isoformat()})
                await c.execute(
                    """UPDATE recon_evidence_rows
                          SET audit_qty = CASE WHEN $3 THEN $4::numeric ELSE audit_qty END,
                              vendor_qty = CASE WHEN $5 THEN $6::numeric ELSE vendor_qty END,
                              verdict = CASE WHEN $7 THEN $8 ELSE verdict END,
                              remark = CASE WHEN $9 THEN $10 ELSE remark END,
                              needs_review = false, confidence = 1.0, corrected_by = $11, corrected_at = now(),
                              original_json = $12::jsonb, value_history = $13::jsonb, auto_verdict = $14
                        WHERE id = $1::uuid AND tenant_id = $2::uuid""",
                    row_id, tenant, "audit_qty" in patch, patch.get("audit_qty"), "vendor_qty" in patch,
                    patch.get("vendor_qty"), "verdict" in patch, patch.get("verdict"), "remark" in patch,
                    patch.get("remark"), actor, json.dumps(original), json.dumps(hist, default=str) if hist else None,
                    vocab.auto_verdict(r["row_type"], patch["verdict"] if "verdict" in patch else r["verdict"],
                                       patch["remark"] if "remark" in patch else r["remark"],
                                       patch["audit_qty"] if "audit_qty" in patch else r["audit_qty"]))
                # The correction is also a decision, so a later re-extraction can
                # put it back (plan §6.2). The row is the current view; the log is
                # the durable record.
                await self.record_decision(
                    c, tenant, line_uid=str(r["line_uid"]) if r["line_uid"] else None,
                    kind="QTY_CORRECTED", actor=actor,
                    payload={k: patch[k] for k in ("audit_qty", "vendor_qty", "verdict", "remark") if k in patch}
                            | {"was": original})
                return str(r["segment_id"])

    # ── bills (existing tables) ────────────────────────────────────────────────
    async def supplier_bills(self, tenant: str, supplier: str, lookback_days: int = 365) -> list[dict]:
        async with self.pool.acquire() as c:
            rows = await c.fetch(
                """SELECT fi.invoice_id, fi.invoice_number, fi.invoice_date, fi.total_amount, fi.upload_id,
                          fi.brand_id, sb.taxable_amount, sb.gstin_seller, sb.stg_bill_id
                     FROM fact_invoices fi
                     LEFT JOIN stg_bills sb ON sb.stg_bill_id = COALESCE(fi.stg_bill_id, fi.archived_stg_bill_id)
                    WHERE fi.tenant_id = $1::uuid AND fi.supplier_id = $2::uuid
                      AND COALESCE(fi.soft_status, 'active') = 'active'
                      AND (fi.invoice_date IS NULL OR fi.invoice_date >= $3)""",
                tenant, supplier, date.today() - timedelta(days=lookback_days))
        return [dict(r) for r in rows]

    async def bill(self, tenant: str, bill_id: str) -> dict | None:
        async with self.pool.acquire() as c:
            r = await c.fetchrow(
                """SELECT fi.invoice_id, fi.invoice_number, fi.invoice_date, fi.total_amount, fi.upload_id,
                          fi.supplier_id, fi.brand_id, sb.taxable_amount, sb.gstin_seller, sb.stg_bill_id,
                          sb.cgst_amount, sb.sgst_amount, sb.igst_amount, sb.cgst_rate, sb.sgst_rate, sb.igst_rate,
                          sb.place_of_supply, sb.subtotal
                     FROM fact_invoices fi
                     LEFT JOIN stg_bills sb ON sb.stg_bill_id = COALESCE(fi.stg_bill_id, fi.archived_stg_bill_id)
                    WHERE fi.tenant_id = $1::uuid AND fi.invoice_id = $2::uuid""", tenant, bill_id)
        return dict(r) if r else None

    async def bill_lines(self, tenant: str, stg_bill_id) -> list[InvoiceLine]:
        if not stg_bill_id:
            return []
        async with self.pool.acquire() as c:
            rows = await c.fetch(
                """SELECT line_number, product_name, hsn_code, quantity, unit, unit_price, line_total, tax_rate_percent
                     FROM stg_bill_line_items WHERE stg_bill_id = $1 AND tenant_id = $2::uuid
                    ORDER BY line_number""", stg_bill_id, tenant)
        return [InvoiceLine(
            key=f"bill:{stg_bill_id}:{r['line_number']}", sno=r["line_number"], description=r["product_name"] or "",
            hsn=r["hsn_code"], unit=r["unit"],
            qty=Sourced(value=r["quantity"]) if r["quantity"] is not None else None,
            rate=Sourced(value=r["unit_price"]) if r["unit_price"] is not None else None,
            amount=Sourced(value=r["line_total"]) if r["line_total"] is not None else None,
            tax_rate=r["tax_rate_percent"]) for r in rows]

    # ── cases ──────────────────────────────────────────────────────────────────
    async def ensure_case(self, tenant: str, supplier: str, *, brand: str | None = None, bill_id: str | None = None,
                          invoice_no: str | None = None, po_id: str | None = None, store_sn: str | None = None,
                          invoice_segment_id: str | None = None) -> str:
        async with self.pool.acquire() as c:
            if bill_id:
                existing = await c.fetchval("SELECT id FROM recon_cases WHERE tenant_id = $1::uuid AND bill_id = $2::uuid",
                                            tenant, bill_id)
                if existing:
                    await c.execute(
                        """UPDATE recon_cases SET po_id = COALESCE($2::uuid, po_id), store_sn = COALESCE($3, store_sn),
                                  invoice_segment_id = COALESCE($4::uuid, invoice_segment_id),
                                  invoice_no = COALESCE(invoice_no, $5)
                            WHERE id = $1""", existing, po_id, store_sn, invoice_segment_id, invoice_no)
                    return str(existing)
            elif invoice_segment_id:
                existing = await c.fetchval(
                    "SELECT id FROM recon_cases WHERE tenant_id = $1::uuid AND invoice_segment_id = $2::uuid",
                    tenant, invoice_segment_id)
                if existing:
                    return str(existing)
            # Next case number for this tenant; the lock keeps two new cases from taking the same one.
            async with c.transaction():
                await c.execute("SELECT pg_advisory_xact_lock(hashtext('recon_case_ref:' || $1))", tenant)
                return str(await c.fetchval(
                    """INSERT INTO recon_cases (tenant_id, supplier_id, brand_id, bill_id, invoice_no, po_id, store_sn,
                              invoice_segment_id, status, ref_no)
                       VALUES ($1::uuid, $2::uuid, $3::uuid, $4::uuid, $5, $6::uuid, $7, $8::uuid, 'IN_PROGRESS',
                               (SELECT COALESCE(MAX(ref_no), 0) + 1 FROM recon_cases WHERE tenant_id = $1::uuid))
                       RETURNING id""", tenant, supplier, brand, bill_id, invoice_no, po_id, store_sn, invoice_segment_id))

    async def set_case(self, case_id: str, **fields) -> None:
        allowed = {"bill_id", "po_id", "store_sn", "invoice_no", "invoice_segment_id", "status"}
        sets, args = [], [case_id]
        for k, v in fields.items():
            if k not in allowed:
                raise ValueError(k)
            args.append(v)
            cast = "::uuid" if k.endswith("_id") else ""
            sets.append(f"{k} = ${len(args)}{cast}")
        if sets:
            async with self.pool.acquire() as c:
                await c.execute(f"UPDATE recon_cases SET {', '.join(sets)} WHERE id = $1::uuid", *args)

    async def case_row(self, tenant: str, case_id: str) -> dict | None:
        async with self.pool.acquire() as c:
            r = await c.fetchrow("""SELECT rc.*, po.po_number || '-' || po.revision AS po_number,
                                           COALESCE(fi.soft_status = 'deleted', false) AS bill_deleted
                                      FROM recon_cases rc
                                      LEFT JOIN purchase_orders po ON po.id = rc.po_id
                                      LEFT JOIN fact_invoices fi ON fi.invoice_id = rc.bill_id
                                     WHERE rc.id = $1::uuid AND rc.tenant_id = $2::uuid""", case_id, tenant)
        if not r:
            return None
        d = dict(r)
        d["summary_json"] = _p(d.get("summary_json"))
        d["counts"] = _p(d.get("counts"))
        return d

    async def cases_for_supplier(self, tenant: str, supplier: str) -> list[dict]:
        async with self.pool.acquire() as c:
            rows = await c.fetch(
                """SELECT rc.*, po.po_number || '-' || po.revision AS po_number,
                          -- Whether the bill behind this case has been deleted.
                          -- Hiding such a case takes its DOCUMENTS off the screen
                          -- too — they stay linked to a case nothing resolves, so
                          -- their rows show no check and the vendor looks
                          -- unreconciled. Said out loud instead.
                          COALESCE(fi.soft_status = 'deleted', false) AS bill_deleted,
                          (SELECT json_agg(json_build_object('role', cs.role, 'kind', s.kind))
                             FROM recon_case_segments cs JOIN recon_doc_segments s ON s.id = cs.segment_id
                            WHERE cs.case_id = rc.id) AS docs
                     FROM recon_cases rc
                     LEFT JOIN purchase_orders po ON po.id = rc.po_id
                     LEFT JOIN fact_invoices fi ON fi.invoice_id = rc.bill_id
                    WHERE rc.tenant_id = $1::uuid AND rc.supplier_id = $2::uuid
                    ORDER BY rc.created_at DESC""", tenant, supplier)
        out = []
        for r in rows:
            d = dict(r)
            for k in ("summary_json", "counts", "docs"):
                d[k] = _p(d.get(k))
            out.append(d)
        return out

    async def case_for_bill(self, tenant: str, bill_id: str) -> str | None:
        async with self.pool.acquire() as c:
            v = await c.fetchval("SELECT id FROM recon_cases WHERE tenant_id = $1::uuid AND bill_id = $2::uuid",
                                 tenant, bill_id)
        return str(v) if v else None

    async def cases_for_po(self, tenant: str, po_id: str) -> list[dict]:
        async with self.pool.acquire() as c:
            rows = await c.fetch("SELECT id, bill_id, status FROM recon_cases WHERE tenant_id = $1::uuid AND po_id = $2::uuid",
                                 tenant, po_id)
        return [dict(r) for r in rows]

    async def attach(self, tenant: str, case_id: str, seg_id: str, role: str, method: str,
                     score: float | None = None, by: str | None = None) -> None:
        async with self.pool.acquire() as c:
            async with c.transaction():
                await c.execute(
                    """INSERT INTO recon_case_segments (case_id, segment_id, tenant_id, role, link_method, link_score, linked_by)
                       VALUES ($1::uuid, $2::uuid, $3::uuid, $4, $5, $6, $7)
                       ON CONFLICT (case_id, segment_id) DO UPDATE SET role = EXCLUDED.role,
                              link_method = EXCLUDED.link_method, link_score = EXCLUDED.link_score,
                              linked_by = EXCLUDED.linked_by, linked_at = now()""",
                    case_id, seg_id, tenant, role, method, score, by)
                await c.execute("UPDATE recon_doc_segments SET status = 'LINKED' WHERE id = $1::uuid", seg_id)

    async def detach(self, tenant: str, case_id: str, seg_id: str) -> None:
        async with self.pool.acquire() as c:
            async with c.transaction():
                await c.execute("DELETE FROM recon_case_segments WHERE case_id = $1::uuid AND segment_id = $2::uuid "
                                "AND tenant_id = $3::uuid", case_id, seg_id, tenant)
                await c.execute("UPDATE recon_doc_segments SET status = 'UNLINKED' WHERE id = $1::uuid "
                                "AND NOT EXISTS (SELECT 1 FROM recon_case_segments WHERE segment_id = $1::uuid)", seg_id)

    async def case_segments(self, case_id: str) -> list[dict]:
        async with self.pool.acquire() as c:
            rows = await c.fetch(
                """SELECT s.*, cs.role, cs.link_method, cs.link_score, cs.linked_by, d.file_name
                     FROM recon_case_segments cs JOIN recon_doc_segments s ON s.id = cs.segment_id
                     JOIN vendor_documents d ON d.id = s.doc_id AND d.deleted_at IS NULL
                    WHERE cs.case_id = $1::uuid ORDER BY cs.linked_at""", case_id)
        return [self._seg(r) for r in rows]

    async def cases_using_segment(self, seg_id: str) -> list[str]:
        async with self.pool.acquire() as c:
            rows = await c.fetch("SELECT case_id FROM recon_case_segments WHERE segment_id = $1::uuid", seg_id)
        return [str(r["case_id"]) for r in rows]

    async def prior_billing(self, tenant: str, po_id: str, case_id: str) -> tuple[dict[str, Decimal], Decimal]:
        """Billed qty per PO line and taxable value on *other* cases of the same PO (running bills, E-PO-06)."""
        async with self.pool.acquire() as c:
            rows = await c.fetch(
                """SELECT r.po_line_key, SUM((r.result->>'billed_qty')::numeric) AS q
                     FROM recon_line_results r JOIN recon_cases rc ON rc.id = r.case_id
                    WHERE rc.tenant_id = $1::uuid AND rc.po_id = $2::uuid AND rc.id <> $3::uuid
                      AND r.po_line_key IS NOT NULL
                    GROUP BY r.po_line_key""", tenant, po_id, case_id)
            value = await c.fetchval(
                """SELECT COALESCE(SUM((summary_json->>'billed_total')::numeric), 0) FROM recon_cases
                    WHERE tenant_id = $1::uuid AND po_id = $2::uuid AND id <> $3::uuid""", tenant, po_id, case_id)
        return {r["po_line_key"]: r["q"] for r in rows if r["q"] is not None}, Decimal(value or 0)

    async def other_invoice_numbers(self, tenant: str, supplier: str, bill_id: str | None) -> list[str]:
        async with self.pool.acquire() as c:
            rows = await c.fetch(
                """SELECT invoice_number FROM fact_invoices
                    WHERE tenant_id = $1::uuid AND supplier_id = $2::uuid AND invoice_number IS NOT NULL
                      AND ($3::uuid IS NULL OR invoice_id <> $3::uuid)
                      AND COALESCE(soft_status, 'active') = 'active'""", tenant, supplier, bill_id)
        return [r["invoice_number"] for r in rows]

    # ── overrides, aliases ─────────────────────────────────────────────────────
    async def overrides(self, case_id: str, as_of: datetime | None = None) -> dict[str, str | None]:
        """Reviewer-confirmed pairings for this case, as `{other_key: po_line_key}`.

        Two sources, in this order (plan §6.2):

        1. `recon_decisions`, keyed on `line_uid`, translated back to the row's
           *current* surrogate key. This is the durable record and is what makes a
           confirmation survive re-extraction.
        2. `recon_match_overrides`, the legacy case-scoped table, overlaid on top
           so pre-migration confirmations keep working unchanged.

        `as_of` reconstructs the set as it stood at that moment.
        """
        async with self.pool.acquire() as c:
            tenant = await c.fetchval("SELECT tenant_id FROM recon_cases WHERE id = $1::uuid", case_id)
            out: dict[str, str | None] = {}
            if tenant:
                rows = await c.fetch(
                    """WITH r AS (
                            SELECT er.id, er.line_uid, 'ev' AS pfx
                              FROM recon_evidence_rows er
                              JOIN recon_case_segments cs ON cs.segment_id = er.segment_id
                             WHERE cs.case_id = $1::uuid AND er.line_uid IS NOT NULL
                            UNION ALL
                            SELECT il.id, il.line_uid, 'rl'
                              FROM recon_invoice_lines il
                              JOIN recon_case_segments cs ON cs.segment_id = il.segment_id
                             WHERE cs.case_id = $1::uuid AND il.line_uid IS NOT NULL
                       ), live AS (
                            SELECT DISTINCT ON (line_uid) line_uid, kind, payload
                              FROM recon_decisions
                             WHERE tenant_id = $2::uuid
                               AND kind IN ('MATCH_CONFIRMED', 'MATCH_REJECTED')
                               AND line_uid IN (SELECT line_uid FROM r)
                               AND ($3::timestamptz IS NULL OR decided_at <= $3::timestamptz)
                             ORDER BY line_uid, decided_at DESC, decision_id DESC
                       )
                       SELECT r.pfx || ':' || r.id AS other_key, live.kind, live.payload
                         FROM r JOIN live ON live.line_uid = r.line_uid""",
                    case_id, tenant, as_of)
                for r in rows:
                    p = _p(r["payload"]) or {}
                    out[r["other_key"]] = None if r["kind"] == "MATCH_REJECTED" else p.get("po_line_key")
            legacy = await c.fetch(
                "SELECT other_key, po_line_key FROM recon_match_overrides WHERE case_id = $1::uuid", case_id)
        out.update({r["other_key"]: r["po_line_key"] for r in legacy})
        return out

    async def set_override(self, tenant: str, case_id: str, other_key: str, po_key: str | None, by: str) -> None:
        """Record a reviewer's pairing decision.

        Written twice on purpose: the append-only decision (durable, keyed on the
        line's identity) and the legacy table (the current-state cache the matcher
        already reads). The decision is the record; the table is a view of it.
        """
        async with self.pool.acquire() as c:
            async with c.transaction():
                await c.execute(
                    """INSERT INTO recon_match_overrides (case_id, tenant_id, po_line_key, other_key, decided_by)
                       VALUES ($1::uuid, $2::uuid, $3, $4, $5)
                       ON CONFLICT (case_id, other_key) DO UPDATE SET po_line_key = EXCLUDED.po_line_key,
                              decided_by = EXCLUDED.decided_by, decided_at = now()""",
                    case_id, tenant, po_key, other_key, by)
                line_uid = await self._line_uid_of_key(c, tenant, other_key)
                await self.record_decision(
                    c, tenant, line_uid=line_uid, case_id=case_id,
                    kind="MATCH_CONFIRMED" if po_key else "MATCH_REJECTED",
                    payload={"po_line_key": po_key, "other_key": other_key}, actor=by)

    async def backfill_override_decisions(self, tenant: str | None = None) -> dict[str, int]:
        """Copy legacy `recon_match_overrides` rows into the decision log.

        Idempotent: a row that already has a matching decision is skipped, so it
        can be run repeatedly and before/after a deploy. An override whose row no
        longer exists (the evidence or invoice line was deleted by an earlier
        re-extraction) has no `line_uid` to hang on and is reported as
        `unanchored` rather than silently dropped — those are precisely the
        confirmations the old design was losing.

        This must run green before `recon_match_overrides` is retired to a view.
        """
        done = skipped = unanchored = 0
        async with self.pool.acquire() as c:
            rows = await c.fetch(
                """SELECT case_id, tenant_id, po_line_key, other_key, decided_by, decided_at
                     FROM recon_match_overrides
                    WHERE ($1::uuid IS NULL OR tenant_id = $1::uuid)
                    ORDER BY decided_at""", tenant)
            for r in rows:
                t = str(r["tenant_id"])
                line_uid = await self._line_uid_of_key(c, t, r["other_key"])
                if line_uid is None:
                    unanchored += 1
                    continue
                exists = await c.fetchval(
                    """SELECT 1 FROM recon_decisions
                        WHERE tenant_id = $1::uuid AND line_uid = $2::uuid
                          AND kind IN ('MATCH_CONFIRMED', 'MATCH_REJECTED')
                          AND payload ->> 'other_key' = $3 LIMIT 1""",
                    t, line_uid, r["other_key"])
                if exists:
                    skipped += 1
                    continue
                await c.execute(
                    """INSERT INTO recon_decisions (tenant_id, line_uid, case_id, kind, payload,
                                                    actor, actor_kind, decided_at)
                       VALUES ($1::uuid, $2::uuid, $3::uuid, $4, $5::jsonb, $6, 'human', $7)""",
                    t, line_uid, str(r["case_id"]),
                    "MATCH_CONFIRMED" if r["po_line_key"] else "MATCH_REJECTED",
                    json.dumps({"po_line_key": r["po_line_key"], "other_key": r["other_key"],
                                "backfilled_from": "recon_match_overrides"}),
                    r["decided_by"], r["decided_at"])
                done += 1
        return {"migrated": done, "already_present": skipped, "unanchored": unanchored,
                "total": len(rows)}

    async def _line_uid_of_key(self, c, tenant: str, key: str) -> str | None:
        """`ev:<uuid>` / `rl:<uuid>` → the row's durable line_uid, if it has one."""
        pfx, _, row_id = key.partition(":")
        table = {"ev": "recon_evidence_rows", "rl": "recon_invoice_lines"}.get(pfx)
        if not table or not row_id:
            return None
        try:
            return await c.fetchval(
                f"SELECT line_uid FROM {table} WHERE id = $1::uuid AND tenant_id = $2::uuid", row_id, tenant)
        except Exception:
            return None   # a synthetic key (bill:…, tmp:…) has no row of its own

    async def aliases(self, tenant: str, supplier: str) -> dict[str, str]:
        async with self.pool.acquire() as c:
            rows = await c.fetch("SELECT alias_norm, po_item_norm FROM vendor_item_aliases "
                                 "WHERE tenant_id = $1::uuid AND supplier_id = $2::uuid", tenant, supplier)
        return {r["alias_norm"]: r["po_item_norm"] for r in rows}

    async def save_alias(self, tenant: str, supplier: str, alias_text: str, po_text: str | None, by: str) -> None:
        a = norm(alias_text)
        async with self.pool.acquire() as c:
            if po_text is None:
                await c.execute("DELETE FROM vendor_item_aliases WHERE tenant_id = $1::uuid AND supplier_id = $2::uuid "
                                "AND alias_norm = $3", tenant, supplier, a)
                return
            p = norm(po_text)
            if a == p:
                return
            await c.execute(
                """INSERT INTO vendor_item_aliases (tenant_id, supplier_id, alias_norm, po_item_norm, confirmed_by)
                   VALUES ($1::uuid, $2::uuid, $3, $4, $5)
                   ON CONFLICT (tenant_id, supplier_id, alias_norm) DO UPDATE SET po_item_norm = EXCLUDED.po_item_norm,
                          confirmed_by = EXCLUDED.confirmed_by, created_at = now()""", tenant, supplier, a, p, by)

    # ── the match surface, as a projection (plan §3) ──────────────────────────
    async def edge_shape(self, tenant: str, case_id: str) -> dict:
        """The case's graph, aggregated for drawing.

        Not the edges themselves: thirty-eight invoice lines against
        thirty-eight PO lines is a hairball nobody reads. What answers "how is
        this reconciliation held together" is **how many** lines each leg
        carries and how strong those links are — so this returns one row per
        edge kind with its count, its weakest and average score, and how many
        a person confirmed.

        The weakest link is reported because an average hides it, and one bad
        pairing on a large line is the thing worth looking at.
        """
        async with self.pool.acquire() as c:
            rows = await c.fetch(
                """SELECT kind, count(*) AS n,
                          round(avg(score), 3) AS avg_score,
                          round(min(score), 3) AS min_score,
                          count(*) FILTER (WHERE confirmed) AS confirmed,
                          count(*) FILTER (WHERE method = 'EXACT' OR method = 'HUMAN') AS certain
                     FROM recon_edges
                    WHERE tenant_id = $1::uuid AND case_id = $2::uuid
                    GROUP BY kind ORDER BY kind""",
                tenant, case_id)
            built = await c.fetchval(
                "SELECT max(built_at) FROM recon_edges WHERE case_id = $1::uuid", case_id)
        return {
            "built_at": built,
            "links": [{"kind": r["kind"], "n": r["n"],
                       "avg_score": float(r["avg_score"]) if r["avg_score"] is not None else None,
                       "min_score": float(r["min_score"]) if r["min_score"] is not None else None,
                       "confirmed": r["confirmed"], "certain": r["certain"]} for r in rows],
        }

    async def rebuild_edges(self, tenant: str, case_id: str) -> int:
        """Wipe and re-derive this case's edges. Returns the edge count.

        Safe to run at any time: edges hold no authored state, so losing them
        loses nothing. Reviewer confirmations are read from `recon_decisions`
        and stamped onto the rebuilt edges — never the other way round.
        """
        from . import edges as E
        async with self.pool.acquire() as c:
            rows = await c.fetch(
                """SELECT result FROM recon_line_results
                    WHERE case_id = $1::uuid AND tenant_id = $2::uuid ORDER BY ord""", case_id, tenant)
            line_results = [from_json(LineResult, _p(r["result"])) for r in rows]
            confirmed = {k for k, v in (await self.overrides(case_id)).items() if v is not None}
            async with c.transaction():
                await c.execute("DELETE FROM recon_edges WHERE case_id = $1::uuid", case_id)
                built = E.derive(line_results, confirmed_keys=confirmed)
                if built:
                    await c.executemany(
                        """INSERT INTO recon_edges (tenant_id, case_id, kind, src_key, dst_key,
                                  method, score, confirmed)
                           VALUES ($1::uuid, $2::uuid, $3, $4, $5, $6, $7, $8)
                           ON CONFLICT (case_id, kind, src_key, dst_key) DO NOTHING""",
                        [(tenant, case_id, e.kind, e.src_key, e.dst_key, e.method, e.score, e.confirmed)
                         for e in built])
                    # Resolve the durable line identity in one pass. Kept out of
                    # the insert because the same parameter cannot be both the
                    # varchar column and the text it is matched against.
                    await c.execute(
                        """UPDATE recon_edges e SET src_line_uid = r.line_uid
                             FROM (SELECT 'ev:' || id::text AS k, line_uid FROM recon_evidence_rows
                                    WHERE line_uid IS NOT NULL
                                   UNION ALL
                                   SELECT 'rl:' || id::text, line_uid FROM recon_invoice_lines
                                    WHERE line_uid IS NOT NULL) r
                            WHERE e.case_id = $1::uuid AND e.src_key = r.k""", case_id)
                await c.execute(
                    """INSERT INTO recon_events (tenant_id, case_id, kind, payload, actor)
                       VALUES ($1::uuid, $2::uuid, 'EDGES_REBUILT', $3::jsonb, 'system')""",
                    tenant, case_id, json.dumps({"edges": len(built)}))
        return len(built)

    async def evidence_path(self, tenant: str, case_id: str, start_key: str,
                            max_depth: int = 4) -> list[dict]:
        """Everything reachable from one line, with the path that reaches it.

        Plan §3.1, option 1: a recursive CTE over `recon_edges`, not a graph
        database. Apache AGE is not available on this RDS instance, and the
        traversals the rules need are 1–2 hops.

        **The walk is undirected**, which is the whole point. Edges point at the
        PO line from both sides — an invoice line BILLS_AGAINST it, an audit row
        CERTIFIES it — so reaching the audit evidence for a bill means arriving
        at the PO line and leaving again against the arrow.

        `path` guards against cycles and is itself the answer: a verdict rests on
        a path, so the path is what gets cited as evidence.
        """
        async with self.pool.acquire() as c:
            rows = await c.fetch(
                """WITH RECURSIVE walk(node, path, kinds, depth) AS (
                       SELECT $3::text, ARRAY[$3::text], ARRAY[]::text[], 0
                       UNION ALL
                       SELECT nxt.node, walk.path || nxt.node, walk.kinds || nxt.kind, walk.depth + 1
                         FROM walk
                         JOIN LATERAL (
                              SELECT e.dst_key AS node, e.kind FROM recon_edges e
                               WHERE e.tenant_id = $1::uuid AND e.case_id = $2::uuid
                                 AND e.src_key = walk.node
                              UNION ALL
                              SELECT e.src_key, e.kind FROM recon_edges e
                               WHERE e.tenant_id = $1::uuid AND e.case_id = $2::uuid
                                 AND e.dst_key = walk.node
                         ) nxt ON true
                        WHERE walk.depth < $4 AND NOT (nxt.node = ANY(walk.path))
                   )
                   SELECT DISTINCT ON (node) node, path, kinds, depth
                     FROM walk WHERE depth > 0
                    ORDER BY node, depth""",
                tenant, case_id, start_key, max_depth)
        return [{"node": r["node"], "path": list(r["path"]), "via": list(r["kinds"]),
                 "hops": r["depth"]} for r in rows]

    async def po_line_position(self, tenant: str, case_id: str, po_line_key: str) -> list[str]:
        """Which invoice lines bill against one PO line (R6: one PO, many invoices)."""
        async with self.pool.acquire() as c:
            rows = await c.fetch(
                """SELECT src_key FROM recon_edges
                    WHERE tenant_id = $1::uuid AND case_id = $2::uuid
                      AND kind = 'BILLS_AGAINST' AND dst_key = $3
                    ORDER BY src_key""", tenant, case_id, po_line_key)
        return [r["src_key"] for r in rows]

    async def edges(self, tenant: str, case_id: str) -> list[dict]:
        async with self.pool.acquire() as c:
            rows = await c.fetch(
                """SELECT kind, src_key, dst_key, method, score, confirmed FROM recon_edges
                    WHERE case_id = $1::uuid AND tenant_id = $2::uuid
                    ORDER BY kind, src_key, dst_key""", case_id, tenant)
        return [dict(r) for r in rows]

    # ── GRN, the receipt leg (plan §7) ────────────────────────────────────────
    async def save_grn_lines(self, tenant: str, lines, source_file: str | None = None) -> int:
        """Insert GRN lines from an MSD extract. Re-loading the same file is a no-op.

        `ON CONFLICT DO UPDATE` rather than `DO NOTHING`: a corrected re-export
        of the same GRN should replace the figures, not be ignored. The unique
        index is what makes a repeat load idempotent instead of doubling the
        received quantity.
        """
        if not lines:
            return 0
        async with self.pool.acquire() as c:
            await c.executemany(
                """INSERT INTO recon_grn_lines (tenant_id, grn_number, grn_date, po_number, po_line_no,
                          item_code, description, norm, unit, qty_received, rate, amount, msd_voucher,
                          source_file)
                   VALUES ($1::uuid, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14)
                   ON CONFLICT (tenant_id, grn_number, po_number,
                                COALESCE(po_line_no,''), COALESCE(item_code,''))
                   DO UPDATE SET qty_received = EXCLUDED.qty_received, rate = EXCLUDED.rate,
                                 amount = EXCLUDED.amount, description = EXCLUDED.description,
                                 unit = EXCLUDED.unit, grn_date = EXCLUDED.grn_date,
                                 ingested_at = now()""",
                [(tenant, l.grn_number, l.grn_date, l.po_number, l.po_line_no, l.item_code,
                  l.description, norm(l.description or ""), l.unit, l.qty_received, l.rate,
                  l.amount, l.msd_voucher, source_file) for l in lines])
        return len(lines)

    async def grn_lines(self, tenant: str, po_number: str) -> list:
        """GRN lines for a PO, as grn.GrnLine, for the agreement check (R3/R8)."""
        from .grn import GrnLine
        async with self.pool.acquire() as c:
            rows = await c.fetch(
                """SELECT grn_number, grn_date, po_number, po_line_no, item_code, description,
                          unit, qty_received, rate, amount, msd_voucher
                     FROM recon_grn_lines
                    WHERE tenant_id = $1::uuid AND po_number = $2
                    ORDER BY po_line_no NULLS LAST, item_code NULLS LAST""", tenant, po_number)
        return [GrnLine(po_number=r["po_number"], qty_received=r["qty_received"],
                        grn_number=r["grn_number"], grn_date=r["grn_date"],
                        po_line_no=r["po_line_no"], item_code=r["item_code"],
                        description=r["description"], unit=r["unit"], rate=r["rate"],
                        amount=r["amount"], msd_voucher=r["msd_voucher"]) for r in rows]

    async def grn_receipt_total(self, tenant: str, po_number: str) -> Decimal | None:
        """Value received against a PO, for the ±₹100 check (R7).

        None when no GRN line carries a value — the check must abstain, never
        compare an invoice against zero.
        """
        async with self.pool.acquire() as c:
            return await c.fetchval(
                """SELECT sum(COALESCE(amount, qty_received * rate))
                     FROM recon_grn_lines
                    WHERE tenant_id = $1::uuid AND po_number = $2
                      AND (amount IS NOT NULL OR rate IS NOT NULL)""",
                tenant, po_number)

    async def recon_settings(self, tenant: str) -> dict:
        """Everything configured for this tenant's recon service."""
        async with self.pool.acquire() as c:
            raw = await c.fetchval(
                """SELECT config FROM tenant_service
                    WHERE tenant_id = $1::uuid AND service_key = 'recon'""", tenant)
        return _p(raw) or {}

    async def set_recon_setting(self, tenant: str, key: str, value, actor: str = "system") -> dict:
        """Merge one key into the tenant's recon config. Returns the new config.

        Two things this does that a hand-written UPDATE does not:

        * it never changes `enabled`. A `tenant_service` row's absence means
          "inherit `service_catalog.default_enabled`", and `recon` defaults to
          *false* — so an INSERT that forgot `enabled` would silently switch
          recon off for that tenant. The insert path copies the effective value.
        * it records the change in `recon_events`, because a settings change can
          move money (a tolerance, a rule profile) and should be as auditable as
          a reviewer's decision.

        `value=None` removes the key, so a bad mapping can be withdrawn without
        hand-editing JSON.
        """
        async with self.pool.acquire() as c:
            async with c.transaction():
                before = _p(await c.fetchval(
                    "SELECT config FROM tenant_service WHERE tenant_id = $1::uuid AND service_key = 'recon'",
                    tenant)) or {}
                exists = await c.fetchval(
                    "SELECT 1 FROM tenant_service WHERE tenant_id = $1::uuid AND service_key = 'recon'", tenant)
                after = {k: v for k, v in before.items() if k != key}
                if value is not None:
                    after[key] = value
                if exists:
                    await c.execute(
                        """UPDATE tenant_service SET config = $2::jsonb, updated_by = NULL, updated_at = now()
                            WHERE tenant_id = $1::uuid AND service_key = 'recon'""",
                        tenant, json.dumps(after))
                else:
                    await c.execute(
                        """INSERT INTO tenant_service (tenant_id, service_key, enabled, config, enabled_at)
                           VALUES ($1::uuid, 'recon',
                                   COALESCE((SELECT default_enabled FROM service_catalog
                                              WHERE service_key = 'recon'), false),
                                   $2::jsonb, now())""",
                        tenant, json.dumps(after))
                await c.execute(
                    """INSERT INTO recon_events (tenant_id, kind, payload, actor)
                       VALUES ($1::uuid, 'settings_changed', $2::jsonb, $3)""",
                    tenant, json.dumps({"key": key, "was": before.get(key), "now": value}, default=str), actor)
        return after

    async def tenant_grn_mapping(self, tenant: str) -> dict[str, str] | None:
        """The tenant's declared GRN column mapping, beside their rule profile.

        `tenant_service.config -> 'grn_column_map'`, e.g.
        `{"po_number": "Purchase Order", "qty_received": "Qty Passed"}`.
        Absent means "infer from the headers", which is the right default for a
        client whose export we have not seen yet.
        """
        async with self.pool.acquire() as c:
            raw = await c.fetchval(
                """SELECT config -> 'grn_column_map' FROM tenant_service
                    WHERE tenant_id = $1::uuid AND service_key = 'recon'""", tenant)
        m = _p(raw)
        return {str(k): str(v) for k, v in m.items()} if isinstance(m, dict) and m else None

    async def tenant_rule_profile(self, tenant: str) -> str | None:
        """The tenant's named rule profile, from their recon service config.

        Lives in `tenant_service.config->>'rule_profile'` rather than a recon
        table of its own: it is a licensing/settings fact, and the Review Hub and
        admin screens already read a tenant's service config. A tenant with no
        setting gets the default profile.
        """
        async with self.pool.acquire() as c:
            return await c.fetchval(
                """SELECT config ->> 'rule_profile' FROM tenant_service
                    WHERE tenant_id = $1::uuid AND service_key = 'recon'""", tenant)

    async def stamp_fingerprint(self, tenant: str, case_id: str, *, rule_version: str = "r1") -> str:
        """Compute the case's input fingerprint and store it. Returns the hash."""
        fp = await self.case_fingerprint(tenant, case_id, rule_version=rule_version)
        async with self.pool.acquire() as c:
            await c.execute(
                """UPDATE recon_cases SET input_fingerprint = $3, rule_version = $4
                    WHERE id = $1::uuid AND tenant_id = $2::uuid""",
                case_id, tenant, fp, rule_version)
        return fp

    async def case_fingerprint(self, tenant: str, case_id: str, *, rule_version: str = "r1",
                               engine_version: str | None = None) -> str:
        """Fingerprint the inputs of one case, decisions included (plan §8)."""
        async with self.pool.acquire() as c:
            segs = await c.fetch(
                """SELECT s.id, s.extractor_version
                     FROM recon_case_segments cs JOIN recon_doc_segments s ON s.id = cs.segment_id
                    WHERE cs.case_id = $1::uuid ORDER BY s.id""", case_id)
            hwm = await c.fetchval(
                """SELECT max(d.decision_id) FROM recon_decisions d
                    WHERE d.tenant_id = $1::uuid
                      AND (d.case_id = $2::uuid
                           OR d.line_uid IN (
                               SELECT er.line_uid FROM recon_evidence_rows er
                                 JOIN recon_case_segments cs ON cs.segment_id = er.segment_id
                                WHERE cs.case_id = $2::uuid AND er.line_uid IS NOT NULL
                               UNION
                               SELECT il.line_uid FROM recon_invoice_lines il
                                 JOIN recon_case_segments cs ON cs.segment_id = il.segment_id
                                WHERE cs.case_id = $2::uuid AND il.line_uid IS NOT NULL))""",
                tenant, case_id)
        return input_fingerprint(
            segment_versions=[(str(s["id"]), s["extractor_version"]) for s in segs],
            engine_version=engine_version or config.ENGINE_VERSION,
            rule_version=rule_version, decision_hwm=hwm, vocab_version=vocab.VOCAB_VERSION)

    # ── results ────────────────────────────────────────────────────────────────
    async def save_result(self, tenant: str, case_id: str, res: ReconResult) -> str:
        """Replace a case's results. Reviewed marks carry over by line key; an
        acknowledgement survives only if what a human would see is unchanged."""
        h = result_hash(res)
        status = res.summary.status.value
        async with self.pool.acquire() as c:
            async with c.transaction():
                # Serialise per case before touching anything. The rest is
                # DELETE-then-INSERT, and at READ COMMITTED two of those
                # interleave: both delete the rows they can see, both insert,
                # and the case ends up with every line twice. Forced on dev and
                # it happened — 98 rows for 49 lines. Locking the case row
                # makes the second recompute wait and then delete what the
                # first actually wrote.
                await c.execute("SELECT 1 FROM recon_cases WHERE id = $1::uuid FOR UPDATE", case_id)
                reviewed = {r["line_key"]: r for r in await c.fetch(
                    "SELECT line_key, reviewed_by, reviewed_at, reviewed_note FROM recon_line_results "
                    "WHERE case_id = $1::uuid AND reviewed_by IS NOT NULL", case_id)}
                ack = await c.fetchrow("SELECT ack_hash, acknowledged_by FROM recon_cases WHERE id = $1::uuid", case_id)
                if ack and ack["acknowledged_by"] and ack["ack_hash"] == h:
                    status = "ACKNOWLEDGED"
                await c.execute("DELETE FROM recon_line_results WHERE case_id = $1::uuid", case_id)
                await c.executemany(
                    """INSERT INTO recon_line_results (case_id, tenant_id, ord, kind, line_key, po_line_key,
                              invoice_line_key, evidence_row_key, result, severity, statuses, reviewed_by,
                              reviewed_at, reviewed_note)
                       VALUES ($1::uuid, $2::uuid, $3, $4, $5, $6, $7, $8, $9::jsonb, $10, $11, $12, $13, $14)""",
                    [(case_id, tenant, l.ord, l.kind, line_key(l), l.po_key, l.invoice_key, l.evidence_key, _j(l),
                      l.severity.value, [s.value for s in l.statuses],
                      *((reviewed[line_key(l)]["reviewed_by"], reviewed[line_key(l)]["reviewed_at"],
                         reviewed[line_key(l)]["reviewed_note"]) if line_key(l) in reviewed else (None, None, None)))
                     for l in res.lines])
                await c.execute("DELETE FROM recon_header_checks WHERE case_id = $1::uuid", case_id)
                await c.executemany(
                    """INSERT INTO recon_header_checks (case_id, tenant_id, code, label, severity, passed, detail, evidence)
                       VALUES ($1::uuid, $2::uuid, $3, $4, $5, $6, $7, $8::jsonb)""",
                    [(case_id, tenant, x.code, x.label, x.severity.value, x.passed, x.detail, _j(x.evidence))
                     for x in res.header])
                s = res.summary
                await c.execute(
                    """UPDATE recon_cases SET summary_json = $2::jsonb, money_at_risk = $3, under_billed = $4,
                              counts = $5::jsonb, status = $6, result_hash = $7, engine_version = $8, computed_at = now()
                        WHERE id = $1::uuid""",
                    case_id, _j(s), s.money_at_risk, s.under_billed, json.dumps(s.counts), status, h, res.engine_version)
        return status

    async def results(self, case_id: str) -> tuple[list[dict], list[dict]]:
        async with self.pool.acquire() as c:
            lines = await c.fetch("SELECT id, result, reviewed_by, reviewed_at, reviewed_note FROM recon_line_results "
                                  "WHERE case_id = $1::uuid ORDER BY ord", case_id)
            header = await c.fetch("SELECT code, label, severity, passed, detail, evidence FROM recon_header_checks "
                                   "WHERE case_id = $1::uuid ORDER BY passed, code", case_id)
        out = []
        for r in lines:
            d = _p(r["result"])
            d["id"] = str(r["id"])
            d["reviewed"] = ({"by": r["reviewed_by"], "at": r["reviewed_at"].isoformat() if r["reviewed_at"] else None,
                              "note": r["reviewed_note"]} if r["reviewed_by"] else None)
            out.append(d)
        return out, [dict(h, evidence=_p(h["evidence"])) for h in header]

    async def review_line(self, tenant: str, result_id: str, by: str, note: str) -> str | None:
        async with self.pool.acquire() as c:
            v = await c.fetchval(
                """UPDATE recon_line_results SET reviewed_by = $3, reviewed_at = now(), reviewed_note = $4
                    WHERE id = $1::uuid AND tenant_id = $2::uuid RETURNING case_id""", result_id, tenant, by, note)
        return str(v) if v else None

    async def unreviewed_blockers(self, case_id: str) -> int:
        async with self.pool.acquire() as c:
            return await c.fetchval(
                """SELECT count(*) FROM recon_line_results WHERE case_id = $1::uuid AND reviewed_by IS NULL
                      AND (severity = 'BLOCKER' OR (result->>'needs_review_cell')::boolean
                           AND severity <> 'INFO')""", case_id)

    async def acknowledge(self, tenant: str, case_id: str, by: str, note: str) -> None:
        async with self.pool.acquire() as c:
            await c.execute(
                """UPDATE recon_cases SET acknowledged_by = $3, acknowledged_at = now(), ack_note = $4,
                          ack_hash = result_hash, status = 'ACKNOWLEDGED'
                    WHERE id = $1::uuid AND tenant_id = $2::uuid""", case_id, tenant, by, note)

    # ── supplier / bill files ──────────────────────────────────────────────────
    async def supplier_identity(self, tenant: str, supplier: str) -> tuple[str | None, set[str]]:
        async with self.pool.acquire() as c:
            row = await c.fetchrow("SELECT name, gstn FROM dim_suppliers WHERE supplier_id = $1::uuid "
                                   "AND tenant_id = $2::uuid", supplier, tenant)
            try:
                extra = await c.fetch("SELECT gstin FROM supplier_gstins WHERE supplier_id = $1::uuid "
                                      "AND tenant_id = $2::uuid", supplier, tenant)
            except Exception:                      # table absent on very old schemas
                extra = []
        gst = {g for g in ([row["gstn"]] if row and row["gstn"] else []) + [r["gstin"] for r in extra] if g}
        return (row["name"] if row else None), {g.strip().upper() for g in gst}

    async def bill_upload_bytes(self, tenant: str, upload_id: str) -> tuple[str, bytes] | None:
        from ..core import object_store
        async with self.pool.acquire() as c:
            r = await c.fetchrow("SELECT file_name, storage_path, file_data FROM raw_invoice_uploads "
                                 "WHERE upload_id = $1::uuid AND tenant_id = $2::uuid", upload_id, tenant)
        if not r:
            return None
        data = None
        if r["storage_path"]:
            data = await asyncio.to_thread(object_store.load, r["storage_path"])
        if data is None and r["file_data"] is not None:
            data = bytes(r["file_data"])
        return (r["file_name"] or "invoice.pdf", data) if data else None

    async def adopt_bill(self, tenant: str, bill_id: str, actor: str | None,
                         revive: bool = False) -> str | None:
        """Read a bill's own invoice file through recon (no re-upload): a recon
        vendor_documents row pointing at the bill's upload. Idempotent per bill.

        A row the user deleted from Recon normally stays deleted — removing a
        document should not be undone by the next background pass. But that
        left no way out of a real dead end: delete the adopted bill, upload the
        PO again, and the PO waits for an invoice that exists and can never
        arrive, with nothing on the screen to explain it or undo it.

        `revive` is for exactly that moment — a PO actively waiting for its
        invoice. It is a fresh request to read this bill, not the loop
        resurrecting a deletion on its own.
        """
        b = await self.bill(tenant, bill_id)
        if not b or not b.get("upload_id"):
            return None
        # Keyed by the BILL, not by its upload. Re-uploading an invoice makes a
        # second bill row against the SAME upload, so an upload-keyed document
        # was shared by both: deleting the old bill's copy took the new bill's
        # invoice with it, and the live bill could never be read. On the real
        # vendor one upload (b4c3fec7) carried two bill rows, one deleted and
        # one active, and the active one was unreadable because of it.
        ref = f"bill:{bill_id}"
        legacy = f"bill-upload:{b['upload_id']}"
        async with self.pool.acquire() as c:
            row = await c.fetchrow(
                "SELECT id, deleted_at FROM vendor_documents WHERE tenant_id = $1::uuid AND file_path = $2",
                tenant, ref)
            if row is None:
                # An upload-keyed row from before this change still serves its
                # bill — but only while it is alive. A deleted one is left
                # alone, so this bill gets a document of its own below rather
                # than inheriting another bill's deletion.
                row = await c.fetchrow(
                    """SELECT id, deleted_at FROM vendor_documents
                        WHERE tenant_id = $1::uuid AND file_path = $2 AND deleted_at IS NULL""",
                    tenant, legacy)
            if row and row["deleted_at"] is not None and revive:
                await c.execute(
                    """UPDATE vendor_documents
                          SET deleted_at = NULL, recon_status = 'PENDING', recon_stage = NULL,
                              recon_error = NULL
                        WHERE id = $1""", row["id"])
                return str(row["id"])
            if row:
                # Still deleted, and nobody asked for it back.
                return None if row["deleted_at"] is not None else str(row["id"])
            return str(await c.fetchval(
                """INSERT INTO vendor_documents (supplier_id, tenant_id, brand_id, file_name, file_path, uploaded_by,
                          doc_type, doc_label, recon_status, claims_status)
                   VALUES ($1::uuid, $2::uuid, $3::uuid, $4, $5, $6, 'recon', 'Invoice (from bill)', 'PENDING', 'SKIPPED')
                   RETURNING id""",
                str(b["supplier_id"]), tenant, b.get("brand_id"), f"Invoice {b['invoice_number'] or ''}".strip() + ".pdf",
                ref, actor or "recon"))

    async def awaiting_case_for_po(self, tenant: str, po_id: str) -> str | None:
        async with self.pool.acquire() as c:
            v = await c.fetchval("SELECT id FROM recon_cases WHERE tenant_id = $1::uuid AND po_id = $2::uuid "
                                 "AND bill_id IS NULL AND invoice_segment_id IS NULL ORDER BY created_at LIMIT 1",
                                 tenant, po_id)
        return str(v) if v else None

    # ── events / notify ────────────────────────────────────────────────────────
    async def log_event(self, tenant: str, kind: str, payload: dict | None = None, actor: str | None = None,
                        case_id: str | None = None, doc_id: str | None = None) -> None:
        async with self.pool.acquire() as c:
            await c.execute(
                """INSERT INTO recon_events (tenant_id, case_id, doc_id, kind, payload, actor)
                   VALUES ($1::uuid, $2::uuid, $3::uuid, $4, $5::jsonb, $6)""",
                tenant, case_id, doc_id, kind, json.dumps(to_json(payload or {})), actor)

    async def events(self, tenant: str, case_id: str, limit: int = 100) -> list[dict]:
        async with self.pool.acquire() as c:
            rows = await c.fetch("SELECT kind, payload, actor, at FROM recon_events WHERE tenant_id = $1::uuid "
                                 "AND case_id = $2::uuid ORDER BY at DESC LIMIT $3", tenant, case_id, limit)
        return [{"kind": r["kind"], "payload": _p(r["payload"]), "actor": r["actor"], "at": r["at"].isoformat()}
                for r in rows]

    async def notify(self, channel: str, payload: str = "") -> None:
        async with self.pool.acquire() as c:
            await c.execute("SELECT pg_notify($1, $2)", channel, payload)
