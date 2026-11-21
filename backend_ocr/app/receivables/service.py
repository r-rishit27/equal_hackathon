"""CashApplicationService — capture, match, apply, unapply, learn (02_LLD.md §2, §5, §6.6–6.7).

The router and the worker both go through here, so the rules for what the agent
may do alone (policy.decide) and the money invariants (apply) live in one place.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import date
from decimal import Decimal

from .bank_statement import StatementError, finalize, parse_statement
from .detectors import classify_non_receipt
from .matching import (
    MatchConfig, OpenInvoice, Payment, RemittanceLine, identify_customer, match_payment, money, norm_name,
    token_windows,
)
from .policy import Policy, decide
from .repo import CashAppRepository
from .types import InvoiceStatus, JobReason, Method, PaymentStatus

log = logging.getLogger(__name__)
ZERO = Decimal("0")
CENT = Decimal("0.01")
AGENT = "agent"


class ServiceError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def _d(v) -> Decimal:
    return money(v)


class CashApplicationService:
    def __init__(self, repo: CashAppRepository):
        self.repo = repo

    # ── sales invoices ─────────────────────────────────────────────────────────

    async def ingest_invoice(self, tenant: str, payload: dict, actor: str | None,
                             file_bytes: bytes | None = None, file_name: str | None = None) -> dict:
        """An OCR'd (and human-reviewed) sales invoice → ar_invoices. The buyer is the customer."""
        from ..domain.ingest import _infer_due_date, _parse_date, _gstn_clean
        buyer = payload.get("buyer") or {}
        name = (buyer.get("name") or "").strip()
        number = str(payload.get("invoice_number") or "").strip()
        total = payload.get("total_amount")
        if not name:
            raise ServiceError(422, "Customer name is required")
        if not number:
            raise ServiceError(422, "Invoice number is required")
        if total in (None, ""):
            raise ServiceError(422, "Invoice total is required")
        taxes = payload.get("taxes") or {}
        taxable = taxes.get("taxable_amount") if taxes.get("taxable_amount") not in (None, "") else payload.get("subtotal")
        tax = taxes.get("total_tax_amount")
        if tax in (None, ""):
            parts = [taxes.get(k) for k in ("cgst_amount", "sgst_amount", "igst_amount", "cess_amount")]
            tax = sum(Decimal(str(p)) for p in parts if p not in (None, "")) if any(
                p not in (None, "") for p in parts) else None
        inv_date = _parse_date(payload.get("invoice_date"))
        due = _parse_date(payload.get("due_date")) or _infer_due_date(inv_date, payload.get("payment_terms"))
        gstin = _gstn_clean(buyer.get("gstin"))
        pan = (str(buyer.get("pan") or "").strip().upper() or None)
        if not pan and gstin:
            pan = gstin[2:12]

        invoice_id = str(uuid.uuid4())
        storage_ref = None
        if file_bytes:
            from ..core import object_store
            try:
                storage_ref = object_store.save(object_store.key("ar-invoices", tenant, invoice_id, file_name or "invoice.pdf"),
                                                file_bytes, "application/pdf")
            except Exception:
                log.exception("[ar] could not store invoice PDF %s", file_name)

        import asyncpg
        async with self.repo.pool.acquire() as c:
            try:
                async with c.transaction():
                    cid, created = await self.repo.find_or_create_customer(
                        c, tenant, name=name, gstin=gstin, pan=pan, address=buyer.get("address") or None)
                    clean_payload = {k: v for k, v in payload.items() if not str(k).startswith("_")}
                    iid = await c.fetchval(
                        """INSERT INTO ar_invoices (id, tenant_id, customer_id, invoice_number, invoice_date, due_date,
                                   po_number, currency, taxable_amount, tax_amount, total_amount, payment_terms,
                                   source_file, storage_ref, payload, created_by)
                           VALUES ($1::uuid, $2::uuid, $3::uuid, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14,
                                   $15::jsonb, $16) RETURNING id""",
                        invoice_id, tenant, cid, number, inv_date, due,
                        (str(payload.get("po_number") or "").strip() or None),
                        (payload.get("currency_code") or "INR")[:3].upper(),
                        _d(taxable) if taxable not in (None, "") else None,
                        _d(tax) if tax not in (None, "") else None, _d(total),
                        payload.get("payment_terms") or None, file_name, storage_ref,
                        json.dumps(clean_payload, default=str), actor)
                    await self.repo.event(c, tenant, "invoice", iid, "ingested", actor,
                                          {"invoice_number": number, "customer_created": created})
                    # A new invoice may explain money that is already in (edge cases D6, F4).
                    pids = await self.repo.unmatched_for_customer(tenant, cid)
                    await self.repo.enqueue(c, tenant, pids, JobReason.NEW_INVOICE)
            except asyncpg.UniqueViolationError:
                raise ServiceError(409, f"Invoice {number} already exists for {name}")
        return {"invoice_id": str(iid), "customer_id": cid, "customer_created": created}

    # ── capture ────────────────────────────────────────────────────────────────

    async def import_statement(self, tenant: str, data: bytes, filename: str, bank_account: str | None,
                               actor: str | None) -> dict:
        """A bank statement (CSV, XLSX or PDF) → payments queued for the agent.

        The original file is kept (object store, never public) with every line as
        read and what it became, so the statement can be opened again from the app.
        Re-importing the same file is refused up front; an overlapping statement
        imports only the lines not seen before (fingerprints).
        """
        import hashlib
        sha = hashlib.sha256(data).hexdigest()
        prior = await self.repo.statement_by_sha(tenant, sha)
        if prior:
            raise ServiceError(409, f"This statement was already imported on {prior['created_at']:%d %b %Y} "
                                    f"as {prior['file_name']}")
        fmt = "pdf" if filename.lower().endswith(".pdf") else "xlsx" if filename.lower().endswith((".xlsx", ".xlsm")) else "csv"
        account = None
        try:
            if fmt == "pdf":
                import tempfile
                from .statement_pdf import pdf_records
                with tempfile.NamedTemporaryFile(suffix=".pdf") as tmp:
                    tmp.write(data)
                    tmp.flush()
                    records, account = await pdf_records(tmp.name)
                parsed = finalize(records)
            else:
                parsed = parse_statement(data, filename)
        except StatementError as e:
            raise ServiceError(422, str(e))
        credits, lines = parsed["credits"], parsed["lines"]
        if not credits and not parsed["bounces"]:
            raise ServiceError(422, "No credits found in this statement")

        statement_id = str(uuid.uuid4())
        storage_ref = None
        try:
            from ..core import object_store
            ctype = {"pdf": "application/pdf", "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                     }.get(fmt, "text/csv")
            storage_ref = object_store.save(object_store.key("ar-statements", tenant, statement_id, filename), data, ctype)
        except Exception:
            log.exception("[ar] could not store statement %s", filename)
        dates = [date.fromisoformat(ln["date"]) for ln in lines]

        # Same payment already captured from another source (E4): same UTR.
        known_utrs = await self.repo.utr_exists(tenant, [c["utr"] for c in credits if c.get("utr")])
        rows = []
        for c in credits:
            c["statement_id"] = statement_id
            if c.get("utr") and c["utr"] in known_utrs:
                lines[c["line"]]["outcome"] = "duplicate"
                continue
            label = classify_non_receipt(c.get("narration"))
            if label:
                c["status"], c["note"] = PaymentStatus.NOT_RECEIPT, label
            rows.append(c)
        async with self.repo.pool.acquire() as conn:
            async with conn.transaction():
                await self.repo.insert_statement(conn, tenant, {
                    "id": statement_id, "file_name": filename, "file_format": fmt, "sha": sha,
                    "storage_ref": storage_ref, "bank_account": bank_account or account,
                    "period_from": min(dates) if dates else None, "period_to": max(dates) if dates else None,
                    "uploaded_by": actor})
                new = await self.repo.insert_payments(conn, tenant, rows, source="statement", source_file=filename,
                                                      bank_account=bank_account or account, actor=actor)
                imported = set_aside = 0
                for row, res in zip(rows, new):
                    ln = lines[row["line"]]
                    if res is None:
                        ln["outcome"] = "duplicate"
                        continue
                    ln["payment_id"] = res[0]
                    aside = res[1] == PaymentStatus.NOT_RECEIPT
                    ln["outcome"] = "set_aside" if aside else "new"
                    set_aside += aside
                    imported += not aside
                to_match = [r[0] for r in new if r and r[1] == PaymentStatus.UNMATCHED]
                await self.repo.enqueue(conn, tenant, to_match, JobReason.NEW_PAYMENT)
                # E5: a returned cheque / recall points at an earlier receipt.
                bounces = 0
                for b in parsed["bounces"]:
                    lines[b["line"]]["outcome"] = "debit"
                    hits = await self.repo.find_bounced(tenant, b)
                    if len(hits) == 1:
                        lines[b["line"]].update(outcome="bounce", payment_id=str(hits[0]["id"]))
                        await self.repo.flag_payment(conn, tenant, str(hits[0]["id"]), "POSSIBLE_BOUNCE")
                        await self.repo.event(conn, tenant, "payment", hits[0]["id"], "possible_bounce", AGENT,
                                              {"debit": str(b["amount"]), "narration": b["narration"]})
                        bounces += 1
                counts = {"credits": len(credits), "imported": imported, "set_aside": set_aside,
                          "duplicates": len(credits) - imported - set_aside, "possible_bounces": bounces,
                          "queued": len(to_match)}
                await self.repo.finish_statement(conn, tenant, statement_id, lines=lines, counts=counts)
                await self.repo.event(conn, tenant, "statement", statement_id, "statement_imported", actor,
                                      {"file": filename, **counts})
        return {"statement_id": statement_id, **counts}

    async def record_payment(self, tenant: str, body: dict, actor: str | None, force: bool = False) -> dict:
        amount = _d(body.get("amount"))
        if amount <= 0:
            raise ServiceError(422, "Amount must be more than zero")
        received_on = body.get("received_on")
        if isinstance(received_on, str):
            received_on = date.fromisoformat(received_on)
        if not received_on:
            raise ServiceError(422, "Date received is required")
        utr = (body.get("utr") or body.get("reference") or "").strip() or None
        if not force:
            dups = await self.repo.possible_duplicates(tenant, amount, received_on, body.get("payer_name"), utr)
            if dups:
                return {"duplicate_warning": dups}
        cust = body.get("customer_id") or None
        if cust and not await self.repo.get_customer(tenant, cust):
            raise ServiceError(404, "Customer not found")
        row = {"received_on": received_on, "amount": amount, "method": body.get("method"),
               "reference": body.get("reference"), "utr": utr, "payer_name": body.get("payer_name"),
               "narration": body.get("narration") or body.get("note"), "customer_id": cust}
        async with self.repo.pool.acquire() as c:
            async with c.transaction():
                new = await self.repo.insert_payments(c, tenant, [row], source="manual", source_file=None,
                                                      bank_account=body.get("bank_account"), actor=actor)
                pid = new[0][0]  # manual rows carry no fingerprint, so they always insert
                await self.repo.event(c, tenant, "payment", pid, "recorded", actor, {"amount": str(amount)})
        # Matched now rather than via the queue: the person is waiting on this screen.
        await self.run_match(tenant, pid)
        return {"payment_id": pid}

    # ── remittance ─────────────────────────────────────────────────────────────

    async def add_remittance(self, tenant: str, *, data: dict, source: str, raw_text: str | None,
                             source_file: str | None, storage_ref: str | None, actor: str | None) -> dict:
        policy = await self.repo.settings(tenant)
        total = Decimal(str(data["total_amount"])) if data.get("total_amount") is not None else None
        pid = await self.repo.payment_for_remittance(tenant, data.get("payment_reference"), total,
                                                     data.get("payment_date"), policy.amount_tolerance,
                                                     data.get("payer_name"))
        async with self.repo.pool.acquire() as c:
            async with c.transaction():
                rid = await self.repo.insert_remittance(c, tenant, data, source=source, source_file=source_file,
                                                        storage_ref=storage_ref, raw_text=raw_text, actor=actor)
                await self.repo.event(c, tenant, "remittance", rid, "received", actor,
                                      {"lines": len(data.get("lines") or []), "linked_payment": pid})
                if pid:
                    await self.repo.link_remittance(c, tenant, rid, pid)
                    p = await self.repo.get_payment(tenant, pid, c)
                    if p["status"] in PaymentStatus.MATCHABLE:
                        await self.repo.enqueue(c, tenant, [pid], JobReason.REMITTANCE)
                    elif p["status"] == PaymentStatus.APPLIED:
                        # G2: never overrule an application silently; flag if they disagree.
                        apps = await self.repo.applications_for_payment(tenant, pid)
                        applied = {norm_name(a["invoice_number"]) for a in apps if not a["reversed_at"]}
                        named = {norm_name(ln["invoice_number"]) for ln in data.get("lines") or []
                                 if (ln.get("amount_paid") or 0) > 0}
                        if named and named != applied:
                            await self.repo.flag_payment(c, tenant, pid, "REMITTANCE_DISAGREES")
                elif total is not None:
                    # Not linkable on arrival (no UTR hit, or the amount fits several): let the
                    # waiting payments of about this amount re-match — each looks for an
                    # unlinked remittance that fits it alone (edge case C4).
                    near = await self.repo.matchable_near_amount(tenant, total, policy.amount_tolerance)
                    await self.repo.enqueue(c, tenant, near, JobReason.REMITTANCE)
        return {"remittance_id": rid, "payment_id": pid}

    # ── matching ───────────────────────────────────────────────────────────────

    async def drain(self, tenant: str, payment_ids: list[str], limit: int = 500) -> int:
        """Match the payments an upload just queued, right away, in this process.

        Runs as a background task after the response, so a statement, remittance,
        invoice or alias is acted on within seconds whether or not the CashAppWorker
        is running. Scoped to these payments and claimed with SKIP LOCKED, so it
        never races the worker or touches other tenants' jobs; anything left over
        (past `limit`, or failed) stays queued for the worker.
        """
        ids = list(dict.fromkeys(payment_ids))[:limit]
        done = 0
        while ids:
            jobs = await self.repo.claim_jobs_for(tenant, ids, 50)
            if not jobs:
                break
            for j in jobs:
                try:
                    await self.run_match(tenant, j["payment_id"], allow_auto=j["reason"] != JobReason.UNAPPLIED)
                    await self.repo.finish_job(j["id"])
                except ServiceError:
                    await self.repo.finish_job(j["id"])
                except Exception as e:  # noqa: BLE001 — leave it to the worker's retries
                    log.exception("[ar] inline match of %s failed", j["payment_id"])
                    await self.repo.fail_job(j["id"], j["attempts"], f"{type(e).__name__}: {e}")
                done += 1
        return done


    async def run_match(self, tenant: str, payment_id: str, *, allow_auto: bool = True) -> dict:
        """Recompute the agent's view of one payment; apply it if policy allows."""
        repo = self.repo
        p = await repo.get_payment(tenant, payment_id)
        if not p:
            raise ServiceError(404, "Payment not found")
        if p["status"] not in PaymentStatus.MATCHABLE:
            return {"status": p["status"], "skipped": True}
        policy = await repo.settings(tenant)
        cfg = MatchConfig(tolerance=policy.amount_tolerance, tds_rates=policy.tds_rates)
        remaining = _d(p["amount"]) - _d(p["applied_amount"])
        if remaining <= 0:
            return {"status": p["status"], "skipped": True}

        text = " ".join(filter(None, [p.get("narration"), p.get("reference")]))
        remit = await repo.remittance_for_payment(tenant, p, policy.amount_tolerance)
        lines = [RemittanceLine(str(ln["invoice_number"]), _d(ln["amount_paid"]), _d(ln.get("deduction_amount") or 0),
                                ln.get("deduction_reason")) for ln in (remit or {}).get("lines") or []]

        invoices: dict[str, OpenInvoice] = {}
        for inv in await repo.invoices_by_tokens(tenant, token_windows(text)):
            invoices[inv.id] = inv
        if lines:
            for inv in await repo.invoices_by_numbers(tenant, [ln.invoice_number for ln in lines],
                                                      str(p["customer_id"]) if p["customer_id"] else None):
                invoices[inv.id] = inv
        pay = Payment(remaining, p["received_on"], p.get("payer_name") or (remit or {}).get("payer_name"),
                      p.get("narration"), p.get("reference"),
                      str(p["customer_id"]) if p["customer_id"] else None)
        customers = await repo.customers_for_match(
            tenant, pay.payer_name, pay.narration,
            {i.customer_id for i in invoices.values()} | ({pay.customer_id} if pay.customer_id else set()))
        cid, _, _, _ = identify_customer(pay, customers, list(invoices.values()))
        paid: list[OpenInvoice] = []
        if cid:
            for inv in await repo.open_invoices(tenant, cid):
                invoices[inv.id] = inv
            paid = await repo.paid_invoices(tenant, cid)
        else:
            for inv in await repo.invoices_near_amount(tenant, remaining, policy.amount_tolerance):
                invoices[inv.id] = inv

        result = match_payment(pay, customers, list(invoices.values()), lines or None, cfg=cfg, paid_invoices=paid)
        hint = next((c.tds_rate_hint for c in customers if c.id == result.customer_id), None)
        decision = decide(result, policy, customer_tds_hint=hint)
        # A person already took an application off this payment: never put it back alone.
        if allow_auto and await repo.pool.fetchval(
                "SELECT 1 FROM ar_applications WHERE payment_id = $1::uuid AND tenant_id = $2::uuid "
                "AND reversed_at IS NOT NULL LIMIT 1", payment_id, tenant):
            allow_auto = False
        suggestion = {**result.to_json(), "decision": {"action": decision.action, "reason": decision.reason},
                      "customer_name": next((c.name for c in customers if c.id == result.customer_id), None),
                      "remittance_id": str(remit["id"]) if remit else None}
        status = (p["status"] if p["status"] == PaymentStatus.PARTIALLY_APPLIED
                  else PaymentStatus.NEEDS_REVIEW if result.best else PaymentStatus.UNMATCHED)
        async with repo.pool.acquire() as c:
            async with c.transaction():
                await repo.save_match(c, tenant, payment_id, status=status, suggestion=suggestion,
                                      confidence=result.best.confidence if result.best else None,
                                      flags=result.flags)
                await repo.event(c, tenant, "payment", payment_id, "matched", AGENT,
                                 {"kind": result.best.kind if result.best else None,
                                  "confidence": str(result.best.confidence) if result.best else None,
                                  "decision": decision.action, "flags": result.flags})
        if decision.action == "AUTO" and allow_auto:
            allocs = [a.__dict__ for a in result.best.allocations]
            await self.apply(tenant, payment_id, allocs, version=None, method=Method.AUTO, actor=AGENT,
                             customer_id=result.best.customer_id, kind=result.best.kind,
                             confidence=result.best.confidence)
            return {"status": PaymentStatus.APPLIED, "auto_applied": True, "suggestion": suggestion}
        return {"status": status, "auto_applied": False, "suggestion": suggestion}

    # ── application ────────────────────────────────────────────────────────────

    async def apply(self, tenant: str, payment_id: str, allocations: list[dict], *, version: int | None,
                    method: str, actor: str | None, customer_id: str | None = None, kind: str | None = None,
                    confidence: Decimal | None = None, allow_disputed: bool = False) -> dict:
        """Apply cash to invoices — the money invariants of 02_LLD.md §6.6, in one transaction."""
        if not allocations:
            raise ServiceError(422, "Nothing to apply")
        repo = self.repo
        policy = await repo.settings(tenant)
        tol = policy.amount_tolerance
        new_alias = False
        async with repo.pool.acquire() as c:
            async with c.transaction():
                p = await repo.get_payment(tenant, payment_id, c, lock=True)
                if not p:
                    raise ServiceError(404, "Payment not found")
                if version is not None and p["version"] != version:
                    raise ServiceError(409, "This payment changed since you opened it — reload and try again")
                if p["status"] in (PaymentStatus.NOT_RECEIPT, PaymentStatus.REVERSED, PaymentStatus.APPLIED):
                    raise ServiceError(409, f"A payment that is {p['status'].replace('_', ' ')} can't be applied")
                if method == Method.AUTO and p["status"] not in PaymentStatus.MATCHABLE:
                    raise ServiceError(409, "Payment is no longer waiting for the agent")
                remaining = _d(p["amount"]) - _d(p["applied_amount"])
                rows = []
                for a in allocations:
                    rows.append({"invoice_id": str(a["invoice_id"]), "applied": _d(a.get("amount_applied")),
                                 "tds": _d(a.get("tds_amount") or 0), "ded": _d(a.get("deduction_amount") or 0),
                                 "code": a.get("reason_code") or ("TDS" if _d(a.get("tds_amount") or 0) else None),
                                 "note": a.get("reason_note")})
                if any(r["applied"] < 0 or r["tds"] < 0 or r["ded"] < 0 for r in rows):
                    raise ServiceError(422, "Amounts can't be negative")
                if any(r["ded"] > 0 and not r["code"] for r in rows):
                    raise ServiceError(422, "Every deduction needs a reason")
                total = sum((r["applied"] for r in rows), ZERO)
                if total > remaining + CENT:
                    raise ServiceError(422, f"Applying {total} but only {remaining} of this payment is left")
                if total <= 0 and not any(r["tds"] or r["ded"] for r in rows):
                    raise ServiceError(422, "Nothing to apply")
                ids = sorted({r["invoice_id"] for r in rows})
                invs = {str(r["id"]): dict(r) for r in await c.fetch(
                    "SELECT id, invoice_number, customer_id, status, outstanding, taxable_amount, amount_received, "
                    "tds_amount, deduction_amount FROM ar_invoices WHERE tenant_id = $1::uuid AND id = ANY($2::uuid[]) "
                    "ORDER BY id FOR UPDATE", tenant, ids)}
                if len(invs) != len(ids):
                    raise ServiceError(404, "One of the invoices was not found")
                allowed = set(InvoiceStatus.APPLICABLE) | ({InvoiceStatus.DISPUTED} if allow_disputed else set())
                left = {k: _d(v["outstanding"]) for k, v in invs.items()}
                for r in rows:
                    inv = invs[r["invoice_id"]]
                    if inv["status"] not in allowed:
                        raise ServiceError(409, f"Invoice {inv['invoice_number']} is {inv['status'].replace('_', ' ')}")
                    need = r["applied"] + r["tds"] + r["ded"]
                    if need > left[r["invoice_id"]] + tol:
                        raise ServiceError(422, f"{inv['invoice_number']} only has {left[r['invoice_id']]} outstanding")
                    left[r["invoice_id"]] -= need
                # Settled to within tolerance: the paise go on record as a ROUNDING deduction
                # on that invoice's last line, so the invoice reads paid and the trail says why.
                for iid, rest in left.items():
                    if ZERO < rest <= tol:
                        last = [r for r in rows if r["invoice_id"] == iid][-1]
                        last["ded"] += rest
                        last["code"] = last["code"] or "ROUNDING"
                        left[iid] = ZERO
                custs = {str(v["customer_id"]) for v in invs.values()}
                cust = customer_id or (str(p["customer_id"]) if p["customer_id"] else None) or (
                    next(iter(custs)) if len(custs) == 1 else None)

                for r in rows:
                    await c.execute(
                        """INSERT INTO ar_applications (tenant_id, payment_id, invoice_id, amount_applied, tds_amount,
                                   deduction_amount, reason_code, reason_note, method, kind, confidence, applied_by)
                           VALUES ($1::uuid, $2::uuid, $3::uuid, $4, $5, $6, $7, $8, $9, $10, $11, $12)""",
                        tenant, payment_id, r["invoice_id"], r["applied"], r["tds"], r["ded"], r["code"], r["note"],
                        method, kind, confidence, actor)
                for iid in ids:
                    sub = [r for r in rows if r["invoice_id"] == iid]
                    settled = left[iid] <= CENT
                    await c.execute(
                        """UPDATE ar_invoices SET
                                  amount_received = amount_received + $3,
                                  tds_amount = tds_amount + $4,
                                  deduction_amount = deduction_amount + $5,
                                  status = CASE WHEN $6 THEN 'paid'
                                                WHEN status = 'disputed' THEN status ELSE 'partially_paid' END,
                                  paid_at = CASE WHEN $6 THEN now() ELSE paid_at END,
                                  updated_at = now()
                            WHERE id = $1::uuid AND tenant_id = $2::uuid""",
                        iid, tenant, sum((r["applied"] for r in sub), ZERO), sum((r["tds"] for r in sub), ZERO),
                        sum((r["ded"] for r in sub), ZERO), settled)
                left_on_payment = remaining - total
                status = PaymentStatus.APPLIED if left_on_payment <= CENT else PaymentStatus.PARTIALLY_APPLIED
                first = _d(p["applied_amount"]) == 0
                await c.execute(
                    """UPDATE ar_payments SET applied_amount = applied_amount + $3, status = $4,
                              customer_id = COALESCE($5::uuid, customer_id),
                              auto_applied = CASE WHEN $6 THEN $7 ELSE auto_applied END,
                              applied_at = now(), applied_by = $8, version = version + 1,
                              flags = array_remove(array_remove(flags, 'REMITTANCE_DISAGREES'), 'POSSIBLE_BOUNCE')
                        WHERE id = $1::uuid AND tenant_id = $2::uuid""",
                    payment_id, tenant, total, status, cust, first, method == Method.AUTO, actor)
                await repo.event(c, tenant, "payment", payment_id, "applied", actor,
                                 {"method": method, "kind": kind, "total": str(total),
                                  "allocations": [{**r, "applied": str(r["applied"]), "tds": str(r["tds"]),
                                                   "ded": str(r["ded"])} for r in rows]})

                # Learning (02_LLD.md §6.7): only from a person's decision, never from the agent's own.
                if method != Method.AUTO and cust and len(custs) == 1:
                    if p.get("payer_name"):
                        new_alias = await repo.add_alias(c, tenant, cust, p["payer_name"], "learned")
                    tds_rows = [(r, invs[r["invoice_id"]]) for r in rows if r["tds"] and invs[r["invoice_id"]]["taxable_amount"]]
                    if tds_rows:
                        r, inv = tds_rows[0]
                        rate = (r["tds"] / _d(inv["taxable_amount"]) * 100).quantize(Decimal("0.1"))
                        await c.execute("UPDATE ar_customers SET tds_rate_hint = $3, updated_at = now() "
                                        "WHERE id = $1::uuid AND tenant_id = $2::uuid", cust, tenant, rate)
                # The customer's balances just moved: their other waiting payments may have
                # been suggested against an invoice this payment has now settled (two equal
                # invoices, two equal payments) — re-match them against the ledger as it is.
                if cust:
                    stale = [x for x in await repo.waiting_for_customer(tenant, cust) if x != payment_id]
                    await repo.enqueue(c, tenant, stale, JobReason.LEDGER_CHANGED)
                if new_alias:
                    # The same payer's other waiting payments can now be identified.
                    others = [str(r["id"]) for r in await c.fetch(
                        "SELECT id FROM ar_payments WHERE tenant_id = $1::uuid AND id <> $2::uuid "
                        "AND status IN ('unmatched','needs_review') AND upper(payer_name) = upper($3) LIMIT 200",
                        tenant, payment_id, p["payer_name"])]
                    await repo.enqueue(c, tenant, others, JobReason.ALIAS_LEARNED)
        return {"status": status, "applied": str(total), "left_on_account": str(max(ZERO, left_on_payment))}

    async def unapply(self, tenant: str, payment_id: str, reason: str, actor: str | None, *,
                      to_status: str = PaymentStatus.UNMATCHED, requeue: bool = True) -> dict:
        """Reverse every live application (G3). Append-only: rows are marked, never deleted."""
        if not (reason or "").strip():
            raise ServiceError(422, "A reason is required")
        repo = self.repo
        async with repo.pool.acquire() as c:
            async with c.transaction():
                p = await repo.get_payment(tenant, payment_id, c, lock=True)
                if not p:
                    raise ServiceError(404, "Payment not found")
                apps = await c.fetch(
                    "SELECT id, invoice_id, amount_applied, tds_amount, deduction_amount FROM ar_applications "
                    "WHERE payment_id = $1::uuid AND tenant_id = $2::uuid AND reversed_at IS NULL ORDER BY invoice_id",
                    payment_id, tenant)
                for a in apps:
                    await c.execute(
                        """UPDATE ar_invoices SET amount_received = amount_received - $3, tds_amount = tds_amount - $4,
                                  deduction_amount = GREATEST(0, deduction_amount - $5), paid_at = NULL,
                                  status = CASE WHEN status IN ('disputed','void','written_off') THEN status
                                                WHEN amount_received - $3 <= 0 AND tds_amount - $4 <= 0 THEN 'open'
                                                ELSE 'partially_paid' END,
                                  updated_at = now()
                            WHERE id = $1::uuid AND tenant_id = $2::uuid""",
                        str(a["invoice_id"]), tenant, a["amount_applied"], a["tds_amount"], a["deduction_amount"])
                await c.execute("UPDATE ar_applications SET reversed_at = now(), reversed_by = $3 "
                                "WHERE payment_id = $1::uuid AND tenant_id = $2::uuid AND reversed_at IS NULL",
                                payment_id, tenant, actor)
                await c.execute(
                    """UPDATE ar_payments SET applied_amount = 0, status = $3, auto_applied = false, applied_at = NULL,
                              applied_by = NULL, version = version + 1, note = $4
                        WHERE id = $1::uuid AND tenant_id = $2::uuid""", payment_id, tenant, to_status, reason)
                await repo.event(c, tenant, "payment", payment_id, "unapplied", actor,
                                 {"reason": reason, "applications": len(apps), "to": to_status})
                if requeue and to_status == PaymentStatus.UNMATCHED:
                    await repo.enqueue(c, tenant, [payment_id], JobReason.UNAPPLIED)
                if p["customer_id"]:   # reopened invoices may explain other waiting payments
                    stale = [x for x in await repo.waiting_for_customer(tenant, str(p["customer_id"]))
                             if x != payment_id]
                    await repo.enqueue(c, tenant, stale, JobReason.LEDGER_CHANGED)
        return {"status": to_status, "reversed": len(apps)}

    async def set_status(self, tenant: str, payment_id: str, *, action: str, actor: str | None,
                         reason_code: str | None = None, note: str | None = None) -> dict:
        """exception | resolve | not_receipt | restore | reverse (bounce confirmed)."""
        repo = self.repo
        p = await repo.get_payment(tenant, payment_id)
        if not p:
            raise ServiceError(404, "Payment not found")
        if action == "reverse":
            return await self.unapply(tenant, payment_id, note or "Bounced / recalled", actor,
                                      to_status=PaymentStatus.REVERSED, requeue=False)
        transitions = {
            "exception": (PaymentStatus.MATCHABLE, PaymentStatus.EXCEPTION, False),
            "resolve": ((PaymentStatus.EXCEPTION,), PaymentStatus.UNMATCHED, True),
            "not_receipt": ((PaymentStatus.UNMATCHED, PaymentStatus.NEEDS_REVIEW, PaymentStatus.EXCEPTION),
                            PaymentStatus.NOT_RECEIPT, False),
            "restore": ((PaymentStatus.NOT_RECEIPT,), PaymentStatus.UNMATCHED, True),
        }
        if action not in transitions:
            raise ServiceError(422, "Unknown action")
        allowed, to, requeue = transitions[action]
        if p["status"] not in allowed:
            raise ServiceError(409, f"Can't {action.replace('_', ' ')} a payment that is {p['status'].replace('_', ' ')}")
        if action == "exception" and not reason_code:
            raise ServiceError(422, "Pick a reason")
        async with repo.pool.acquire() as c:
            async with c.transaction():
                await c.execute(
                    "UPDATE ar_payments SET status = $3, reason_code = $4, note = COALESCE($5, note), "
                    "version = version + 1 WHERE id = $1::uuid AND tenant_id = $2::uuid",
                    payment_id, tenant, to, reason_code if action == "exception" else None, note)
                await repo.event(c, tenant, "payment", payment_id, action, actor,
                                 {"reason_code": reason_code, "note": note, "from": p["status"]})
                if requeue:
                    await repo.enqueue(c, tenant, [payment_id], JobReason.RESOLVED)
        return {"status": to}

    async def choose_customer(self, tenant: str, payment_id: str, customer_id: str | None, actor: str | None) -> dict:
        """A person says who paid (or clears it); re-matched straight away."""
        if customer_id and not await self.repo.get_customer(tenant, customer_id):
            raise ServiceError(404, "Customer not found")
        async with self.repo.pool.acquire() as c:
            async with c.transaction():
                r = await c.execute(
                    "UPDATE ar_payments SET customer_id = $3::uuid, version = version + 1 "
                    "WHERE id = $1::uuid AND tenant_id = $2::uuid AND applied_amount = 0",
                    payment_id, tenant, customer_id)
                if r.endswith("0"):
                    raise ServiceError(409, "Unapply this payment before changing its customer")
                await self.repo.event(c, tenant, "payment", payment_id, "customer_chosen", actor,
                                      {"customer_id": customer_id})
        return await self.run_match(tenant, payment_id)
