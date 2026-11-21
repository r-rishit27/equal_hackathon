#!/usr/bin/env python3
"""Queue contracts to be read again by the contract reader.

  * Scanned contracts that were skipped for having no text layer
    (claims_status='SKIPPED', claims_error='no usable text layer'): the reader
    now transcribes scans with vision.
  * With --reread, also contracts already read by an older prompt version than
    the current one (comm_extract.PROMPT_VERSION) — e.g. read before commercial
    terms (fees, payment conditions, notice periods) were extracted.

Each contract costs a gpt-4o call (~$0.03), and a scan a vision call per page
on top (~$0.01 a page, up to config.MAX_PDF_PAGES pages). Re-reading a
contract writes a new extraction; the panel shows the newest, and terms
already applied to the vendor show as on file again.

    python3.11 scripts/requeue_scanned_contracts.py --dry-run           # list skipped scans
    python3.11 scripts/requeue_scanned_contracts.py                     # queue them
    python3.11 scripts/requeue_scanned_contracts.py --reread --dry-run  # + contracts read by an older prompt
    python3.11 scripts/requeue_scanned_contracts.py --reread

The API's contract worker picks them up (immediately via NOTIFY, else on its
safety poll).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend_ocr.app.config import get_conn, put_conn  # noqa: E402
from backend_ocr.app.review.comm_extract import PROMPT_VERSION  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--reread", action="store_true",
                    help=f"also re-read contracts last read by a prompt other than {PROMPT_VERSION}")
    args = ap.parse_args()
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT d.id, d.file_name, d.claims_status
                  FROM vendor_documents d
                 WHERE d.deleted_at IS NULL AND d.doc_type = 'contract'
                   AND (
                        (d.claims_status = 'SKIPPED' AND d.claims_error = 'no usable text layer')
                     OR (%s AND d.claims_status = 'DONE' AND COALESCE((
                            SELECT e.prompt_version FROM comm_extractions e
                             WHERE e.source_type = 'contract' AND e.source_id = d.id
                             ORDER BY e.created_at DESC LIMIT 1), '') <> %s)
                   )
                 ORDER BY d.uploaded_at
            """, (args.reread, PROMPT_VERSION))
            docs = cur.fetchall()
            print(f"{len(docs)} contract(s) to read")
            for doc_id, name, status in docs:
                print(f"  {name} ({doc_id}) — {'skipped scan' if status == 'SKIPPED' else 'read by an older prompt'}")
            if args.dry_run or not docs:
                return
            cur.execute("""
                UPDATE vendor_documents SET claims_status = 'PENDING', claims_error = NULL
                 WHERE id = ANY(%s::uuid[])
            """, ([str(d[0]) for d in docs],))
            for doc_id, _, _ in docs:
                cur.execute("SELECT pg_notify('ch_comm_extract', %s)", (str(doc_id),))
        conn.commit()
        print("queued")
    finally:
        put_conn(conn)


if __name__ == "__main__":
    main()
