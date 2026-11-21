"""Cash forecast rules: calendar, collection model, payables amounts, overrides, engine edges, auth."""

from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from backend_ocr.app.cashflow import engine, scenario as sc
from backend_ocr.app.cashflow.calendar import BusinessCalendar
from backend_ocr.app.cashflow.collection_model import CollectionModel, percentile_nearest_rank
from backend_ocr.app.cashflow.rules import Settings, SourceData, assemble
from backend_ocr.app.cashflow.types import to_paise

IST = timezone(timedelta(hours=5, minutes=30))
CAL = BusinessCalendar({date(2026, 11, 24)})


# ── Calendar ────────────────────────────────────────────────────────────────
def test_banking_days():
    assert CAL.is_banking_day(date(2026, 11, 21))          # 3rd Saturday
    assert not CAL.is_banking_day(date(2026, 11, 28))      # 4th Saturday
    assert not CAL.is_banking_day(date(2026, 12, 12))      # 2nd Saturday
    assert not CAL.is_banking_day(date(2026, 11, 24))      # holiday
    assert not CAL.is_banking_day(date(2026, 11, 22))      # Sunday
    assert CAL.prev_banking_day(date(2026, 12, 20)) == date(2026, 12, 19)   # GST due Sunday → Saturday
    assert CAL.next_banking_day(date(2026, 11, 28)) == date(2026, 11, 30)
    assert CAL.add_banking_days(date(2026, 11, 21), 2) == date(2026, 11, 25)


# ── Money ───────────────────────────────────────────────────────────────────
def test_to_paise_half_up():
    assert to_paise("43,51,482.505".replace(",", "")) == 435148251
    assert to_paise("0.005") == 1 and to_paise(None) == 0 and to_paise(-1.5) == -150


# ── Collection model ────────────────────────────────────────────────────────
def test_percentile_nearest_rank():
    assert percentile_nearest_rank([1, 2, 3, 4, 5], 4, 5) == 4
    assert percentile_nearest_rank([7], 4, 5) == 7
    assert percentile_nearest_rank(list(range(10)), 4, 5) == 7


def history(customer, delays):
    due = date(2026, 6, 1)
    return [(customer, due, due + timedelta(days=d)) for d in delays]


def test_customer_vs_tenant_profile_and_conditional_delay():
    rows = history("a", [0, 2, 4]) + history("b", [30]) + history("c", [10, 20, 40, 50])
    m = CollectionModel(rows)
    assert m.profile("a").basis == "customer" and m.profile("a").median == 2
    assert m.profile("b").basis == "tenant"
    start = date(2026, 11, 23)
    not_due = m.dates_for("a", date(2026, 11, 25), start, CAL)
    assert not_due.expected == date(2026, 11, 27) and "this customer typically pays 2 days late (median of 3 paid invoices)" in not_due.basis_expected
    # 15 days late; customer c's comparable delays 20, 40, 50 → remaining 5, 25, 35 → median 25.
    late = m.dates_for("c", start - timedelta(days=15), start, CAL)
    assert late.expected == CAL.next_banking_day(start + timedelta(days=25))
    assert "from this customer that ran this late took 25 more days (median of 3)" in late.basis_expected
    # Later than any history → fallback.
    lost = m.dates_for("a", start - timedelta(days=200), start, CAL)
    assert "no comparable payment history" in lost.basis_expected
    # Promise moves only the expected date.
    promised = m.dates_for("c", start - timedelta(days=15), start, CAL, date(2026, 11, 26))
    assert promised.expected == date(2026, 11, 26) and promised.downside == late.downside


# ── Snapshot assembly ───────────────────────────────────────────────────────
def books(**over):
    acct = "11111111-1111-4111-8111-111111111111"
    d = SourceData(
        accounts=[dict(bank_account_id=acct, account_name="Ops", account_mask="XX1", account_type="CURRENT", include=True,
                       od_limit_paise=0)],
        balances=[dict(bank_account_id=acct, balance_paise=10_00_000_00, as_of=datetime(2026, 11, 20, 18, tzinfo=IST),
                       source="statement")])
    for k, v in over.items():
        setattr(d, k, v)
    return d


def bill(**over):
    b = dict(invoice_id="b1", stg_bill_id="s1", supplier_id="v1", supplier_name="Vendor", bill_number="V/1",
             due_date=date(2026, 11, 25), status="APPROVED", payment_status="unpaid", validation_flag="OK",
             soft_status="active", currency="INR", outstanding_paise=118_000_00, amount_paid_paise=0, tds_paise=1_000_00,
             net_payable_paise=117_000_00)
    b.update(over)
    return b


def build(data, **settings):
    return assemble(data, Settings(reserve_paise=5_00_000_00, holidays={date(2026, 11, 24): "x"}, **settings),
                    date(2026, 11, 21), "t")


def test_bill_amount_is_net_of_tds_until_first_payment():
    snap = build(books(bills=[bill(), bill(invoice_id="b2", stg_bill_id="s2", amount_paid_paise=50_000_00,
                                         outstanding_paise=68_000_00)]))
    assert snap.event("bill:b1").amount_paise == 117_000_00
    assert snap.event("bill:b2").amount_paise == 68_000_00


def test_pipeline_bill_not_in_no_collections_and_setting_respected():
    pending = bill(status="PENDING_FC")
    e = build(books(bills=[pending])).event("bill:b1")
    assert e.confidence == "pipeline" and e.dates.no_collections is None and e.dates.expected == date(2026, 11, 25)
    assert build(books(bills=[pending]), include_pending_approval_ap=False).event("bill:b1") is None


def test_overdue_bill_catches_up_and_non_inr_is_excluded():
    snap = build(books(bills=[bill(due_date=date(2026, 11, 2)), bill(invoice_id="b3", stg_bill_id="s3", currency="USD")]))
    assert snap.event("bill:b1").dates.expected == date(2026, 11, 21)
    assert [x.reason for x in snap.exclusions] == ["NON_INR"]


def test_missing_balance_and_partial_coverage():
    data = books()
    data.accounts.append(dict(bank_account_id="2", account_name="SBI", account_mask=None, account_type="CURRENT",
                              include=True, od_limit_paise=0))
    snap = build(data)
    assert snap.coverage["state"] == "partial" and snap.coverage["missing_balances"] == ["SBI"]
    with pytest.raises(Exception):
        build(books(balances=[]))


def test_recurring_template_without_amount_needs_setup():
    rec = dict(id="r1", name="GST", category="statutory", direction="out", amount_paise=None, frequency="monthly",
               anchor="20", business_day_rule="previous_banking_day", confidence="committed", statutory=True,
               start_date=date(2026, 4, 1), end_date=None, active=True)
    snap = build(books(recurring=[rec]))
    assert snap.coverage["needs_setup"] == ["GST"] and not snap.events
    snap = build(books(recurring=[dict(rec, amount_paise=100)]))
    assert [(e.dates.expected, e.fixed) for e in snap.events] == [(date(2026, 12, 19), True)]


# ── Engine edges ────────────────────────────────────────────────────────────
def test_reserve_is_strict_and_earliest_minimum_wins():
    snap = build(books(bills=[bill(outstanding_paise=5_01_000_00, tds_paise=1_000_00)]))   # leaves exactly ₹5 L
    r = engine.project(snap, "expected", calendar=CAL)
    assert r.metrics.minimum_closing_paise == 5_00_000_00 and r.metrics.first_reserve_breach_date is None
    assert r.metrics.minimum_date == date(2026, 11, 25)


# ── Overrides ───────────────────────────────────────────────────────────────
def shift(key, d):
    return sc.ShiftEvent(op="shift_event", event_key=key, to_date=d)


@pytest.mark.parametrize("override,code", [
    (shift("bill:b1", date(2026, 11, 27)), "OUTSIDE_PAYMENT_WINDOW"),
    (shift("bill:b1", date(2026, 11, 28)), "NON_BANKING_DAY"),
    (shift("bill:b1", date(2026, 11, 20)), "BEFORE_HORIZON"),
    (shift("nope", date(2026, 11, 26)), "EVENT_NOT_FOUND"),
    (sc.ExcludeEvent(op="exclude_event", event_key="bill:b1"), "INFLOW_ONLY"),
    (sc.AddItem(op="add_item", label="CC drawdown", direction="in", amount_paise=1, on_date=date(2026, 11, 26),
                category="financing"), "EXCEEDS_OD_HEADROOM"),
])
def test_refusals(override, code):
    snap = build(books(bills=[bill()]))
    refusals = sc.validate(snap, [override], "expected", CAL)
    assert refusals and refusals[0]["code"] == code


def test_window_allows_up_to_latest_and_earlier_is_always_fine():
    snap = build(books(bills=[bill()], windows={"b1": dict(earliest=date(2026, 11, 25), latest=date(2026, 12, 2))}))
    assert sc.validate(snap, [shift("bill:b1", date(2026, 12, 2))], "expected", CAL) == []
    assert sc.validate(snap, [shift("bill:b1", date(2026, 12, 3))], "expected", CAL)[0]["code"] == "OUTSIDE_PAYMENT_WINDOW"
    assert sc.validate(snap, [shift("bill:b1", date(2026, 11, 23))], "expected", CAL) == []
    assert sc.validate(snap, [shift("bill:b1", date(2026, 11, 23)), shift("bill:b1", date(2026, 11, 25))],
                       "expected", CAL)[0]["code"] == "DUPLICATE_TARGET"


def test_apply_shift_and_kinds():
    snap = build(books(bills=[bill()], windows={"b1": dict(earliest=date(2026, 11, 25), latest=date(2026, 12, 2))}))
    events, applied = sc.apply(snap, [shift("bill:b1", date(2026, 12, 1))], "expected", CAL)
    moved = next(e for e in events if e.event_key == "bill:b1")
    assert moved.dates.expected == date(2026, 12, 1) and moved.dates.downside == date(2026, 11, 25)
    assert applied[0]["kind"] == "decision"


# ── Router authorisation ────────────────────────────────────────────────────
@pytest.mark.parametrize("role,cap,allowed", [
    ("auditor", "view", True), ("auditor", "edit", False), ("accountant", "edit", True),
    ("accountant", "approve", False), ("finance_controller", "approve", True), ("member", "view", False),
    ("approver", "view", False), ("accountant", "settings", False), ("admin", "settings", True),
])
def test_role_matrix(monkeypatch, role, cap, allowed):
    from backend_ocr.app.routers import cash_forecast as r
    from backend_ocr.app.security import auth
    monkeypatch.setattr(r, "require_tenant", lambda: "t")
    monkeypatch.setattr(r, "is_impersonating", lambda: False)
    token = auth._current_roles.set((role,))
    try:
        if allowed:
            assert r._require(cap)[0] == "t"
        else:
            with pytest.raises(HTTPException) as e:
                r._require(cap)
            assert e.value.status_code == 403
    finally:
        auth._current_roles.reset(token)


def test_impersonated_session_is_read_only(monkeypatch):
    from backend_ocr.app.routers import cash_forecast as r
    from backend_ocr.app.security import auth
    monkeypatch.setattr(r, "require_tenant", lambda: "t")
    monkeypatch.setattr(r, "is_impersonating", lambda: True)
    token = auth._current_roles.set(("admin",))
    try:
        assert r._require("view")
        with pytest.raises(HTTPException):
            r._require("edit")
    finally:
        auth._current_roles.reset(token)


def test_csv_cells_are_formula_safe():
    from backend_ocr.app.routers.cash_forecast import _cell
    assert _cell("=HYPERLINK(1)") == "'=HYPERLINK(1)" and _cell("-1500.00") == "-1500.00" and _cell("Ankur") == "Ankur"
