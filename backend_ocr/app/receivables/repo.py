"""CashAppRepository — every SQL statement the receivables module runs (02_LLD.md §3, §7).

asyncpg, like recon. Every query is scoped by tenant_id. Candidate retrieval is
narrow and indexed — the engine never sees a whole tenant's ledger:

  * invoices whose number / PO equals a token window of the narration
  * the identified customer's oldest open invoices (capped)
  * open invoices whose outstanding is within tolerance of the amount
  * customers by exact alias, then by trigram similarity (top 5)
"""
from __future__ import annotations

import json
import logging
from datetime import date
from decimal import Decimal

import asyncpg

from .matching import Customer, OpenInvoice, norm_name
from .policy import Policy
from .types import InvoiceStatus, PaymentStatus

log = logging.getLogger(__name__)

OPEN = ("open", "partially_paid")
MATCHABLE_INVOICE = ("open", "partially_paid", "disputed")
NOTIFY_CHANNEL = "ar_match"
# Flags the engine recomputes on every run (others — POSSIBLE_BOUNCE,
# REMITTANCE_DISAGREES — are raised by events and survive a re-match).
_ENGINE_FLAGS = ["CLUE_CONFLICT", "POSSIBLE_DUPLICATE", "AMBIGUOUS_PAYER", "CROSS_CUSTOMER", "ADVANCE",
                 "FOREIGN_CURRENCY", "DISPUTED_INVOICE", "TDS_ON_GROSS"]


def _j(v) -> str | None:
    return None if v is None else json.dumps(v, default=str)


def _rows(rs) -> list[dict]:
    return [dict(r) for r in rs]


def _payer_fits(a: str | None, b: str | None) -> bool:
    """Two payer names that could be the same party. Unknown on either side passes:
    the amount-and-date rule alone decides then, as before."""
    na, nb = norm_name(a), norm_name(b)
    if not na or not nb:
        return True
    try:
        from rapidfuzz import fuzz
        return fuzz.token_set_ratio(na, nb) >= 70
    except ImportError:  # pragma: no cover
        return na.split()[0] == nb.split()[0]


class CashAppRepository:
    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool
        self._trgm: bool | None = None
        # Payments queued through this instance (one per request): the route hands
        # them to CashApplicationService.drain so an upload is matched straight away.
        self.enqueued: list[str] = []

    # ── settings ───────────────────────────────────────────────────────────────

    async def settings(self, tenant: str, conn=None) -> Policy:
        c = conn or self.pool
        row = await c.fetchrow("SELECT * FROM ar_settings WHERE tenant_id = $1::uuid", tenant)
        return Policy.from_row(dict(row) if row else None)

    async def save_settings(self, tenant: str, p: Policy, actor: str | None) -> None:
        async with self.pool.acquire() as c:
            async with c.transaction():
                await c.execute(
                    """INSERT INTO ar_settings (tenant_id, auto_apply_enabled, auto_apply_threshold, amount_tolerance,
                                                writeoff_tolerance, tds_rates, trust_learned_tds, updated_at, updated_by)
                       VALUES ($1::uuid, $2, $3, $4, $5, $6::numeric[], $7, now(), $8)
                       ON CONFLICT (tenant_id) DO UPDATE SET
                         auto_apply_enabled = EXCLUDED.auto_apply_enabled,
                         auto_apply_threshold = EXCLUDED.auto_apply_threshold,
                         amount_tolerance = EXCLUDED.amount_tolerance,
                         writeoff_tolerance = EXCLUDED.writeoff_tolerance,
                         tds_rates = EXCLUDED.tds_rates,
                         trust_learned_tds = EXCLUDED.trust_learned_tds,
                         updated_at = now(), updated_by = EXCLUDED.updated_by""",
                    tenant, p.auto_apply_enabled, p.auto_apply_threshold, p.amount_tolerance,
                    p.writeoff_tolerance, list(p.tds_rates), p.trust_learned_tds, actor)
                await self.event(c, tenant, "settings", None, "settings_changed", actor, p.to_json())

    # ── audit ──────────────────────────────────────────────────────────────────

    async def event(self, conn, tenant: str, entity: str, entity_id, action: str, actor: str | None,
                    payload: dict | None = None) -> None:
        await conn.execute(
            "INSERT INTO ar_events (tenant_id, entity, entity_id, action, actor, payload) "
            "VALUES ($1::uuid, $2, $3::uuid, $4, $5, $6::jsonb)",
            tenant, entity, str(entity_id) if entity_id else None, action, actor or "agent", _j(payload))

    async def events(self, tenant: str, entity: str, entity_id: str, limit: int = 50) -> list[dict]:
        rs = await self.pool.fetch(
            "SELECT action, actor, payload, at FROM ar_events WHERE tenant_id = $1::uuid AND entity = $2 "
            "AND entity_id = $3::uuid ORDER BY at DESC LIMIT $4", tenant, entity, entity_id, limit)
        return [{**dict(r), "payload": json.loads(r["payload"]) if r["payload"] else None} for r in rs]

    # ── customers ──────────────────────────────────────────────────────────────

    async def find_or_create_customer(self, conn, tenant: str, *, name: str, gstin: str | None,
                                      pan: str | None = None, address: str | None = None,
                                      email: str | None = None, phone: str | None = None,
                                      terms_days: int | None = None) -> tuple[str, bool]:
        """(customer_id, created). GSTIN first, then the normalised name."""
        nn = norm_name(name)
        row = None
        if gstin:
            row = await conn.fetchrow("SELECT id FROM ar_customers WHERE tenant_id = $1::uuid AND gstin = $2",
                                      tenant, gstin)
        if not row and nn:
            row = await conn.fetchrow(
                "SELECT id FROM ar_customers WHERE tenant_id = $1::uuid AND name_norm = $2 "
                "AND (gstin IS NULL OR $3::text IS NULL) ORDER BY created_at LIMIT 1", tenant, nn, gstin)
        if row:
            await conn.execute(
                """UPDATE ar_customers SET gstin = COALESCE(gstin, $3), pan = COALESCE(pan, $4),
                          address = COALESCE(address, $5), updated_at = now()
                   WHERE id = $1::uuid AND tenant_id = $2::uuid""",
                str(row["id"]), tenant, gstin, pan, address)
            return str(row["id"]), False
        cid = await conn.fetchval(
            """INSERT INTO ar_customers (tenant_id, name, name_norm, gstin, pan, address, email, phone, payment_terms_days)
               VALUES ($1::uuid, $2, $3, $4, $5, $6, $7, $8, $9) RETURNING id""",
            tenant, name, nn, gstin, pan, address, email, phone, terms_days)
        # The name on our own invoice is how the customer is most likely to appear.
        await self.add_alias(conn, tenant, str(cid), name, "invoice")
        return str(cid), True

    async def add_alias(self, conn, tenant: str, customer_id: str, raw: str, source: str) -> bool:
        an = norm_name(raw)
        if len(an) < 3:
            return False
        r = await conn.fetchval(
            """INSERT INTO ar_payer_aliases (tenant_id, alias_norm, alias_raw, customer_id, source)
               VALUES ($1::uuid, $2, $3, $4::uuid, $5)
               ON CONFLICT (tenant_id, alias_norm, customer_id)
               DO UPDATE SET confirmations = ar_payer_aliases.confirmations + 1, last_seen_at = now()
               RETURNING (xmax = 0)""",
            tenant, an, raw, customer_id, source)
        return bool(r)

    async def remove_alias(self, tenant: str, customer_id: str, alias_id: str) -> None:
        await self.pool.execute(
            "DELETE FROM ar_payer_aliases WHERE id = $1::uuid AND tenant_id = $2::uuid AND customer_id = $3::uuid",
            alias_id, tenant, customer_id)

    async def list_customers(self, tenant: str, q: str | None, limit: int, offset: int) -> tuple[list[dict], int]:
        qn = norm_name(q) if q else None
        where = "c.tenant_id = $1::uuid AND ($2::text IS NULL OR c.name_norm LIKE '%' || $2 || '%' OR c.gstin = upper($2))"
        rs = await self.pool.fetch(f"""
            SELECT c.id, c.name, c.gstin, c.pan, c.email, c.payment_terms_days, c.tds_rate_hint,
                   COALESCE(i.open_count, 0) AS open_count, COALESCE(i.outstanding, 0) AS outstanding,
                   COALESCE(i.overdue, 0) AS overdue, COALESCE(p.unapplied, 0) AS unapplied,
                   p.last_payment
              FROM ar_customers c
              LEFT JOIN LATERAL (
                SELECT count(*) FILTER (WHERE status IN ('open','partially_paid')) AS open_count,
                       sum(outstanding) FILTER (WHERE status IN ('open','partially_paid','disputed')) AS outstanding,
                       sum(outstanding) FILTER (WHERE status IN ('open','partially_paid') AND due_date < current_date) AS overdue
                  FROM ar_invoices WHERE tenant_id = c.tenant_id AND customer_id = c.id) i ON true
              LEFT JOIN LATERAL (
                SELECT sum(amount - applied_amount) FILTER (
                         WHERE status IN ('unmatched','needs_review','partially_applied','exception')) AS unapplied,
                       max(received_on) AS last_payment
                  FROM ar_payments WHERE tenant_id = c.tenant_id AND customer_id = c.id) p ON true
             WHERE {where}
             ORDER BY COALESCE(i.outstanding, 0) DESC, c.name
             LIMIT $3 OFFSET $4""", tenant, qn, limit, offset)
        total = await self.pool.fetchval(f"SELECT count(*) FROM ar_customers c WHERE {where}", tenant, qn)
        return _rows(rs), total

    async def get_customer(self, tenant: str, customer_id: str) -> dict | None:
        r = await self.pool.fetchrow("SELECT * FROM ar_customers WHERE id = $1::uuid AND tenant_id = $2::uuid",
                                     customer_id, tenant)
        if not r:
            return None
        aliases = await self.pool.fetch(
            "SELECT id, alias_raw, alias_norm, source, confirmations, last_seen_at FROM ar_payer_aliases "
            "WHERE tenant_id = $1::uuid AND customer_id = $2::uuid ORDER BY confirmations DESC, alias_norm",
            tenant, customer_id)
        return {**dict(r), "aliases": _rows(aliases)}

    async def update_customer(self, tenant: str, customer_id: str, fields: dict, actor: str | None) -> None:
        allowed = {"name", "gstin", "pan", "email", "phone", "address", "payment_terms_days", "tds_rate_hint"}
        sets, args = [], [customer_id, tenant]
        for k, v in fields.items():
            if k in allowed:
                args.append(v)
                sets.append(f"{k} = ${len(args)}")
                if k == "name":
                    args.append(norm_name(v))
                    sets.append(f"name_norm = ${len(args)}")
        if not sets:
            return
        async with self.pool.acquire() as c:
            async with c.transaction():
                await c.execute(f"UPDATE ar_customers SET {', '.join(sets)}, updated_at = now() "
                                "WHERE id = $1::uuid AND tenant_id = $2::uuid", *args)
                await self.event(c, tenant, "customer", customer_id, "updated", actor, fields)

    async def _has_trgm(self) -> bool:
        if self._trgm is None:
            try:
                self._trgm = bool(await self.pool.fetchval(
                    "SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm'"))
            except Exception:
                self._trgm = False
        return self._trgm

    async def customers_for_match(self, tenant: str, payer: str | None, narration: str | None,
                                  extra_ids: set[str]) -> list[Customer]:
        """The few customers worth comparing against: exact alias hits, trigram
        look-alikes of the payer name, and whoever owns a quoted invoice."""
        pn = norm_name(payer) or None
        hay = pn or norm_name(narration) or None
        ids: set[str] = set(extra_ids)
        if pn:
            ids |= {str(r["customer_id"]) for r in await self.pool.fetch(
                "SELECT customer_id FROM ar_payer_aliases WHERE tenant_id = $1::uuid AND alias_norm = $2",
                tenant, pn)}
            ids |= {str(r["id"]) for r in await self.pool.fetch(
                "SELECT id FROM ar_customers WHERE tenant_id = $1::uuid AND name_norm = $2", tenant, pn)}
        if hay and len(hay) >= 3:
            if await self._has_trgm():
                rs = await self.pool.fetch(
                    """SELECT id FROM (
                         SELECT id, similarity(name_norm, $2) AS s FROM ar_customers WHERE tenant_id = $1::uuid
                         UNION ALL
                         SELECT customer_id, similarity(alias_norm, $2) FROM ar_payer_aliases WHERE tenant_id = $1::uuid
                       ) x WHERE s > 0.2 ORDER BY s DESC LIMIT 5""", tenant, hay)
            else:
                first = hay.split(" ")[0][:6]
                rs = await self.pool.fetch(
                    "SELECT id FROM ar_customers WHERE tenant_id = $1::uuid AND name_norm LIKE $2 || '%' LIMIT 10",
                    tenant, first)
            ids |= {str(r["id"]) for r in rs}
        if not ids:
            return []
        rs = await self.pool.fetch(
            """SELECT c.id, c.name, c.pan, c.tds_rate_hint,
                      COALESCE(array_agg(a.alias_norm) FILTER (WHERE a.alias_norm IS NOT NULL), '{}') AS aliases
                 FROM ar_customers c LEFT JOIN ar_payer_aliases a ON a.customer_id = c.id AND a.tenant_id = c.tenant_id
                WHERE c.tenant_id = $1::uuid AND c.id = ANY($2::uuid[])
                GROUP BY c.id""", tenant, list(ids))
        return [Customer(str(r["id"]), r["name"], list(r["aliases"]),
                         Decimal(str(r["tds_rate_hint"])) if r["tds_rate_hint"] is not None else None, r["pan"])
                for r in rs]

    # ── invoices ───────────────────────────────────────────────────────────────

    @staticmethod
    def _open_invoice(r) -> OpenInvoice:
        return OpenInvoice(
            id=str(r["id"]), number=r["invoice_number"], customer_id=str(r["customer_id"]),
            outstanding=r["outstanding"], total=r["total_amount"], taxable=r["taxable_amount"],
            invoice_date=r["invoice_date"], due_date=r["due_date"], po_number=r["po_number"],
            currency=r["currency"], status=r["status"],
            untouched=(r["amount_received"] == 0 and r["tds_amount"] == 0 and r["deduction_amount"] == 0))

    _INV_COLS = ("id, invoice_number, customer_id, outstanding, total_amount, taxable_amount, invoice_date, due_date, "
                 "po_number, currency, status, amount_received, tds_amount, deduction_amount")

    async def invoices_by_tokens(self, tenant: str, tokens: set[str]) -> list[OpenInvoice]:
        if not tokens:
            return []
        rs = await self.pool.fetch(
            f"SELECT {self._INV_COLS} FROM ar_invoices WHERE tenant_id = $1::uuid AND status = ANY($3::text[]) "
            "AND (number_norm = ANY($2::text[]) OR (po_norm <> '' AND po_norm = ANY($2::text[]))) LIMIT 50",
            tenant, list(tokens), list(MATCHABLE_INVOICE))
        return [self._open_invoice(r) for r in rs]

    async def invoices_by_numbers(self, tenant: str, numbers: list[str], customer_id: str | None) -> list[OpenInvoice]:
        """Invoices a remittance names, including near-misses by suffix (resolve_number decides)."""
        from .matching import norm_ref
        norms = [n for n in (norm_ref(x) for x in numbers) if len(n) >= 3]
        if not norms:
            return []
        rs = await self.pool.fetch(
            f"""SELECT {self._INV_COLS} FROM ar_invoices
                 WHERE tenant_id = $1::uuid AND status = ANY($4::text[])
                   AND ($3::uuid IS NULL OR customer_id = $3::uuid)
                   AND (number_norm = ANY($2::text[])
                        OR EXISTS (SELECT 1 FROM unnest($2::text[]) q WHERE number_norm LIKE '%' || q
                                   OR q LIKE '%' || number_norm))
                 LIMIT 100""", tenant, norms, customer_id, list(MATCHABLE_INVOICE))
        return [self._open_invoice(r) for r in rs]

    async def open_invoices(self, tenant: str, customer_id: str, limit: int = 200) -> list[OpenInvoice]:
        rs = await self.pool.fetch(
            f"SELECT {self._INV_COLS} FROM ar_invoices WHERE tenant_id = $1::uuid AND customer_id = $2::uuid "
            "AND status = ANY($3::text[]) AND outstanding > 0 ORDER BY due_date NULLS LAST, invoice_date LIMIT $4",
            tenant, customer_id, list(MATCHABLE_INVOICE), limit)
        return [self._open_invoice(r) for r in rs]

    async def invoices_near_amount(self, tenant: str, amount: Decimal, tol: Decimal) -> list[OpenInvoice]:
        rs = await self.pool.fetch(
            f"SELECT {self._INV_COLS} FROM ar_invoices WHERE tenant_id = $1::uuid AND status = ANY($4::text[]) "
            "AND outstanding BETWEEN $2 AND $3 LIMIT 20",
            tenant, amount - tol, amount + tol, list(OPEN))
        return [self._open_invoice(r) for r in rs]

    async def paid_invoices(self, tenant: str, customer_id: str, days: int = 180) -> list[OpenInvoice]:
        rs = await self.pool.fetch(
            f"SELECT {self._INV_COLS} FROM ar_invoices WHERE tenant_id = $1::uuid AND customer_id = $2::uuid "
            "AND status = 'paid' AND COALESCE(paid_at, updated_at) > now() - make_interval(days => $3) LIMIT 100",
            tenant, customer_id, days)
        return [self._open_invoice(r) for r in rs]

    async def insert_invoice(self, conn, tenant: str, f: dict) -> str:
        return str(await conn.fetchval(
            """INSERT INTO ar_invoices (tenant_id, customer_id, invoice_number, invoice_date, due_date, po_number,
                                        currency, taxable_amount, tax_amount, total_amount, payment_terms,
                                        source_file, storage_ref, payload, created_by)
               VALUES ($1::uuid, $2::uuid, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14::jsonb, $15)
               RETURNING id""",
            tenant, f["customer_id"], f["invoice_number"], f.get("invoice_date"), f.get("due_date"),
            f.get("po_number"), f.get("currency") or "INR", f.get("taxable_amount"), f.get("tax_amount"),
            f["total_amount"], f.get("payment_terms"), f.get("source_file"), f.get("storage_ref"),
            _j(f.get("payload")), f.get("created_by")))

    async def list_invoices(self, tenant: str, status: list[str] | None, customer_id: str | None,
                            q: str | None, overdue: bool, limit: int, offset: int) -> tuple[list[dict], int]:
        from .matching import norm_ref
        where = """i.tenant_id = $1::uuid
                   AND ($2::text[] IS NULL OR i.status = ANY($2::text[]))
                   AND ($3::uuid IS NULL OR i.customer_id = $3::uuid)
                   AND ($4::text IS NULL OR i.number_norm LIKE '%' || $4 || '%' OR c.name_norm LIKE '%' || $5 || '%')
                   AND (NOT $6 OR (i.due_date < current_date AND i.status IN ('open','partially_paid')))"""
        args = [tenant, status, customer_id, norm_ref(q) if q else None, norm_name(q) if q else None, overdue]
        rs = await self.pool.fetch(f"""
            SELECT i.id, i.invoice_number, i.invoice_date, i.due_date, i.po_number, i.currency,
                   i.taxable_amount, i.tax_amount, i.total_amount, i.amount_received, i.tds_amount,
                   i.deduction_amount, i.outstanding, i.status, i.created_at, i.storage_ref IS NOT NULL AS has_document,
                   c.id AS customer_id, c.name AS customer_name,
                   CASE WHEN i.status IN ('open','partially_paid') AND i.due_date < current_date
                        THEN current_date - i.due_date END AS days_overdue
              FROM ar_invoices i JOIN ar_customers c ON c.id = i.customer_id
             WHERE {where}
             ORDER BY i.invoice_date DESC NULLS LAST, i.created_at DESC
             LIMIT $7 OFFSET $8""", *args, limit, offset)
        total = await self.pool.fetchval(
            f"SELECT count(*) FROM ar_invoices i JOIN ar_customers c ON c.id = i.customer_id WHERE {where}", *args)
        return _rows(rs), total

    async def get_invoice(self, tenant: str, invoice_id: str) -> dict | None:
        r = await self.pool.fetchrow(
            """SELECT i.*, c.name AS customer_name, c.gstin AS customer_gstin
                 FROM ar_invoices i JOIN ar_customers c ON c.id = i.customer_id
                WHERE i.id = $1::uuid AND i.tenant_id = $2::uuid""", invoice_id, tenant)
        if not r:
            return None
        apps = await self.pool.fetch(
            """SELECT a.*, p.received_on, p.utr, p.payer_name, p.method
                 FROM ar_applications a JOIN ar_payments p ON p.id = a.payment_id
                WHERE a.invoice_id = $1::uuid AND a.tenant_id = $2::uuid ORDER BY a.created_at""",
            invoice_id, tenant)
        d = dict(r)
        d.pop("payload", None)
        return {**d, "applications": _rows(apps)}

    async def set_invoice_status(self, tenant: str, invoice_id: str, status: str, actor: str | None,
                                 note: str | None) -> bool:
        async with self.pool.acquire() as c:
            async with c.transaction():
                old = await c.fetchval("SELECT status FROM ar_invoices WHERE id = $1::uuid AND tenant_id = $2::uuid "
                                       "FOR UPDATE", invoice_id, tenant)
                if old is None:
                    return False
                await c.execute("UPDATE ar_invoices SET status = $3, updated_at = now() "
                                "WHERE id = $1::uuid AND tenant_id = $2::uuid", invoice_id, tenant, status)
                await self.event(c, tenant, "invoice", invoice_id, f"status_{status}", actor,
                                 {"from": old, "note": note})
        return True

    async def invoice_document_ref(self, tenant: str, invoice_id: str) -> tuple[str | None, str | None]:
        r = await self.pool.fetchrow("SELECT storage_ref, source_file FROM ar_invoices "
                                     "WHERE id = $1::uuid AND tenant_id = $2::uuid", invoice_id, tenant)
        return (r["storage_ref"], r["source_file"]) if r else (None, None)

    # ── payments ───────────────────────────────────────────────────────────────

    async def insert_payments(self, conn, tenant: str, rows: list[dict], *, source: str,
                              source_file: str | None, bank_account: str | None, actor: str | None
                              ) -> list[tuple[str, str]]:
        """Insert, skipping fingerprints already present. Returns one entry per row, in
        order: (id, status) for a new payment, None for a duplicate."""
        out: list[tuple[str, str] | None] = []
        for r in rows:
            rec = await conn.fetchrow(
                """INSERT INTO ar_payments (tenant_id, received_on, amount, currency, method, reference, utr, payer_name,
                                            payer_account, narration, bank_account, source, source_file, customer_id,
                                            status, reason_code, fingerprint, created_by, note, statement_id,
                                            statement_line)
                   VALUES ($1::uuid, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14::uuid, $15, $16, $17, $18,
                           $19, $20::uuid, $21)
                   ON CONFLICT (tenant_id, fingerprint) WHERE fingerprint IS NOT NULL DO NOTHING
                   RETURNING id, status""",
                tenant, r["received_on"], r["amount"], r.get("currency") or "INR", r.get("method"),
                r.get("reference"), r.get("utr"), r.get("payer_name"), r.get("payer_account"), r.get("narration"),
                bank_account, source, source_file, r.get("customer_id"),
                r.get("status") or PaymentStatus.UNMATCHED, r.get("reason_code"), r.get("fingerprint"), actor,
                r.get("note"), r.get("statement_id"), r.get("line"))
            out.append((str(rec["id"]), rec["status"]) if rec else None)
        return out

    async def utr_exists(self, tenant: str, utrs: list[str]) -> set[str]:
        if not utrs:
            return set()
        rs = await self.pool.fetch("SELECT utr FROM ar_payments WHERE tenant_id = $1::uuid AND utr = ANY($2::text[])",
                                   tenant, utrs)
        return {r["utr"] for r in rs}

    async def possible_duplicates(self, tenant: str, amount: Decimal, received_on: date, payer: str | None,
                                  utr: str | None) -> list[dict]:
        rs = await self.pool.fetch(
            """SELECT id, received_on, amount, payer_name, utr, status FROM ar_payments
                WHERE tenant_id = $1::uuid AND status <> 'reversed'
                  AND ((($5::text IS NOT NULL) AND utr = $5)
                       OR (amount = $2 AND received_on BETWEEN $3::date - 2 AND $3::date + 2
                           AND ($4::text IS NULL OR payer_name IS NULL OR upper(payer_name) = upper($4))))
                LIMIT 5""", tenant, amount, received_on, payer, utr)
        return _rows(rs)

    async def get_payment(self, tenant: str, payment_id: str, conn=None, *, lock: bool = False) -> dict | None:
        c = conn or self.pool
        r = await c.fetchrow(
            "SELECT * FROM ar_payments WHERE id = $1::uuid AND tenant_id = $2::uuid" + (" FOR UPDATE" if lock else ""),
            payment_id, tenant)
        if not r:
            return None
        d = dict(r)
        if isinstance(d.get("suggestion"), str):
            d["suggestion"] = json.loads(d["suggestion"])
        return d

    async def list_payments(self, tenant: str, status: list[str] | None, customer_id: str | None,
                            q: str | None, limit: int, offset: int) -> tuple[list[dict], int]:
        where = """p.tenant_id = $1::uuid
                   AND ($2::text[] IS NULL OR p.status = ANY($2::text[]))
                   AND ($3::uuid IS NULL OR p.customer_id = $3::uuid)
                   AND ($4::text IS NULL OR upper(coalesce(p.narration,'') || ' ' || coalesce(p.payer_name,'') || ' '
                        || coalesce(p.utr,'') || ' ' || coalesce(p.reference,'')) LIKE '%' || upper($4) || '%'
                        OR p.amount::text = $4)"""
        args = [tenant, status, customer_id, q]
        rs = await self.pool.fetch(f"""
            SELECT p.id, p.received_on, p.amount, p.method, p.reference, p.utr, p.payer_name, p.narration,
                   p.source, p.status, p.applied_amount, p.note,
                   -- Set-aside and reversed lines were never customer money waiting to be applied.
                   CASE WHEN p.status IN ('not_receipt','reversed') THEN 0
                        ELSE p.amount - p.applied_amount END AS unapplied,
                   p.match_confidence, p.flags, p.auto_applied, p.reason_code, p.version,
                   p.suggestion -> 'best' ->> 'kind' AS suggestion_kind,
                   p.suggestion -> 'best' -> 'clues' ->> -1 AS suggestion_reason,
                   (SELECT string_agg(a->>'invoice_number', ', ') FROM jsonb_array_elements(
                        coalesce(p.suggestion -> 'best' -> 'allocations', '[]'::jsonb)) a) AS suggestion_invoices,
                   COALESCE(p.customer_id, (p.suggestion ->> 'customer_id')::uuid) AS customer_id,
                   c.name AS customer_name, p.customer_id IS NOT NULL AS customer_confirmed,
                   p.created_at, p.applied_at
              FROM ar_payments p
              LEFT JOIN ar_customers c ON c.id = COALESCE(p.customer_id, (p.suggestion ->> 'customer_id')::uuid)
             WHERE {where}
             ORDER BY p.received_on DESC, p.created_at DESC
             LIMIT $5 OFFSET $6""", *args, limit, offset)
        total = await self.pool.fetchval(f"SELECT count(*) FROM ar_payments p WHERE {where}", *args)
        return _rows(rs), total

    async def review_board(self, tenant: str, status: list[str], q: str | None, limit: int = 200) -> list[dict]:
        """Payments waiting on a person, grouped by customer, each with the customer's open invoices —
        the review board draws every payment → invoice allocation as a line (CashApplicationPage)."""
        pays = await self.pool.fetch(
            """SELECT p.id, p.received_on, p.amount, p.method, p.reference, p.utr, p.payer_name, p.source,
                      p.status, p.version, p.match_confidence, p.flags, p.statement_id,
                      p.suggestion -> 'best' AS best, p.suggestion -> 'decision' AS decision,
                      COALESCE(p.customer_id, (p.suggestion ->> 'customer_id')::uuid) AS customer_id,
                      r.id AS remittance_id, r.total_amount AS remittance_total
                 FROM ar_payments p
                 LEFT JOIN LATERAL (SELECT id, total_amount FROM ar_remittances
                                     WHERE tenant_id = p.tenant_id AND payment_id = p.id
                                     ORDER BY created_at DESC LIMIT 1) r ON true
                WHERE p.tenant_id = $1::uuid AND p.status = ANY($2::text[])
                  AND ($3::text IS NULL OR upper(coalesce(p.narration,'') || ' ' || coalesce(p.payer_name,'') || ' '
                       || coalesce(p.utr,'') || ' ' || coalesce(p.reference,'')) LIKE '%' || upper($3) || '%'
                       OR p.amount::text = $3
                       OR EXISTS (SELECT 1 FROM ar_customers c WHERE c.id = COALESCE(p.customer_id, (p.suggestion ->> 'customer_id')::uuid)
                                  AND upper(c.name) LIKE '%' || upper($3) || '%'))
                ORDER BY p.received_on, p.created_at
                LIMIT $4""", tenant, status, q or None, limit)
        if not pays:
            return []
        cust_ids = list({str(r["customer_id"]) for r in pays if r["customer_id"]})
        custs = {str(r["id"]): dict(r) for r in await self.pool.fetch(
            """SELECT c.id, c.name, c.payment_terms_days,
                      COALESCE(sum(i.outstanding) FILTER (WHERE i.status IN ('open','partially_paid','disputed')), 0) AS open_ar,
                      COALESCE(sum(i.outstanding) FILTER (WHERE i.status IN ('open','partially_paid') AND i.due_date < current_date), 0) AS overdue
                 FROM ar_customers c LEFT JOIN ar_invoices i ON i.customer_id = c.id AND i.tenant_id = c.tenant_id
                WHERE c.tenant_id = $1::uuid AND c.id = ANY($2::uuid[])
                GROUP BY c.id""", tenant, cust_ids)} if cust_ids else {}
        invs = await self.pool.fetch(
            """SELECT id, invoice_number, invoice_date, due_date, po_number, total_amount, amount_received, tds_amount,
                      deduction_amount, outstanding, status, customer_id, taxable_amount,
                      CASE WHEN status IN ('open','partially_paid') AND due_date < current_date
                           THEN current_date - due_date END AS days_overdue
                 FROM ar_invoices
                WHERE tenant_id = $1::uuid AND customer_id = ANY($2::uuid[]) AND status = ANY($3::text[]) AND outstanding > 0
                ORDER BY due_date NULLS LAST, invoice_date""", tenant, cust_ids, list(MATCHABLE_INVOICE)) if cust_ids else []
        groups: dict[str, dict] = {}
        for r in pays:
            key = str(r["customer_id"]) if r["customer_id"] else ""
            g = groups.setdefault(key, {"customer": custs.get(key), "payments": [], "invoices": []})
            d = dict(r)
            for k in ("best", "decision"):
                if isinstance(d.get(k), str):
                    d[k] = json.loads(d[k])
            groups[key]["payments"].append(d)
        for r in invs:
            g = groups.get(str(r["customer_id"]))
            if g is not None:
                g["invoices"].append(dict(r))
        return list(groups.values())

    async def status_counts(self, tenant: str) -> dict[str, int]:
        rs = await self.pool.fetch("SELECT status, count(*) AS n FROM ar_payments WHERE tenant_id = $1::uuid "
                                   "GROUP BY status", tenant)
        return {r["status"]: r["n"] for r in rs}

    async def applications_for_payment(self, tenant: str, payment_id: str) -> list[dict]:
        rs = await self.pool.fetch(
            """SELECT a.*, i.invoice_number FROM ar_applications a JOIN ar_invoices i ON i.id = a.invoice_id
                WHERE a.payment_id = $1::uuid AND a.tenant_id = $2::uuid ORDER BY a.created_at""",
            payment_id, tenant)
        return _rows(rs)

    async def save_match(self, conn, tenant: str, payment_id: str, *, status: str, suggestion: dict,
                         confidence: Decimal | None, flags: list[str]) -> None:
        """Store the agent's view. The agent's customer guess lives only inside
        `suggestion`: ar_payments.customer_id holds a customer a person chose or
        confirmed by applying, so a guess can never be mistaken for certainty on
        the next run."""
        await conn.execute(
            """UPDATE ar_payments SET status = $3, suggestion = $4::jsonb, match_confidence = $5,
                      flags = array(SELECT DISTINCT f FROM unnest(
                                $6::text[] || array(SELECT x FROM unnest(flags) x WHERE NOT x = ANY($7::text[]))) f),
                      matched_at = now(), version = version + 1
                WHERE id = $1::uuid AND tenant_id = $2::uuid""",
            payment_id, tenant, status, _j(suggestion), confidence, flags, _ENGINE_FLAGS)

    async def unmatched_for_customer(self, tenant: str, customer_id: str | None, limit: int = 200) -> list[str]:
        """Payments a new invoice / alias could now explain: this customer's, plus
        payer-unknown ones (the new invoice may be what identifies them)."""
        rs = await self.pool.fetch(
            """SELECT id FROM ar_payments WHERE tenant_id = $1::uuid
                 AND status IN ('unmatched','needs_review','partially_applied')
                 AND ($2::uuid IS NULL OR customer_id = $2::uuid OR customer_id IS NULL)
               ORDER BY received_on DESC LIMIT $3""", tenant, customer_id, limit)
        return [str(r["id"]) for r in rs]

    async def waiting_for_customer(self, tenant: str, customer_id: str, limit: int = 200) -> list[str]:
        """Waiting payments that belong to this customer — confirmed, or the agent's current
        guess. Narrower than unmatched_for_customer: after an apply, only these can have a
        stale suggestion, and re-matching every payer-unknown payment would cascade."""
        rs = await self.pool.fetch(
            """SELECT id FROM ar_payments WHERE tenant_id = $1::uuid
                 AND status IN ('unmatched','needs_review','partially_applied')
                 AND (customer_id = $2::uuid OR (suggestion ->> 'customer_id') = $2::text)
               ORDER BY received_on LIMIT $3""", tenant, customer_id, limit)
        return [str(r["id"]) for r in rs]

    async def find_bounced(self, tenant: str, b: dict) -> list[dict]:
        rs = await self.pool.fetch(
            """SELECT id, received_on, amount, narration, status FROM ar_payments
                WHERE tenant_id = $1::uuid AND amount = $2 AND status NOT IN ('reversed')
                  AND received_on BETWEEN $3::date - 30 AND $3::date
                  AND ($4::text IS NULL OR reference = $4 OR utr = $4 OR narration ILIKE '%' || $4 || '%')
                ORDER BY received_on DESC LIMIT 3""", tenant, b["amount"], b["date"], b.get("reference"))
        return _rows(rs)

    async def flag_payment(self, conn, tenant: str, payment_id: str, flag: str) -> None:
        await conn.execute(
            "UPDATE ar_payments SET flags = array(SELECT DISTINCT unnest(flags || $3::text)), version = version + 1 "
            "WHERE id = $1::uuid AND tenant_id = $2::uuid", payment_id, tenant, flag)

    # ── statements ─────────────────────────────────────────────────────────────

    async def statement_by_sha(self, tenant: str, sha: str) -> dict | None:
        r = await self.pool.fetchrow("SELECT id, file_name, created_at FROM ar_statements "
                                     "WHERE tenant_id = $1::uuid AND content_sha256 = $2 ORDER BY created_at LIMIT 1",
                                     tenant, sha)
        return dict(r) if r else None

    async def insert_statement(self, conn, tenant: str, f: dict) -> str:
        return str(await conn.fetchval(
            """INSERT INTO ar_statements (id, tenant_id, file_name, file_format, content_sha256, storage_ref,
                                          bank_account, period_from, period_to, uploaded_by)
               VALUES ($1::uuid, $2::uuid, $3, $4, $5, $6, $7, $8, $9, $10) RETURNING id""",
            f["id"], tenant, f["file_name"], f["file_format"], f["sha"], f.get("storage_ref"),
            f.get("bank_account"), f.get("period_from"), f.get("period_to"), f.get("uploaded_by")))

    async def finish_statement(self, conn, tenant: str, statement_id: str, *, lines: list[dict], counts: dict) -> None:
        await conn.execute(
            """UPDATE ar_statements SET lines = $3::jsonb, credits = $4, imported = $5, duplicates = $6,
                      set_aside = $7, bounces = $8
                WHERE id = $1::uuid AND tenant_id = $2::uuid""",
            statement_id, tenant, _j(lines), counts["credits"], counts["imported"], counts["duplicates"],
            counts["set_aside"], counts["possible_bounces"])

    async def list_statements(self, tenant: str, limit: int, offset: int) -> list[dict]:
        rs = await self.pool.fetch(
            """SELECT id, file_name, file_format, bank_account, period_from, period_to, credits, imported,
                      duplicates, set_aside, bounces, uploaded_by, created_at, storage_ref IS NOT NULL AS has_document
                 FROM ar_statements WHERE tenant_id = $1::uuid ORDER BY created_at DESC LIMIT $2 OFFSET $3""",
            tenant, limit, offset)
        return _rows(rs)

    async def get_statement(self, tenant: str, statement_id: str) -> dict | None:
        r = await self.pool.fetchrow("SELECT * FROM ar_statements WHERE id = $1::uuid AND tenant_id = $2::uuid",
                                     statement_id, tenant)
        if not r:
            return None
        d = dict(r)
        d["lines"] = json.loads(d["lines"]) if isinstance(d["lines"], str) else d["lines"]
        # Each line's payment as it stands now (status moves on after import).
        pays = {str(p["id"]): dict(p) for p in await self.pool.fetch(
            """SELECT p.id, p.status, p.applied_amount, p.auto_applied, c.name AS customer_name
                 FROM ar_payments p LEFT JOIN ar_customers c ON c.id = p.customer_id
                WHERE p.tenant_id = $1::uuid AND p.statement_id = $2::uuid""", tenant, statement_id)}
        for ln in d["lines"]:
            p = pays.get(ln.get("payment_id") or "")
            if p:
                ln["payment_status"] = p["status"]
                ln["auto_applied"] = p["auto_applied"]
                ln["customer_name"] = p["customer_name"]
        d["has_document"] = bool(d.pop("storage_ref", None))
        return d

    async def statement_document(self, tenant: str, statement_id: str) -> tuple[str | None, str | None, str | None]:
        r = await self.pool.fetchrow("SELECT storage_ref, file_name, file_format FROM ar_statements "
                                     "WHERE id = $1::uuid AND tenant_id = $2::uuid", statement_id, tenant)
        return (r["storage_ref"], r["file_name"], r["file_format"]) if r else (None, None, None)

    # ── remittances ────────────────────────────────────────────────────────────

    async def insert_remittance(self, conn, tenant: str, d: dict, *, source: str, source_file: str | None,
                                storage_ref: str | None, raw_text: str | None, actor: str | None) -> str:
        return str(await conn.fetchval(
            """INSERT INTO ar_remittances (tenant_id, payer_name, payment_reference, payment_date, total_amount, lines,
                                           source, source_file, storage_ref, raw_text, created_by)
               VALUES ($1::uuid, $2, $3, $4, $5, $6::jsonb, $7, $8, $9, $10, $11) RETURNING id""",
            tenant, d.get("payer_name"), d.get("payment_reference"), d.get("payment_date"),
            Decimal(str(d["total_amount"])) if d.get("total_amount") is not None else None,
            _j(d.get("lines") or []), source, source_file, storage_ref, (raw_text or "")[:50000], actor))

    async def payment_for_remittance(self, tenant: str, ref: str | None, total: Decimal | None,
                                     on: date | None, tol: Decimal, payer: str | None = None) -> str | None:
        """UTR / reference first; else a unique payment with the same amount within 10 days
        whose payer name fits the remittance's."""
        if ref:
            rs = await self.pool.fetch(
                """SELECT id FROM ar_payments WHERE tenant_id = $1::uuid AND status <> 'reversed'
                     AND (utr = $2 OR reference = $2 OR narration ILIKE '%' || $2 || '%') LIMIT 2""", tenant, ref)
            if len(rs) == 1:
                return str(rs[0]["id"])
        if total is not None:
            rs = await self.pool.fetch(
                """SELECT id, payer_name FROM ar_payments WHERE tenant_id = $1::uuid
                     AND status IN ('unmatched','needs_review','partially_applied','applied')
                     AND amount BETWEEN $2 AND $3
                     AND ($4::date IS NULL OR received_on BETWEEN $4::date - 10 AND $4::date + 10) LIMIT 10""",
                tenant, total - tol, total + tol, on)
            rs = [r for r in rs if _payer_fits(payer, r["payer_name"])]
            if len(rs) == 1:
                return str(rs[0]["id"])
        return None

    async def link_remittance(self, conn, tenant: str, remittance_id: str, payment_id: str) -> None:
        await conn.execute("UPDATE ar_remittances SET payment_id = $3::uuid, status = 'linked' "
                           "WHERE id = $1::uuid AND tenant_id = $2::uuid", remittance_id, tenant, payment_id)

    async def remittance_for_payment(self, tenant: str, payment: dict, tol: Decimal) -> dict | None:
        """A linked remittance, or (edge case C4) an unlinked one that fits this payment — linked now."""
        r = await self.pool.fetchrow("SELECT * FROM ar_remittances WHERE tenant_id = $1::uuid AND payment_id = $2::uuid "
                                     "ORDER BY created_at DESC LIMIT 1", tenant, str(payment["id"]))
        if not r:
            refs = [x for x in (payment.get("utr"), payment.get("reference")) if x]
            rs = await self.pool.fetch(
                """SELECT * FROM ar_remittances WHERE tenant_id = $1::uuid AND status = 'unlinked'
                     AND ((payment_reference IS NOT NULL AND payment_reference = ANY($2::text[]))
                          OR (total_amount BETWEEN $3 AND $4
                              AND (payment_date IS NULL OR payment_date BETWEEN $5::date - 10 AND $5::date + 10)))
                   ORDER BY created_at DESC LIMIT 10""",
                tenant, refs, payment["amount"] - tol, payment["amount"] + tol, payment["received_on"])
            # By UTR, or by amount + date + a payer name on the remittance that fits this
            # payment's — never by amount alone here, or a nameless advice would attach to
            # whichever same-amount payment happened to re-match first.
            rs = [r for r in rs if r["payment_reference"] in refs
                  or (r["payer_name"] and _payer_fits(r["payer_name"], payment.get("payer_name")))]
            if len(rs) != 1:
                return None
            r = rs[0]
            async with self.pool.acquire() as c:
                await self.link_remittance(c, tenant, str(r["id"]), str(payment["id"]))
        d = dict(r)
        d["lines"] = json.loads(d["lines"]) if isinstance(d["lines"], str) else d["lines"]
        return d

    async def list_remittances(self, tenant: str, status: str | None, limit: int, offset: int) -> list[dict]:
        rs = await self.pool.fetch(
            """SELECT r.id, r.payer_name, r.payment_reference, r.payment_date, r.total_amount, r.lines, r.status,
                      r.source, r.source_file, r.created_at, r.payment_id, p.amount AS payment_amount,
                      r.storage_ref IS NOT NULL AS has_document,
                      p.received_on AS payment_received_on
                 FROM ar_remittances r LEFT JOIN ar_payments p ON p.id = r.payment_id
                WHERE r.tenant_id = $1::uuid AND ($2::text IS NULL OR r.status = $2)
                ORDER BY r.created_at DESC LIMIT $3 OFFSET $4""", tenant, status, limit, offset)
        return [{**dict(r), "lines": json.loads(r["lines"]) if isinstance(r["lines"], str) else r["lines"]} for r in rs]

    async def get_remittance(self, tenant: str, remittance_id: str) -> dict | None:
        r = await self.pool.fetchrow(
            """SELECT r.*, p.amount AS payment_amount, p.received_on AS payment_received_on, p.status AS payment_status,
                      p.utr AS payment_utr, c.name AS customer_name
                 FROM ar_remittances r
                 LEFT JOIN ar_payments p ON p.id = r.payment_id
                 LEFT JOIN ar_customers c ON c.id = COALESCE(r.customer_id, p.customer_id)
                WHERE r.id = $1::uuid AND r.tenant_id = $2::uuid""", remittance_id, tenant)
        if not r:
            return None
        d = dict(r)
        d["lines"] = json.loads(d["lines"]) if isinstance(d["lines"], str) else d["lines"]
        d["has_document"] = bool(d.pop("storage_ref", None))
        return d

    async def remittance_document(self, tenant: str, remittance_id: str) -> tuple[str | None, str | None]:
        r = await self.pool.fetchrow("SELECT storage_ref, source_file FROM ar_remittances "
                                     "WHERE id = $1::uuid AND tenant_id = $2::uuid", remittance_id, tenant)
        return (r["storage_ref"], r["source_file"]) if r else (None, None)

    async def remittances_for_payment(self, tenant: str, payment_id: str) -> list[dict]:
        rs = await self.pool.fetch("SELECT id, payer_name, payment_reference, payment_date, total_amount, lines, "
                                   "source, source_file, created_at, storage_ref IS NOT NULL AS has_document "
                                   "FROM ar_remittances "
                                   "WHERE tenant_id = $1::uuid AND payment_id = $2::uuid ORDER BY created_at DESC",
                                   tenant, payment_id)
        return [{**dict(r), "lines": json.loads(r["lines"]) if isinstance(r["lines"], str) else r["lines"]} for r in rs]

    # ── job queue ──────────────────────────────────────────────────────────────

    async def enqueue(self, conn, tenant: str, payment_ids: list[str], reason: str, delay_s: int = 0) -> int:
        if not payment_ids:
            return 0
        self.enqueued.extend(payment_ids)
        n = 0
        for pid in payment_ids:
            r = await conn.execute(
                """INSERT INTO ar_match_jobs (tenant_id, payment_id, reason, run_after)
                   VALUES ($1::uuid, $2::uuid, $3, now() + make_interval(secs => $4))
                   ON CONFLICT (payment_id) WHERE status IN ('PENDING','RUNNING') DO NOTHING""",
                tenant, pid, reason, delay_s)
            n += r.endswith("1")
        await conn.execute("SELECT pg_notify($1, '')", NOTIFY_CHANNEL)
        return n

    async def claim_jobs(self, limit: int) -> list[dict]:
        rs = await self.pool.fetch(
            """UPDATE ar_match_jobs SET status = 'RUNNING', locked_at = now(), attempts = attempts + 1
                WHERE id IN (SELECT id FROM ar_match_jobs WHERE status = 'PENDING' AND run_after <= now()
                             ORDER BY run_after LIMIT $1 FOR UPDATE SKIP LOCKED)
            RETURNING id, tenant_id, payment_id, reason, attempts""", limit)
        return [{k: (str(v) if k in ("id", "tenant_id", "payment_id") else v) for k, v in dict(r).items()} for r in rs]

    async def claim_jobs_for(self, tenant: str, payment_ids: list[str], limit: int) -> list[dict]:
        """Claim the pending jobs of these payments only — an upload drains what it queued,
        never another tenant's work. SKIP LOCKED: if the worker got there first, nothing."""
        rs = await self.pool.fetch(
            """UPDATE ar_match_jobs SET status = 'RUNNING', locked_at = now(), attempts = attempts + 1
                WHERE id IN (SELECT id FROM ar_match_jobs
                              WHERE status = 'PENDING' AND tenant_id = $1::uuid AND payment_id = ANY($2::uuid[])
                              ORDER BY run_after LIMIT $3 FOR UPDATE SKIP LOCKED)
            RETURNING id, tenant_id, payment_id, reason, attempts""", tenant, payment_ids, limit)
        return [{k: (str(v) if k in ("id", "tenant_id", "payment_id") else v) for k, v in dict(r).items()} for r in rs]

    async def matchable_near_amount(self, tenant: str, amount: Decimal, tol: Decimal) -> list[str]:
        rs = await self.pool.fetch(
            """SELECT id FROM ar_payments WHERE tenant_id = $1::uuid
                 AND status IN ('unmatched','needs_review','partially_applied')
                 AND amount BETWEEN $2 AND $3 AND received_on > current_date - 180 LIMIT 20""",
            tenant, amount - tol, amount + tol)
        return [str(r["id"]) for r in rs]

    async def finish_job(self, job_id: str) -> None:
        await self.pool.execute("UPDATE ar_match_jobs SET status = 'DONE', done_at = now(), error = NULL "
                                "WHERE id = $1::uuid", job_id)

    async def fail_job(self, job_id: str, attempts: int, error: str) -> None:
        if attempts >= 5:
            await self.pool.execute("UPDATE ar_match_jobs SET status = 'FAILED', error = $2, done_at = now() "
                                    "WHERE id = $1::uuid", job_id, error[:2000])
        else:
            await self.pool.execute(
                "UPDATE ar_match_jobs SET status = 'PENDING', error = $2, "
                "run_after = now() + make_interval(secs => $3) WHERE id = $1::uuid",
                job_id, error[:2000], 30 * 2 ** attempts)

    async def reset_stale_jobs(self, minutes: int) -> int:
        r = await self.pool.execute(
            "UPDATE ar_match_jobs SET status = 'PENDING', run_after = now() "
            "WHERE status = 'RUNNING' AND locked_at < now() - make_interval(mins => $1)", minutes)
        return int(r.split()[-1])

    async def sweep(self) -> int:
        """Nightly-ish: re-queue anything unmatched for a day (catches missed triggers)."""
        rs = await self.pool.fetch(
            """SELECT p.tenant_id, p.id FROM ar_payments p
                WHERE p.status = 'unmatched' AND COALESCE(p.matched_at, p.created_at) < now() - interval '1 day'
                  AND NOT EXISTS (SELECT 1 FROM ar_match_jobs j WHERE j.payment_id = p.id
                                  AND j.status IN ('PENDING','RUNNING'))
                LIMIT 500""")
        async with self.pool.acquire() as c:
            for r in rs:
                await self.enqueue(c, str(r["tenant_id"]), [str(r["id"])], "sweep")
        return len(rs)

    # ── KPIs ───────────────────────────────────────────────────────────────────

    async def summary(self, tenant: str, days: int) -> dict:
        p = await self.pool.fetchrow(
            """SELECT count(*) FILTER (WHERE status NOT IN ('not_receipt','reversed')) AS receipts,
                      COALESCE(sum(amount) FILTER (WHERE status NOT IN ('not_receipt','reversed')), 0) AS receipts_total,
                      COALESCE(sum(applied_amount) FILTER (WHERE status NOT IN ('not_receipt','reversed')), 0) AS applied_total,
                      count(*) FILTER (WHERE auto_applied) AS auto_count,
                      count(*) FILTER (WHERE status IN ('applied','partially_applied') AND NOT auto_applied) AS manual_count,
                      count(*) FILTER (WHERE status IN ('needs_review','unmatched','exception')) AS open_count,
                      avg(EXTRACT(EPOCH FROM (applied_at - created_at)) / 3600)
                          FILTER (WHERE applied_at IS NOT NULL) AS hours_to_apply,
                      avg(EXTRACT(EPOCH FROM (applied_at - created_at)) / 3600)
                          FILTER (WHERE applied_at IS NOT NULL AND auto_applied) AS hours_to_apply_auto
                 FROM ar_payments WHERE tenant_id = $1::uuid AND received_on >= current_date - $2::int""",
            tenant, days)
        aging = await self.pool.fetchrow(
            """SELECT COALESCE(sum(amount - applied_amount) FILTER (WHERE current_date - received_on <= 30), 0) AS b0_30,
                      COALESCE(sum(amount - applied_amount) FILTER (WHERE current_date - received_on BETWEEN 31 AND 60), 0) AS b31_60,
                      COALESCE(sum(amount - applied_amount) FILTER (WHERE current_date - received_on > 60), 0) AS b61_plus,
                      count(*) AS items
                 FROM ar_payments WHERE tenant_id = $1::uuid AND amount - applied_amount > 0.5
                  AND status IN ('unmatched','needs_review','partially_applied','exception')""", tenant)
        ar = await self.pool.fetchrow(
            """SELECT COALESCE(sum(outstanding) FILTER (WHERE status IN ('open','partially_paid','disputed')), 0) AS open_ar,
                      COALESCE(sum(outstanding) FILTER (WHERE status IN ('open','partially_paid') AND due_date < current_date), 0) AS overdue,
                      COALESCE(sum(total_amount) FILTER (WHERE invoice_date >= current_date - 90), 0) AS billed_90,
                      COALESCE(sum(tds_amount), 0) AS tds_receivable,
                      count(*) FILTER (WHERE status IN ('open','partially_paid')) AS open_invoices
                 FROM ar_invoices WHERE tenant_id = $1::uuid""", tenant)
        prev = await self.pool.fetchrow(
            """SELECT COALESCE(sum(amount) FILTER (WHERE status NOT IN ('not_receipt','reversed')), 0) AS receipts_total,
                      count(*) FILTER (WHERE status NOT IN ('not_receipt','reversed')) AS receipts
                 FROM ar_payments WHERE tenant_id = $1::uuid
                  AND received_on >= current_date - 2 * $2::int AND received_on < current_date - $2::int""",
            tenant, days)
        # What was open and what had been billed a month ago, rebuilt from invoice dates and the
        # applications live at the time, so DSO can be compared month on month.
        ar_then = await self.pool.fetchrow(
            """WITH inv AS (
                   SELECT i.id, i.total_amount, i.invoice_date FROM ar_invoices i
                    WHERE i.tenant_id = $1::uuid AND i.status NOT IN ('void','written_off')
                      AND i.invoice_date <= current_date - 30)
               SELECT COALESCE((SELECT sum(total_amount) FROM inv), 0)
                      - COALESCE((SELECT sum(a.amount_applied + a.tds_amount + a.deduction_amount)
                                    FROM ar_applications a JOIN inv ON inv.id = a.invoice_id
                                   WHERE a.tenant_id = $1::uuid AND a.created_at < current_date - 30
                                     AND (a.reversed_at IS NULL OR a.reversed_at >= current_date - 30)), 0) AS open_ar,
                      COALESCE((SELECT sum(total_amount) FROM inv WHERE invoice_date >= current_date - 120), 0) AS billed_90""",
            tenant)
        in_review = await self.pool.fetchval(
            "SELECT COALESCE(sum(amount - applied_amount), 0) FROM ar_payments "
            "WHERE tenant_id = $1::uuid AND status = 'needs_review'", tenant)
        reviewed = await self.pool.fetchrow(
            """SELECT count(*) FILTER (WHERE method = 'accepted') AS accepted,
                      count(*) FILTER (WHERE method IN ('accepted','manual')) AS human
                 FROM ar_applications WHERE tenant_id = $1::uuid AND created_at >= now() - make_interval(days => $2)""",
            tenant, days)
        return {"payments": dict(p), "aging": dict(aging), "ar": dict(ar), "reviewed": dict(reviewed),
                "previous": {**dict(prev), "open_ar": ar_then["open_ar"], "billed_90": ar_then["billed_90"]},
                "unapplied_in_review": in_review,
                "status_counts": await self.status_counts(tenant)}
