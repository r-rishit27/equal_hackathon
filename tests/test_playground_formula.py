"""The expression language behind a Formula node.

These expressions arrive from a text box in the browser and are stored per
tenant, so the first group of tests is the important one: this must not be an
interpreter. The rest pin the arithmetic a finance team would expect, and the
tolerance for the shapes spreadsheet data actually arrives in.
"""
from __future__ import annotations

import pytest

from backend_ocr.app.domain.playground.formula import FormulaError, evaluate


# ── it is not an interpreter ────────────────────────────────────────────────

@pytest.mark.parametrize("attack", [
    '__import__("os").system("echo pwned")',
    'open("/etc/passwd").read()',
    '(1).__class__.__bases__',
    'ratecard.__dict__',
    'eval("1+1")',
    'exec("x=1")',
    'getattr(ratecard, "keys")()',
    '[].__class__',
    'globals()',
    'lambda: 1',
])
def test_nothing_reaches_python(attack):
    """Every one of these is a remote-code-execution path if the expression is
    ever handed to eval(). There is no code path here that could run them."""
    with pytest.raises(FormulaError):
        evaluate(attack, {"ratecard": {"a": 1}})


def test_only_the_named_functions_exist():
    with pytest.raises(FormulaError, match="no function called"):
        evaluate("system('ls')", {})


def test_a_name_that_was_not_supplied_is_not_resolved():
    with pytest.raises(FormulaError, match="nothing here is called"):
        evaluate("secret", {})


# ── the arithmetic ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("expr,expected", [
    ("1 + 2", 3),
    ("10 - 4", 6),
    ("3 * 4", 12),
    ("10 / 4", 2.5),
    ("2 ^ 10", 1024),
    ("-5 + 2", -3),
    ("(1 + 2) * 3", 9),
    ("1 - 0.08", 0.92),
    ("100 * (1 - 0.08)", 92),
])
def test_arithmetic(expr, expected):
    assert evaluate(expr, {}) == pytest.approx(expected)


def test_multiplication_binds_tighter_than_addition():
    assert evaluate("2 + 3 * 4", {}) == 14


def test_division_by_zero_is_named_as_such():
    """A rate card with no working days in the month is a data problem, and
    saying "division by zero" points at the row rather than the formula."""
    with pytest.raises(FormulaError, match="division by zero"):
        evaluate("100 / 0", {})


# ── reading the source sheet ────────────────────────────────────────────────

SHEET = {"ratecard": {"Bill Rate": 350000, "Working Days in Month": 22, "No of Days": 15},
         "contract": {"% Routing": 0.08}}


def test_a_column_is_read_by_name():
    assert evaluate('ratecard["Bill Rate"]', SHEET) == 350000


def test_the_staffing_formula():
    got = evaluate('ratecard["Bill Rate"] / ratecard["Working Days in Month"] * ratecard["No of Days"]', SHEET)
    assert got == pytest.approx(350000 / 22 * 15)


def test_a_value_from_a_different_node():
    assert evaluate('1 - contract["% Routing"]', SHEET) == pytest.approx(0.92)


def test_a_misspelled_column_says_which_one():
    with pytest.raises(FormulaError, match="no column called 'Bill rat'"):
        evaluate('ratecard["Bill rat"]', SHEET)


def test_a_column_name_matches_despite_case_and_padding():
    """Headers drift between exports more than people expect, and failing a
    whole run over a capital letter helps nobody."""
    assert evaluate('ratecard["  bill rate "]', SHEET) == 350000


def test_a_node_that_is_not_connected_says_so():
    with pytest.raises(FormulaError, match="no node called 'bills'"):
        evaluate('bills["Amount"]', SHEET)


# ── the shapes spreadsheet values arrive in ─────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("1,652", 1652),
    ("350,000.00", 350000),
    ("₹95,000", 95000),
    ("  22  ", 22),
    (22, 22),
    (22.0, 22),
])
def test_numbers_that_arrived_as_text_still_calculate(raw, expected):
    assert evaluate('x * 1', {"x": raw}) == pytest.approx(expected)


def test_text_that_is_not_a_number_is_refused_rather_than_guessed():
    """A % Routing column holding "50% Margin to be shared after BGV" is a
    sentence. Treating it as 50 would produce a confident wrong number."""
    with pytest.raises(FormulaError, match="not a number"):
        evaluate('1 - x', {"x": "50% Margin to be shared after one time BGV cost deduction"})


def test_an_empty_cell_is_not_silently_zero():
    with pytest.raises(FormulaError, match="not a number"):
        evaluate('x * 2', {"x": None})


# ── the aggregate functions ─────────────────────────────────────────────────

COLUMN = {"GR@100%": [100.0, 250.0, 75.5, None]}


@pytest.mark.parametrize("expr,expected", [
    ("sum(GR@100%)", 425.5),
    ("count(GR@100%)", 3),
    ("min(GR@100%)", 75.5),
    ("max(GR@100%)", 250.0),
    ("avg(GR@100%)", 425.5 / 3),
    ("median(GR@100%)", 100.0),
])
def test_totals_over_a_column(expr, expected):
    assert evaluate(expr, COLUMN, ["GR@100%"]) == pytest.approx(expected)


def test_blank_cells_are_left_out_of_a_total_rather_than_counted_as_zero():
    """Counting them would drag an average down by however many rows happened
    to be empty."""
    assert evaluate("count(GR@100%)", COLUMN, ["GR@100%"]) == 3


def test_the_provision_fee_over_a_whole_sheet():
    scope = {**COLUMN, "contract": {"% Routing": 0.08}}
    got = evaluate('(1 - contract["% Routing"]) * sum(GR@100%)', scope, ["GR@100%"])
    assert got == pytest.approx(0.92 * 425.5)


def test_an_empty_column_totals_to_zero_not_an_error():
    assert evaluate("sum(x)", {"x": []}, ["x"]) == 0


# ── names as a finance team writes them ─────────────────────────────────────

def test_a_name_with_at_and_percent():
    assert evaluate("GR@100% * 2", {"GR@100%": 10}, ["GR@100%"]) == 20


def test_a_name_with_a_space():
    assert evaluate("Total GR / 2", {"Total GR": 50}, ["Total GR"]) == 25


def test_a_longer_name_wins_over_a_shorter_one_that_prefixes_it():
    scope = {"GR": 1, "GR@100%": 100}
    assert evaluate("GR@100%", scope, ["GR", "GR@100%"]) == 100
    assert evaluate("GR", scope, ["GR", "GR@100%"]) == 1


def test_a_quoted_column_is_not_read_as_a_name():
    scope = {"ratecard": {"Bill Rate": 7}, "Rate": 999}
    assert evaluate('ratecard["Bill Rate"]', scope, ["Rate"]) == 7


# ── malformed input is reported, never raised raw ───────────────────────────

@pytest.mark.parametrize("expr", ["", "   ", "1 +", "(1 + 2", "* 3", "sum(", '"unclosed'])
def test_a_broken_expression_gives_a_readable_message(expr):
    with pytest.raises(FormulaError):
        evaluate(expr, {})


def test_round_and_if_behave():
    assert evaluate("round(10 / 3, 2)", {}) == pytest.approx(3.33)
    assert evaluate("if(1 > 0, 5, 9)", {}) == 5
    assert evaluate("if(0 > 1, 5, 9)", {}) == 9
