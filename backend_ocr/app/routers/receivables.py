"""Receivables API — sales invoices, customers, incoming payments and the cash
application agent (docs/receivables/02_LLD.md §8).

Every route resolves the tenant from the JWT; records of another tenant 404.
Mounted behind require_service("receivables").

Roles: receivables share the payables role model and approval chain — there is no
separate receivables chain (decision 2026-11-17). Capturing (upload, import,
record, remittance) needs a role that can initiate payables; applying cash,
unapplying and parking exceptions need a role with accounting approval; settings
are admin-only.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from ..receivables.policy import Policy
from ..receivables.repo import CashAppRepository
from ..receivables.service import CashApplicationService, ServiceError
from ..receivables.types import ExceptionCode, InvoiceStatus, Method, PaymentStatus, ReasonCode
from ..security.auth import current_username, require_role, require_tenant

router = APIRouter()

# Same roles as the payable equivalents (frontend/src/auth/permissions.ts).
CAPTURE_ROLES = ("admin", "finance_controller", "accountant", "approver", "member")     # payables.initiate
POSTING_ROLES = ("admin", "finance_controller", "accountant")                           # payables.accounting_approval

MAX_UPLOAD = 20 * 1024 * 1024


async def _svc() -> CashApplicationService:
    from db import get_pool
    return CashApplicationService(CashAppRepository(await get_pool()))


def _j(v):
    """JSON-safe: Decimal → str, dates → ISO, UUID → str."""
    if isinstance(v, dict):
        return {k: _j(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_j(x) for x in v]
    if isinstance(v, Decimal):
        return str(v)
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    if isinstance(v, uuid.UUID):
        return str(v)
    return v


def _uuid(v: str | None, what: str) -> str | None:
    if v is None or v == "":
        return None
    try:
        return str(uuid.UUID(v))
    except ValueError:
        raise HTTPException(404, f"{what} not found")


def _kick(bg: BackgroundTasks, svc: CashApplicationService, tenant: str) -> None:
    """Match whatever this request queued, straight after the response (service.drain).
    Every upload re-runs the agent on the payments it can affect — no worker needed."""
    if svc.repo.enqueued:
        bg.add_task(svc.drain, tenant, list(svc.repo.enqueued))


def _err(e: ServiceError):
    raise HTTPException(e.status, e.message)


def _statuses(raw: str | None, allowed) -> list[str] | None:
    if not raw:
        return None
    out = [s for s in raw.split(",") if s in allowed]
    return out or None


# ── summary + settings ────────────────────────────────────────────────────────

@router.get("/api/ar/summary")
async def ar_summary(days: int = Query(30, ge=1, le=365)):
    tenant = require_tenant()
    svc = await _svc()
    s = await svc.repo.summary(tenant, days)
    p = s["payments"]
    receipts = p["receipts"] or 0
    total = p["receipts_total"] or Decimal(0)
    billed = s["ar"]["billed_90"] or Decimal(0)
    kpis = {
        "match_rate": round(p["auto_count"] / receipts, 4) if receipts else None,
        "exception_rate": round((receipts - p["auto_count"]) / receipts, 4) if receipts else None,
        "applied_cash_pct": round(float(p["applied_total"] / total), 4) if total else None,
        "hours_to_apply": round(float(p["hours_to_apply"]), 3) if p["hours_to_apply"] is not None else None,
        "dso": round(float(s["ar"]["open_ar"] / billed * 90), 1) if billed else None,
        "suggestion_acceptance": (round(s["reviewed"]["accepted"] / s["reviewed"]["human"], 4)
                                  if s["reviewed"]["human"] else None),
        "dso_previous": (round(float(s["previous"]["open_ar"] / s["previous"]["billed_90"] * 90), 1)
                         if s["previous"]["billed_90"] else None),
    }
    return _j({"days": days, "kpis": kpis, **s})


class SettingsBody(BaseModel):
    auto_apply_enabled: bool
    auto_apply_threshold: Decimal = Field(ge=Decimal("0.5"), le=Decimal("1"))
    amount_tolerance: Decimal = Field(ge=0, le=100)
    writeoff_tolerance: Decimal = Field(ge=0, le=10000)
    tds_rates: list[Decimal]
    trust_learned_tds: bool


@router.get("/api/ar/settings")
async def ar_get_settings():
    tenant = require_tenant()
    return (await (await _svc()).repo.settings(tenant)).to_json()


@router.put("/api/ar/settings")
async def ar_put_settings(body: SettingsBody):
    tenant = require_tenant()
    require_role("admin")
    rates = tuple(sorted({r for r in body.tds_rates if Decimal("0") < r <= Decimal("30")}))
    p = Policy(body.auto_apply_enabled, body.auto_apply_threshold, body.amount_tolerance,
               body.writeoff_tolerance, rates or Policy().tds_rates, body.trust_learned_tds)
    await (await _svc()).repo.save_settings(tenant, p, current_username())
    return p.to_json()


# ── invoices ─────────────────────────────────────────────────────────────────

class IngestBody(BaseModel):
    payload: dict


@router.post("/api/ar/invoices/ingest")
async def ar_ingest_invoice(body: IngestBody, bg: BackgroundTasks):
    tenant = require_tenant()
    require_role(*CAPTURE_ROLES)
    # The PDF was written to the shared upload area by /api/invoices/ocr; keep it
    # in the object store against this invoice (never public — see the document route).
    from ..core.storage import UPLOADS_DIR
    src = Path(str(body.payload.get("_source_file") or "")).name
    data = None
    if src:
        path = UPLOADS_DIR / src
        if path.is_file() and path.stat().st_size <= MAX_UPLOAD:
            data = path.read_bytes()
    try:
        svc = await _svc()
        out = await svc.ingest_invoice(tenant, body.payload, current_username(), data, src or None)
        _kick(bg, svc, tenant)
        return out
    except ServiceError as e:
        _err(e)


@router.get("/api/ar/invoices")
async def ar_list_invoices(status: str | None = None, customer_id: str | None = None, q: str | None = None,
                           overdue: bool = False, limit: int = Query(50, ge=1, le=500),
                           offset: int = Query(0, ge=0)):
    tenant = require_tenant()
    rows, total = await (await _svc()).repo.list_invoices(
        tenant, _statuses(status, InvoiceStatus.ALL), _uuid(customer_id, "Customer"), q, overdue, limit, offset)
    return _j({"items": rows, "total": total})


@router.get("/api/ar/invoices/{invoice_id}")
async def ar_get_invoice(invoice_id: str):
    tenant = require_tenant()
    inv = await (await _svc()).repo.get_invoice(tenant, _uuid(invoice_id, "Invoice"))
    if not inv:
        raise HTTPException(404, "Invoice not found")
    inv["has_document"] = bool(inv.pop("storage_ref", None))
    return _j(inv)


class InvoiceStatusBody(BaseModel):
    status: str
    note: str | None = None


@router.patch("/api/ar/invoices/{invoice_id}")
async def ar_set_invoice_status(invoice_id: str, body: InvoiceStatusBody):
    """Put on hold (disputed), release (open) or void. Paid/part-paid states come only from applications."""
    tenant = require_tenant()
    require_role(*POSTING_ROLES)
    if body.status not in (InvoiceStatus.DISPUTED, InvoiceStatus.OPEN, InvoiceStatus.VOID):
        raise HTTPException(422, "Status can be disputed, open or void")
    svc = await _svc()
    iid = _uuid(invoice_id, "Invoice")
    inv = await svc.repo.get_invoice(tenant, iid)
    if not inv:
        raise HTTPException(404, "Invoice not found")
    if body.status == InvoiceStatus.VOID and any(not a["reversed_at"] for a in inv["applications"]):
        raise HTTPException(409, "Unapply the payments on this invoice before voiding it")
    if body.status == InvoiceStatus.OPEN and inv["status"] not in (InvoiceStatus.DISPUTED,):
        raise HTTPException(409, "Only a disputed invoice can be released")
    if body.status == InvoiceStatus.OPEN and (inv["amount_received"] or inv["tds_amount"]):
        body.status = InvoiceStatus.PARTIALLY_PAID
    await svc.repo.set_invoice_status(tenant, iid, body.status, current_username(), body.note)
    return {"status": body.status}


@router.get("/api/ar/invoices/{invoice_id}/document")
async def ar_invoice_document(invoice_id: str, signed: bool = False):
    """The invoice PDF. Tenant-checked; with ?signed=1 a 5-minute signed link (never a public URL)."""
    tenant = require_tenant()
    ref, name = await (await _svc()).repo.invoice_document_ref(tenant, _uuid(invoice_id, "Invoice"))
    return _serve(ref, name or "invoice.pdf", "application/pdf", signed)


def _serve(ref: str | None, name: str | None, media_type: str, signed: bool, inline: bool = True):
    """A stored document: tenant already checked by the caller. With ?signed=1 and S3, a
    5-minute signed link; otherwise streamed through the API. Never a public URL."""
    if not ref:
        raise HTTPException(404, "No document stored")
    from ..core import object_store
    if signed and object_store.is_s3(ref):
        resp = object_store.signed_link_response(ref)
        if resp is not None:
            return resp
    data = object_store.load(ref)
    if data is None:
        raise HTTPException(404, "Document not found")
    disp = "inline" if inline else "attachment"
    safe = (name or "document").replace('"', "")
    return Response(data, media_type=media_type,
                    headers={"Cache-Control": "no-store", "Content-Disposition": f'{disp}; filename="{safe}"'})


# ── customers ────────────────────────────────────────────────────────────────

@router.get("/api/ar/customers")
async def ar_list_customers(q: str | None = None, limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0)):
    tenant = require_tenant()
    rows, total = await (await _svc()).repo.list_customers(tenant, q, limit, offset)
    return _j({"items": rows, "total": total})


class CustomerBody(BaseModel):
    name: str
    gstin: str | None = None
    pan: str | None = None
    email: str | None = None
    phone: str | None = None
    address: str | None = None
    payment_terms_days: int | None = None


@router.post("/api/ar/customers")
async def ar_create_customer(body: CustomerBody):
    tenant = require_tenant()
    require_role(*CAPTURE_ROLES)
    if not body.name.strip():
        raise HTTPException(422, "Name is required")
    svc = await _svc()
    async with svc.repo.pool.acquire() as c:
        async with c.transaction():
            cid, created = await svc.repo.find_or_create_customer(
                c, tenant, name=body.name.strip(), gstin=(body.gstin or "").strip().upper() or None,
                pan=(body.pan or "").strip().upper() or None, address=body.address, email=body.email,
                phone=body.phone, terms_days=body.payment_terms_days)
            await svc.repo.event(c, tenant, "customer", cid, "created" if created else "matched_existing",
                                 current_username())
    return {"customer_id": cid, "created": created}


@router.get("/api/ar/customers/{customer_id}")
async def ar_get_customer(customer_id: str):
    tenant = require_tenant()
    svc = await _svc()
    cid = _uuid(customer_id, "Customer")
    cust = await svc.repo.get_customer(tenant, cid)
    if not cust:
        raise HTTPException(404, "Customer not found")
    invoices, _ = await svc.repo.list_invoices(tenant, None, cid, None, False, 200, 0)
    payments, _ = await svc.repo.list_payments(tenant, None, cid, None, 100, 0)
    return _j({**cust, "invoices": invoices, "payments": payments})


class CustomerPatch(BaseModel):
    name: str | None = None
    gstin: str | None = None
    pan: str | None = None
    email: str | None = None
    phone: str | None = None
    address: str | None = None
    payment_terms_days: int | None = None
    tds_rate_hint: Decimal | None = None


@router.patch("/api/ar/customers/{customer_id}")
async def ar_update_customer(customer_id: str, body: CustomerPatch):
    tenant = require_tenant()
    require_role(*POSTING_ROLES)
    svc = await _svc()
    cid = _uuid(customer_id, "Customer")
    if not await svc.repo.get_customer(tenant, cid):
        raise HTTPException(404, "Customer not found")
    await svc.repo.update_customer(tenant, cid, body.model_dump(exclude_unset=True), current_username())
    return {"ok": True}


class AliasBody(BaseModel):
    alias: str


@router.post("/api/ar/customers/{customer_id}/aliases")
async def ar_add_alias(customer_id: str, body: AliasBody, bg: BackgroundTasks):
    tenant = require_tenant()
    require_role(*POSTING_ROLES)
    svc = await _svc()
    cid = _uuid(customer_id, "Customer")
    if not await svc.repo.get_customer(tenant, cid):
        raise HTTPException(404, "Customer not found")
    async with svc.repo.pool.acquire() as c:
        async with c.transaction():
            if not await svc.repo.add_alias(c, tenant, cid, body.alias, "manual") and len(body.alias.strip()) < 3:
                raise HTTPException(422, "Payer name is too short")
            await svc.repo.event(c, tenant, "customer", cid, "alias_added", current_username(), {"alias": body.alias})
            pids = await svc.repo.unmatched_for_customer(tenant, None, 200)
            await svc.repo.enqueue(c, tenant, pids, "alias_learned")
    _kick(bg, svc, tenant)
    return {"ok": True}


@router.delete("/api/ar/customers/{customer_id}/aliases/{alias_id}")
async def ar_remove_alias(customer_id: str, alias_id: str):
    tenant = require_tenant()
    require_role(*POSTING_ROLES)
    await (await _svc()).repo.remove_alias(tenant, _uuid(customer_id, "Customer"), _uuid(alias_id, "Alias"))
    return {"ok": True}


# ── payments ─────────────────────────────────────────────────────────────────

@router.get("/api/ar/payments")
async def ar_list_payments(status: str | None = None, customer_id: str | None = None, q: str | None = None,
                           limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0)):
    tenant = require_tenant()
    svc = await _svc()
    rows, total = await svc.repo.list_payments(tenant, _statuses(status, PaymentStatus.ALL),
                                               _uuid(customer_id, "Customer"), q, limit, offset)
    return _j({"items": rows, "total": total, "counts": await svc.repo.status_counts(tenant)})


@router.get("/api/ar/review-board")
async def ar_review_board(status: str | None = "needs_review", q: str | None = None,
                          limit: int = Query(200, ge=1, le=500)):
    """Payments waiting on a person, grouped by customer with that customer's open invoices."""
    tenant = require_tenant()
    svc = await _svc()
    st = _statuses(status, PaymentStatus.ALL) or ["needs_review"]
    return _j({"groups": await svc.repo.review_board(tenant, st, q, limit)})


class PaymentBody(BaseModel):
    received_on: date
    amount: Decimal = Field(gt=0)
    method: str | None = None
    reference: str | None = None
    utr: str | None = None
    payer_name: str | None = None
    customer_id: str | None = None
    narration: str | None = None
    bank_account: str | None = None
    force: bool = False


@router.post("/api/ar/payments")
async def ar_record_payment(body: PaymentBody):
    tenant = require_tenant()
    require_role(*CAPTURE_ROLES)
    d = body.model_dump()
    d["customer_id"] = _uuid(body.customer_id, "Customer")
    try:
        return _j(await (await _svc()).record_payment(tenant, d, current_username(), force=body.force))
    except ServiceError as e:
        _err(e)


@router.post("/api/ar/payments/import")
async def ar_import_statement(request: Request, bg: BackgroundTasks):
    tenant = require_tenant()
    require_role(*CAPTURE_ROLES)
    async with request.form() as form:
        f = form.get("file")
        bank_account = str(form.get("bank_account") or "") or None
        if f is None or not getattr(f, "filename", None):
            raise HTTPException(422, "Attach a bank statement (PDF, CSV or XLSX)")
        name = Path(f.filename).name
        if not name.lower().endswith((".csv", ".xlsx", ".xlsm", ".txt", ".pdf")):
            raise HTTPException(400, "Upload the statement as PDF, CSV or XLSX")
        data = await f.read()
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, "Statement is larger than 20 MB — split it by month")
    try:
        svc = await _svc()
        out = await svc.import_statement(tenant, data, name, bank_account, current_username())
        _kick(bg, svc, tenant)
        return out
    except ServiceError as e:
        _err(e)


@router.get("/api/ar/payments/{payment_id}")
async def ar_get_payment(payment_id: str):
    """Everything the review workbench needs for one payment."""
    tenant = require_tenant()
    svc = await _svc()
    pid = _uuid(payment_id, "Payment")
    p = await svc.repo.get_payment(tenant, pid)
    if not p:
        raise HTTPException(404, "Payment not found")
    sug = p.get("suggestion") or {}
    cust_id = str(p["customer_id"]) if p["customer_id"] else sug.get("customer_id")
    open_invoices = []
    customer = None
    if cust_id:
        customer = await svc.repo.get_customer(tenant, cust_id)
        open_invoices, _ = await svc.repo.list_invoices(
            tenant, [InvoiceStatus.OPEN, InvoiceStatus.PARTIALLY_PAID, InvoiceStatus.DISPUTED], cust_id,
            None, False, 200, 0)
    return _j({
        "payment": p,
        "customer": {"id": customer["id"], "name": customer["name"], "gstin": customer["gstin"],
                     "tds_rate_hint": customer["tds_rate_hint"],
                     "confirmed": p["customer_id"] is not None} if customer else None,
        "open_invoices": open_invoices,
        "applications": await svc.repo.applications_for_payment(tenant, pid),
        "remittances": await svc.repo.remittances_for_payment(tenant, pid),
        "statement": await _statement_ref(svc, tenant, p.get("statement_id")),
        "events": await svc.repo.events(tenant, "payment", pid),
    })


async def _statement_ref(svc, tenant: str, statement_id) -> dict | None:
    if not statement_id:
        return None
    r = await svc.repo.pool.fetchrow(
        "SELECT id, file_name, created_at FROM ar_statements WHERE id = $1::uuid AND tenant_id = $2::uuid",
        str(statement_id), tenant)
    return dict(r) if r else None


@router.post("/api/ar/payments/{payment_id}/match")
async def ar_rematch(payment_id: str):
    tenant = require_tenant()
    require_role(*CAPTURE_ROLES)
    try:
        # A person asked: show the suggestion, never apply it behind their back.
        return _j(await (await _svc()).run_match(tenant, _uuid(payment_id, "Payment"), allow_auto=False))
    except ServiceError as e:
        _err(e)


class AllocationIn(BaseModel):
    invoice_id: str
    amount_applied: Decimal = Field(ge=0)
    tds_amount: Decimal = Field(default=Decimal(0), ge=0)
    deduction_amount: Decimal = Field(default=Decimal(0), ge=0)
    reason_code: str | None = None
    reason_note: str | None = None


class ApplyBody(BaseModel):
    allocations: list[AllocationIn]
    version: int
    customer_id: str | None = None
    # "accepted" = the agent's suggestion unchanged; "manual" = edited / built by hand.
    method: str = Method.MANUAL
    kind: str | None = None
    confidence: Decimal | None = None
    allow_disputed: bool = False


@router.post("/api/ar/payments/{payment_id}/apply")
async def ar_apply(payment_id: str, body: ApplyBody, bg: BackgroundTasks):
    tenant = require_tenant()
    require_role(*POSTING_ROLES)
    if body.method not in (Method.ACCEPTED, Method.MANUAL):
        raise HTTPException(422, "method must be accepted or manual")
    for a in body.allocations:
        _uuid(a.invoice_id, "Invoice")
        if a.reason_code and a.reason_code not in ReasonCode.ALL:
            raise HTTPException(422, f"Unknown reason {a.reason_code}")
    try:
        svc = await _svc()
        out = await svc.apply(
            tenant, _uuid(payment_id, "Payment"), [a.model_dump() for a in body.allocations],
            version=body.version, method=body.method, actor=current_username(),
            customer_id=_uuid(body.customer_id, "Customer"), kind=body.kind, confidence=body.confidence,
            allow_disputed=body.allow_disputed)
        _kick(bg, svc, tenant)   # a newly learned payer name re-checks that payer's waiting payments
        return out
    except ServiceError as e:
        _err(e)


class ReasonBody(BaseModel):
    reason: str


@router.post("/api/ar/payments/{payment_id}/unapply")
async def ar_unapply(payment_id: str, body: ReasonBody, bg: BackgroundTasks):
    tenant = require_tenant()
    require_role(*POSTING_ROLES)
    try:
        svc = await _svc()
        out = await svc.unapply(tenant, _uuid(payment_id, "Payment"), body.reason, current_username())
        _kick(bg, svc, tenant)
        return out
    except ServiceError as e:
        _err(e)


class StatusBody(BaseModel):
    action: str        # exception | resolve | not_receipt | restore | reverse
    reason_code: str | None = None
    note: str | None = None


@router.post("/api/ar/payments/{payment_id}/status")
async def ar_payment_status(payment_id: str, body: StatusBody, bg: BackgroundTasks):
    tenant = require_tenant()
    require_role(*POSTING_ROLES)
    if body.action == "exception" and body.reason_code not in ExceptionCode.ALL:
        raise HTTPException(422, "Pick a reason")
    try:
        svc = await _svc()
        out = await svc.set_status(tenant, _uuid(payment_id, "Payment"), action=body.action,
                                               actor=current_username(), reason_code=body.reason_code,
                                               note=body.note)
    except ServiceError as e:
        _err(e)
    _kick(bg, svc, tenant)
    return out


class CustomerChoice(BaseModel):
    customer_id: str | None = None


@router.post("/api/ar/payments/{payment_id}/customer")
async def ar_choose_customer(payment_id: str, body: CustomerChoice):
    tenant = require_tenant()
    require_role(*POSTING_ROLES)
    try:
        return _j(await (await _svc()).choose_customer(tenant, _uuid(payment_id, "Payment"),
                                                       _uuid(body.customer_id, "Customer"), current_username()))
    except ServiceError as e:
        _err(e)


# ── remittances ──────────────────────────────────────────────────────────────

@router.post("/api/ar/remittances")
async def ar_add_remittance(request: Request, bg: BackgroundTasks):
    """Pasted email text (`text`) or a file (`file`: PDF or photo) → structured lines, linked to a payment."""
    tenant = require_tenant()
    require_role(*CAPTURE_ROLES)
    from ..receivables import remittance
    async with request.form() as form:
        text = str(form.get("text") or "").strip()
        f = form.get("file")
        name = Path(f.filename).name if f is not None and getattr(f, "filename", None) else None
        data = await f.read() if name else None
    if not text and not data:
        raise HTTPException(422, "Paste the remittance text or attach the advice")
    storage_ref = None
    try:
        if data:
            if len(data) > MAX_UPLOAD:
                raise HTTPException(413, "File is larger than 20 MB")
            from ..integrations.ocr import as_pdf, is_invoice_file
            from ..core import object_store
            import tempfile
            if not is_invoice_file(name):
                raise HTTPException(400, "Upload a PDF or a photo (JPG, PNG, WebP)")
            pdf, name = as_pdf(data, name)
            with tempfile.NamedTemporaryFile(suffix=".pdf") as tmp:
                tmp.write(pdf)
                tmp.flush()
                parsed, raw = await remittance.read_pdf(tmp.name)
            try:
                storage_ref = object_store.save(object_store.key("ar-remittances", tenant, uuid.uuid4(), name),
                                                pdf, "application/pdf")
            except Exception:
                storage_ref = None
            source = "pdf"
        else:
            parsed, raw, source = await remittance.read_text(text), text, "text"
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, f"Couldn't read the remittance: {type(e).__name__}")
    try:
        svc = await _svc()
        out = await svc.add_remittance(tenant, data=parsed, source=source, raw_text=raw,
                                                  source_file=name, storage_ref=storage_ref,
                                                  actor=current_username())
    except ServiceError as e:
        _err(e)
    _kick(bg, svc, tenant)
    return _j({**out, "parsed": parsed})


@router.get("/api/ar/remittances")
async def ar_list_remittances(status: str | None = None, limit: int = Query(50, ge=1, le=500),
                              offset: int = Query(0, ge=0)):
    tenant = require_tenant()
    if status and status not in ("unlinked", "linked", "conflict"):
        status = None
    return _j({"items": await (await _svc()).repo.list_remittances(tenant, status, limit, offset)})


@router.get("/api/ar/remittances/{remittance_id}")
async def ar_get_remittance(remittance_id: str):
    tenant = require_tenant()
    r = await (await _svc()).repo.get_remittance(tenant, _uuid(remittance_id, "Remittance"))
    if not r:
        raise HTTPException(404, "Remittance not found")
    return _j(r)


@router.get("/api/ar/remittances/{remittance_id}/document")
async def ar_remittance_document(remittance_id: str, signed: bool = False):
    tenant = require_tenant()
    ref, name = await (await _svc()).repo.remittance_document(tenant, _uuid(remittance_id, "Remittance"))
    return _serve(ref, name, "application/pdf", signed)


# ── bank statements ──────────────────────────────────────────────────────────

@router.get("/api/ar/statements")
async def ar_list_statements(limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0)):
    tenant = require_tenant()
    return _j({"items": await (await _svc()).repo.list_statements(tenant, limit, offset)})


@router.get("/api/ar/statements/{statement_id}")
async def ar_get_statement(statement_id: str):
    """The statement as it was read — every line and what it became — plus each payment's status now."""
    tenant = require_tenant()
    st = await (await _svc()).repo.get_statement(tenant, _uuid(statement_id, "Statement"))
    if not st:
        raise HTTPException(404, "Statement not found")
    return _j(st)


_STATEMENT_TYPES = {"pdf": "application/pdf", "csv": "text/csv",
                    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}


@router.get("/api/ar/statements/{statement_id}/document")
async def ar_statement_document(statement_id: str, signed: bool = False):
    """The original file. A PDF opens inline; a spreadsheet downloads."""
    tenant = require_tenant()
    ref, name, fmt = await (await _svc()).repo.statement_document(tenant, _uuid(statement_id, "Statement"))
    return _serve(ref, name, _STATEMENT_TYPES.get(fmt or "", "application/octet-stream"), signed,
                  inline=fmt == "pdf")
