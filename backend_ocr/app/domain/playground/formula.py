"""Evaluating the expressions people write in a Formula node.

A hand-written tokeniser and recursive-descent parser, deliberately, rather
than `eval` or `simpleeval`. These expressions arrive from a text box in the
browser and are stored per tenant, so anything that reaches a Python
interpreter is a remote-code-execution path wearing a spreadsheet costume.
Here the only things that exist are numbers, strings, names, the five
arithmetic operators, comparisons, and a fixed table of functions — there is
no attribute access, no indexing into Python objects, no call to anything the
table does not name.

The language is what a finance team already writes:

    ratecard["Bill Rate"] / ratecard["Working Days in Month"] * ratecard["No of Days"]
    GR@100% * 0.952
    (1 - contract["% Routing"]) * sum(GR@100%)

Names may contain spaces, `@` and `%`, because real column names do
("GR@100%", "% Routing", "Total GR"). That is why names are resolved against a
known set supplied by the caller instead of being lexed by a general rule: with
spaces allowed, `Total GR / 2` is otherwise indistinguishable from two names.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Iterable, Sequence


class FormulaError(ValueError):
    """Raised with a message meant for the person who wrote the expression."""


# ── numbers ─────────────────────────────────────────────────────────────────

def _num(v: Any) -> float | None:
    """A cell's value as a number, or None when it is not one.

    Spreadsheet values arrive as text more often than not — "1,652", "₹95,000",
    "22 days" — so the common formats are accepted rather than turning the
    whole row into an error.
    """
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v) if not isinstance(v, bool) else None
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return None
        s = s.replace(",", "").replace("₹", "").replace("$", "").strip()
        s = re.sub(r"[%\s]+$", "", s)
        try:
            return float(Decimal(s))
        except (InvalidOperation, ValueError):
            return None
    return None


def _need_num(v: Any, where: str) -> float:
    n = _num(v)
    if n is None:
        raise FormulaError(f"{where} is not a number ({v!r})")
    return n


# ── functions ───────────────────────────────────────────────────────────────

def _flatten(args: Sequence[Any]) -> list[Any]:
    out: list[Any] = []
    for a in args:
        if isinstance(a, (list, tuple)):
            out.extend(a)
        else:
            out.append(a)
    return out


def _nums(args: Sequence[Any]) -> list[float]:
    return [n for n in (_num(a) for a in _flatten(args)) if n is not None]


def _safe_div(a: float, b: float) -> float:
    if b == 0:
        # A zero divisor is a data problem, not an expression problem — a rate
        # card with no working days in the month, say — so it is named as such.
        raise FormulaError("division by zero")
    return a / b


FUNCS: dict[str, Callable[..., Any]] = {
    "sum": lambda *a: sum(_nums(a)),
    "avg": lambda *a: (sum(_nums(a)) / len(_nums(a))) if _nums(a) else 0.0,
    "average": lambda *a: (sum(_nums(a)) / len(_nums(a))) if _nums(a) else 0.0,
    "mean": lambda *a: (sum(_nums(a)) / len(_nums(a))) if _nums(a) else 0.0,
    "min": lambda *a: min(_nums(a)) if _nums(a) else 0.0,
    "max": lambda *a: max(_nums(a)) if _nums(a) else 0.0,
    "count": lambda *a: float(len([x for x in _flatten(a) if x not in (None, "")])),
    "median": lambda *a: _median(_nums(a)),
    "first": lambda *a: (_flatten(a)[0] if _flatten(a) else None),
    "last": lambda *a: (_flatten(a)[-1] if _flatten(a) else None),
    "abs": lambda x: abs(_need_num(x, "abs()")),
    "round": lambda x, d=0: round(_need_num(x, "round()"), int(_need_num(d, "round() places"))),
    "floor": lambda x: float(math.floor(_need_num(x, "floor()"))),
    "ceil": lambda x: float(math.ceil(_need_num(x, "ceil()"))),
    "if": lambda c, a, b=None: a if _truthy(c) else b,
    "coalesce": lambda *a: next((x for x in _flatten(a) if x not in (None, "")), None),
    # For a column that holds a rate on some rows and a sentence on others —
    # "% Routing" is 0.1 on one row and "50% Margin to be shared…" on the next.
    "isnumber": lambda x: _num(x) is not None,
    "istext": lambda x: _num(x) is None and x not in (None, ""),
    "isblank": lambda x: x in (None, ""),
}

# Functions that reduce a whole column to one value. The playground's two
# sections turn on this distinction, so the list is shared with the engine.
AGGREGATES = {"sum", "avg", "average", "mean", "min", "max", "count", "median", "first", "last"}


def _median(xs: list[float]) -> float:
    if not xs:
        return 0.0
    s = sorted(xs)
    mid = len(s) // 2
    return s[mid] if len(s) % 2 else (s[mid - 1] + s[mid]) / 2


def _truthy(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    n = _num(v)
    if n is not None:
        return n != 0
    return bool(v)


# ── tokens ──────────────────────────────────────────────────────────────────

@dataclass
class _Tok:
    kind: str          # num | str | name | op | lparen | rparen | comma | end
    text: str
    value: Any = None


_OPS = ("<=", ">=", "<>", "!=", "==", "+", "-", "*", "/", "^", "<", ">", "=")


def _tokenise(src: str, names: Iterable[str]) -> list[_Tok]:
    """Names are matched longest-first from a known set, so `Total GR` is one
    token and not `Total` followed by `GR`."""
    known = sorted({n for n in names if n.strip()}, key=len, reverse=True)
    toks: list[_Tok] = []
    i, n = 0, len(src)
    while i < n:
        c = src[i]
        if c.isspace():
            i += 1
            continue
        if c in "([":
            toks.append(_Tok("lparen", c))
            i += 1
            continue
        if c in ")]":
            toks.append(_Tok("rparen", c))
            i += 1
            continue
        if c == ",":
            toks.append(_Tok("comma", c))
            i += 1
            continue
        if c in "\"'":
            j = src.find(c, i + 1)
            if j < 0:
                raise FormulaError("a quote is never closed")
            toks.append(_Tok("str", src[i:j + 1], src[i + 1:j]))
            i = j + 1
            continue
        if c.isdigit() or (c == "." and i + 1 < n and src[i + 1].isdigit()):
            m = re.match(r"\d+(\.\d+)?", src[i:])
            toks.append(_Tok("num", m.group(0), float(m.group(0))))
            i += len(m.group(0))
            continue
        # A known name wins over anything the generic rule would produce.
        hit = next((k for k in known if src.startswith(k, i)), None)
        if hit:
            toks.append(_Tok("name", hit, hit))
            i += len(hit)
            continue
        m = re.match(r"[A-Za-z_][\w@%]*", src[i:])
        if m:
            toks.append(_Tok("name", m.group(0), m.group(0)))
            i += len(m.group(0))
            continue
        op = next((o for o in _OPS if src.startswith(o, i)), None)
        if op:
            toks.append(_Tok("op", op))
            i += len(op)
            continue
        raise FormulaError(f"{c!r} is not something this understands")
    toks.append(_Tok("end", ""))
    return toks


# ── parse and evaluate in one pass ──────────────────────────────────────────

class _Parser:
    def __init__(self, toks: list[_Tok], scope: dict[str, Any]):
        self.t = toks
        self.i = 0
        self.scope = scope

    def peek(self) -> _Tok:
        return self.t[self.i]

    def take(self) -> _Tok:
        tok = self.t[self.i]
        self.i += 1
        return tok

    def expect(self, kind: str) -> _Tok:
        if self.peek().kind != kind:
            raise FormulaError(f"expected {kind} but found {self.peek().text or 'the end'!r}")
        return self.take()

    # comparison < additive < multiplicative < power < unary < primary
    def parse(self) -> Any:
        v = self.comparison()
        if self.peek().kind != "end":
            raise FormulaError(f"unexpected {self.peek().text!r}")
        return v

    def comparison(self) -> Any:
        left = self.additive()
        while self.peek().kind == "op" and self.peek().text in ("<", ">", "<=", ">=", "=", "==", "<>", "!="):
            op = self.take().text
            right = self.additive()
            a, b = _num(left), _num(right)
            if a is None or b is None:
                a, b = str(left), str(right)
            left = {"<": a < b, ">": a > b, "<=": a <= b, ">=": a >= b,
                    "=": a == b, "==": a == b, "<>": a != b, "!=": a != b}[op]
        return left

    def additive(self) -> Any:
        left = self.multiplicative()
        while self.peek().kind == "op" and self.peek().text in ("+", "-"):
            op = self.take().text
            right = self.multiplicative()
            a = _need_num(left, "left of " + op)
            b = _need_num(right, "right of " + op)
            left = a + b if op == "+" else a - b
        return left

    def multiplicative(self) -> Any:
        left = self.power()
        while self.peek().kind == "op" and self.peek().text in ("*", "/"):
            op = self.take().text
            right = self.power()
            a = _need_num(left, "left of " + op)
            b = _need_num(right, "right of " + op)
            left = a * b if op == "*" else _safe_div(a, b)
        return left

    def power(self) -> Any:
        left = self.unary()
        if self.peek().kind == "op" and self.peek().text == "^":
            self.take()
            return _need_num(left, "left of ^") ** _need_num(self.power(), "right of ^")
        return left

    def unary(self) -> Any:
        if self.peek().kind == "op" and self.peek().text in ("+", "-"):
            op = self.take().text
            v = _need_num(self.unary(), "after " + op)
            return -v if op == "-" else v
        return self.primary()

    def primary(self) -> Any:
        tok = self.take()
        if tok.kind == "num" or tok.kind == "str":
            return tok.value
        if tok.kind == "lparen":
            v = self.comparison()
            self.expect("rparen")
            return v
        if tok.kind == "name":
            name = tok.value
            # a call?
            if self.peek().kind == "lparen" and self.peek().text == "(":
                self.take()
                if name.lower() == "if":
                    return self._if()
                args: list[Any] = []
                if not (self.peek().kind == "rparen"):
                    args.append(self.comparison())
                    while self.peek().kind == "comma":
                        self.take()
                        args.append(self.comparison())
                self.expect("rparen")
                fn = FUNCS.get(name.lower())
                if fn is None:
                    raise FormulaError(f"there is no function called {name!r}")
                try:
                    return fn(*args)
                except FormulaError:
                    raise
                except TypeError:
                    raise FormulaError(f"{name}() was given the wrong number of values")
            # a subscript: ratecard["Bill Rate"]
            if self.peek().kind == "lparen" and self.peek().text == "[":
                self.take()
                key = self.comparison()
                self.expect("rparen")
                return self._lookup(f"{name}[{key}]", name, str(key))
            return self._lookup(name, name, None)
        raise FormulaError(f"unexpected {tok.text or 'end of expression'!r}")


    def _if(self) -> Any:
        """`if(test, then, else)` with the untaken branch allowed to fail.

        A column can hold a rate on one row and a sentence on the next — a
        "% Routing" of 0.1 beside "50% Margin to be shared after BGV". The
        point of branching on it is that only one side is arithmetic for any
        given row, so an eager call that evaluated both would fail on exactly
        the rows the test was written to protect.

        Both sides are still parsed, because the parser consumes as it reads;
        only the error from the branch not taken is discarded.
        """
        cond = _truthy(self.comparison())
        self.expect("comma")

        def branch() -> tuple[Any, FormulaError | None]:
            try:
                return self.comparison(), None
            except FormulaError as e:
                return None, e

        then_v, then_err = branch()
        else_v, else_err = None, None
        if self.peek().kind == "comma":
            self.take()
            else_v, else_err = branch()
        self.expect("rparen")

        if cond:
            if then_err:
                raise then_err
            return then_v
        if else_err:
            raise else_err
        return else_v

    def _lookup(self, shown: str, name: str, key: str | None) -> Any:
        if key is None:
            if name in self.scope:
                return self.scope[name]
            raise FormulaError(f"nothing here is called {name!r}")
        box = self.scope.get(name)
        if box is None:
            raise FormulaError(f"no node called {name!r} is connected to this one")
        if not isinstance(box, dict):
            raise FormulaError(f"{name!r} has no columns to read")
        if key in box:
            return box[key]
        # Spreadsheet headers drift in case and spacing more than people expect.
        folded = {str(k).strip().casefold(): v for k, v in box.items()}
        hit = folded.get(key.strip().casefold())
        if hit is not None:
            return hit
        raise FormulaError(f"{name} has no column called {key!r}")


def evaluate(expr: str, scope: dict[str, Any], names: Iterable[str] = ()) -> Any:
    """Work out one expression. `names` are the multi-word names to lex whole."""
    if not expr or not expr.strip():
        raise FormulaError("the expression is empty")
    toks = _tokenise(expr, list(names) + list(scope.keys()))
    return _Parser(toks, scope).parse()
