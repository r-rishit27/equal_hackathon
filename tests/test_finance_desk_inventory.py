from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi import HTTPException

from backend_ocr.app.routers.inventory import Plan, evaluate, solve_pack_qubo


def plan(**changes):
    fields = dict(line_id=uuid4(), start=date(2026, 11, 21), on_hand=10, reserved=2,
                  daily_demand=4, lead_days=2, pack=6, minimum_order=1, spendable_paise=50_000)
    return Plan(**(fields | changes))


def test_rounding_and_arrival_before_demand():
    result = evaluate(plan(), Decimal("20.50"))
    assert (result["units"], result["spend_paise"]) == (24, 49_200)
    assert result["days"][2]["incoming"] == 24
    assert result["days"][-1]["closing"] == 4
    assert result["reasons"] == []


def test_quote_budget_and_late_arrival():
    result = evaluate(plan(lead_days=3, landed_unit_paise=2100, spendable_paise=37_000), Decimal("20.50"))
    assert result["days"][2]["unmet"] == 4
    assert result["units"] == 12
    assert result["spend_paise"] == 25_200
    assert result["remaining_paise"] == 11_800
    assert result["additional_demand_covered"] == 12
    assert len(result["reasons"]) == 2


def test_no_order_and_invalid_reservations():
    assert evaluate(plan(on_hand=30), Decimal("20"))["units"] == 0
    with pytest.raises(HTTPException):
        evaluate(plan(reserved=11), Decimal("20"))

def test_firm_inbound_covers_later_demand_only():
    result = evaluate(plan(inbound_units=30, inbound_date=date(2026, 11, 25)), Decimal("20"))
    assert result["units"] == 12
    assert result["days"][4]["incoming"] == 30
    assert not any(day["unmet"] for day in result["days"])


def test_late_delivery_and_expired_quote():
    result = evaluate(plan(lead_days=7), Decimal("20"))
    assert result["units"] == 0
    assert result["reasons"]
    result = evaluate(plan(landed_unit_paise=2000, quote_expiry=date(2026, 11, 20)), Decimal("25"))
    assert "expired" in result["reasons"][0]
    assert result["units"] == 0

def test_fractional_invoice_quantity_rounds_up_to_whole_packs():
    result = evaluate(plan(on_hand=Decimal("8.75"), reserved=0, daily_demand=Decimal("2.25"),
                           pack=Decimal("2.5"), lead_days=0), Decimal("42.50"))
    assert result["units"] == Decimal("7.5")
    assert result["spend_paise"] == 31_875
    assert result["days"][-1]["closing"] == Decimal("0.5")

def test_minimum_order_exceeds_budget():
    result = evaluate(plan(minimum_order=13, spendable_paise=30_000), Decimal("20"))
    assert result["units"] == 0
    assert result["remaining_paise"] == 30_000

def test_pack_qubo_matches_exhaustive_feasible_orders():
    for capacity in range(34):
        for minimum in (1, 3, 7):
            for target in range(42):
                feasible = range(minimum, capacity + 1)
                expected = min(feasible, key=lambda n: (n - target) ** 2) if target and feasible else 0
                assert solve_pack_qubo(target, minimum, capacity) == expected
