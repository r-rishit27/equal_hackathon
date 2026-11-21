"""When will a customer pay? (docs/cashflow-forecast/02_TECHNICAL_DESIGN.md §6).

A transparent statistical rule an accountant can check by hand:
- delay = paid date − due date, from settled invoices;
- the customer's own median / p80 when it has enough history, else the tenant's;
- an invoice already `o` days late uses the *conditional* remaining delay of
  comparable invoices that were at least that late.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import date, timedelta


def percentile_nearest_rank(values, q_num: int, q_den: int) -> int:
    """Nearest-rank percentile with integer maths (q = q_num / q_den)."""
    s = sorted(values)
    k = -(-len(s) * q_num // q_den) - 1
    return s[max(0, min(len(s) - 1, k))]


def median(values) -> int:
    return round(statistics.median(values))


def _d(d: date) -> str:
    return f"{d.day} {d:%b}"


def _days(n: int) -> str:
    if n == 0:
        return "on the due date"
    return f"{abs(n)} day{'s' if abs(n) != 1 else ''} {'late' if n > 0 else 'early'}"


def _who(basis: str) -> str:
    return "this customer" if basis == "customer" else "customers overall (too little history for this one)"


@dataclass(frozen=True)
class PaymentProfile:
    median: int
    p80: int
    n: int
    basis: str          # customer | tenant

    @classmethod
    def of(cls, delays, basis):
        return cls(median(delays), percentile_nearest_rank(delays, 4, 5), len(delays), basis)


@dataclass(frozen=True)
class InvoiceDates:
    expected: date
    downside: date
    basis_expected: str
    basis_downside: str
    overdue_days: int


class CollectionModel:
    def __init__(self, history, min_history: int = 3, fallback_days: int = 5):
        """history: iterable of (customer_id, due_date, paid_on)."""
        self.min_history = min_history
        self.fallback_days = fallback_days
        self.delays: dict[str, list[int]] = {}
        for customer_id, due, paid_on in history:
            if due and paid_on:
                self.delays.setdefault(str(customer_id), []).append((paid_on - due).days)
        self.all_delays = [x for v in self.delays.values() for x in v]
        self.tenant = PaymentProfile.of(self.all_delays, "tenant") if self.all_delays else PaymentProfile(0, 0, 0, "tenant")

    def profile(self, customer_id) -> PaymentProfile:
        own = self.delays.get(str(customer_id), [])
        if len(own) >= self.min_history:
            return PaymentProfile.of(own, "customer")
        return self.tenant

    def dates_for(self, customer_id, due: date, start: date, calendar, promise_date: date | None = None) -> InvoiceDates:
        prof = self.profile(customer_id)
        overdue = (start - due).days
        if overdue <= 0:
            exp = max(start, due + timedelta(days=prof.median))
            down = max(start, due + timedelta(days=prof.p80))
            b_exp = f"Due {_d(due)}; {_who(prof.basis)} typically pays {_days(prof.median)} (median of {prof.n} paid invoices)"
            b_down = f"Due {_d(due)}; slow case {_days(prof.p80)} (80th percentile of {prof.n} paid invoices)"
        else:
            exp = None
            for pool, basis in ((self.delays.get(str(customer_id), []), "customer"), (self.all_delays, "tenant")):
                rest = [x - overdue for x in pool if x > overdue]
                if len(rest) >= self.min_history:
                    r_med, r_p80 = median(rest), percentile_nearest_rank(rest, 4, 5)
                    exp, down = start + timedelta(days=r_med), start + timedelta(days=r_p80)
                    b_exp = (f"{overdue} days overdue; invoices from {_who(basis)} that ran this late "
                             f"took {r_med} more days (median of {len(rest)})")
                    b_down = f"{overdue} days overdue; slow case {r_p80} more days (80th percentile of {len(rest)})"
                    break
            if exp is None:
                exp = calendar.add_banking_days(start, self.fallback_days)
                down = exp + timedelta(days=14)
                b_exp = b_down = f"{overdue} days overdue; no comparable payment history, so assumed soon"
        if promise_date is not None and promise_date >= start:
            exp, b_exp = promise_date, f"Customer promised to pay on {_d(promise_date)}"
        return InvoiceDates(calendar.next_banking_day(exp), calendar.next_banking_day(down), b_exp, b_down, overdue)
