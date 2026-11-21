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

def test_randomized_projections_match_independent_daily_simulation():
    """Enumerate every useful order size; score by lost sales, spend, then units."""
    from datetime import timedelta
    from decimal import ROUND_HALF_UP
    from random import Random

    rng = Random(5571)
    for _ in range(1500):
        stock = rng.randrange(21)
        cost = Decimal(rng.choice(["0.005", "0.125", "1.15", "13.81"]))
        scenario = plan(on_hand=stock, reserved=rng.randint(0, stock),
                        daily_demand=Decimal(rng.randint(1, 12)) / 2,
                        lead_days=rng.randrange(10), pack=Decimal(rng.randint(1, 8)) / 2,
                        minimum_order=rng.randint(1, 15), spendable_paise=rng.randrange(15000),
                        inbound_units=rng.randrange(16),
                        inbound_date=date(2026, 11, 21) + timedelta(days=rng.randrange(10)),
                        quote_expiry=date(2026, 11, 21) + timedelta(days=rng.randrange(-1, 3)))
        choices = []
        # No scenario in this test needs more than 42 units or has MOQ above 15.
        for packs in range(int(42 / scenario.pack) + 2):
            qty = packs * scenario.pack
            spend = int((qty * cost * 100).to_integral_value(rounding=ROUND_HALF_UP))
            if spend > scenario.spendable_paise or (qty and (
                    qty < scenario.minimum_order or scenario.quote_expiry < scenario.start)):
                continue
            available = scenario.on_hand - scenario.reserved
            lost = 0
            series = []
            for day in range(7):
                if day == scenario.lead_days:
                    available += qty
                if scenario.start + timedelta(days=day) == scenario.inbound_date:
                    available += scenario.inbound_units
                sold = min(available, scenario.daily_demand)
                available -= sold
                missed = scenario.daily_demand - sold
                lost += missed
                series.append((available, missed))
            choices.append((lost, spend, qty, series))
        _, spend, qty, series = min(choices)
        result = evaluate(scenario, cost)
        assert (result["units"], result["spend_paise"]) == (qty, spend)
        assert result["remaining_paise"] == scenario.spendable_paise - spend
        assert [(d["closing"], d["unmet"]) for d in result["days"]] == series


def test_maximum_horizon_inputs_and_smallest_pack():
    scenario = plan(start=date(9999, 12, 24), on_hand=0, reserved=0, lead_days=0,
                    daily_demand=10**7, pack=Decimal("0.00000001"), spendable_paise=10**14)
    result = evaluate(scenario, Decimal("0.01"))
    assert result["units"] == 70_000_000
    assert result["additional_demand_covered"] == result["units"]
    assert result["days"][-1]["date"] == date(9999, 12, 30)

@pytest.mark.parametrize("changes", [
    {"pack": 0}, {"pack": Decimal("0.000000001")}, {"minimum_order": 0},
    {"spendable_paise": -1}, {"lead_days": -1}, {"lead_days": 366},
    {"on_hand": -1}, {"daily_demand": 0}, {"landed_unit_paise": 0},
    {"start": date.max}, {"line_id": "invalid"}, {"tenant_id": "untrusted"},
])
def test_invalid_planning_inputs_are_rejected(changes):
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        plan(**changes)


@pytest.mark.parametrize("inbound_date", [None, date(2026, 11, 20)])
def test_firm_inbound_needs_arrival_on_or_after_start(inbound_date):
    with pytest.raises(HTTPException) as exc:
        evaluate(plan(inbound_units=1, inbound_date=inbound_date), Decimal("1"))
    assert exc.value.status_code == 422
