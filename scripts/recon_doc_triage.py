"""Find recon documents whose stored file cannot be read, and label them honestly.

    python scripts/recon_doc_triage.py                 # report only (default)
    python scripts/recon_doc_triage.py --fix           # rewrite their error text
    python scripts/recon_doc_triage.py --fix --tenant <uuid|name>

A document whose bytes live on another machine is **not** a parsing failure, but
it looks exactly like one in the Needs-you list — so people press "Read again"
on a file that can never be read from here. This marks those rows with the real
reason instead.

Nothing is deleted and no file_path is altered: if the bytes are later copied to
S3, re-pointing the ref is a separate, deliberate step. `--fix` only rewrites
`recon_error`, which is display text.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))


def _dsn() -> str:
    for var in ("RECON_DB_URL", "DEV_DB_URL", "DATABASE_URL"):
        if os.getenv(var):
            return os.environ[var].replace("?sslmode=require", "")
    env = pathlib.Path(__file__).resolve().parents[1] / ".env"
    for raw in env.read_text(encoding="utf-8", errors="replace").splitlines():
        for var in ("RECON_DB_URL", "DEV_DB_URL", "DATABASE_URL"):
            if raw.strip().startswith(var + "="):
                v = raw.strip().split("=", 1)[1].strip()
                v = v[1:-1] if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'" else v
                return v.replace("?sslmode=require", "")
    raise SystemExit("no database URL: set RECON_DB_URL or DEV_DB_URL")


async def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fix", action="store_true", help="rewrite recon_error for unreadable documents")
    ap.add_argument("--tenant", help="limit to one tenant (uuid or name fragment)")
    a = ap.parse_args()

    import asyncpg
    from backend_ocr.app.core import object_store

    pool = await asyncpg.create_pool(_dsn(), min_size=1, max_size=2, ssl="require")
    try:
        async with pool.acquire() as c:
            tenant = None
            if a.tenant:
                row = await c.fetchrow(
                    """SELECT tenant_id, legal_name FROM dim_tenants
                        WHERE tenant_id::text = $1 OR legal_name ILIKE '%' || $1 || '%' LIMIT 1""", a.tenant)
                if not row:
                    raise SystemExit(f"no tenant matches {a.tenant!r}")
                tenant = str(row["tenant_id"])
                print(f"tenant: {row['legal_name']} ({tenant})")

            rows = await c.fetch(
                """SELECT d.id, d.tenant_id, d.file_name, d.file_path, d.recon_status, d.recon_error,
                          d.uploaded_at
                     FROM vendor_documents d
                    WHERE d.doc_type = 'recon' AND d.deleted_at IS NULL
                      AND ($1::uuid IS NULL OR d.tenant_id = $1::uuid)
                    ORDER BY d.uploaded_at DESC""", tenant)

            unreadable, ok = [], 0
            for r in rows:
                why = object_store.unreadable_here(r["file_path"])
                if why:
                    unreadable.append((r, why))
                else:
                    ok += 1

            print(f"\n{len(rows)} recon documents · {ok} readable · {len(unreadable)} unreadable")
            for r, why in unreadable:
                kind = "s3" if str(r["file_path"] or "").startswith("s3://") else "local path"
                print(f"\n  {r['file_name'][:42]}  [{r['recon_status']}]  ({kind})")
                print(f"     stored at: {str(r['file_path'])[:90]}")
                print(f"     reason:    {why[:88]}")
                print(f"     shows now: {str(r['recon_error'])[:88]}")

            if not unreadable:
                print("\nNothing to do.")
                return
            if not a.fix:
                print("\nReport only. Re-run with --fix to rewrite their error text "
                      "(nothing is deleted, no file_path changes).")
                return

            n = 0
            for r, why in unreadable:
                if (r["recon_error"] or "") == why:
                    continue
                await c.execute(
                    """UPDATE vendor_documents SET recon_status = 'FAILED', recon_error = $2
                        WHERE id = $1::uuid""", r["id"], why)
                await c.execute(
                    """INSERT INTO recon_events (tenant_id, doc_id, kind, payload, actor)
                       VALUES ($1::uuid, $2::uuid, 'doc_triaged', $3::jsonb, 'cli')""",
                    str(r["tenant_id"]), str(r["id"]),
                    __import__("json").dumps({"was": r["recon_error"], "now": why}))
                n += 1
            print(f"\nRelabelled {n} document(s). Their rows and files are untouched.")
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
