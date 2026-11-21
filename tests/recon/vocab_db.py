"""Apply the recon vocabulary (codes, aliases, generated code columns, foreign keys) to a test database,
the same way migrations._ensure_recon_tables does after the recon DDL."""
from __future__ import annotations


def apply_vocab(db_url: str) -> dict:
    import psycopg2

    from backend_ocr.app.recon import vocab
    conn = psycopg2.connect(db_url)
    try:
        with conn.cursor() as cur:
            # The recon tables were just dropped and recreated: forget the mapping version so the
            # generated columns are rebuilt on them.
            cur.execute("CREATE TABLE IF NOT EXISTS vocab_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL, "
                        "at TIMESTAMPTZ NOT NULL DEFAULT now())")
            cur.execute("DELETE FROM vocab_meta WHERE key = 'mapping_version'")
            stats = vocab.sync(cur)
        conn.commit()
        return stats
    finally:
        conn.close()
