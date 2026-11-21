"""Refresh the public schema reference from the project's default development database."""

import os
from collections import defaultdict
from datetime import date
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
DOCUMENT = ROOT / "docs/full_database_schema.md"
APPENDIX = "## Appendix scope"


def code(value):
    return "`" + str(value).replace("|", r"\|") + "`"


def grouped(cursor, query):
    cursor.execute(query)
    groups = defaultdict(list)
    for key, *values in cursor.fetchall():
        groups[key].append(values)
    return groups


def main():
    load_dotenv(ROOT / ".env")
    previous = DOCUMENT.read_text(encoding="utf-8")
    _, marker, appendix = previous.partition("\n" + APPENDIX + "\n")
    if not marker:
        raise ValueError("Missing licensing appendix boundary")

    with psycopg2.connect(os.environ["DEV_DB_URL"], connect_timeout=10) as db:
        db.set_session(readonly=True, isolation_level="REPEATABLE READ")
        with db.cursor() as cur:
            cur.execute("SELECT current_database(), current_setting('server_version')")
            database, version = cur.fetchone()
            if database != "onsumm_db":
                raise ValueError("DEV_DB_URL must point to onsumm_db for this reference")
            cur.execute("""
                SELECT oid, relname FROM pg_class
                WHERE relnamespace = 'public'::regnamespace AND relkind IN ('r', 'p')
                ORDER BY relname
            """)
            tables = cur.fetchall()
            enums = grouped(cur, """
                SELECT typname, enumlabel FROM pg_enum JOIN pg_type ON pg_type.oid = enumtypid
                WHERE typnamespace = 'public'::regnamespace ORDER BY typname, enumsortorder
            """)
            columns = grouped(cur, """
                SELECT c.oid, a.attname, format_type(a.atttypid, a.atttypmod), a.attnotnull,
                       pg_get_expr(d.adbin, d.adrelid), a.attidentity, a.attgenerated
                FROM pg_class c JOIN pg_attribute a ON a.attrelid = c.oid
                LEFT JOIN pg_attrdef d ON d.adrelid = c.oid AND d.adnum = a.attnum
                WHERE c.relnamespace = 'public'::regnamespace AND c.relkind IN ('r', 'p')
                  AND a.attnum > 0 AND NOT a.attisdropped ORDER BY c.oid, a.attnum
            """)
            constraints = grouped(cur, """
                SELECT conrelid, conname, pg_get_constraintdef(oid) FROM pg_constraint
                WHERE connamespace = 'public'::regnamespace ORDER BY conrelid, conname
            """)
            indexes = grouped(cur, """
                SELECT i.indrelid, c.relname, pg_get_indexdef(c.oid)
                FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid
                WHERE c.relnamespace = 'public'::regnamespace ORDER BY i.indrelid, c.relname
            """)

    out = ["# Full Database Schema Documentation", "",
           f"Snapshot of the `public` schema in `{database}` on {date.today():%d %B %Y} "
           f"(PostgreSQL {version}). The schema contains {len(tables)} tables and "
           f"{len(enums)} enum types. The default development connection is `DEV_DB_URL`.",
           "", "## Enum Types", ""]
    for name, labels in enums.items():
        out.extend([f"### {code(name)}", "", ", ".join(code(label) for label, in labels), ""])
    for oid, name in tables:
        out.extend([f"## Table: {code(name)}", "", "### Columns", "",
                    "| Column | Type | Nullable | Default or generation expression |",
                    "|---|---|---|---|"])
        for col, typ, required, expr, identity, generated in columns[oid]:
            if identity:
                mode = "ALWAYS" if identity == "a" else "BY DEFAULT"
                expr = f"GENERATED {mode} AS IDENTITY"
            elif generated:
                storage = "STORED" if generated == "s" else "VIRTUAL"
                expr = f"GENERATED ALWAYS AS ({expr}) {storage}"
            out.append(f"| {code(col)} | {code(typ)} | {'NO' if required else 'YES'} | "
                       f"{code(expr) if expr is not None else 'None'} |")
        for title, records in [("Keys and Constraints", constraints[oid]), ("Indexes", indexes[oid])]:
            out.extend(["", f"### {title}", ""])
            out.extend([f"- {code(key)} - {code(definition)}" for key, definition in records] or ["None."])
        out.extend(["", "---", ""])

    DOCUMENT.write_text("\n".join(out) + marker + appendix, encoding="utf-8")
    print(f"Documented {len(tables)} tables and {len(enums)} enum types from {database}")


if __name__ == "__main__":
    main()
