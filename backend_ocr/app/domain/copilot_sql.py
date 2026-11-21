"""Compile a bounded finance query into PostgreSQL over an already authorized relation."""
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# Output names from the tenant-scoped projections. Physical sources and types are
# documented in docs/full_database_schema.md. Unit columns keep aggregates comparable.
CATALOG = {
    "bills": ("fact_invoices", {"total_amount": "currency_code", "amount_paid": "currency_code", "outstanding_amount": "currency_code"}, ["supplier", "stage", "record_state", "currency_code", "graph_link", "invoice_number"], ["due_date", "invoice_date"]),
    "approvals": ("fact_invoices", {"total_amount": "currency_code", "amount_paid": "currency_code", "outstanding_amount": "currency_code"}, ["supplier", "stage", "currency_code", "graph_link", "invoice_number"], ["due_date", "invoice_date"]),
    "receivables": ("ar_invoices", {"outstanding": "currency"}, ["customer", "status", "currency", "title"], ["due_date"]),
    "cash_application": ("ar_payments", {"amount": "currency", "applied_amount": "currency"}, ["status", "currency", "title"], ["received_on"]),
    "inventory": ("stg_bill_line_items", {"quantity": "unit", "unit_price": "currency_code"}, ["title", "unit", "currency_code", "bill_number"], ["bill_date"]),
    "cash_forecast": ("fact_cashflow_daily", {"inflows_forecast": "currency_code", "outflows_forecast": "currency_code", "opening_balance": "currency_code", "closing_balance": "currency_code"}, ["currency_code"], ["title"]),
    "vendors": ("dim_suppliers", {"payment_terms_days": None}, ["title", "status"], []),
    "review": ("rh_findings", {"money_at_risk": "money_currency"}, ["severity", "status", "subject_type", "money_currency"], []),
}


class Predicate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    field: str = Field(max_length=48)
    op: Literal["eq", "contains", "gte", "gt", "lte", "lt"]
    value: str = Field(min_length=1, max_length=120)


class Analysis(BaseModel):
    model_config = ConfigDict(extra="forbid")
    domain: str
    operation: Literal["count", "sum", "avg", "min", "max"]
    metric: str | None = None
    group_by: list[str] = Field(default_factory=list, max_length=2)
    filters: list[Predicate] = Field(default_factory=list, max_length=5)
    descending: bool = True
    limit: int = Field(default=8, ge=1, le=20)


def schema_context(allowed):
    return {key: dict(table=table, metrics_and_units=metrics, dimensions=dims, dates=dates)
            for key, (table, metrics, dims, dates) in CATALOG.items() if key in allowed}


def compile_query(plan, relation):
    if plan.domain not in CATALOG:
        raise ValueError("Unknown reporting domain")
    _, metrics, dimensions, dates = CATALOG[plan.domain]
    groups = list(dict.fromkeys(plan.group_by))
    if any(field not in dimensions + dates for field in groups):
        raise ValueError("Unknown grouping")
    units = []
    if plan.operation == "count":
        aggregate = "count(*)"
    else:
        if plan.metric not in metrics:
            raise ValueError("Unknown metric")
        if plan.operation == "sum" and plan.metric in {"unit_price", "payment_terms_days", "opening_balance", "closing_balance"}:
            raise ValueError("This measure is not additive")
        # Bill source exposes its decimal as text for the UX. Aggregate as numeric.
        aggregate = f"{plan.operation}(q.{plan.metric}::numeric)"
        units = [metrics[plan.metric]] if metrics[plan.metric] else []
        if plan.metric == "unit_price":
            units.append("unit")
        for unit in units:
            if unit and unit not in groups:
                groups.append(unit)
    conditions = []
    params = {}
    for i, predicate in enumerate(plan.filters):
        field = predicate.field
        if field not in [*metrics, *dimensions, *dates]:
            raise ValueError("Unknown filter field")
        key = f"filter_{i}"
        param = f"%({key})s"
        value = predicate.value
        expr = f"q.{field}"
        if field in dates:
            value = date.fromisoformat(value)
            expr += "::date"
        elif field in metrics:
            try:
                value = Decimal(value)
            except InvalidOperation as exc:
                raise ValueError("Expected decimal filter") from exc
            if not value.is_finite():
                raise ValueError("Expected finite value")
            expr += "::numeric"
        else:
            expr = f"lower({expr}::text)"
            value = value.lower()
        if predicate.op == "contains":
            if field not in dimensions:
                raise ValueError("Text search requires a dimension")
            conditions.append(f"strpos({expr},{param}) > 0")
        else:
            op = {"eq":"=", "gt":">", "gte":">=", "lt":"<", "lte":"<="}[predicate.op]
            conditions.append(f"{expr} {op} {param}")
        params[key] = value
    columns = [f"q.{field}" for field in groups]
    sql = "SELECT " + ", ".join([*columns, aggregate + " AS result"]) + " FROM (" + relation + ") q"
    if conditions:
        sql += " WHERE " + " AND ".join(conditions)
    if columns:
        sql += " GROUP BY " + ", ".join(columns)
        direction = "DESC" if plan.descending else "ASC"
        if units and any(group not in units for group in groups):
            order = "result " + direction + " NULLS LAST, " + ", ".join(groups)
            rank = "row_number() OVER (PARTITION BY " + ", ".join(units) + " ORDER BY " + order + ")"
            ranked = f"SELECT grouped.*, {rank} AS rank FROM ({sql}) grouped"
            sql = f"SELECT * FROM ({ranked}) ranked WHERE rank <= %(result_limit)s"
            return sql + " ORDER BY " + ", ".join([*units, "rank"]) + " LIMIT 40", dict(params, result_limit=plan.limit)
        sql += " ORDER BY " + (", ".join(units) if units else "result " + direction + " NULLS LAST, " + ", ".join(columns))
    return sql + " LIMIT %(result_limit)s", dict(params, result_limit=plan.limit)
