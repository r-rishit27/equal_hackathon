"""Check every number docs/reconciliation/STRESS_TESTING.md asserts against the live state.

A record of a stress test is only worth having if its figures are still true.
This prints each claim beside what dev and the source actually say, and exits
non-zero when any has drifted, so the document can be re-checked in one command
instead of audited by hand. The first such pass found three stale counts.

Run from the repository root:  python scripts/verify_stress_doc.py
"""
import asyncio
import ast
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(".").resolve()))
import asyncpg                                                    # noqa: E402


def url() -> str:
    for raw in pathlib.Path(".env").read_text(encoding="utf-8", errors="replace").splitlines():
        if raw.strip().startswith("DEV_DB_URL="):
            v = raw.strip().split("=", 1)[1].strip()
            v = v[1:-1] if v and v[0] in "\"'" else v
            return v.replace("?sslmode=require", "")
    raise SystemExit("DEV_DB_URL not found")


def ok(claim: str, actual, expected) -> bool:
    good = actual == expected
    print(f"  {'ok  ' if good else 'WRONG'} {claim}: doc says {expected}, actual {actual}")
    return good


async def main() -> None:
    c = await asyncpg.connect(url(), ssl="require")
    bad = 0

    # §1.1 key distribution
    dist = {(r["key_basis"], float(r["key_confidence"])): r["n"] for r in await c.fetch(
        """SELECT key_basis, key_confidence, count(*) n FROM recon_evidence_rows
            WHERE key_basis IS NOT NULL GROUP BY 1, 2""")}
    bad += not ok("ASSET_CODE 0.99 rows", dist.get(("ASSET_CODE", 0.99)), 45)
    bad += not ok("ORDINAL 0.40 rows", dist.get(("ORDINAL", 0.4)), 13)
    bad += not ok("PRINTED_NO 0.95 rows", dist.get(("PRINTED_NO", 0.95)), 176)
    bad += not ok("crossed basis/confidence", await c.fetchval(
        """SELECT count(*) FROM recon_evidence_rows
            WHERE key_basis = 'ORDINAL' AND key_confidence >= 0.80
               OR (key_basis <> 'ORDINAL' AND key_confidence < 0.80)"""), 0)

    # §1.3 / §7 shared uploads
    bad += not ok("uploads shared by several bills", await c.fetchval(
        """SELECT count(*) FROM (SELECT upload_id FROM fact_invoices WHERE upload_id IS NOT NULL
                                  GROUP BY 1 HAVING count(*) > 1) x"""), 26)
    bad += not ok("invoice numbers with two live bills", await c.fetchval(
        """SELECT count(*) FROM (SELECT supplier_id, invoice_number FROM fact_invoices
             WHERE soft_status <> 'deleted' AND invoice_number IS NOT NULL
             GROUP BY 1,2 HAVING count(*) > 1) x"""), 44)

    # §1.4 no doubled cases
    bad += not ok("cases with duplicated line rows", await c.fetchval(
        """SELECT count(*) FROM (SELECT case_id FROM recon_line_results
                                  GROUP BY case_id, ord HAVING count(*) > 1) x"""), 0)

    # §2.10 audit trail
    bad += not ok("cases on dev", await c.fetchval("SELECT count(*) FROM recon_cases"), 3)
    bad += not ok("cases with a fingerprint", await c.fetchval(
        "SELECT count(*) FROM recon_cases WHERE input_fingerprint IS NOT NULL"), 3)
    bad += not ok("distinct check codes", await c.fetchval(
        "SELECT count(DISTINCT code) FROM recon_header_checks"), 12)
    bad += not ok("distinct line statuses", await c.fetchval(
        """SELECT count(DISTINCT s) FROM (
             SELECT jsonb_array_elements_text(result -> 'statuses') s
               FROM recon_line_results) x"""), 14)

    # §6 litter
    bad += not ok("probe rows in the decision log", await c.fetchval(
        """SELECT count(*) FROM recon_decisions
            WHERE kind IN ('race_probe', 'STRESS_PROBE', 'QTY_CORRECTED')"""), 10)

    # §4 method counts, from the source
    repo = pathlib.Path("backend_ocr/app/recon/repo.py")
    names = []
    for node in ast.walk(ast.parse(repo.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ClassDef) and node.name == "ReconRepository":
            names += [i.name for i in node.body
                      if isinstance(i, (ast.FunctionDef, ast.AsyncFunctionDef))
                      and not i.name.startswith("__")]
    bad += not ok("methods on ReconRepository", len(names), 83)

    await c.close()
    print(f"\n{bad} claim(s) wrong" if bad else "\nevery checked claim holds")
    return bad


raise SystemExit(asyncio.run(main()))
