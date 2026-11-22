"""Daily cash projection (docs/cashflow-forecast/04_LLD.md §5.7). Pure: no I/O, no clock."""

from __future__ import annotations

from .calendar import BusinessCalendar
from .types import IN, DayRow, ForecastResult, Metrics, Snapshot, View


def project(snap: Snapshot, view: View, events=None, calendar: BusinessCalendar | None = None) -> ForecastResult:
    """Project `events` (default: the snapshot's) for one view.

    Closing = opening + inflows − outflows per local date. Intraday order is
    not modelled. A day is below reserve when closing is strictly less.
    """
    cal = calendar or BusinessCalendar()
    evs = [e for e in (snap.events if events is None else events) if e.in_view(view)]
    horizon = snap.horizon()
    end = snap.end
    buckets = {d: [0, 0, 0] for d in horizon}            # in, out, count
    beyond = {"in": 0, "out": 0}
    categories: dict[str, int] = {}
    for e in evs:
        d = e.effective_date(view)
        if d > end:
            beyond[e.direction] += e.amount_paise
            continue
        if d < snap.start:                               # defensive: overrides are validated
            d = snap.start
        b = buckets[d]
        b[0 if e.direction == IN else 1] += e.amount_paise
        b[2] += 1
        k = f"{e.direction}:{e.category}"
        categories[k] = categories.get(k, 0) + e.amount_paise

    bal = snap.opening_total()
    days = []
    for d in horizon:
        inflow, outflow, n = buckets[d]
        close = bal + inflow - outflow
        days.append(DayRow(d, cal.is_banking_day(d), bal, inflow, outflow, close, close < snap.reserve_paise, n))
        bal = close

    low = min(days, key=lambda r: (r.closing_paise, r.date))
    breach = next((r.date for r in days if r.below_reserve), None)
    negative = next((r.date for r in days if r.closing_paise < 0), None)
    metrics = Metrics(
        minimum_closing_paise=low.closing_paise, minimum_date=low.date, first_reserve_breach_date=breach,
        first_negative_date=negative, days_below_reserve=sum(1 for r in days if r.below_reserve),
        total_inflow_paise=sum(r.inflow_paise for r in days), total_outflow_paise=sum(r.outflow_paise for r in days),
        closing_paise=days[-1].closing_paise, beyond_horizon_inflow_paise=beyond["in"],
        beyond_horizon_outflow_paise=beyond["out"],
        runway_days=(negative - snap.start).days if negative else None)
    return ForecastResult(view=view, opening_paise=snap.opening_total(), reserve_paise=snap.reserve_paise,
                          days=tuple(days), metrics=metrics, category_totals=dict(sorted(categories.items())),
                          events=tuple(evs))


def delta(baseline: ForecastResult, scenario: ForecastResult) -> dict:
    return {
        "minimum_change_paise": scenario.metrics.minimum_closing_paise - baseline.metrics.minimum_closing_paise,
        "closing_change_paise": scenario.metrics.closing_paise - baseline.metrics.closing_paise,
        "baseline_first_breach": baseline.metrics.first_reserve_breach_date,
        "scenario_first_breach": scenario.metrics.first_reserve_breach_date,
        "closing_diff_paise": [s.closing_paise - b.closing_paise for b, s in zip(baseline.days, scenario.days)],
    }
