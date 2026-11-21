"""Golden parity: the engine reproduces docs/cashflow-forecast/dummy-data/seed/expected_forecast.json.

The seed and its expected output come from the reference rules in
generate_dummy_data.py; any rule change has to be made in both places.
"""

import json
from datetime import date

import pytest

from backend_ocr.app.cashflow import engine, scenario
from backend_ocr.app.cashflow.calendar import BusinessCalendar
from backend_ocr.app.cashflow.rules import assemble
from backend_ocr.app.cashflow.sources import SEED_DIR, fixture_today, load_books_fixture, load_inputs_fixture

GOLDEN = json.loads((SEED_DIR / "expected_forecast.json").read_text())


@pytest.fixture(scope="module")
def built():
    data = load_books_fixture()
    settings = load_inputs_fixture(data)
    snap = assemble(data, settings, fixture_today(), GOLDEN["tenant_id"])
    return snap, BusinessCalendar(settings.holidays)


def rows(result):
    return [dict(date=r.date.isoformat(), banking_day=r.banking_day, opening_paise=r.opening_paise,
                 inflow_paise=r.inflow_paise, outflow_paise=r.outflow_paise, closing_paise=r.closing_paise,
                 below_reserve=r.below_reserve, event_count=r.event_count) for r in result.days]


def check(result, golden):
    assert rows(result) == golden["days"]
    m = result.metrics
    iso = lambda d: d.isoformat() if d else None
    assert (m.minimum_closing_paise, iso(m.minimum_date), iso(m.first_reserve_breach_date), iso(m.first_negative_date),
            m.days_below_reserve, m.total_inflow_paise, m.total_outflow_paise, m.closing_paise,
            m.beyond_horizon_inflow_paise, m.beyond_horizon_outflow_paise) == (
        golden["minimum_closing_paise"], golden["minimum_date"], golden["first_reserve_breach_date"],
        golden["first_negative_date"], golden["days_below_reserve"], golden["total_inflow_paise"],
        golden["total_outflow_paise"], golden["closing_paise"], golden["beyond_horizon_inflow_paise"],
        golden["beyond_horizon_outflow_paise"])


def test_opening_and_horizon(built):
    snap, _ = built
    assert snap.opening_total() == GOLDEN["opening_paise"] == 487043184
    assert (snap.start, snap.end) == (date(2026, 11, 21), date(2026, 12, 20))
    assert snap.od_headroom_paise == GOLDEN["od_headroom_paise"]
    assert {b.freshness for b in snap.balances} == {"fresh"}


@pytest.mark.parametrize("view", ["expected", "downside", "no_collections"])
def test_views_match_golden(built, view):
    snap, cal = built
    result = engine.project(snap, view, calendar=cal)
    check(result, GOLDEN["views"][view])
    assert result.category_totals == GOLDEN["category_totals"][view]


def test_every_event_matches_golden(built):
    snap, _ = built
    expected = {}
    for e in GOLDEN["events"]:
        for v in e["views"]:
            expected[(e["event_key"], v)] = (e["amount_paise"], e["date"], e["direction"])
    ours = {(e.event_key, v): (e.amount_paise, e.dates.get(v).isoformat(), e.direction)
            for e in snap.events for v in ("expected", "downside", "no_collections") if e.in_view(v)}
    assert ours == expected


def test_exclusions_match_golden(built):
    snap, _ = built
    ours = sorted((x.reason, x.source_id, x.amount_paise) for x in snap.exclusions)
    golden = sorted((x["reason"], x["source_id"], x["amount_paise"]) for x in GOLDEN["exclusions"])
    assert ours == golden


@pytest.mark.parametrize("name,view", [("defer_windowed_bills", "expected"), ("defer_windowed_bills", "downside"),
                                        ("sahyadri_slips_10_days", "expected")])
def test_scenarios_match_golden(built, name, view):
    snap, cal = built
    gs = GOLDEN["scenarios"][name]
    overrides = [scenario.ShiftEvent(op="shift_event", event_key=k, to_date=date.fromisoformat(v))
                 for k, v in gs["overrides"].items()]
    assert scenario.validate(snap, overrides, view, cal) == []
    events, applied = scenario.apply(snap, overrides, view, cal)
    check(engine.project(snap, view, events, cal), gs[view])
    if name == "defer_windowed_bills":
        assert {a["kind"] for a in applied} == {"decision"}


def test_content_hash_is_stable(built):
    snap, _ = built
    data = load_books_fixture()
    again = assemble(data, load_inputs_fixture(data), fixture_today(), GOLDEN["tenant_id"])
    assert again.content_hash == snap.content_hash
    data = load_books_fixture()
    data.bills[0]["outstanding_paise"] += 100
    changed = assemble(data, load_inputs_fixture(data), fixture_today(), GOLDEN["tenant_id"])
    assert changed.content_hash != snap.content_hash
