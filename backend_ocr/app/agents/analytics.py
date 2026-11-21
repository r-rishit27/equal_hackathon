"""Read-only approval lifecycle reporting for the API and standalone agent."""

from psycopg2.extras import RealDictCursor

from ..config import get_conn, put_conn


def activity_report(tenant: str, brand_id: str | None = None):
    """Summarize approval-chain turnaround and rework per invoice."""
    conn = get_conn()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                WITH ev AS (
                    SELECT
                        c.invoice_id,
                        c.action,
                        c.actor_role,
                        c.created_at,
                        COALESCE(
                            LAG(c.created_at) OVER (
                                PARTITION BY c.invoice_id ORDER BY c.created_at, c.id
                            ),
                            fi.created_at
                        ) AS prev_at
                    FROM bill_approval_chain c
                    JOIN fact_invoices fi
                          ON fi.invoice_id = c.invoice_id
                         AND fi.tenant_id  = c.tenant_id
                    WHERE c.tenant_id = %s
                      AND c.step <> 99
                      AND (%s::uuid IS NULL OR fi.brand_id = %s::uuid)
                ),
                per_role AS (
                    SELECT
                        invoice_id,
                        COALESCE(NULLIF(TRIM(actor_role), ''), 'Unattributed') AS role,
                        SUM(
                            GREATEST(EXTRACT(EPOCH FROM (created_at - prev_at)), 0)
                        ) / 86400.0 AS days
                    FROM ev
                    GROUP BY 1, 2
                ),
                role_json AS (
                    SELECT invoice_id,
                           jsonb_object_agg(role, ROUND(days::numeric, 4)) AS role_days
                    FROM per_role
                    GROUP BY 1
                )
                SELECT
                    ev.invoice_id::text                        AS invoice_id,
                    MIN(ev.created_at)                         AS first_at,
                    MAX(ev.created_at) FILTER (
                        WHERE ev.action IN ('approve', 'approved')
                    )                                          AS approved_at,
                    COUNT(*) FILTER (
                        WHERE ev.action IN ('send_back', 'sent_back', 'reject')
                    )::int                                     AS send_backs,
                    COALESCE(rj.role_days, '{}'::jsonb)        AS role_days
                FROM ev
                LEFT JOIN role_json rj ON rj.invoice_id = ev.invoice_id
                GROUP BY ev.invoice_id, rj.role_days
                """,
                (tenant, brand_id, brand_id),
            )
            rows = cur.fetchall()
    finally:
        put_conn(conn)

    def iso(v):
        return v.isoformat() if v is not None else None

    return {
        "rows": [
            {
                "invoice_id": r["invoice_id"],
                "first_at": iso(r["first_at"]),
                "approved_at": iso(r["approved_at"]),
                "send_backs": r["send_backs"],
                "role_days": r["role_days"] or {},
            }
            for r in rows
        ],
    }
