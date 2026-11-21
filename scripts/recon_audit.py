"""Audit a recon database, and the SQL that talks to it.

Written during the stress run in `STRESS_TESTING.md`, where each of these
checks found something. They are here so the next person can run them instead
of rediscovering them.

Every check is phrased so that **a non-zero count is a finding**, and prints a
line saying what would be wrong — the output is meant to be readable by
somebody who did not write it.

    python scripts/recon_audit.py                 # integrity + schema drift
    python scripts/recon_audit.py --dsn "$DEV_DB_URL"
    python scripts/recon_audit.py --code-only     # no database needed

Read-only. It never writes.
"""
from __future__ import annotations

import argparse
import ast
import asyncio
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

SOURCES = ["backend_ocr/app/recon/repo.py", "backend_ocr/app/routers/recon.py"]

# ── integrity: what must never be true of the data ────────────────────────────
CHECKS: list[tuple[str, str, str]] = [
    ("case points at a bill that does not exist",
     "a reconciliation about nothing; the case cannot resolve its invoice",
     """SELECT count(*) FROM recon_cases rc
         WHERE rc.bill_id IS NOT NULL
           AND NOT EXISTS (SELECT 1 FROM fact_invoices fi WHERE fi.invoice_id = rc.bill_id)"""),
    ("case points at a soft-deleted bill",
     "a withdrawn bill still carrying a reconciliation — flagged in the UI, not hidden",
     """SELECT count(*) FROM recon_cases rc JOIN fact_invoices fi ON fi.invoice_id = rc.bill_id
         WHERE fi.soft_status = 'deleted'"""),
    ("one upload shared by several bill rows",
     "re-uploading an invoice makes a second bill row on the same upload",
     """SELECT count(*) FROM (SELECT upload_id FROM fact_invoices WHERE upload_id IS NOT NULL
                              GROUP BY 1 HAVING count(*) > 1) x"""),
    ("line results outnumber their lines",
     "two recomputes raced; every line is stored twice and so is every sum over them",
     """SELECT count(*) FROM (SELECT case_id FROM recon_line_results
                              GROUP BY case_id, ord HAVING count(*) > 1) x"""),
    ("orphaned line result",
     "a verdict whose case is gone: a cascade failed or a delete bypassed it",
     """SELECT count(*) FROM recon_line_results lr
         WHERE NOT EXISTS (SELECT 1 FROM recon_cases rc WHERE rc.id = lr.case_id)"""),
    ("orphaned header check",
     "a check whose case is gone",
     """SELECT count(*) FROM recon_header_checks h
         WHERE NOT EXISTS (SELECT 1 FROM recon_cases rc WHERE rc.id = h.case_id)"""),
    ("case segment pointing at a missing segment",
     "a case attached to a document part that no longer exists",
     """SELECT count(*) FROM recon_case_segments cs
         WHERE NOT EXISTS (SELECT 1 FROM recon_doc_segments s WHERE s.id = cs.segment_id)"""),
    ("segment attached to a case but its document is deleted",
     "a case showing a document the user removed",
     """SELECT count(*) FROM recon_case_segments cs
          JOIN recon_doc_segments s ON s.id = cs.segment_id
          JOIN vendor_documents d ON d.id = s.doc_id
         WHERE d.deleted_at IS NOT NULL"""),
    ("key basis and confidence disagree",
     "a row claiming to be identified by a printed code while scored as positional",
     """SELECT count(*) FROM recon_evidence_rows
         WHERE key_basis = 'ORDINAL' AND key_confidence >= 0.80
            OR (key_basis <> 'ORDINAL' AND key_confidence < 0.80)"""),
    ("decision resting on an untrusted key",
     "a reviewer's decision keyed to an identity that may not carry one unattended",
     """SELECT count(*) FROM recon_decisions d
          JOIN recon_evidence_rows e ON e.line_uid = d.line_uid
         WHERE e.key_confidence < 0.80"""),
    ("document stuck mid-read",
     "a crashed worker left it RUNNING with nothing to retry it",
     """SELECT count(*) FROM vendor_documents
         WHERE recon_status = 'RUNNING' AND uploaded_at < now() - interval '1 hour'"""),
    ("stored risk with no line to justify it",
     "a stale verdict: the summary was not recomputed after the lines changed",
     """SELECT count(*) FROM recon_cases rc
         WHERE rc.money_at_risk IS NOT NULL AND rc.money_at_risk <> 0
           AND NOT EXISTS (SELECT 1 FROM recon_line_results lr
                            WHERE lr.case_id = rc.id AND (lr.result ->> 'delta')::numeric > 0)"""),
]

INSERT = re.compile(r"INSERT\s+INTO\s+([a-z_]+)\s*\(([^)]*)\)", re.I | re.S)
UPDATE_SET = re.compile(r"UPDATE\s+([a-z_]+)\s+SET\s+(.+?)(?:\s+WHERE|\s*$)", re.I | re.S)
ASSIGN = re.compile(r"([a-z_]+)\s*=")
NOT_A_COLUMN = {"now", "true", "false", "null", "coalesce", "excluded"}


def _literals(path: pathlib.Path):
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and len(node.value) > 20:
            yield node.lineno, node.value


def dead_methods() -> tuple[list[str], list[tuple[str, int]]]:
    """Repository methods nothing calls, and ones no test calls.

    The second list is where the next silent breakage will be: both save-path
    bugs in STRESS_TESTING.md §1.5 lived in methods with callers and no tests.
    """
    repo = ROOT / "backend_ocr/app/recon/repo.py"
    app = list((ROOT / "backend_ocr").rglob("*.py")) + list((ROOT / "scripts").rglob("*.py"))
    tests = list((ROOT / "tests").rglob("*.py"))
    names: list[str] = []
    for node in ast.walk(ast.parse(repo.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ClassDef) and node.name == "ReconRepository":
            names += [i.name for i in node.body
                      if isinstance(i, (ast.FunctionDef, ast.AsyncFunctionDef))
                      and not i.name.startswith("__")]

    def hits(name: str, files, skip=None) -> int:
        pat = re.compile(rf"\.{re.escape(name)}\s*\(")
        n = 0
        for f in files:
            if skip and f.resolve() == skip.resolve():
                continue
            n += len(pat.findall(f.read_text(encoding="utf-8", errors="replace")))
        return n

    dead, untested = [], []
    for m in sorted(names):
        a, r, t = hits(m, app, skip=repo), hits(m, [repo]), hits(m, tests)
        if not (a or r or t):
            dead.append(m)
        elif not t:
            untested.append((m, a + r))
    return dead, untested


async def run_db(dsn: str) -> int:
    import asyncpg
    c = await asyncpg.connect(dsn, ssl="require" if "localhost" not in dsn else None)
    findings = 0
    print("integrity")
    for name, why, sql in CHECKS:
        try:
            n = await c.fetchval(sql)
        except Exception as exc:                                  # noqa: BLE001
            print(f"  ??   {name}: {type(exc).__name__}: {str(exc)[:60]}")
            continue
        print(f"  {'FAIL' if n else 'ok  '} {name}: {n}")
        if n:
            findings += 1
            print(f"       -> {why}")

    print("\nschema drift — every column our SQL names must exist")
    cols: dict[str, set[str]] = {}
    for r in await c.fetch("SELECT table_name, column_name FROM information_schema.columns "
                           "WHERE table_schema = 'public'"):
        cols.setdefault(r["table_name"], set()).add(r["column_name"])
    checked, bad = 0, []
    for name in SOURCES:
        path = ROOT / name
        if not path.exists():
            continue
        for lineno, sql in _literals(path):
            for table, collist in INSERT.findall(sql):
                if table not in cols:
                    bad.append(f"{name}:{lineno} no such table {table}")
                    continue
                named = {x.strip() for x in collist.replace("\n", " ").split(",") if x.strip()}
                checked += len(named)
                if miss := sorted(x for x in named if x not in cols[table]):
                    bad.append(f"{name}:{lineno} {table} has no column(s): {', '.join(miss)}")
            for table, sets in UPDATE_SET.findall(sql):
                if table not in cols:
                    continue
                named = {m for m in ASSIGN.findall(sets)} - NOT_A_COLUMN
                checked += len(named)
                if miss := sorted(x for x in named if x not in cols[table]):
                    bad.append(f"{name}:{lineno} UPDATE {table} sets unknown: {', '.join(miss)}")
    print(f"  {checked} column references checked")
    for b in bad:
        print("  FAIL " + b)
    findings += len(bad)
    await c.close()
    return findings


def run_code() -> None:
    dead, untested = dead_methods()
    print("\ncode paths")
    print(f"  repository methods nothing calls: {len(dead)}")
    for m in dead:
        print(f"     {m}")
    print(f"  methods with callers but no test: {len(untested)}")
    for m, n in sorted(untested, key=lambda t: -t[1])[:10]:
        print(f"     {m:32} {n} call site(s)")
    if len(untested) > 10:
        print(f"     … and {len(untested) - 10} more")
    print("  (SQL arity and row width are guarded by tests/recon/test_sql_arity.py)")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dsn", help="database to audit; defaults to DEV_DB_URL in .env")
    ap.add_argument("--code-only", action="store_true", help="skip the database checks")
    args = ap.parse_args()

    findings = 0
    if not args.code_only:
        dsn = args.dsn
        if not dsn:
            for raw in (ROOT / ".env").read_text(encoding="utf-8", errors="replace").splitlines():
                if raw.strip().startswith("DEV_DB_URL="):
                    v = raw.strip().split("=", 1)[1].strip()
                    dsn = (v[1:-1] if v and v[0] in "\"'" else v).replace("?sslmode=require", "")
        if not dsn:
            sys.exit("no DSN: pass --dsn or set DEV_DB_URL in .env")
        findings = asyncio.run(run_db(dsn))
    run_code()
    print(f"\n{findings} data finding(s)")
    sys.exit(1 if findings else 0)


if __name__ == "__main__":
    main()
