"""Turn source rows into a snapshot: dated events plus exclusions.

Pure functions, no I/O (docs/cashflow-forecast/04_LLD.md §5.2–5.6). The live
and fixture sources both hand over the same normalised rows (`SourceData`), so
the golden test on the fixture exercises exactly the code that runs in
production.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date, timedelta
from zoneinfo import ZoneInfo

from .calendar import NEXT, BusinessCalendar
from .collection_model import CollectionModel
from .types import (FIXED_CATEGORIES, IN, OUT, VIEWS, CashEvent, Exclusion, OpeningBalance, PaymentWindow,
                    Snapshot, ViewDates, jsonable, pct_of)

ALL = ("expected", "downside", "no_collections")
NOT_COLLECTIONS = ("expected", "downside")
PENDING_AP = {"PENDING_APPROVER", "PENDING_ACCOUNTANT", "PENDING_FC", "PENDING", "NEEDS_REVISION"}
CLOSED_AP = {"REJECTED", "VOID", "CANCELLED"}
INFLIGHT = {"PENDING", "PENDING_OTP", "PROCESSING", "INITIATED"}
OPEN_SCHEDULE = {"PENDING", "PARTIAL", "OVERDUE"}
UNAPPLIED_CONFIDENCE = 0.90


@dataclass
class Settings:
    reserve_paise: int = 0
    horizon_days: int = 30
    timezone: str = "Asia/Kolkata"
    default_view: str = "expected"
    include_pending_approval_ap: bool = True
    overdue_fallback_days: int = 5
    downside_exclude_overdue_after_days: int = 60
    min_customer_history: int = 3
    allow_self_approval: bool = False
    publish_daily: bool = True
    holidays: dict = field(default_factory=dict)        # date -> name

    @classmethod
    def from_row(cls, row: dict | None, holidays=None):
        s = cls()
        for k, v in (row or {}).items():
            if hasattr(s, k) and k != "holidays" and v is not None:
                setattr(s, k, v)
        s.holidays = dict(holidays or {})
        return s


@dataclass
class SourceData:
    """Normalised rows. Money in paise, dates as date, timestamps tz-aware."""
    accounts: list = field(default_factory=list)       # bank_account_id, account_name, account_mask, account_type, include, od_limit_paise
    balances: list = field(default_factory=list)       # latest per account: bank_account_id, balance_paise, as_of, source
    bills: list = field(default_factory=list)
    schedules: list = field(default_factory=list)
    disbursements: list = field(default_factory=list)
    windows: dict = field(default_factory=dict)        # invoice_id -> dict(earliest, latest, agreed_with, evidence)
    planned: dict = field(default_factory=dict)        # (source_type, source_id) -> date
    ar_open: list = field(default_factory=list)
    ar_history: list = field(default_factory=list)     # (customer_id, due_date, paid_on)
    unapplied: dict = field(default_factory=dict)      # invoice_id -> payment dict
    promises: dict = field(default_factory=dict)       # invoice_id -> dict(promised_date, promised_amount_paise)
    recurring: list = field(default_factory=list)
    adjustments: list = field(default_factory=list)
    failed_sources: list = field(default_factory=list)


class NoOpeningBalance(Exception):
    pass


def _freshness(cal: BusinessCalendar, as_of_local: date, today: date) -> str:
    age = cal.banking_days_between(as_of_local, today)
    return "fresh" if age <= 1 else "stale" if age <= 3 else "expired"


def assemble(data: SourceData, settings: Settings, today: date, tenant_id: str = "") -> Snapshot:
    tz = ZoneInfo(settings.timezone)
    cal = BusinessCalendar(settings.holidays)

    # ── Opening balance ────────────────────────────────────────────────────
    accounts = {str(a["bank_account_id"]): a for a in data.accounts}
    latest = {str(b["bank_account_id"]): b for b in data.balances}
    included = [a for a in data.accounts if a.get("include")]
    present = [latest[str(a["bank_account_id"])] for a in included if str(a["bank_account_id"]) in latest]
    if not present:
        raise NoOpeningBalance("No included bank account has a balance.")
    as_of = min(b["as_of"] for b in present)
    start = as_of.astimezone(tz).date() + timedelta(days=1)
    end = start + timedelta(days=settings.horizon_days - 1)
    balances = tuple(
        OpeningBalance(str(b["bank_account_id"]), accounts[str(b["bank_account_id"])]["account_name"],
                       accounts[str(b["bank_account_id"])].get("account_mask"), int(b["balance_paise"]), b["as_of"],
                       b.get("source", "statement"), _freshness(cal, b["as_of"].astimezone(tz).date(), today))
        for b in present)
    od_headroom = 0
    for a in data.accounts:
        if a.get("account_type") == "OVERDRAFT" and not a.get("include"):
            bal = latest.get(str(a["bank_account_id"]), {}).get("balance_paise", 0)
            od_headroom += max(0, int(a.get("od_limit_paise") or 0) - max(0, -int(bal)))

    events: list[CashEvent] = []
    exclusions: list[Exclusion] = []
    needs_setup: list[str] = []

    def first_on_or_after_start():
        return cal.next_banking_day(start)

    # ── Disbursements: in flight count once; succeeded are already in the bank ──
    inflight = {str(d["invoice_id"]): d for d in data.disbursements if d["status"] in INFLIGHT}
    succeeded = {str(d["invoice_id"]) for d in data.disbursements if d["status"] == "SUCCESS"}
    bill_by_id = {str(b["invoice_id"]): b for b in data.bills}
    for d in inflight.values():
        b = bill_by_id.get(str(d["invoice_id"]), {})
        supplier = b.get("supplier_name", "Supplier")
        day = first_on_or_after_start()
        events.append(CashEvent(
            event_key=f"disbursement:{d['disbursement_id']}", source_type="disbursement", source_id=str(d["disbursement_id"]),
            label=f"Payout in flight · {supplier}", direction=OUT, amount_paise=int(d["amount_paise"]), category="supplier",
            confidence="confirmed", dates=ViewDates(day, day, day), date_basis={v: "Payout already sent to the bank; clears on the first banking day" for v in VIEWS},
            counterparty=supplier, counterparty_id=str(b.get("supplier_id") or ""), document_number=b.get("bill_number"),
            fixed=True, link_path="/payments"))

    # ── Payables ───────────────────────────────────────────────────────────
    schedules = {}
    for s in data.schedules:
        if s["status"] in OPEN_SCHEDULE:
            schedules.setdefault(str(s["stg_bill_id"]), []).append(s)
    for b in data.bills:
        bid = str(b["invoice_id"])
        label = f"{b['supplier_name']} · {b['bill_number']}"
        link = f"/bills/{bid}"
        if b.get("payment_status") == "paid" or b.get("soft_status", "active") != "active":
            continue
        if b["status"] in CLOSED_AP:
            reason = "REJECTED" if b["status"] == "REJECTED" else "VOID"
            exclusions.append(Exclusion("bill", bid, label, b["net_payable_paise"], reason,
                                        "Bill rejected in approval." if reason == "REJECTED" else "Bill voided or cancelled.",
                                        link_path=link))
            continue
        if b["status"] == "DRAFT":
            continue
        if bid in inflight:
            exclusions.append(Exclusion("bill", bid, label, b["net_payable_paise"], "PAYOUT_IN_FLIGHT",
                                        "Counted once, as the in-flight payout.", link_path=link))
            continue
        if bid in succeeded:
            exclusions.append(Exclusion("bill", bid, label, b["net_payable_paise"], "PAID_VIA_DISBURSEMENT",
                                        "Payout already succeeded and is in the bank balance; bill status not yet synced.",
                                        link_path=link))
            continue
        if b.get("validation_flag") == "DUPLICATE":
            exclusions.append(Exclusion("bill", bid, label, b["net_payable_paise"], "SUSPECTED_DUPLICATE",
                                        "Held for review; not scheduled.", link_path="/review"))
            continue
        if (b.get("currency") or "INR") != "INR":
            exclusions.append(Exclusion("bill", bid, label, b["outstanding_paise"], "NON_INR",
                                        f"Bill is in {b.get('currency')}; only INR is forecast.", link_path=link))
            continue
        approved = b["status"] == "APPROVED"
        if not approved and (b["status"] not in PENDING_AP or not settings.include_pending_approval_ap):
            continue
        w = data.windows.get(bid)
        window = PaymentWindow(w["earliest"], w["latest"], w.get("agreed_with"), w.get("evidence")) if w else None
        units = []
        for s in schedules.get(str(b.get("stg_bill_id")), []):
            units.append((f"schedule:{s['schedule_id']}", "schedule", str(s["schedule_id"]),
                          int(s["scheduled_paise"]) - int(s["paid_paise"]), s["due_date"], "Instalment due"))
        if not units:
            amount = int(b["outstanding_paise"]) - (int(b.get("tds_paise") or 0) if not b.get("amount_paid_paise") else 0)
            units.append((f"bill:{bid}", "bill", bid, amount, b.get("due_date"), "Due"))
        for key, stype, sid, amount, due, basis in units:
            planned = data.planned.get((stype, sid)) or data.planned.get(("bill", bid))
            if planned:
                nominal, basis = planned, "Approved plan: pay"
            else:
                nominal = due
            if nominal is None:
                exclusions.append(Exclusion("bill", bid, label, amount, "UNDATED", "Bill has no due date. Add one to forecast it.",
                                            link_path=link))
                continue
            if amount <= 0:
                continue
            if nominal < start:
                day = first_on_or_after_start()
                basis = f"Overdue since {_d(nominal)}; paid on the first banking day"
            else:
                day = cal.next_banking_day(nominal)
                basis = f"{basis} {_d(nominal)}" + ("" if day == nominal else f"; not a banking day, so {_d(day)}")
            views = ALL if approved else NOT_COLLECTIONS
            dates = ViewDates(*(day if v in views else None for v in VIEWS))
            events.append(CashEvent(
                event_key=key, source_type=stype, source_id=sid, label=label, direction=OUT, amount_paise=amount,
                category="supplier", confidence="committed" if approved else "pipeline", dates=dates,
                date_basis={v: basis for v in views}, nominal_date=nominal, counterparty=b["supplier_name"],
                counterparty_id=str(b.get("supplier_id") or ""), document_number=b["bill_number"], window=window,
                link_path=link))

    # ── Receivables ────────────────────────────────────────────────────────
    model = CollectionModel(data.ar_history, settings.min_customer_history, settings.overdue_fallback_days)
    for inv in data.ar_open:
        if inv["status"] not in ("open", "partially_paid", "disputed") or int(inv["outstanding_paise"]) <= 0:
            continue
        iid = str(inv["id"])
        label = f"{inv['customer_name']} · {inv['invoice_number']}"
        link = f"/receivables/invoices/{iid}"
        if iid in data.unapplied:
            pay = data.unapplied[iid]
            exclusions.append(Exclusion("ar_invoice", iid, label, int(inv["outstanding_paise"]), "SETTLED_PENDING_APPLICATION",
                                        f"Receipt of {pay['received_on']:%d %b} is already in the bank balance and awaits cash application.",
                                        link_path=f"/receivables/cash-application?payment={pay['id']}"))
            continue
        if inv["status"] == "disputed":
            exclusions.append(Exclusion("ar_invoice", iid, label, int(inv["outstanding_paise"]), "DISPUTED",
                                        "Disputed invoices are not forecast.", link_path=link))
            continue
        if (inv.get("currency") or "INR") != "INR":
            exclusions.append(Exclusion("ar_invoice", iid, label, int(inv["outstanding_paise"]), "NON_INR",
                                        f"Invoice is in {inv.get('currency')}; only INR is forecast.", link_path=link))
            continue
        if inv.get("due_date") is None:
            exclusions.append(Exclusion("ar_invoice", iid, label, int(inv["outstanding_paise"]), "UNDATED",
                                        "Invoice has no due date.", link_path=link))
            continue
        exp_tds = pct_of(int(inv.get("taxable_paise") or 0), inv.get("tds_rate_hint")) if not inv.get("tds_paise") else 0
        amount = int(inv["outstanding_paise"]) - exp_tds
        promise = data.promises.get(iid)
        d = model.dates_for(inv["customer_id"], inv["due_date"], start, cal,
                            promise["promised_date"] if promise else None)
        down = d.downside
        basis = {"expected": d.basis_expected, "downside": d.basis_downside}
        if d.overdue_days > settings.downside_exclude_overdue_after_days:
            down = None
            basis.pop("downside")
            exclusions.append(Exclusion("ar_invoice", iid, label, amount, "AGED_OVER_60_DAYS_DOWNSIDE",
                                        f"{d.overdue_days} days overdue; counted in the expected view only.",
                                        views=("downside",), link_path=link))
        if exp_tds:
            basis["tds"] = f"Net of ₹{exp_tds / 100:,.2f} TDS the customer is expected to deduct"
        events.append(CashEvent(
            event_key=f"ar:{iid}", source_type="ar_invoice", source_id=iid, label=label, direction=IN, amount_paise=amount,
            category="customer", confidence="expected", dates=ViewDates(d.expected, down, None), date_basis=basis,
            nominal_date=inv["due_date"], counterparty=inv["customer_name"], counterparty_id=str(inv["customer_id"]),
            document_number=inv["invoice_number"], link_path=link))

    # ── Recurring items ────────────────────────────────────────────────────
    for r in data.recurring:
        if not r.get("active", True):
            continue
        if not r.get("amount_paise"):
            needs_setup.append(r["name"])
            continue
        for nominal in _occurrences(r, start - timedelta(days=10), end + timedelta(days=10)):
            pay_on = cal.roll(nominal, r.get("business_day_rule") or NEXT)
            if not (start <= pay_on <= end):
                continue
            if r.get("start_date") and nominal < r["start_date"] or r.get("end_date") and nominal > r["end_date"]:
                continue
            planned = data.planned.get(("recurring", f"{r['id']}:{nominal.isoformat()}"))
            day = planned or pay_on
            events.append(CashEvent(
                event_key=f"recurring:{r['id']}:{nominal.isoformat()}", source_type="recurring", source_id=str(r["id"]),
                label=r["name"], direction=r.get("direction", OUT), amount_paise=int(r["amount_paise"]),
                category=r["category"], confidence=r.get("confidence", "committed"), dates=ViewDates(day, day, day),
                date_basis={v: (f"Approved plan: pay {_d(day)}" if planned else _recurring_basis(r, nominal, pay_on)) for v in VIEWS},
                nominal_date=nominal, fixed=r["category"] in FIXED_CATEGORIES or bool(r.get("statutory"))))

    # ── Adjustments ────────────────────────────────────────────────────────
    for a in data.adjustments:
        if not a.get("active", True):
            continue
        day = data.planned.get(("adjustment", str(a["id"]))) or cal.next_banking_day(max(a["on_date"], start))
        if day > end + timedelta(days=366):
            continue
        estimated_inflow = a["direction"] == IN and a["confidence"] != "committed"
        views = ("expected",) if estimated_inflow else ALL
        events.append(CashEvent(
            event_key=f"adjustment:{a['id']}", source_type="adjustment", source_id=str(a["id"]), label=a["name"],
            direction=a["direction"], amount_paise=int(a["amount_paise"]), category=a["category"],
            confidence=a["confidence"], dates=ViewDates(*(day if v in views else None for v in VIEWS)),
            date_basis={v: "One-off item entered in forecast inputs" for v in views}, nominal_date=a["on_date"],
            fixed=a["category"] in FIXED_CATEGORIES))

    missing = [a["account_name"] for a in included if str(a["bank_account_id"]) not in latest]
    coverage = {
        "state": "partial" if (data.failed_sources or missing) else "complete",
        "failed_sources": list(data.failed_sources),
        "missing_balances": missing,
        "needs_setup": needs_setup,
        "event_count": len(events),
        "exclusion_count": len(exclusions),
    }
    snap = Snapshot(tenant_id=str(tenant_id), as_of=as_of, start=start, horizon_days=settings.horizon_days,
                    reserve_paise=int(settings.reserve_paise), od_headroom_paise=od_headroom, balances=balances,
                    events=tuple(sorted(events, key=lambda e: e.event_key)),
                    exclusions=tuple(sorted(exclusions, key=lambda x: (x.source_type, x.source_id, x.reason))),
                    coverage=coverage)
    return _with_hash(snap)


def _d(d: date) -> str:
    return f"{d.day} {d:%b}"


def _ordinal(n: int) -> str:
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def _recurring_basis(r, nominal: date, pay_on: date) -> str:
    anchor = str(r["anchor"])
    if r["frequency"] == "weekly":
        when = f"Every {['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'][int(anchor)]}"
    elif anchor == "last_banking_day":
        when = "Monthly, on the last banking day"
    else:
        when = f"{'Quarterly' if r['frequency'] == 'quarterly' else 'Monthly'}, on the {_ordinal(int(anchor))}"
    if pay_on != nominal:
        side = "before" if pay_on < nominal else "after"
        when += f"; {_d(nominal)} isn't a banking day, so the banking day {side}"
    return when


def _occurrences(r, lo: date, hi: date):
    """Nominal due dates of a recurring item in [lo, hi]."""
    freq, anchor = r["frequency"], str(r["anchor"])
    d = lo
    while d <= hi:
        last_day = (d + timedelta(days=1)).month != d.month
        if freq == "weekly" and d.weekday() == int(anchor):
            yield d
        elif freq == "monthly":
            if anchor == "last_banking_day":
                if last_day:
                    yield d
            elif d.day == int(anchor) or (last_day and d.day < int(anchor)):
                yield d
        elif freq == "quarterly" and d.month in (r.get("quarter_months") or []):
            if d.day == int(anchor) or (last_day and d.day < int(anchor)):
                yield d
        d += timedelta(days=1)


def _with_hash(snap: Snapshot) -> Snapshot:
    canonical = {
        "balances": sorted((b.bank_account_id, b.balance_paise, b.as_of.isoformat()) for b in snap.balances),
        "events": [(e.event_key, e.direction, e.amount_paise, jsonable(e.dates), e.confidence, e.category,
                    sorted(e.date_basis.items()), jsonable(e.window)) for e in snap.events],
        "exclusions": [(x.source_type, x.source_id, x.reason, x.amount_paise, list(x.views)) for x in snap.exclusions],
        "settings": (snap.reserve_paise, snap.horizon_days, snap.start.isoformat(), snap.od_headroom_paise),
    }
    digest = hashlib.sha256(json.dumps(canonical, separators=(",", ":"), sort_keys=True, default=str).encode()).hexdigest()
    from dataclasses import replace
    return replace(snap, content_hash=digest)
