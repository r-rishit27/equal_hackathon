"""Regression checks for schema-grounded analytical SQL and finance semantics."""
from pathlib import Path
import pytest
from backend_ocr.app.domain.copilot_sql import Analysis, CATALOG, compile_query


def test_reporting_tables_in_documented_schema():
    schema = (Path(__file__).resolve().parents[1] / "docs/full_database_schema.md").read_text(encoding="utf8")
    for table, *_ in CATALOG.values():
        assert f"## Table: `{table}`" in schema


def test_compiles_bound_range_with_currency_and_ranking():
    plan = Analysis(domain="receivables", operation="sum", metric="outstanding", group_by=["customer"],
                    filters=[{"field": "due_date", "op": "lt", "value": "2026-11-21"}], limit=5)
    sql, args = compile_query(plan, "SELECT * FROM scoped")
    assert "GROUP BY q.customer, q.currency" in sql and "q.due_date::date < %(filter_0)s" in sql
    assert args["result_limit"] == 5 and args["filter_0"].isoformat() == "2026-11-21"


@pytest.mark.parametrize("kwargs", [
    {"metric":"amount_paid"}, {"group_by":["tenant_id"]},
    {"filters":[{"field":"unknown","op":"eq","value":"x"}]},
    {"filters":[{"field":"due_date","op":"lt","value":"not a date"}]},
])
def test_unknown_identifiers_and_invalid_types_fail_before_database(kwargs):
    fields = dict(domain="receivables", operation="sum", metric="outstanding")
    fields.update(kwargs)
    with pytest.raises(ValueError):
        compile_query(Analysis(**fields), "SELECT 1")
