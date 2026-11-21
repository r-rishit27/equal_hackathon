#!/usr/bin/env python3
"""Read spreadsheets already in vendors' Documents into vendor_doc_rows.

New uploads are parsed as they arrive (backend_ocr/app/core/vendor_doc_tables.py).
This fills in the .xlsx / .xlsm / .csv files uploaded before that, and any left
PENDING because the API restarted mid-parse. Run after
scripts/run_api_migrations.py has created the tables.

    python3 scripts/backfill_vendor_doc_tables.py            # parse what isn't parsed
    python3 scripts/backfill_vendor_doc_tables.py --dry-run  # list them only
    python3 scripts/backfill_vendor_doc_tables.py --all      # re-parse every spreadsheet

Idempotent: a document's rows are replaced, never duplicated.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend_ocr.app.config import get_conn, put_conn  # noqa: E402
from backend_ocr.app.core import object_store  # noqa: E402
from backend_ocr.app.core.vendor_doc_tables import SPREADSHEET_EXTS, store_tables  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--all", action="store_true", help="re-parse documents already PARSED too")
    args = ap.parse_args()

    like = " OR ".join("lower(file_name) LIKE %s" for _ in SPREADSHEET_EXTS)
    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute(
            f"""SELECT id, tenant_id, supplier_id, file_name, file_path FROM vendor_documents
                 WHERE deleted_at IS NULL AND ({like})
                   AND (%s OR data_status IS NULL OR data_status <> 'PARSED')
                 ORDER BY uploaded_at""",
            [f"%{e}" for e in SPREADSHEET_EXTS] + [args.all])
        docs = cur.fetchall()
    put_conn(conn)

    print(f"{len(docs)} spreadsheet(s) to read")
    done = missing = 0
    for doc_id, tenant, supplier, name, path in docs:
        if args.dry_run:
            print(f"  would read {name} ({doc_id})")
            continue
        content = object_store.load(path)
        if content is None:
            # A pre-S3 file on another server's disk: not readable from here.
            print(f"  skip {name} ({doc_id}): file not on this server")
            missing += 1
            continue
        n = store_tables(str(doc_id), str(tenant), str(supplier), name, content)
        print(f"  {name}: {n} rows")
        done += 1
    if not args.dry_run:
        print(f"read {done}, file missing {missing}")


if __name__ == "__main__":
    main()
