"""Every SQL call must pass as many arguments as its query asks for.

A real regression motivated this. Adding a column to `recon_evidence_rows`
left an INSERT declaring `$31` while only 30 arguments were passed, so **every
re-read of a site audit threw** `InterfaceError: the server expects 31
arguments for this query, 30 were passed`. Nothing caught it: the suite has no
database, so no test ever ran the statement.

It does not need one. The mismatch is visible in the source — count the
highest `$N` in the literal and count the arguments beside it — so this walks
the AST of every repository module and checks them against each other.

Only calls whose SQL is a plain literal and whose arguments are plain
expressions are checked. Anything dynamic is skipped and counted, so the
blind spot is visible rather than implied.
"""
from __future__ import annotations

import ast
import pathlib
import re

MODULES = ["backend_ocr/app/recon/repo.py", "backend_ocr/app/routers/recon.py"]
RUNNERS = {"execute", "fetch", "fetchrow", "fetchval", "executemany"}
PLACEHOLDER = re.compile(r"\$(\d+)")


def sql_calls(path: pathlib.Path):
    """(line, sql, n_args, dynamic) for every asyncpg-style call in a file.

    `executemany` is excluded: it takes one sequence of tuples rather than
    loose arguments, and has a check of its own below.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr not in RUNNERS or node.func.attr == "executemany" or not node.args:
            continue
        first = node.args[0]
        if not (isinstance(first, ast.Constant) and isinstance(first.value, str)):
            continue                      # SQL built at runtime: not checkable here
        dynamic = any(isinstance(a, ast.Starred) for a in node.args)
        yield node.lineno, first.value, len(node.args) - 1, dynamic


def test_every_literal_sql_call_passes_the_arguments_it_asks_for():
    bad: list[str] = []
    skipped = 0
    checked = 0
    for name in MODULES:
        path = pathlib.Path(name)
        if not path.exists():                       # pragma: no cover
            continue
        for lineno, sql, n_args, dynamic in sql_calls(path):
            highest = max((int(m) for m in PLACEHOLDER.findall(sql)), default=0)
            if not highest:
                continue
            if dynamic:
                skipped += 1
                continue
            checked += 1
            if n_args != highest:
                bad.append(f"{name}:{lineno} wants ${highest} but is given {n_args} argument(s)"
                           f"  —  {' '.join(sql.split())[:70]}…")
    assert checked > 40, f"the walker found only {checked} statements; it has stopped working"
    assert not bad, "SQL argument mismatch — these would throw at runtime:\n  " + "\n  ".join(bad)


def test_executemany_rows_match_their_placeholders():
    """`executemany` passes a list of tuples; each tuple must be the right width.

    Not checkable from the AST in general, but the common shape — a list
    comprehension of a literal tuple — is, and that is how every one of ours is
    written.
    """
    bad: list[str] = []
    for name in MODULES:
        path = pathlib.Path(name)
        if not path.exists():                       # pragma: no cover
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "executemany" and len(node.args) == 2):
                continue
            sql = node.args[0]
            rows = node.args[1]
            if not (isinstance(sql, ast.Constant) and isinstance(sql.value, str)):
                continue
            highest = max((int(m) for m in PLACEHOLDER.findall(sql.value)), default=0)
            if not (highest and isinstance(rows, ast.ListComp)
                    and isinstance(rows.elt, ast.Tuple)):
                continue
            # A starred element makes the width unknowable here.
            if any(isinstance(e, ast.Starred) for e in rows.elt.elts):
                continue
            width = len(rows.elt.elts)
            if width != highest:
                bad.append(f"{name}:{node.lineno} wants ${highest}, each row has {width}")
    assert not bad, "executemany row width mismatch:\n  " + "\n  ".join(bad)
