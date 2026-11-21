"""Read and write a tenant's recon settings without hand-written SQL.

    python scripts/recon_settings.py list
    python scripts/recon_settings.py show  --tenant <uuid|name>
    python scripts/recon_settings.py set   --tenant <uuid|name> --key rule_profile --value bata
    python scripts/recon_settings.py set   --tenant <uuid|name> --key grn_column_map --json '{"po_number":"PO"}'
    python scripts/recon_settings.py unset --tenant <uuid|name> --key grn_column_map

A settings change here can move money — a rule profile decides whether a rate
above the PO fails, a column mapping decides what counts as received — so every
write goes through `repo.set_recon_setting`, which preserves `enabled` and
records the change in `recon_events`.

`--dry-run` prints what would change and writes nothing.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

KNOWN_KEYS = {
    "rule_profile": "named rule set: default | bata (backend_ocr/app/recon/profiles.py)",
    "grn_column_map": "canonical GRN field -> the column name in this client's extract",
}


def _dsn() -> str:
    for var in ("RECON_DB_URL", "DEV_DB_URL", "DATABASE_URL"):
        if os.getenv(var):
            return os.environ[var].replace("?sslmode=require", "")
    env = pathlib.Path(__file__).resolve().parents[1] / ".env"
    if env.exists():
        for raw in env.read_text(encoding="utf-8", errors="replace").splitlines():
            for var in ("RECON_DB_URL", "DEV_DB_URL", "DATABASE_URL"):
                if raw.strip().startswith(var + "="):
                    v = raw.strip().split("=", 1)[1].strip()
                    v = v[1:-1] if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'" else v
                    return v.replace("?sslmode=require", "")
    raise SystemExit("no database URL: set RECON_DB_URL or DEV_DB_URL")


async def _resolve_tenant(conn, who: str) -> str:
    row = await conn.fetchrow(
        """SELECT tenant_id, legal_name FROM dim_tenants
            WHERE tenant_id::text = $1 OR legal_name ILIKE '%' || $1 || '%'
            ORDER BY (tenant_id::text = $1) DESC LIMIT 2""", who)
    if not row:
        raise SystemExit(f"no tenant matches {who!r}")
    return str(row["tenant_id"]), row["legal_name"]


async def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("action", choices=("list", "show", "set", "unset"))
    ap.add_argument("--tenant")
    ap.add_argument("--key")
    ap.add_argument("--value")
    ap.add_argument("--json", dest="json_value")
    ap.add_argument("--actor", default=os.getenv("USER") or "cli")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    import asyncpg
    from backend_ocr.app.recon.repo import ReconRepository

    pool = await asyncpg.create_pool(_dsn(), min_size=1, max_size=2, ssl="require")
    repo = ReconRepository(pool)
    try:
        if a.action == "list":
            async with pool.acquire() as c:
                rows = await c.fetch(
                    """SELECT t.legal_name, t.tenant_id, ts.enabled, ts.config
                         FROM dim_tenants t
                         LEFT JOIN tenant_service ts
                                ON ts.tenant_id = t.tenant_id AND ts.service_key = 'recon'
                        ORDER BY t.legal_name NULLS LAST""")
            for r in rows:
                cfg = r["config"]
                cfg = json.loads(cfg) if isinstance(cfg, str) else (cfg or {})
                print(f"{(r['legal_name'] or '(unnamed)')[:38]:<38} enabled={str(r['enabled']):<5} {cfg or '{}'}")
            return

        if not a.tenant:
            raise SystemExit("--tenant is required")
        async with pool.acquire() as c:
            tenant, name = await _resolve_tenant(c, a.tenant)
        print(f"tenant: {name} ({tenant})")

        if a.action == "show":
            cfg = await repo.recon_settings(tenant)
            print(json.dumps(cfg, indent=2) if cfg else "(no recon settings)")
            for k, doc in KNOWN_KEYS.items():
                print(f"  {k:<16} {'set' if k in cfg else 'unset':<6} {doc}")
            return

        if not a.key:
            raise SystemExit("--key is required")
        value = None
        if a.action == "set":
            if a.json_value:
                value = json.loads(a.json_value)
            elif a.value is not None:
                value = a.value
            else:
                raise SystemExit("set needs --value or --json")
        before = await repo.recon_settings(tenant)
        print(f"  {a.key}: {before.get(a.key)!r} -> {value!r}")
        if a.key not in KNOWN_KEYS:
            print(f"  note: {a.key!r} is not a key recon reads ({', '.join(KNOWN_KEYS)})")
        if a.dry_run:
            print("dry run, nothing written")
            return
        after = await repo.set_recon_setting(tenant, a.key, value, actor=a.actor)
        print("written. config is now:", json.dumps(after))
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
