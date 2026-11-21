"""ReconPipeline — reading, extraction, linking and the engine, tied to the DB
(03_LLD_BACKEND.md §6, 05_USER_FLOWS.md F1–F8).

ingest(doc)          read → classify → segment → extract → link → recompute touched cases
recompute(case)      CaseBuilder → match (aliases, overrides) → engine → save → Review Hub
relink_supplier()    retry unlinked segments when something new arrives (a bill, a PO)
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date
from dataclasses import dataclass, field

from . import config as C
from decimal import Decimal

from . import decisions, grn, profiles
from .normalize import norm
from .assemble import reconcile
from .case import CaseBuilder
from .classify import PageClassifier
from .clean import doc_number_ok
from .extract import ExtractContext, FieldSheetExtractor, for_segment
from .extract.spreadsheet import map_sheets
from .link import CaseView, LinkCandidate, decide, is_foreign, norm_no, po_base, po_invoice_fit, score, top3
from .llm import LLM
from .match import Adjudicator
from .pages import PageReader
from .repo import ReconRepository, load_extracted
from .segment import Segment, Segmenter
from .types import (
    DocClass, ExtractedDoc, ExtractedInvoice, ExtractedMemo, ExtractedOther, ExtractedPO, ExtractedPOD,
    MatchMethod, PVSection, ReconResult, RuleConfig, SegmentKind,
)

logger = logging.getLogger(__name__)

_ORDER = {SegmentKind.PURCHASE_ORDER: 0, SegmentKind.TAX_INVOICE: 1, SegmentKind.PV_SECTION: 2,
          SegmentKind.POD: 3, SegmentKind.APPROVAL_MEMO: 4, SegmentKind.OTHER: 5}
_ROLE = {SegmentKind.PURCHASE_ORDER: "po", SegmentKind.TAX_INVOICE: "invoice", SegmentKind.PV_SECTION: "evidence",
         SegmentKind.POD: "pod", SegmentKind.APPROVAL_MEMO: "memo", SegmentKind.OTHER: "other"}


@dataclass
class IngestOutcome:
    status: str
    touched_cases: set[str] = field(default_factory=set)
    warnings: list[str] = field(default_factory=list)


def _glossary(res) -> list[tuple[str, str]]:
    """The pairings on this case we are already sure of.

    These are the confident edges of the match graph, and they are the most
    useful thing we can tell a model about the two documents: this vendor bills
    "Gypsum False Ceiling India Gypsum" as "False ceiling - gypsum", and the
    way to learn that is from the lines that matched cleanly.

    What teaches is a pairing we are sure of **whose two wordings differ**. An
    EXACT match is exact because the words are already the same, so it has
    nothing to say; measured on the real case it produced an empty glossary.
    The entries that carry vocabulary are:

      - HUMAN — somebody looked at both and said yes. If it needed a person,
        the wordings differ.
      - ALIAS — a learned mapping for this vendor. It IS a glossary entry.
      - a high-scoring match whose RATE also agrees. The money corroborating
        the text is what separates this from teaching one guess with another:
        a 0.73 text score alone would spread a plausible mistake across the
        whole invoice.
    """
    out = []
    for l in res.lines:
        if not (l.po_key and l.invoice_key):
            continue
        rate_agrees = (l.po_rate is not None and l.billed_rate is not None
                       and abs(Decimal(str(l.po_rate)) - Decimal(str(l.billed_rate)))
                       <= Decimal("0.01"))
        trusted = (l.match_method in (MatchMethod.HUMAN, MatchMethod.ALIAS)
                   or (l.match_method == MatchMethod.SCORE
                       and (l.match_score or 0) >= 0.90 and rate_agrees))
        if not trusted:
            continue
        billed = l.invoice_text or l.description
        if billed and l.description and norm(billed) != norm(l.description):
            out.append((l.description, billed))
    return out


class ReconPipeline:
    def __init__(self, repo: ReconRepository, llm: LLM | None = None, adjudicate: Adjudicator | None = None,
                 config: RuleConfig | None = None, load_bytes=None) -> None:
        self.repo = repo
        self.llm = llm
        self.adjudicate = adjudicate
        self.config = config
        self._load_bytes = load_bytes        # injectable for tests: (tenant, file_path) -> bytes

    # ── recompute ──────────────────────────────────────────────────────────────
    # ── GRN extract (plan §7) ──────────────────────────────────────────────────
    async def ingest_grn_extract(self, tenant: str, file_name: str, contents: bytes,
                                 actor: str | None = None):
        """Load an MSD goods-receipt extract. Returns a grn.LoadReport.

        The tenant's declared column mapping decides; inference is the fallback.
        Nothing is saved unless at least one usable line was produced, and the
        report always says which sheet was used, what was left unmapped and
        which rows were skipped — a half-loaded receipt must never pass for a
        complete one.
        """
        from .core_tables import parse_spreadsheet_safe
        declared = await self.repo.tenant_grn_mapping(tenant)
        sheets = parse_spreadsheet_safe(file_name, contents)
        report = grn.load_extract(sheets, declared)
        if report.lines:
            await self.repo.save_grn_lines(tenant, report.lines, source_file=file_name)
        await self.repo.log_event(tenant, "grn_ingested", {
            "file": file_name, "sheet": report.sheet, "mapping": report.mapping_source,
            "saved": len(report.lines), "rows_read": report.rows_read,
            "skipped": len(report.problems), "unmapped_columns": report.unmapped_columns,
            "declared_but_absent": report.declared_but_absent,
            "rejected_sheets": report.rejected_sheets,
        }, actor=actor)
        logger.info("[recon] grn file=%s sheet=%s mapping=%s saved=%d skipped=%d",
                    file_name, report.sheet, report.mapping_source, len(report.lines),
                    len(report.problems))
        return report

    async def _try_grn(self, tenant: str, name: str, data: bytes):
        """Load this spreadsheet as a goods receipt, or return None.

        Deliberately strict: only a sheet whose columns satisfy the required
        GRN fields counts. An audit table that happens to have a quantity
        column must not be swallowed as a receipt, so a partial match falls
        through to the ordinary reader rather than guessing.
        """
        from .core_tables import parse_spreadsheet_safe
        try:
            declared = await self.repo.tenant_grn_mapping(tenant)
            sheets = await asyncio.to_thread(parse_spreadsheet_safe, name, data)
            report = grn.load_extract(sheets, declared)
            if not report.lines or report.declared_but_absent:
                return None
            await self.repo.save_grn_lines(tenant, report.lines, source_file=name)
            return report
        except Exception:
            logger.exception("[recon] could not read %s as a goods receipt", name)
            return None

    async def _config_for(self, tenant: str) -> tuple[RuleConfig, str]:
        """The rule set this tenant is reconciled under, and its profile name.

        An explicitly injected config always wins (tests, one-off runs). Failing
        that the tenant's own setting decides, and an unreadable setting falls
        back to the default rather than stopping the run — reconciliation must
        not depend on the settings table being reachable.
        """
        if self.config is not None:
            return self.config, "explicit"
        try:
            name = await self.repo.tenant_rule_profile(tenant)
        except Exception:
            logger.exception("[recon] could not read rule profile for tenant=%s", tenant)
            name = None
        return profiles.resolve(name), (name or "default")

    async def _adjudicated(self, inp, aliases, overrides, case_id=None):
        """Reconcile, consulting the decisions layer about what is in doubt.

        Returns the finished `ReconResult`. The collector pass is not free —
        matching is O(n²) scoring plus O(n³) assignment, measured at 0.2s for
        100 lines but **28s for 1000** — so the first pass's result is RETURNED
        rather than thrown away. Only a case where something was actually
        judged pays for a second pass; everything else pays once, as it did
        before the decisions layer existed.

        Failure here is never fatal: the reconciliation this is trying to
        improve already works without it.
        """
        if not decisions.ENABLED:
            return reconcile(inp, aliases=aliases, overrides=overrides)
        seen = decisions.Collector()
        first = reconcile(inp, aliases=aliases, overrides=overrides, adjudicate=seen)
        try:
            if not seen.pairs:
                return first
            judged = await decisions.judge_pairs(
                seen.pairs, glossary=_glossary(first), cache_key=case_id)
            taken = {k: v for k, v in judged.items() if v.decided and v.value is True}
            if not taken:
                return first
            logger.info("[recon] decisions placed %d of %d doubtful line(s)",
                        len(taken), len({p[0].split("|")[1] for p in seen.pairs}))
            return reconcile(inp, aliases=aliases, overrides=overrides,
                             adjudicate=decisions.lookup_adjudicator(judged))
        except Exception:
            logger.exception("[recon] adjudication failed; keeping the deterministic match")
            return first

    async def recompute(self, tenant: str, case_id: str, actor: str | None = None) -> ReconResult:
        cfg, profile_name = await self._config_for(tenant)
        inp, case = await CaseBuilder(self.repo).load_input(tenant, case_id, cfg)
        aliases = await self.repo.aliases(tenant, str(case["supplier_id"]))
        overrides = await self.repo.overrides(case_id)
        res = (reconcile(inp, aliases=aliases, overrides=overrides, adjudicate=self.adjudicate)
               if self.adjudicate
               else await self._adjudicated(inp, aliases, overrides, case_id))
        status = await self.repo.save_result(tenant, case_id, res)
        # Stamp what this verdict was computed from, decisions included (plan §8),
        # then refresh the derived match surface (plan §3). Both are best-effort:
        # a verdict that is already saved must not be lost because a projection
        # failed to rebuild, so neither is allowed to break the recompute.
        fingerprint = edges_built = None
        try:
            fingerprint = await self.repo.stamp_fingerprint(tenant, case_id, rule_version=profile_name[:16])
        except Exception:
            logger.exception("[recon] fingerprint failed case=%s", case_id)
        try:
            edges_built = await self.repo.rebuild_edges(tenant, case_id)
        except Exception:
            logger.exception("[recon] edge rebuild failed case=%s", case_id)
        await self.repo.log_event(tenant, "recomputed", {
            "status": status, "money_at_risk": res.summary.money_at_risk,
            "under_billed": res.summary.under_billed, "counts": res.summary.counts,
            "input_fingerprint": fingerprint, "edges": edges_built,
            # Which policy produced this verdict. Without it, a verdict read a
            # year later cannot be judged: the same documents under a different
            # tolerance are a different answer.
            "rule_profile": profile_name, "rules": profiles.describe(cfg),
        }, actor=actor, case_id=case_id)
        await self.repo.notify("review_adapters", "recon")
        logger.info("[recon] case=%s status=%s risk=%s under=%s", case_id, status,
                    res.summary.money_at_risk, res.summary.under_billed)
        return res

    # ── ingest ─────────────────────────────────────────────────────────────────
    async def ingest(self, doc_row: dict) -> IngestOutcome:
        tenant, supplier, doc_id = str(doc_row["tenant_id"]), str(doc_row["supplier_id"]), str(doc_row["id"])
        name, path = doc_row["file_name"], doc_row["file_path"]
        out = IngestOutcome(status="READY")
        data = await self._bytes(tenant, path)
        if not data:
            # Name the actual cause. "Could not be loaded" sent people to press
            # "Read again" on a file whose bytes were never reachable from here.
            from ..core import object_store
            raise ValueError(object_store.unreadable_here(path)
                             or "The file could not be loaded from storage")
        supplier_name, supplier_gstins = await self.repo.supplier_identity(tenant, supplier)
        ctx = ExtractContext(tenant_id=tenant, supplier_id=supplier, supplier_name=supplier_name, llm=self.llm)

        from ..core.vendor_doc_tables import is_spreadsheet
        extracted: list[tuple[str, Segment, ExtractedDoc]] = []
        saved: set[str] = set()                 # POs are saved as soon as read, so later segments can use them
        if is_spreadsheet(name):
            await self.repo.set_doc(doc_id, stage="extracting")
            # A goods-receipt export is just a spreadsheet someone dropped in —
            # there is no second upload button for it. If its columns map to a
            # GRN it loads as the receipt leg; otherwise it falls through to the
            # ordinary sheet reader and is read as a PO or an audit table.
            loaded = await self._try_grn(tenant, name, data)
            if loaded is not None:
                out.status = "READY"
                await self.repo.set_doc(doc_id, status="READY", stage=None)
                await self.repo.log_event(tenant, "grn_ingested", {
                    "file": name, "sheet": loaded.sheet, "mapping": loaded.mapping_source,
                    "saved": len(loaded.lines), "rows_read": loaded.rows_read,
                    "skipped": len(loaded.problems), "unmapped_columns": loaded.unmapped_columns,
                }, doc_id=doc_id)
                logger.info("[recon] %s read as a goods receipt: %d line(s)", name, len(loaded.lines))
                return out
            sheets = await asyncio.to_thread(map_sheets, name, data)
            segs = [Segment(kind=s.kind, pages=[i + 1], llm_label=s.sheet, section_title=s.sheet,
                            confidence=s.confidence) for i, s in enumerate(sheets)]
            ids = await self.repo.replace_segments(doc_id, tenant, supplier, [s.to_row() for s in segs])
            for sid, seg, sheet in zip(ids, segs, sheets):
                sheet.doc.warnings += sheet.warnings
                extracted.append((sid, seg, sheet.doc))
        else:
            reader = PageReader()
            doc = reader.open(data, name)
            ctx.reader, ctx.doc = reader, doc
            await self.repo.set_doc(doc_id, stage="reading")
            pages = reader.read_text(doc)
            reader.mark_blank(doc, pages)
            out.warnings += reader.warnings
            ctx.pages = {p.index: p for p in pages}
            await self.repo.set_doc(doc_id, stage="classifying", progress={"page": 0, "pages": len(pages)})
            thumbs = {p.index: reader.render(doc, p.index, dpi=70) for p in pages
                      if not p.has_text_layer and not p.blank} if self.llm else {}
            labels = await PageClassifier(self.llm).classify(pages, thumbs)
            thumbs.clear()
            await self.repo.save_pages(doc_id, tenant, [
                {**p.to_row(), "doc_class": l.doc_class.value, "class_conf": l.confidence, "class_method": l.method,
                 "llm_label": l.llm_label, "hints": l.hints()} for p, l in zip(pages, labels)])
            ctx.narrative_text = "\n".join(p.text for p, l in zip(pages, labels) if l.doc_class == DocClass.PV_NARRATIVE)
            segs = sorted(Segmenter().segment(labels), key=lambda s: _ORDER.get(s.kind, 9))
            ids = await self.repo.replace_segments(doc_id, tenant, supplier, [s.to_row() for s in segs])
            pos = await self.repo.supplier_pos(tenant, supplier)
            await self.repo.set_doc(doc_id, stage="extracting")
            field_pages = [l.page_index for l in labels if l.doc_class == DocClass.PV_FIELD_SHEET]
            for n, (sid, seg) in enumerate(zip(ids, segs), 1):
                await self.repo.set_doc(doc_id, progress={"segment": n, "segments": len(segs)})
                ctx.po_hint = self._po_hint(seg, pos)
                try:
                    ex = await for_segment(seg).extract(seg, ctx)
                    if isinstance(ex, PVSection) and field_pages and DocClass.PV_ANNEXURE_TYPED in seg.classes:
                        await FieldSheetExtractor().merge(ex, field_pages, ctx)
                except Exception as exc:                       # one bad segment doesn't sink the file
                    logger.exception("[recon] extract failed doc=%s seg=%s", doc_id, sid)
                    await self.repo.set_segment(sid, status="FAILED")
                    out.warnings.append(f"Pages {_pages(seg.pages)}: {exc}")
                    continue
                extracted.append((sid, seg, ex))
                if isinstance(ex, ExtractedPO) and ex.lines and doc_number_ok(ex.po_number, ex.store_sn):
                    await self.repo.save_extraction(tenant, supplier, sid, seg.kind.value, ex)
                    saved.add(sid)
                    pos = await self.repo.supplier_pos(tenant, supplier)
        await self.repo.set_doc(doc_id, stage="linking")
        for sid, seg, ex in extracted:
            if sid not in saved:
                await self.repo.save_extraction(tenant, supplier, sid, seg.kind.value, ex,
                                                status="NEEDS_REVIEW" if _needs_review(ex) else "EXTRACTED")
        # POs and invoices first, then the vendor's parts still waiting (a PO from an earlier file may now
        # find its invoice), and only then the reports — so an audit sheet sees PO and invoice already
        # together on one case instead of opening a "PO, no invoice yet" case of its own.
        mine = {sid for sid, _, _ in extracted}
        anchors = [x for x in extracted if isinstance(x[2], (ExtractedPO, ExtractedInvoice))]
        for sid, seg, ex in anchors:
            out.touched_cases |= await self._link(tenant, supplier, sid, seg.kind, ex, supplier_name,
                                                  supplier_gstins)
        out.touched_cases |= await self.relink_supplier(tenant, supplier, recompute=False, skip=mine)
        for sid, seg, ex in extracted:
            if not isinstance(ex, (ExtractedPO, ExtractedInvoice)):
                out.touched_cases |= await self._link(tenant, supplier, sid, seg.kind, ex, supplier_name,
                                                      supplier_gstins)
        out.touched_cases |= await self.relink_supplier(tenant, supplier, recompute=False, skip=mine)
        await self.repo.set_doc(doc_id, stage="matching")
        for case_id in out.touched_cases:
            await self.recompute(tenant, case_id)
        out.status = await self._doc_status(doc_id, extracted, out)
        return out

    async def _bytes(self, tenant: str, path: str) -> bytes | None:
        if self._load_bytes:
            return await self._load_bytes(tenant, path)
        if path.startswith("bill-upload:"):
            r = await self.repo.bill_upload_bytes(tenant, path.split(":", 1)[1])
            return r[1] if r else None
        from ..core import object_store
        return await asyncio.to_thread(object_store.load, path)

    @staticmethod
    def _po_hint(seg: Segment, pos: list[tuple[str, ExtractedPO]]) -> ExtractedPO | None:
        if not pos:
            return None
        for _, po in pos:
            if po_base(po.po_number) in {po_base(x) for x in seg.po_numbers}:
                return po
        if seg.store_sn:
            same = [po for _, po in pos if po.store_sn and po.store_sn == seg.store_sn]
            if len(same) == 1:
                return same[0]
        return pos[0][1] if len(pos) == 1 else None

    async def _doc_status(self, doc_id: str, extracted, out: IngestOutcome) -> str:
        segs = await self.repo.segments_for_doc(doc_id)
        if segs and all(s["status"] == "FAILED" for s in segs):
            return "FAILED"
        if any(s["status"] == "UNLINKED" for s in segs):
            return "NEEDS_LINK"
        if any(s["status"] == "NEEDS_REVIEW" for s in segs) or any(_needs_review(ex) for _, _, ex in extracted):
            return "NEEDS_REVIEW"
        return "READY"

    # ── re-extract one segment (user changed its type, F7) ─────────────────────
    async def reextract_segment(self, tenant: str, seg_id: str) -> set[str]:
        s = await self.repo.segment(tenant, seg_id)
        if s is None:
            raise LookupError(seg_id)
        doc = await self.repo.get_doc(tenant, str(s["doc_id"]))
        data = await self._bytes(tenant, doc["file_path"])
        supplier = str(s["supplier_id"])
        name, gstins = await self.repo.supplier_identity(tenant, supplier)
        reader = PageReader()
        pdf = reader.open(data, doc["file_name"])
        pages = reader.read_text(pdf)
        stored = {p["page_index"]: p for p in await self.repo.load_pages(str(s["doc_id"]))}
        kind = SegmentKind(s["kind"])
        classes = []
        for i in s["pages"]:
            dc = stored.get(i, {}).get("doc_class")
            classes.append(DocClass(dc) if dc else DocClass.OTHER)
        if kind == SegmentKind.PV_SECTION and DocClass.PV_ANNEXURE_TYPED not in classes:
            classes = [DocClass.PV_SHEET_SCANNED] * len(classes)
        if kind == SegmentKind.TAX_INVOICE and DocClass.TAX_INVOICE not in classes:
            classes = [DocClass.TAX_INVOICE] + [DocClass.INVOICE_ANNEXURE] * (len(classes) - 1)
        seg = Segment(kind=kind, pages=list(s["pages"]), classes=classes, section_title=s.get("section_title"),
                      store_sn=s.get("store_sn"))
        ctx = ExtractContext(tenant_id=tenant, supplier_id=supplier, supplier_name=name, llm=self.llm, reader=reader,
                             doc=pdf, pages={p.index: p for p in pages})
        ctx.po_hint = self._po_hint(seg, await self.repo.supplier_pos(tenant, supplier))
        ex = await for_segment(seg).extract(seg, ctx)
        before = await self.repo.cases_using_segment(seg_id)
        for case_id in before:
            await self.repo.detach(tenant, case_id, seg_id)
        await self.repo.save_extraction(tenant, supplier, seg_id, kind.value, ex,
                                        status="NEEDS_REVIEW" if _needs_review(ex) else "EXTRACTED")
        touched = set(before) | await self._link(tenant, supplier, seg_id, kind, ex, name, gstins)
        for case_id in touched:
            await self.recompute(tenant, case_id)
        return touched

    # ── linking ────────────────────────────────────────────────────────────────
    async def _views(self, tenant: str, supplier: str) -> list[CaseView]:
        cases = await self.repo.cases_for_supplier(tenant, supplier)
        pos = dict(await self.repo.supplier_pos(tenant, supplier))
        bills = {str(b["invoice_id"]): b for b in await self.repo.supplier_bills(tenant, supplier, C.LOOKBACK_DAYS)}
        views: list[CaseView] = []
        cased_pos: set[str] = set()
        for c in cases:
            b = bills.get(str(c["bill_id"])) if c["bill_id"] else None
            po_id = str(c["po_id"]) if c["po_id"] else None
            if po_id:
                cased_pos.add(po_id)
            views.append(CaseView(
                target_type="case", target_id=str(c["id"]), case_id=str(c["id"]), bill_id=str(c["bill_id"]) if c["bill_id"] else None,
                po_id=po_id, label=f"{c.get('invoice_no') or 'No invoice yet'} · {c.get('po_number') or 'no PO'}",
                invoice_no=c.get("invoice_no") or (b["invoice_number"] if b else None),
                invoice_date=b["invoice_date"] if b else None, invoice_total=b["total_amount"] if b else None,
                invoice_taxable=b["taxable_amount"] if b else None, po=pos.get(po_id) if po_id else None,
                store_sn=c.get("store_sn")))
        for po_id, po in pos.items():
            if po_id not in cased_pos:
                views.append(CaseView(target_type="po", target_id=po_id, po_id=po_id, po=po, store_sn=po.store_sn,
                                      label=f"PO {po.po_number} (no invoice yet)"))
        cased_bills = {v.bill_id for v in views if v.bill_id}
        for bid, b in bills.items():
            if bid not in cased_bills:
                views.append(CaseView(target_type="bill", target_id=bid, bill_id=bid, invoice_no=b["invoice_number"],
                                      invoice_date=b["invoice_date"], invoice_total=b["total_amount"],
                                      invoice_taxable=b["taxable_amount"],
                                      label=f"Bill {b['invoice_number'] or ''}".strip()))
        return views

    async def _link(self, tenant: str, supplier: str, sid: str, kind: SegmentKind, ex: ExtractedDoc,
                    supplier_name: str | None, supplier_gstins: set[str]) -> set[str]:
        touched: set[str] = set()
        if isinstance(ex, ExtractedPO):
            po_id = await self.repo.find_po(tenant, (ex.po_number or "").partition("-")[0])
            if not po_id:
                await self.repo.set_segment(sid, status="UNLINKED")
                return touched
            # By number only when both sides print a Bata PO number: a PO with none (or an invoice with
            # none) must not "match" every other one — that once let a misread sheet take over a case.
            base = po_base(ex.po_number)
            hits = [v for v in await self._views(tenant, supplier) if base and v.target_type == "case"
                    and await self._case_po_ref(tenant, v) == base]
            for v in hits:
                await self.repo.set_case(v.case_id, po_id=po_id)
                await self.repo.attach(tenant, v.case_id, sid, "po", "auto", 1.0)
                touched.add(v.case_id)
            if not hits:
                # The invoice may not print the PO number: match on its lines, store and dates.
                linked = await self._link_po_by_content(tenant, supplier, sid, po_id, ex)
                if linked:
                    return touched | {linked}
                await self._read_waiting_bills(tenant, supplier, ex)
            return touched

        if isinstance(ex, ExtractedInvoice):
            if is_foreign(ex.vendor, supplier_name, supplier_gstins):
                # Another vendor's invoice (or sheet) inside this vendor's file: set aside, as a report section is.
                await self.repo.set_segment(sid, status="FOREIGN")
                return touched
            if not doc_number_ok(ex.invoice_no, getattr(ex, "store_sn", None)):
                await self.repo.set_segment(sid, status="UNLINKED", candidates=[])
                return touched
            return await self._link_invoice(tenant, supplier, sid, ex)

        if isinstance(ex, PVSection) and is_foreign(ex.vendor, supplier_name, supplier_gstins):
            await self.repo.set_segment(sid, status="FOREIGN")
            return touched

        views = await self._views(tenant, supplier)
        cands: list[LinkCandidate] = []
        if isinstance(ex, (PVSection, ExtractedOther)) and getattr(ex, "rows", None):
            rows = ex.rows
            date = ex.verification_date if isinstance(ex, PVSection) else None
            store = ex.store_sn if isinstance(ex, PVSection) else None
            cands = [score(v, store_sn=store, doc_date=date, rows=rows) for v in views if v.po is not None]
        elif isinstance(ex, ExtractedPOD):
            cands = [score(v, refs={"invoice_nos": ex.invoice_nos}, amount=ex.total_invoice_value,
                           doc_date=ex.receipt.date or ex.ship_date) for v in views if v.target_type in ("case", "bill")]
        elif isinstance(ex, ExtractedMemo):
            same_store = [v for v in views if v.target_type == "case" and ex.store_sn and
                          (v.store_sn or (v.po.store_sn if v.po else None)) == ex.store_sn]
            for v in same_store:                          # memos are informational: attach to every match
                await self.repo.attach(tenant, v.case_id, sid, "memo", "auto", 0.9)
                touched.add(v.case_id)
            if not same_store:
                await self.repo.set_segment(sid, status="UNLINKED", candidates=[])
            return touched
        else:
            await self.repo.set_segment(sid, status="UNLINKED", candidates=[])
            return touched

        pick = decide(cands)
        if pick is None:
            await self.repo.set_segment(sid, status="UNLINKED", candidates=top3(cands))
            return touched
        case_id = await self._case_for(tenant, supplier, pick)
        await self.repo.attach(tenant, case_id, sid, _ROLE[kind], "auto", pick.score)
        await self.repo.set_segment(sid, candidates=top3(cands))
        touched.add(case_id)
        return touched

    async def _read_waiting_bills(self, tenant: str, supplier: str, po: ExtractedPO, limit: int = 5) -> list[str]:
        """A PO with no invoice yet: the invoice may already be in the app as a bill.
        Bills don't store a PO number, so read this vendor's bills dated on or after
        the PO through recon (their own file, no re-upload); the invoice's PO
        reference then links bill and PO (05_USER_FLOWS.md F8)."""
        queued = []
        cased = {str(c["bill_id"]) for c in await self.repo.cases_for_supplier(tenant, supplier) if c["bill_id"]}
        bills = await self.repo.supplier_bills(tenant, supplier, C.LOOKBACK_DAYS)
        bills.sort(key=lambda b: b["invoice_date"] or po.po_date or po.delivery_date or date.min,
                   reverse=True)
        for b in bills:
            bid = str(b["invoice_id"])
            if bid in cased or not b.get("upload_id"):
                continue
            if po.po_date and b["invoice_date"] and b["invoice_date"] < po.po_date:
                continue
            # A PO is waiting for its invoice: a fresh reason to read this
            # bill, even if its adopted copy was removed from Recon before.
            doc_id = await self.repo.adopt_bill(tenant, bid, "recon", revive=True)
            if doc_id:
                queued.append(doc_id)
            if len(queued) >= limit:
                break
        if queued:
            await self.repo.notify("recon_docs", '{"kind": "doc"}')
            logger.info("[recon] PO %s waiting — reading %d existing bill(s)", po.po_number, len(queued))
        return queued

    async def _case_for(self, tenant: str, supplier: str, pick: LinkCandidate) -> str:
        if pick.case_id:
            return pick.case_id
        if pick.target_type == "bill":
            b = await self.repo.bill(tenant, pick.bill_id)
            return await self.repo.ensure_case(tenant, supplier, bill_id=pick.bill_id,
                                               invoice_no=b["invoice_number"] if b else None)
        # A PO that has no invoice yet: open a case that waits for it (F8).
        existing = await self.repo.awaiting_case_for_po(tenant, pick.po_id)
        if existing:
            return existing
        po = await self.repo.load_po(tenant, pick.po_id)
        case_id = await self.repo.ensure_case(tenant, supplier, po_id=pick.po_id, store_sn=po.store_sn if po else None)
        if po:
            await self._read_waiting_bills(tenant, supplier, po)
        if po and po.segment_id:
            await self.repo.attach(tenant, case_id, po.segment_id, "po", "auto", 1.0)
        return case_id

    async def _link_invoice(self, tenant: str, supplier: str, sid: str, inv: ExtractedInvoice) -> set[str]:
        bills = await self.repo.supplier_bills(tenant, supplier, C.LOOKBACK_DAYS)
        numbers = {norm_no(inv.invoice_no)} | {norm_no(c.handwritten) for c in inv.corrections}
        bill = next((b for b in bills if norm_no(b["invoice_number"]) in numbers and norm_no(b["invoice_number"])), None)
        po_id = await self.repo.find_po(tenant, f"PPO{int(po_base(inv.po_ref)):08d}") if po_base(inv.po_ref) else None
        case_id = None
        if bill:
            case_id = await self.repo.case_for_bill(tenant, str(bill["invoice_id"]))
            if case_id is None and po_id:
                case_id = await self.repo.awaiting_case_for_po(tenant, po_id)
                if case_id:
                    await self.repo.set_case(case_id, bill_id=str(bill["invoice_id"]))
            if case_id is None:
                case_id = await self.repo.ensure_case(tenant, supplier, bill_id=str(bill["invoice_id"]),
                                                      invoice_no=bill["invoice_number"])
        else:
            if po_id:
                case_id = await self.repo.awaiting_case_for_po(tenant, po_id)
            case_id = case_id or await self.repo.ensure_case(tenant, supplier, invoice_segment_id=sid,
                                                             invoice_no=inv.invoice_no)
        await self.repo.set_case(case_id, invoice_segment_id=sid, invoice_no=inv.invoice_no)
        if not po_id and not po_base(inv.po_ref):
            # No Bata PO number on the invoice: a PO already here may still be its PO by content.
            po_id = await self._po_for_invoice_by_content(tenant, supplier, case_id)
        if po_id:
            await self.repo.set_case(case_id, po_id=po_id)
            po = await self.repo.load_po(tenant, po_id)
            await self.repo.set_case(case_id, store_sn=po.store_sn if po else None)
            if po and po.segment_id:
                await self.repo.attach(tenant, case_id, po.segment_id, "po", "auto", 1.0)
        await self.repo.attach(tenant, case_id, sid, "invoice", "auto", 1.0)
        return {case_id}

    async def _invoice_context(self, tenant: str, case: dict) -> dict | None:
        """An invoice's lines, store, date, value and printed PO reference, for content matching."""
        seg = await self.repo.segment(tenant, str(case["invoice_segment_id"])) if case.get("invoice_segment_id") else None
        if seg is None:                                   # linked as a part, not (yet) as the case's invoice
            seg = next((x for x in await self.repo.case_segments(str(case["id"])) if x["role"] == "invoice"), None)
        inv = load_extracted(SegmentKind.TAX_INVOICE.value, seg.get("extracted_json")) if seg else None
        if inv is not None:
            lines = await self.repo.invoice_lines(seg["id"])
            return {"lines": lines, "store": seg.get("store_sn"), "date": inv.invoice_date, "po_ref": inv.po_ref,
                    "amount": inv.taxable or inv.printed_subtotal, "label": f"Invoice {inv.invoice_no}"}
        if case.get("bill_id"):
            bill = await self.repo.bill(tenant, str(case["bill_id"]))
            if bill:
                return {"lines": await self.repo.bill_lines(tenant, bill["stg_bill_id"]), "store": None,
                        "date": bill.get("invoice_date"), "po_ref": None,
                        "amount": bill.get("taxable_amount") or bill.get("subtotal"), "label": f"Invoice {bill['invoice_number']}"}
        return None

    async def _link_po_by_content(self, tenant: str, supplier: str, sid: str, po_id: str, po: ExtractedPO) -> str | None:
        """A PO whose number no invoice prints: score the vendor's invoices still waiting for a PO.
        A clear winner links; close calls go to "Needs you" as choices; nothing → WAITING."""
        cands: list[LinkCandidate] = []
        for case in await self.repo.cases_for_supplier(tenant, supplier):
            if case.get("po_id") or not (case.get("invoice_segment_id") or case.get("bill_id")):
                continue
            ctx = await self._invoice_context(tenant, case)
            if not ctx:
                continue
            sc, sig = po_invoice_fit(po, ctx["lines"], inv_store=ctx["store"], inv_date=ctx["date"],
                                     inv_amount=ctx["amount"], inv_po_ref=ctx["po_ref"])
            if sc > 0:
                cands.append(LinkCandidate(target_type="case", target_id=str(case["id"]), label=ctx["label"],
                                           score=sc, signals=sig, case_id=str(case["id"])))
        pick = decide(cands)
        if pick:
            await self.repo.set_case(pick.case_id, po_id=po_id, store_sn=po.store_sn)
            await self.repo.attach(tenant, pick.case_id, sid, "po", "auto", pick.score)
            await self.repo.set_segment(sid, candidates=top3(cands))
            await self.repo.log_event(tenant, "linked_by_content", {"segment_id": sid, "score": pick.score,
                                                                    "signals": pick.signals}, case_id=pick.case_id)
            return pick.case_id
        good = [c for c in cands if c.score >= 0.45]
        await self.repo.set_segment(sid, status="UNLINKED" if good else "WAITING", candidates=top3(good))
        return None

    async def _po_for_invoice_by_content(self, tenant: str, supplier: str, case_id: str) -> str | None:
        """An invoice with no Bata PO number: the vendor's POs scored on its lines; only a clear winner links."""
        case = await self.repo.case_row(tenant, case_id)
        ctx = await self._invoice_context(tenant, case) if case else None
        if not ctx:
            return None
        cands = []
        for pid, po in await self.repo.supplier_pos(tenant, supplier):
            sc, sig = po_invoice_fit(po, ctx["lines"], inv_store=ctx["store"], inv_date=ctx["date"],
                                     inv_amount=ctx["amount"], inv_po_ref=ctx["po_ref"])
            if sc > 0:
                cands.append(LinkCandidate(target_type="po", target_id=pid, label=f"PO {po.po_number}", score=sc,
                                           signals=sig, po_id=pid))
        pick = decide(cands)
        if pick:
            await self.repo.log_event(tenant, "linked_by_content", {"po_id": pick.po_id, "score": pick.score,
                                                                    "signals": pick.signals}, case_id=case_id)
        return pick.po_id if pick else None

    async def _case_po_ref(self, tenant: str, v: CaseView) -> str | None:
        row = await self.repo.case_row(tenant, v.case_id)
        if not row or not row.get("invoice_segment_id"):
            return None
        seg = await self.repo.segment(tenant, str(row["invoice_segment_id"]))
        inv = load_extracted(SegmentKind.TAX_INVOICE.value, seg.get("extracted_json")) if seg else None
        return po_base(inv.po_ref) if inv else None

    async def relink_supplier(self, tenant: str, supplier: str, recompute: bool = True,
                              skip: set[str] | None = None) -> set[str]:
        """Retry segments still waiting for a home — after a new bill, PO or report arrives (F8)."""
        touched: set[str] = set()
        name, gstins = await self.repo.supplier_identity(tenant, supplier)
        for s in await self.repo.unlinked_segments(tenant, supplier):
            if skip and s["id"] in skip or s["status"] in ("FOREIGN", "IGNORED", "FAILED"):
                continue
            ex = load_extracted(s["kind"], s.get("extracted_json"))
            if ex is None:
                continue
            if isinstance(ex, (PVSection, ExtractedOther)):
                ex.rows = await self.repo.evidence_rows(s["id"])
            touched |= await self._link(tenant, supplier, s["id"], SegmentKind(s["kind"]), ex, name, gstins)
        if recompute:
            for case_id in touched:
                await self.recompute(tenant, case_id)
        return touched


def _needs_review(ex: ExtractedDoc) -> bool:
    rows = getattr(ex, "rows", None) or []
    return any(r.needs_review for r in rows)


def _pages(p: list[int]) -> str:
    return f"{p[0]}–{p[-1]}" if len(p) > 1 else str(p[0])
