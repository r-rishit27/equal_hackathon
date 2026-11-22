"""What-if overrides: typed, validated, applied to a copy of the snapshot's events.

Overrides never touch source records (docs/cashflow-forecast/04_LLD.md §5.8).
A *decision* is something the business controls (paying later inside an agreed
window); an *assumption* is a prediction (a customer paying late). Only
decisions are carried into future forecasts when a plan is approved.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field

from .calendar import BusinessCalendar
from .types import IN, OUT, VIEWS, CashEvent, Snapshot, ViewDates, pct_of

MAX_OVERRIDES = 200
MOVABLE_RECURRING_DAYS = 15


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str | None = Field(default=None, max_length=500)


class ShiftEvent(_Base):
    op: Literal["shift_event"]
    event_key: str = Field(min_length=1, max_length=200)
    to_date: date


class DelayCustomer(_Base):
    op: Literal["delay_customer"]
    customer_id: str = Field(min_length=1, max_length=64)
    days: int = Field(ge=1, le=90)


class HaircutCustomer(_Base):
    op: Literal["haircut_customer"]
    customer_id: str = Field(min_length=1, max_length=64)     # "*" = every customer
    percent: int = Field(ge=0, le=100)


class ExcludeEvent(_Base):
    op: Literal["exclude_event"]
    event_key: str = Field(min_length=1, max_length=200)


class AddItem(_Base):
    op: Literal["add_item"]
    label: str = Field(min_length=1, max_length=120)
    direction: Literal["in", "out"]
    amount_paise: int = Field(gt=0, le=10**14)
    on_date: date
    category: str = Field(default="other", max_length=16)
    confidence: Literal["committed", "estimated"] = "estimated"


Override = Annotated[Union[ShiftEvent, DelayCustomer, HaircutCustomer, ExcludeEvent, AddItem], Field(discriminator="op")]


class Refused(Exception):
    def __init__(self, refusals):
        super().__init__("override refused")
        self.refusals = refusals


def kind(o, snap: Snapshot) -> str:
    if isinstance(o, ShiftEvent):
        e = snap.event(o.event_key)
        return "assumption" if e is not None and e.direction == IN else "decision"
    if isinstance(o, AddItem):
        return "decision" if o.confidence == "committed" else "assumption"
    return "assumption"


def _fmt(d: date) -> str:
    return f"{d.day} {d:%b %Y}"


def validate(snap: Snapshot, overrides, view: str, cal: BusinessCalendar) -> list[dict]:
    """Return a list of refusals (empty when every override is acceptable)."""
    out = []

    def refuse(i, code, message, **details):
        out.append({"index": i, "code": code, "message": message, "details": details})

    if len(overrides) > MAX_OVERRIDES:
        refuse(MAX_OVERRIDES, "LIMIT_EXCEEDED", f"At most {MAX_OVERRIDES} changes per scenario.")
        return out
    seen = set()
    for i, o in enumerate(overrides):
        if isinstance(o, (ShiftEvent, ExcludeEvent)):
            if o.event_key in seen:
                refuse(i, "DUPLICATE_TARGET", "This item already has a change in the scenario.", event_key=o.event_key)
                continue
            seen.add(o.event_key)
            e = snap.event(o.event_key)
            if e is None:
                refuse(i, "EVENT_NOT_FOUND", "This item is no longer in the forecast.", event_key=o.event_key)
                continue
            if not e.in_view(view):
                refuse(i, "EVENT_NOT_IN_VIEW", "This item isn't counted in the selected view.", event_key=o.event_key)
                continue
        if isinstance(o, ShiftEvent):
            if e.fixed:
                refuse(i, "FIXED_OBLIGATION", "Payroll, statutory dues, loan EMIs and payouts already sent can't be moved.",
                       event_key=o.event_key)
                continue
            if o.to_date < snap.start:
                refuse(i, "BEFORE_HORIZON", f"Choose a date on or after {_fmt(snap.start)}.", event_key=o.event_key)
                continue
            if not cal.is_banking_day(o.to_date):
                refuse(i, "NON_BANKING_DAY", f"{_fmt(o.to_date)} isn't a banking day. Choose another date.",
                       event_key=o.event_key)
                continue
            current = e.effective_date(view)
            if e.direction == OUT and e.source_type in ("bill", "schedule"):
                limit = e.window.latest if e.window else max(current, e.nominal_date or current)
                if o.to_date > limit:
                    who = e.counterparty or "The supplier"
                    msg = (f"{who} agreed to payment no later than {_fmt(e.window.latest)}." if e.window else
                           f"This bill is due {_fmt(limit)}. To pay later, first record the supplier's agreement.")
                    refuse(i, "OUTSIDE_PAYMENT_WINDOW", msg, event_key=o.event_key, latest_date=limit.isoformat(),
                           requested=o.to_date.isoformat())
                    continue
            if e.source_type in ("recurring", "adjustment") and abs((o.to_date - current).days) > MOVABLE_RECURRING_DAYS:
                refuse(i, "SHIFT_TOO_FAR", f"Move recurring items by {MOVABLE_RECURRING_DAYS} days at most.",
                       event_key=o.event_key)
        elif isinstance(o, ExcludeEvent):
            if e.direction != IN:
                refuse(i, "INFLOW_ONLY", "Only receipts can be excluded. Payments can be moved inside their agreed window.",
                       event_key=o.event_key)
        elif isinstance(o, DelayCustomer):
            if not any(e.source_type == "ar_invoice" and e.counterparty_id == o.customer_id and e.in_view(view)
                       for e in snap.events):
                refuse(i, "EVENT_NOT_FOUND", "This customer has no open invoices in the forecast.", customer_id=o.customer_id)
        elif isinstance(o, AddItem):
            if o.on_date < snap.start:
                refuse(i, "BEFORE_HORIZON", f"Choose a date on or after {_fmt(snap.start)}.")
            elif o.category == "financing" and o.direction == IN and o.amount_paise > snap.od_headroom_paise:
                refuse(i, "EXCEEDS_OD_HEADROOM",
                       f"That's more than the ₹{snap.od_headroom_paise / 100:,.0f} available on your cash-credit line.")
    return out


def apply(snap: Snapshot, overrides, view: str, cal: BusinessCalendar, scenario_id: str = "draft") -> tuple[list, list]:
    """Apply validated overrides for one view. Returns (events, applied summary)."""
    events = {e.event_key: e for e in snap.events}
    applied = []
    for i, o in enumerate(overrides):
        affected = []
        if isinstance(o, ShiftEvent):
            e = events[o.event_key]
            old = e.effective_date(view)
            basis = dict(e.date_basis)
            basis[view] = f"scenario: moved from {_fmt(old)}"
            events[o.event_key] = replace(e, dates=e.dates.replace(view, o.to_date), date_basis=basis)
            affected = [o.event_key]
        elif isinstance(o, ExcludeEvent):
            events.pop(o.event_key, None)
            affected = [o.event_key]
        elif isinstance(o, DelayCustomer):
            for k, e in list(events.items()):
                if e.source_type == "ar_invoice" and e.counterparty_id == o.customer_id and e.in_view(view):
                    d = cal.next_banking_day(e.effective_date(view) + timedelta(days=o.days))
                    basis = dict(e.date_basis)
                    basis[view] = f"scenario: customer delayed {o.days}d"
                    events[k] = replace(e, dates=e.dates.replace(view, d), date_basis=basis)
                    affected.append(k)
        elif isinstance(o, HaircutCustomer):
            for k, e in list(events.items()):
                if e.source_type == "ar_invoice" and (o.customer_id == "*" or e.counterparty_id == o.customer_id):
                    remaining = e.amount_paise - pct_of(e.amount_paise, o.percent)
                    if remaining <= 0:
                        events.pop(k)
                    else:
                        events[k] = replace(e, amount_paise=remaining)
                    affected.append(k)
        elif isinstance(o, AddItem):
            key = f"scenario:{scenario_id}:{i}"
            d = cal.next_banking_day(o.on_date)
            dates = ViewDates(*(d for _ in VIEWS))
            events[key] = CashEvent(
                event_key=key, source_type="scenario_item", source_id=key, label=o.label, direction=o.direction,
                amount_paise=o.amount_paise, category=o.category, confidence=o.confidence, dates=dates,
                date_basis={v: "scenario: added item" for v in VIEWS}, nominal_date=o.on_date)
            affected = [key]
        applied.append({"index": i, "op": o.op, "kind": kind(o, snap), "affected_event_keys": affected})
    return list(events.values()), applied
