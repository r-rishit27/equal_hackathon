"""Domain types for the cash forecast (docs/cashflow-forecast/04_LLD.md §3).

Everything here is immutable. Amounts are positive integer paise with a
direction; only balances and deltas are signed.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

View = Literal["expected", "downside", "no_collections"]
VIEWS: tuple[View, ...] = ("expected", "downside", "no_collections")

IN, OUT = "in", "out"

# Categories whose dates are set by law, payroll or a lender; never movable in a plan.
FIXED_CATEGORIES = frozenset({"payroll", "statutory", "debt"})


def to_paise(value) -> int:
    """Convert a rupee amount (Decimal/str/int/float) to integer paise, half-up."""
    if value is None:
        return 0
    return int((Decimal(str(value)) * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def pct_of(paise: int, percent) -> int:
    """`percent`% of `paise`, rounded half-up (TDS, haircuts)."""
    if not percent:
        return 0
    return int((Decimal(paise) * Decimal(str(percent)) / 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))


@dataclass(frozen=True, slots=True)
class ViewDates:
    expected: date | None
    downside: date | None
    no_collections: date | None

    def get(self, view: View) -> date | None:
        return getattr(self, view)

    def replace(self, view: View, value: date | None) -> "ViewDates":
        d = {v: self.get(v) for v in VIEWS}
        d[view] = value
        return ViewDates(**d)


@dataclass(frozen=True, slots=True)
class PaymentWindow:
    earliest: date
    latest: date
    agreed_with: str | None = None
    evidence: str | None = None


@dataclass(frozen=True, slots=True)
class CashEvent:
    event_key: str
    source_type: str          # bill | schedule | disbursement | ar_invoice | recurring | adjustment | scenario_item
    source_id: str
    label: str
    direction: str            # in | out
    amount_paise: int
    category: str
    confidence: str           # confirmed | committed | pipeline | expected | estimated
    dates: ViewDates
    date_basis: dict          # view -> human-readable basis
    nominal_date: date | None = None
    counterparty: str | None = None
    counterparty_id: str | None = None
    document_number: str | None = None
    window: PaymentWindow | None = None
    fixed: bool = False
    link_path: str | None = None

    def in_view(self, view: View) -> bool:
        return self.dates.get(view) is not None

    def effective_date(self, view: View) -> date:
        d = self.dates.get(view)
        if d is None:
            raise ValueError(f"{self.event_key} is not in view {view}")
        return d


@dataclass(frozen=True, slots=True)
class Exclusion:
    source_type: str
    source_id: str
    label: str
    amount_paise: int
    reason: str
    detail: str
    views: tuple = VIEWS      # views the record is missing from
    link_path: str | None = None


@dataclass(frozen=True, slots=True)
class OpeningBalance:
    bank_account_id: str
    account_name: str
    account_mask: str | None
    balance_paise: int
    as_of: datetime
    source: str
    freshness: str            # fresh | stale | expired


@dataclass(frozen=True, slots=True)
class Snapshot:
    tenant_id: str
    as_of: datetime
    start: date
    horizon_days: int
    reserve_paise: int
    od_headroom_paise: int
    balances: tuple
    events: tuple
    exclusions: tuple
    coverage: dict
    content_hash: str = ""
    snapshot_id: str | None = None
    revision: int | None = None

    @property
    def end(self) -> date:
        return self.start + timedelta(days=self.horizon_days - 1)

    def horizon(self) -> list[date]:
        return [self.start + timedelta(days=i) for i in range(self.horizon_days)]

    def opening_total(self) -> int:
        return sum(b.balance_paise for b in self.balances)

    def event(self, key: str) -> CashEvent | None:
        for e in self.events:
            if e.event_key == key:
                return e
        return None


@dataclass(frozen=True, slots=True)
class DayRow:
    date: date
    banking_day: bool
    opening_paise: int
    inflow_paise: int
    outflow_paise: int
    closing_paise: int
    below_reserve: bool
    event_count: int


@dataclass(frozen=True, slots=True)
class Metrics:
    minimum_closing_paise: int
    minimum_date: date
    first_reserve_breach_date: date | None
    first_negative_date: date | None
    days_below_reserve: int
    total_inflow_paise: int
    total_outflow_paise: int
    closing_paise: int
    beyond_horizon_inflow_paise: int
    beyond_horizon_outflow_paise: int
    runway_days: int | None

    def key(self) -> tuple:
        """The figures a plan is judged on; a stale check compares these."""
        return (self.minimum_closing_paise, self.minimum_date, self.first_reserve_breach_date, self.closing_paise)


@dataclass(frozen=True, slots=True)
class ForecastResult:
    view: str
    opening_paise: int
    reserve_paise: int
    days: tuple
    metrics: Metrics
    category_totals: dict = field(default_factory=dict)
    events: tuple = ()        # the in-view events after overrides (not serialised by default)


def jsonable(obj):
    """Dataclass → JSON-friendly dict (dates as ISO strings)."""
    if hasattr(obj, "__dataclass_fields__"):
        return {k: jsonable(v) for k, v in asdict(obj).items()}
    if isinstance(obj, dict):
        return {str(k): jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [jsonable(v) for v in obj]
    if isinstance(obj, (date, datetime)):
        return obj.isoformat()
    return obj
