"""Indian banking-day calendar (docs/cashflow-forecast/04_LLD.md §5.1).

Non-banking days: Sundays, the 2nd and 4th Saturdays, and tenant holidays.
"""

from __future__ import annotations

from datetime import date, timedelta

NEXT, PREVIOUS = "next_banking_day", "previous_banking_day"


class BusinessCalendar:
    def __init__(self, holidays=()):
        self.holidays = frozenset(holidays)

    def is_banking_day(self, d: date) -> bool:
        if d.weekday() == 6:
            return False
        if d.weekday() == 5 and ((d.day - 1) // 7 + 1) in (2, 4):
            return False
        return d not in self.holidays

    def next_banking_day(self, d: date) -> date:
        while not self.is_banking_day(d):
            d += timedelta(days=1)
        return d

    def prev_banking_day(self, d: date) -> date:
        while not self.is_banking_day(d):
            d -= timedelta(days=1)
        return d

    def roll(self, d: date, rule: str) -> date:
        if rule == PREVIOUS:
            return self.prev_banking_day(d)
        if rule == NEXT:
            return self.next_banking_day(d)
        return d

    def add_banking_days(self, d: date, n: int) -> date:
        for _ in range(n):
            d = self.next_banking_day(d + timedelta(days=1))
        return d

    def banking_days_between(self, a: date, b: date) -> int:
        """Banking days in (a, b]; 0 when b <= a."""
        n, d = 0, a
        while d < b:
            d += timedelta(days=1)
            if self.is_banking_day(d):
                n += 1
        return n
