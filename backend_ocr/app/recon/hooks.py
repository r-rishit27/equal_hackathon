"""Small sync hooks other parts of the app call into recon. Never raise."""
from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)


def bill_arrived(tenant_id, supplier_id, invoice_id) -> None:
    """Called after a bill is ingested. If the supplier has recon documents,
    queue a relink and wake the recon worker (05_USER_FLOWS.md F8)."""
    if not (tenant_id and supplier_id):
        return
    try:
        from ..config import get_conn, put_conn
        conn = get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT to_regclass('recon_doc_segments') IS NOT NULL")
                if not cur.fetchone()[0]:
                    return
                cur.execute("SELECT 1 FROM recon_doc_segments WHERE tenant_id = %s AND supplier_id = %s LIMIT 1",
                            (str(tenant_id), str(supplier_id)))
                if cur.fetchone() is None:
                    return
                payload = json.dumps({"supplier_id": str(supplier_id), "bill_id": str(invoice_id) if invoice_id else None})
                cur.execute("INSERT INTO recon_events (tenant_id, kind, payload) VALUES (%s, 'bill_arrived', %s::jsonb)",
                            (str(tenant_id), payload))
                cur.execute("SELECT pg_notify('recon_docs', %s)", (json.dumps({"kind": "bill"}),))
            conn.commit()
        finally:
            put_conn(conn)
    except Exception:
        logger.debug("[recon] bill_arrived hook skipped", exc_info=True)
