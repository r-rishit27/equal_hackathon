"""Coordinate invoice automation and provide an advisory bill preflight."""

import logging

from psycopg2.extras import RealDictCursor

from ..config import get_conn, put_conn
from . import fact_graph
from .invoice_checks import evaluate

logger = logging.getLogger(__name__)


def on_invoice_saved(tenant_id, supplier_id, invoice_id):
    """Dispatch existing post-ingest agents once the bill is committed."""
    from ..recon.hooks import bill_arrived

    try:
        fact_graph.enqueue(fact_graph.enrich_bill, tenant_id, invoice_id)
    except Exception:
        logger.warning("Could not schedule bill graph enrichment", exc_info=True)
    bill_arrived(tenant_id, supplier_id, invoice_id)


def _read_bills(tenant_id, brand_id, invoice_id=None):
    conn = get_conn()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT i.invoice_id::text, i.supplier_id::text, i.invoice_number, i.total_amount,
                       i.currency_code, i.status, i.payment_status, i.due_date,
                       s.name AS vendor_name, s.gstn
                FROM fact_invoices i
                LEFT JOIN dim_suppliers s
                  ON s.tenant_id = i.tenant_id AND s.supplier_id = i.supplier_id
                WHERE i.tenant_id = %s
                  AND (%s::uuid IS NULL OR i.brand_id = %s::uuid)
                  AND (%s::uuid IS NULL OR i.invoice_id = %s::uuid)
                ORDER BY i.created_at DESC NULLS LAST, i.invoice_id
                LIMIT 25
                """,
                (tenant_id, brand_id, brand_id, invoice_id, invoice_id),
            )
            return cur.fetchall()
    finally:
        put_conn(conn)


def recent_bills(tenant_id, brand_id):
    return [
        {key: row[key] for key in ("invoice_id", "supplier_id", "invoice_number", "vendor_name")}
        for row in _read_bills(tenant_id, brand_id)
    ]


def preflight(tenant_id, brand_id, invoice_id):
    rows = _read_bills(tenant_id, brand_id, invoice_id)
    return evaluate(rows[0]) if rows else None
