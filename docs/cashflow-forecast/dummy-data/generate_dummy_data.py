#!/usr/bin/env python3
"""Synthetic dataset and golden forecast for the Reckon.ai Cash Flow Forecast module.

Run from the repository root:

    python3 docs/cashflow-forecast/dummy-data/generate_dummy_data.py

Output goes to docs/cashflow-forecast/dummy-data/seed/. The script is
deterministic (fixed seed, fixed as-of time), so rerunning it reproduces every
file byte for byte. Every name, GSTIN, PAN, account number and UTR is synthetic.

The second half of this file is a *reference* implementation of the forecast
rules in ../04_LLD.md. It exists to produce `expected_forecast.json`, the
golden output the production engine must match. It is deliberately small and
readable; it is not the production engine.

Money is integer paise everywhere. Dates are Asia/Kolkata business dates.
"""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
import json
import random
import statistics
import uuid
from pathlib import Path

OUT = Path(__file__).resolve().parent / "seed"
SEED = 20261121
rng = random.Random(SEED)

TENANT_ID = "7f3c2a10-5b8e-4c1d-9a6f-0c2e4d8b1a01"
AS_OF = "2026-11-20T18:30:00+05:30"          # bank balance timestamp (Friday close)
START = dt.date(2026, 11, 21)                  # first forecast day
HORIZON_DAYS = 30
END = START + dt.timedelta(days=HORIZON_DAYS - 1)
HISTORY_FROM = dt.date(2026, 5, 1)             # AR/AP history used by the collection model
STATEMENT_FROM = dt.date(2026, 8, 22)          # 91 days of bank statement


def uid(*parts: str) -> str:
    """Stable UUID so reruns produce identical ids."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "reckon-cf/" + "/".join(parts)))


def rupees(paise: int) -> str:
    return f"{paise / 100:.2f}"


def inr(paise: int) -> str:
    """Indian digit grouping, for the summary printout."""
    neg = paise < 0
    r = (abs(paise) + 50) // 100          # round half up to whole rupees
    s = str(r)
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        s = ",".join(groups + [tail])
    return ("-₹" if neg else "₹") + s


# ── Business calendar ───────────────────────────────────────────────────────
# Synthetic calendar for the fixture. Production loads the tenant's state
# calendar; verify against the RBI / state holiday list before relying on it.
HOLIDAYS = {
    dt.date(2026, 10, 2): "Gandhi Jayanti",
    dt.date(2026, 10, 20): "Dussehra",
    dt.date(2026, 11, 9): "Diwali (Lakshmi Puja)",
    dt.date(2026, 11, 10): "Diwali (Balipratipada)",
    dt.date(2026, 11, 24): "Guru Nanak Jayanti",
    dt.date(2026, 12, 25): "Christmas",
}


def is_banking_day(d: dt.date) -> bool:
    if d.weekday() == 6:
        return False
    if d.weekday() == 5 and ((d.day - 1) // 7 + 1) in (2, 4):
        return False
    return d not in HOLIDAYS


def next_banking_day(d: dt.date) -> dt.date:
    while not is_banking_day(d):
        d += dt.timedelta(days=1)
    return d


def prev_banking_day(d: dt.date) -> dt.date:
    while not is_banking_day(d):
        d -= dt.timedelta(days=1)
    return d


def add_months(d: dt.date, n: int, day: int) -> dt.date:
    m = d.month - 1 + n
    y, m = d.year + m // 12, m % 12 + 1
    last = (dt.date(y + (m == 12), m % 12 + 1, 1) - dt.timedelta(days=1)).day
    return dt.date(y, m, min(day, last))


# ── Identity helpers (synthetic but format-valid) ───────────────────────────
B36 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def gstin(state: str, pan: str) -> str:
    body = f"{state}{pan}1Z"
    total = 0
    for i, ch in enumerate(body):
        prod = B36.index(ch) * (1 if i % 2 == 0 else 2)
        total += prod // 36 + prod % 36
    return body + B36[(36 - total % 36) % 36]


def pan(entity: str) -> str:
    letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    return ("".join(rng.choice(letters) for _ in range(3)) + entity
            + rng.choice(letters) + f"{rng.randint(1000, 9999)}" + rng.choice(letters))


def utr(bank: str, d: dt.date) -> str:
    return f"{bank}N{d:%y%j}{rng.randint(10**8, 10**9 - 1)}"


# ── Tenant, accounts, settings ──────────────────────────────────────────────
tenant_pan = pan("C")
TENANT = {
    "tenant_id": TENANT_ID,
    "legal_name": "Kaveri Packaging & Distribution Pvt Ltd (synthetic)",
    "trade_name": "Kaveri Pack",
    "industry": "B2B packaging materials distributor",
    "state": "Maharashtra",
    "gstin": gstin("27", tenant_pan),
    "pan": tenant_pan,
    "timezone": "Asia/Kolkata",
    "base_currency": "INR",
    "annual_turnover_paise": 24_00_00_000_00,   # ₹24 Cr
    "employees": 46,
    "users": [
        {"user_id": uid("user", "owner"), "name": "Owner (synthetic)", "email": "owner@kaveri.example", "role": "finance_controller", "persona": "Owner / approver"},
        {"user_id": uid("user", "acct"), "name": "Accountant (synthetic)", "email": "accounts@kaveri.example", "role": "accountant", "persona": "Accountant / preparer"},
        {"user_id": uid("user", "audit"), "name": "CA auditor (synthetic)", "email": "audit@kaveri.example", "role": "auditor", "persona": "Read-only reviewer"},
        {"user_id": uid("user", "member"), "name": "Sales coordinator (synthetic)", "email": "sales@kaveri.example", "role": "member", "persona": "No cash forecast access"},
    ],
}

ACCOUNTS = [
    {"bank_account_id": uid("acct", "hdfc"), "account_name": "HDFC Current - Operations", "bank_name": "HDFC Bank",
     "ifsc_code": "HDFC0000123", "account_mask": "XXXXXX4821", "account_type": "CURRENT", "currency_code": "INR",
     "is_primary": True, "is_active": True, "include_in_forecast": True, "od_limit_paise": 0},
    {"bank_account_id": uid("acct", "sbi"), "account_name": "SBI Current - Collections", "bank_name": "State Bank of India",
     "ifsc_code": "SBIN0004567", "account_mask": "XXXXXXX0937", "account_type": "CURRENT", "currency_code": "INR",
     "is_primary": False, "is_active": True, "include_in_forecast": True, "od_limit_paise": 0},
    {"bank_account_id": uid("acct", "sbiod"), "account_name": "SBI Cash Credit (OD)", "bank_name": "State Bank of India",
     "ifsc_code": "SBIN0004567", "account_mask": "XXXXXXX5512", "account_type": "OVERDRAFT", "currency_code": "INR",
     "is_primary": False, "is_active": True, "include_in_forecast": False, "od_limit_paise": 40_00_000_00},
]
HDFC, SBI = ACCOUNTS[0]["bank_account_id"], ACCOUNTS[1]["bank_account_id"]
# Balances on 22 Aug 2026. The as-of balances fall out of the simulated statement.
STATEMENT_START = {HDFC: 45_20_000_00, SBI: 6_40_000_00}
PAYOUT_SHARE = 0.40
CC_START = 10_00_000_00   # cash credit drawn on 22 Aug

SETTINGS = {
    "tenant_id": TENANT_ID,
    "reserve_paise": 15_00_000_00,           # ≈ one payroll run + rent
    "horizon_days": HORIZON_DAYS,
    "timezone": "Asia/Kolkata",
    "default_view": "expected",
    "include_pending_approval_ap": True,     # expected + downside include bills still in approval
    "overdue_fallback_days": 5,              # overdue AR with no comparable late history: start + N banking days
    "downside_exclude_overdue_after_days": 60,
    "min_customer_history": 3,              # paid invoices needed for a customer-specific delay
    "vendor_payment_roll": "next_banking_day",
    "statutory_payment_roll": "previous_banking_day",
    "receipt_roll": "next_banking_day",
    "show_od_headroom": True,
    "holiday_calendar": [{"date": d.isoformat(), "name": n} for d, n in sorted(HOLIDAYS.items())],
    "updated_by": TENANT["users"][0]["user_id"],
}

# ── Customers (AR) ──────────────────────────────────────────────────────────
# profile: (median delay days, spread) used only to synthesise history.
CUSTOMER_SPECS = [
    ("Sahyadri Agro Foods Pvt Ltd", "27", 45, "slow", 2),
    ("Malabar Fresh Mart LLP", "32", 30, "slight", 0),
    ("Trinetra Pharma Distributors", "36", 30, "on_time", 2),
    ("Kalinga Home Essentials Pvt Ltd", "21", 30, "slight", 1),
    ("Narmada Dairy Products Ltd", "24", 45, "on_time", 2),
    ("Konkan Spices & Masala Co", "27", 30, "erratic", 1),
    ("Brahmaputra Tea Traders", "18", 60, "slow", 0),
    ("Vindhya E-Commerce Fulfilment LLP", "23", 15, "on_time", 0),
    ("Godavari Pharma Labs Pvt Ltd", "37", 45, "slight", 2),
    ("Chambal Cement Products", "08", 30, "slow", 1),
    ("Thar Handicraft Exports", "08", 60, "erratic", 0),
    ("Nilgiri Bakery Chain Pvt Ltd", "33", 30, "on_time", 1),
    ("Saraswati Stationery Mart", "09", 30, "slight", 0),
    ("Mandovi Seafood Exporters", "30", 45, "slow", 2),
    ("Pench Organic Farms LLP", "23", 30, "on_time", 0),
    ("Aravalli Auto Components Ltd", "06", 45, "slight", 2),
    ("Kosi Garments Pvt Ltd", "10", 30, "erratic", 1),
    ("Tapi Textile Mills", "24", 60, "slow", 2),
]
PROFILE = {"on_time": (1, 3), "slight": (11, 6), "slow": (24, 9), "erratic": (14, 18)}
TDS_HINT = {0: None, 1: 0.1, 2: 2.0}   # 194Q 0.1% purchase TDS / 194C 2%

customers = []
for i, (name, state, terms, profile, tds_kind) in enumerate(CUSTOMER_SPECS):
    p = pan("C" if "Ltd" in name else "F")
    customers.append({
        "id": uid("cust", str(i)), "tenant_id": TENANT_ID, "name": name, "gstin": gstin(state, p), "pan": p,
        "email": f"payables@{name.split()[0].lower()}.example", "payment_terms_days": terms,
        "tds_rate_hint": TDS_HINT[tds_kind], "_profile": profile,
    })
CUST = {c["name"].split()[0]: c for c in customers}

# ── Suppliers (AP) ──────────────────────────────────────────────────────────
SUPPLIER_SPECS = [
    # name, state, terms, tds section, tds %, category
    ("Ankur Corrugators Pvt Ltd", "27", 30, "194Q", 0.1, "Raw material - corrugated boxes"),
    ("Raigad Kraft Paper Mills", "27", 45, "194Q", 0.1, "Raw material - kraft paper"),
    ("Polyshield Films LLP", "24", 30, "194Q", 0.1, "Raw material - stretch film"),
    ("Sutlej Adhesive Tapes Pvt Ltd", "03", 30, "194Q", 0.1, "Raw material - BOPP tape"),
    ("Bharat Roadlines Logistics", "27", 15, "194C", 2.0, "Freight outward"),
    ("Ostwal Warehousing LLP", "27", 0, "194I", 10.0, "Warehouse rent"),
    ("Prism Print & Labels", "27", 30, "194C", 2.0, "Printing and labels"),
    ("Vayu Express Couriers", "07", 15, "194C", 2.0, "Courier"),
    ("Mahalaxmi Pallets & Crates", "27", 30, "194C", 1.0, "Pallets"),
    ("Deccan Fuel Station", "27", 7, None, 0.0, "Diesel"),
    ("Kaizen IT Services LLP", "29", 30, "194J", 10.0, "IT and software"),
    ("Sanjivani Facility Services", "27", 30, "194C", 2.0, "Housekeeping and security"),
    ("Indus Strapping Solutions", "24", 45, "194Q", 0.1, "Raw material - strapping"),
    ("Pune Hydraulics & Forklifts", "27", 30, "194C", 2.0, "Equipment maintenance"),
]
suppliers = []
for i, (name, state, terms, sec, rate, cat) in enumerate(SUPPLIER_SPECS):
    p = pan("C" if "Ltd" in name else "F")
    suppliers.append({
        "supplier_id": uid("supp", str(i)), "tenant_id": TENANT_ID, "name": name, "gstin": gstin(state, p), "pan": p,
        "payment_terms_days": terms, "tds_section": sec, "tds_rate_percent": rate, "category": cat,
        "msme_registered": i in (0, 3, 6, 8, 11),   # MSMED Act 45-day rule applies
    })
SUPP = {s["name"].split()[0]: s for s in suppliers}


def money(lo: int, hi: int, step: int = 100) -> int:
    """Random rupee amount in [lo, hi], rounded to `step` rupees, returned in paise."""
    return rng.randrange(lo // step, hi // step + 1) * step * 100


def gst_split(taxable: int, rate: float = 18.0):
    tax = round(taxable * rate / 100)
    return taxable, tax, taxable + tax


# ── AR: paid history + open book ────────────────────────────────────────────
ar_invoices, ar_payments, ar_applications = [], [], []
inv_seq = 1180


def new_invoice(c, inv_date, taxable, status="open", note=None):
    global inv_seq
    inv_seq += 1
    taxable, tax, total = gst_split(taxable)
    due = inv_date + dt.timedelta(days=c["payment_terms_days"])
    inv = {
        "id": uid("ari", str(inv_seq)), "tenant_id": TENANT_ID, "customer_id": c["id"], "customer_name": c["name"],
        "invoice_number": f"KPD/26-27/{inv_seq:05d}", "invoice_date": inv_date.isoformat(), "due_date": due.isoformat(),
        "currency": "INR", "taxable_amount_paise": taxable, "tax_amount_paise": tax, "total_amount_paise": total,
        "amount_received_paise": 0, "tds_amount_paise": 0, "deduction_amount_paise": 0,
        "status": status, "paid_at": None, "note": note,
    }
    ar_invoices.append(inv)
    return inv


def sample_delay(profile: str) -> int:
    mu, sd = PROFILE[profile]
    if profile == "erratic" and rng.random() < 0.3:
        return rng.randint(35, 70)
    return max(-5, round(rng.gauss(mu, sd)))


for c in customers:
    d = HISTORY_FROM + dt.timedelta(days=rng.randint(0, 9))
    while d < dt.date(2026, 10, 20):
        inv = new_invoice(c, d, money(60_000, 6_40_000, 500))
        paid_on = next_banking_day(dt.date.fromisoformat(inv["due_date"]) + dt.timedelta(days=sample_delay(c["_profile"])))
        if paid_on <= dt.date(2026, 11, 19):
            tds = round(inv["taxable_amount_paise"] * (c["tds_rate_hint"] or 0) / 100)
            amount = inv["total_amount_paise"] - tds
            bank = SBI if rng.random() < 0.75 else HDFC
            pay = {"id": uid("arp", inv["id"]), "tenant_id": TENANT_ID, "received_on": paid_on.isoformat(),
                   "amount_paise": amount, "currency": "INR", "method": rng.choice(["NEFT", "RTGS", "IMPS"]) if amount < 2_00_000_00 else "RTGS",
                   "utr": utr("SBIN" if bank == SBI else "HDFC", paid_on), "payer_name": c["name"].upper(),
                   "bank_account_id": bank, "source": "statement", "customer_id": c["id"], "status": "applied",
                   "applied_amount_paise": amount, "match_confidence": 0.99}
            ar_payments.append(pay)
            ar_applications.append({"id": uid("ara", inv["id"]), "tenant_id": TENANT_ID, "payment_id": pay["id"],
                                    "invoice_id": inv["id"], "amount_paise": amount, "tds_paise": tds,
                                    "applied_at": f"{paid_on.isoformat()}T16:00:00+05:30"})
            inv.update(amount_received_paise=amount, tds_amount_paise=tds, status="paid",
                       paid_at=f"{paid_on.isoformat()}T16:00:00+05:30")
        d += dt.timedelta(days=rng.randint(9, 16))

# Open book: recent invoices for every customer, plus named story invoices.
for c in customers:
    d = dt.date(2026, 10, 20) + dt.timedelta(days=rng.randint(0, 6))
    while d <= dt.date(2026, 11, 19):
        new_invoice(c, d, money(80_000, 5_20_000, 500))
        d += dt.timedelta(days=rng.randint(8, 15))

story_ar = {}
story_ar["sahyadri_big"] = new_invoice(CUST["Sahyadri"], dt.date(2026, 10, 14), 14_75_000_00 * 100 // 118,
                                      note="Largest open receivable; customer pays ~3 weeks late. Collections target.")
story_ar["malabar_ptp"] = new_invoice(CUST["Malabar"], dt.date(2026, 10, 30), 6_20_000_00,
                                      note="Customer promised payment on 26 Nov 2026 (call log).")
story_ar["kalinga_paid"] = new_invoice(CUST["Kalinga"], dt.date(2026, 10, 12), 2_40_960_00,
                                       note="Already paid on 20 Nov; receipt awaits cash application.")
story_ar["chambal_dispute"] = new_invoice(CUST["Chambal"], dt.date(2026, 9, 18), 2_62_712_00, status="disputed",
                                          note="Customer disputes short delivery of 400 boxes.")
story_ar["thar_old"] = new_invoice(CUST["Thar"], dt.date(2026, 7, 10), 1_85_000_00,
                                   note="Over 60 days overdue; excluded from downside view.")
story_ar["tapi_partial"] = new_invoice(CUST["Tapi"], dt.date(2026, 10, 1), 4_10_000_00, status="partially_paid",
                                       note="Partly paid; only the remainder is forecast.")
tp = story_ar["tapi_partial"]
tp["amount_received_paise"] = 2_00_000_00
ar_payments.append({"id": uid("arp", "tapi-part"), "tenant_id": TENANT_ID, "received_on": "2026-11-12",
                    "amount_paise": 2_00_000_00, "currency": "INR", "method": "RTGS", "utr": utr("SBIN", dt.date(2026, 11, 12)),
                    "payer_name": "TAPI TEXTILE MILLS", "bank_account_id": SBI, "source": "statement",
                    "customer_id": CUST["Tapi"]["id"], "status": "applied", "applied_amount_paise": 2_00_000_00, "match_confidence": 0.97})
kp = story_ar["kalinga_paid"]
ar_payments.append({"id": uid("arp", "kalinga-unapplied"), "tenant_id": TENANT_ID, "received_on": "2026-11-20",
                    "amount_paise": kp["total_amount_paise"] - round(kp["taxable_amount_paise"] * 0.1 / 100), "currency": "INR",
                    "method": "NEFT", "utr": utr("SBIN", dt.date(2026, 11, 20)), "payer_name": "KALINGA HOME ESSENTIALS",
                    "bank_account_id": SBI, "source": "statement", "customer_id": None, "status": "needs_review",
                    "applied_amount_paise": 0, "match_confidence": 0.96,
                    "suggestion": {"invoice_id": kp["id"], "confidence": 0.96, "reason": "amount net of 0.1% TDS and payer alias match"}})

for inv in ar_invoices:
    inv["outstanding_paise"] = (inv["total_amount_paise"] - inv["amount_received_paise"]
                                - inv["tds_amount_paise"] - inv["deduction_amount_paise"])

promises = [{"id": uid("ptp", "malabar"), "tenant_id": TENANT_ID, "invoice_id": story_ar["malabar_ptp"]["id"],
             "promised_date": "2026-11-26", "promised_amount_paise": story_ar["malabar_ptp"]["outstanding_paise"],
             "source": "call", "recorded_by": TENANT["users"][1]["user_id"], "recorded_at": "2026-11-19T12:10:00+05:30",
             "note": "Spoke to AP head; payment run on Thursday."}]

# ── AP: bills ───────────────────────────────────────────────────────────────
ap_bills = []
bill_seq = 0


def new_bill(s, bill_date, taxable, status="APPROVED", payment_status="unpaid", validation="OK", note=None,
             due=None, amount_paid=0, gst=18.0):
    global bill_seq
    bill_seq += 1
    taxable, tax, total = gst_split(taxable, gst)
    tds = round(taxable * s["tds_rate_percent"] / 100) if s["tds_section"] else 0
    due = due or bill_date + dt.timedelta(days=s["payment_terms_days"])
    b = {
        "invoice_id": uid("apb", str(bill_seq)), "stg_bill_id": uid("stg", str(bill_seq)), "tenant_id": TENANT_ID,
        "invoice_type": "AP", "supplier_id": s["supplier_id"], "supplier_name": s["name"],
        "bill_number": f"{s['name'][:3].upper()}/{bill_date:%y%m}/{rng.randint(100, 999)}",
        "bill_date": bill_date.isoformat(), "due_date": due.isoformat(), "currency_code": "INR",
        "taxable_amount_paise": taxable, "tax_amount_paise": tax, "total_amount_paise": total,
        "tds_section_code": s["tds_section"], "tds_amount_paise": tds, "net_payable_paise": total - tds,
        "amount_paid_paise": amount_paid, "outstanding_amount_paise": total - amount_paid,
        "status": status, "payment_status": payment_status, "validation_flag": validation,
        "soft_status": "active", "category": s["category"], "msme_supplier": s["msme_registered"], "note": note,
    }
    ap_bills.append(b)
    return b


RM = ["Ankur", "Raigad", "Polyshield", "Sutlej", "Indus"]
SERVICES = ["Bharat", "Prism", "Vayu", "Mahalaxmi", "Kaizen", "Sanjivani", "Pune"]
for key in RM:
    s = SUPP[key]
    d = dt.date(2026, 10, 8) + dt.timedelta(days=rng.randint(0, 5))
    while d <= dt.date(2026, 11, 19):
        new_bill(s, d, money(1_40_000, 5_60_000, 500))
        d += dt.timedelta(days=rng.randint(7, 12))
for key in SERVICES:
    s = SUPP[key]
    d = dt.date(2026, 10, 25) + dt.timedelta(days=rng.randint(0, 8))
    while d <= dt.date(2026, 11, 19):
        new_bill(s, d, money(25_000, 1_60_000, 100))
        d += dt.timedelta(days=rng.randint(10, 16))

# The AP desk pays on time: routine bills that fell due before 18 Nov are settled.
# Two are left overdue deliberately so the catch-up rule has something to date.
routine_overdue = [b for b in ap_bills if dt.date.fromisoformat(b["due_date"]) < dt.date(2026, 11, 18)]
for b in routine_overdue[2:]:
    b.update(payment_status="paid", amount_paid_paise=b["total_amount_paise"], outstanding_amount_paise=0)

story_ap = {}
story_ap["ankur_inflight"] = new_bill(SUPP["Ankur"], dt.date(2026, 10, 16), 3_49_400_00, payment_status="unpaid",
                                      note="Payout initiated 20 Nov; bank status PENDING.")
story_ap["raigad_synclag"] = new_bill(SUPP["Raigad"], dt.date(2026, 10, 2), 2_88_000_00, payment_status="unpaid",
                                      note="Paid 19 Nov via disbursement; bill payment status not yet synced.")
story_ap["polyshield_dup"] = new_bill(SUPP["Polyshield"], dt.date(2026, 11, 6), 2_00_000_00, validation="DUPLICATE",
                                      note="Same number and amount as an earlier Polyshield bill. Held for review.")
story_ap["sutlej_partial"] = new_bill(SUPP["Sutlej"], dt.date(2026, 10, 20), 3_10_000_00, payment_status="partial",
                                      amount_paid=1_50_000_00, note="Partly paid; second instalment scheduled.")
story_ap["ankur_flex"] = new_bill(SUPP["Ankur"], dt.date(2026, 10, 26), 4_80_000_00,
                                  note="Supplier agreed in writing to accept payment up to 4 Dec.")
story_ap["indus_flex"] = new_bill(SUPP["Indus"], dt.date(2026, 10, 12), 3_95_000_00,
                                  note="Payment window agreed through 3 Dec (email).")
story_ap["raigad_flex"] = new_bill(SUPP["Raigad"], dt.date(2026, 10, 15), 4_20_000_00,
                                   note="Payment window agreed through 2 Dec.")
for key, amt in (("Raigad", 3_80_000_00), ("Ankur", 2_65_000_00), ("Prism", 1_18_000_00), ("Kaizen", 2_40_000_00)):
    new_bill(SUPP[key], dt.date(2026, 11, 14) + dt.timedelta(days=rng.randint(0, 5)), amt,
             status=rng.choice(["PENDING_APPROVER", "PENDING_FC"]), note="Still in approval.")
new_bill(SUPP["Pune"], dt.date(2026, 11, 17), 48_000_00, status="REJECTED", note="Rejected: rate mismatch.")

payment_schedules = [
    {"schedule_id": uid("sch", "sutlej", "2"), "tenant_id": TENANT_ID, "cycle_type": "PAYABLE",
     "stg_bill_id": story_ap["sutlej_partial"]["stg_bill_id"], "supplier_id": SUPP["Sutlej"]["supplier_id"],
     "installment_number": 2, "due_date": "2026-12-08",
     "scheduled_amount_paise": story_ap["sutlej_partial"]["total_amount_paise"] - 1_50_000_00,
     "paid_amount_paise": 0, "payment_term_days": 30, "currency_code": "INR", "status": "PENDING"},
]

payment_windows = [
    {"id": uid("win", k), "tenant_id": TENANT_ID, "invoice_id": story_ap[k]["invoice_id"],
     "earliest_date": story_ap[k]["due_date"], "latest_date": latest, "agreed_with": story_ap[k]["supplier_name"],
     "evidence": ev, "recorded_by": TENANT["users"][1]["user_id"], "recorded_at": "2026-11-18T11:00:00+05:30"}
    for k, latest, ev in (("ankur_flex", "2026-12-04", "Email from supplier accounts, 17 Nov"),
                          ("indus_flex", "2026-12-03", "Email thread, 18 Nov"),
                          ("raigad_flex", "2026-12-02", "WhatsApp confirmation filed as attachment"))
]

disbursements = [
    {"disbursement_id": uid("dsb", "ankur"), "tenant_id": TENANT_ID, "invoice_id": story_ap["ankur_inflight"]["invoice_id"],
     "supplier_id": SUPP["Ankur"]["supplier_id"], "amount_paise": story_ap["ankur_inflight"]["net_payable_paise"],
     "status": "PENDING", "bank_provider": "HDFC", "remitter_account_id": HDFC, "created_at": "2026-11-20T17:42:00+05:30"},
    {"disbursement_id": uid("dsb", "raigad"), "tenant_id": TENANT_ID, "invoice_id": story_ap["raigad_synclag"]["invoice_id"],
     "supplier_id": SUPP["Raigad"]["supplier_id"], "amount_paise": story_ap["raigad_synclag"]["net_payable_paise"],
     "status": "SUCCESS", "bank_provider": "HDFC", "remitter_account_id": HDFC, "created_at": "2026-11-19T11:05:00+05:30"},
]

# ── Recurring obligations (not in AP) ───────────────────────────────────────
recurring = [
    # name, category, amount, frequency, day, roll, confidence, statutory
    ("Salaries (net pay, 46 staff)", "payroll", 21_80_000_00, "monthly", "last_banking_day", "previous_banking_day", "committed", False),
    ("PF and ESI contribution", "statutory", 3_02_400_00, "monthly", 15, "previous_banking_day", "committed", True),
    ("TDS deposit (previous month)", "statutory", 1_96_850_00, "monthly", 7, "previous_banking_day", "committed", True),
    ("GST payment - GSTR-3B", "statutory", 9_84_300_00, "monthly", 20, "previous_banking_day", "committed", True),
    ("Term loan EMI - SBI", "debt", 2_15_800_00, "monthly", 10, "next_banking_day", "committed", False),
    ("Warehouse rent - Bhiwandi (net of TDS)", "rent", 3_15_000_00, "monthly", 5, "next_banking_day", "committed", False),
    ("Advance tax - Q3 instalment", "statutory", 6_50_000_00, "quarterly", 15, "previous_banking_day", "committed", True),
    ("Electricity - MSEDCL", "utilities", 78_400_00, "monthly", 3, "next_banking_day", "estimated", False),
    ("Diesel for delivery fleet", "operations", 46_000_00, "weekly", 0, "next_banking_day", "estimated", False),
    ("Internet and telephone", "utilities", 18_600_00, "monthly", 12, "next_banking_day", "estimated", False),
]
recurring_items = []
for i, (name, cat, amt, freq, day, roll, conf, stat) in enumerate(recurring):
    recurring_items.append({
        "id": uid("rec", str(i)), "tenant_id": TENANT_ID, "name": name, "category": cat, "direction": "out",
        "amount_paise": amt, "frequency": freq, "anchor": day, "business_day_rule": roll, "confidence": conf,
        "statutory": stat, "start_date": "2026-04-01", "end_date": None, "active": True,
        "bank_account_id": HDFC if cat in ("payroll", "statutory", "rent", "debt") else SBI,
        "quarter_months": [6, 9, 12, 3] if freq == "quarterly" else None,
    })

adjustments = [
    {"id": uid("adj", "insurance"), "tenant_id": TENANT_ID, "name": "Annual insurance renewal - stock and fleet", "category": "insurance",
     "direction": "out", "amount_paise": 6_85_000_00, "date": "2026-11-30", "confidence": "committed",
     "note": "Policy renews 1 Dec; broker debit note received 12 Nov.", "created_by": TENANT["users"][1]["user_id"]},
    {"id": uid("adj", "capex"), "tenant_id": TENANT_ID, "name": "Down payment - new forklift", "category": "capex",
     "direction": "out", "amount_paise": 4_50_000_00, "date": "2026-12-09", "confidence": "committed",
     "note": "Signed purchase order with Pune Hydraulics; balance financed.", "created_by": TENANT["users"][0]["user_id"]},
    {"id": uid("adj", "gstrefund"), "tenant_id": TENANT_ID, "name": "GST refund (inverted duty) - expected", "category": "refund",
     "direction": "in", "amount_paise": 1_42_000_00, "date": "2026-12-16", "confidence": "estimated",
     "note": "RFD-01 filed 28 Oct. Timing uncertain; excluded from downside.", "created_by": TENANT["users"][1]["user_id"]},
]

# ── Bank statement history (91 days) ────────────────────────────────────────
stmt = {HDFC: [], SBI: []}


def post(acct, d, desc, ref, credit=0, debit=0):
    stmt[acct].append({"date": d, "desc": desc, "ref": ref, "credit": credit, "debit": debit})


for p in ar_payments:
    d = dt.date.fromisoformat(p["received_on"])
    if STATEMENT_FROM <= d <= dt.date(2026, 11, 20):
        post(p["bank_account_id"], d, f"{p['method']}-{p['utr']}-{p['payer_name']}", p["utr"], credit=p["amount_paise"])

# Historical AP payment runs (Tue/Thu from HDFC). Like most distributors the
# business pays suppliers out of what it collects: each run spends a share of
# the previous seven days' customer receipts, split across 3-6 suppliers.
receipts_by_day = {}
for rows in stmt.values():
    for r in rows:
        receipts_by_day[r["date"]] = receipts_by_day.get(r["date"], 0) + r["credit"]
d = STATEMENT_FROM
while d <= dt.date(2026, 11, 19):
    if is_banking_day(d) and d.weekday() in (1, 3):
        pool = sum(receipts_by_day.get(d - dt.timedelta(days=k), 0) for k in range(1, 8))
        budget = round(pool * PAYOUT_SHARE * rng.uniform(0.85, 1.15))
        n = rng.randint(3, 6)
        weights = [rng.uniform(0.5, 1.5) for _ in range(n)]
        for w in weights:
            s = rng.choice(suppliers[:9] + suppliers[10:])
            amt = round(budget * w / sum(weights) / 1000) * 1000
            if amt >= 10_000_00:
                ref = f"HDFCH{d:%y%m%d}{rng.randint(10000, 99999)}"
                post(HDFC, d, f"IMPS/NEFT PAYOUT {s['name'].upper()[:28]}", ref, debit=amt)
    d += dt.timedelta(days=1)
post(HDFC, dt.date(2026, 11, 19), f"NEFT PAYOUT RAIGAD KRAFT PAPER MILLS", "HDFCH261119RAIG",
     debit=story_ap["raigad_synclag"]["net_payable_paise"])

for r in recurring_items:
    d = STATEMENT_FROM
    while d <= dt.date(2026, 11, 20):
        due = None
        if r["frequency"] == "weekly" and d.weekday() == 0:
            due = d
        elif r["frequency"] == "monthly" and r["anchor"] == "last_banking_day":
            nxt = d + dt.timedelta(days=1)
            due = d if nxt.month != d.month else None
        elif r["frequency"] == "monthly" and d.day == r["anchor"]:
            due = d
        elif r["frequency"] == "quarterly" and d.month in r["quarter_months"] and d.day == r["anchor"]:
            due = d
        if due:
            pay_on = (prev_banking_day if r["business_day_rule"] == "previous_banking_day" else next_banking_day)(due)
            if pay_on <= dt.date(2026, 11, 20):
                jitter = 1 + rng.uniform(-0.04, 0.04) if r["confidence"] == "estimated" else 1
                post(r["bank_account_id"], pay_on, r["name"].upper()[:40], f"AUTO{pay_on:%y%m%d}{r['category'][:3].upper()}",
                     debit=round(r["amount_paise"] * jitter / 100) * 100)
        d += dt.timedelta(days=1)

# Simulate forward day by day. Credits land before debits. Every Friday the
# collections account sweeps anything above ₹5 L to operations, and on any day
# operations would close below ₹6 L it pulls a top-up from collections first.
for d in (dt.date(2026, 9, 15), dt.date(2026, 10, 15), dt.date(2026, 11, 13)):
    post(HDFC, d, "CASH SALES DEPOSIT", f"CDM{d:%y%m%d}", credit=money(2_00_000, 4_00_000, 1000))

bal = dict(STATEMENT_START)
low = dict(STATEMENT_START)
cc_drawn, cc_rows = CC_START, []
ledger = {HDFC: [], SBI: []}
d = STATEMENT_FROM
while d <= dt.date(2026, 11, 20):
    todays = {a: sorted([r for r in rows if r["date"] == d], key=lambda r: (-r["credit"], r["ref"])) for a, rows in stmt.items()}
    hdfc_need = sum(r["debit"] - r["credit"] for r in todays[HDFC])
    sweep = 0
    if is_banking_day(d):
        if bal[HDFC] - hdfc_need < 6_00_000_00:
            sweep = max(0, min(bal[SBI] + sum(r["credit"] for r in todays[SBI]) - 2_00_000_00,
                               6_00_000_00 - (bal[HDFC] - hdfc_need) + 4_00_000_00))
        if d.weekday() == 4:
            surplus = bal[SBI] + sum(r["credit"] - r["debit"] for r in todays[SBI]) - sweep - 5_00_000_00
            sweep += max(0, surplus)
    sweep = sweep // 100_000_00 * 100_000_00            # sweeps move in round lakhs
    if sweep:
        todays[SBI].append({"date": d, "desc": "INTERNAL TRF TO HDFC OPS XX4821", "ref": f"SWP{d:%y%m%d}", "credit": 0, "debit": sweep})
        todays[HDFC].insert(0, {"date": d, "desc": "INTERNAL TRF FROM SBI XX0937", "ref": f"SWP{d:%y%m%d}", "credit": sweep, "debit": 0})
    # Cash credit: draw in ₹5 L steps to keep operations above ₹5 L, repay above ₹45 L.
    projected = bal[HDFC] + sweep - hdfc_need
    step = 5_00_000_00
    if is_banking_day(d) and projected < step:
        draw = -(-(step - projected) // step) * step
        cc_drawn += draw
        cc_rows.append({"date": d, "desc": "TRF TO HDFC OPS XX4821", "ref": f"CCD{d:%y%m%d}", "credit": 0, "debit": draw})
        todays[HDFC].insert(0, {"date": d, "desc": "CC DRAWDOWN SBI XX5512", "ref": f"CCD{d:%y%m%d}", "credit": draw, "debit": 0})
    elif is_banking_day(d) and cc_drawn and projected > 45_00_000_00:
        repay = min(cc_drawn, (projected - 45_00_000_00) // step * step)
        if repay:
            cc_drawn -= repay
            cc_rows.append({"date": d, "desc": "TRF FROM HDFC OPS XX4821", "ref": f"CCR{d:%y%m%d}", "credit": repay, "debit": 0})
            todays[HDFC].append({"date": d, "desc": "CC REPAYMENT SBI XX5512", "ref": f"CCR{d:%y%m%d}", "credit": 0, "debit": repay})
    for acct in (SBI, HDFC):
        for r in todays[acct]:
            bal[acct] += r["credit"] - r["debit"]
            r["balance"] = bal[acct]
            low[acct] = min(low[acct], bal[acct])
            ledger[acct].append(r)
    d += dt.timedelta(days=1)
stmt = ledger
OPENING = dict(bal)
CC_DRAWN = cc_drawn
SBIOD = ACCOUNTS[2]["bank_account_id"]
for acct, v in low.items():
    if v < 0:
        print(f"WARN statement {acct[:8]} dips below zero ({inr(v)}); retune the fixture")
statement_rows = [(a, STATEMENT_START[a], stmt[a]) for a in (HDFC, SBI)]

# ── Write seed files ────────────────────────────────────────────────────────
OUT.mkdir(parents=True, exist_ok=True)


def dump(name, data):
    (OUT / name).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")


for c in customers:
    c.pop("_profile", None)
dump("tenant.json", TENANT)
dump("settings.json", SETTINGS)
dump("bank_accounts.json", ACCOUNTS)
dump("bank_balances.json", [{"id": uid("bal", a), "tenant_id": TENANT_ID, "bank_account_id": a, "balance_paise": v,
                             "as_of": AS_OF, "source": "bank_statement", "source_ref": f"statement:{a}:2026-11-20"}
                            for a, v in list(OPENING.items()) + [(SBIOD, -CC_DRAWN)]])
dump("customers.json", customers)
dump("suppliers.json", suppliers)
dump("ar_invoices.json", ar_invoices)
dump("ar_payments.json", ar_payments)
dump("ar_applications.json", ar_applications)
dump("collection_promises.json", promises)
dump("ap_bills.json", ap_bills)
dump("payment_schedules.json", payment_schedules)
dump("payment_windows.json", payment_windows)
dump("disbursements.json", disbursements)
dump("recurring_items.json", recurring_items)
dump("adjustments.json", adjustments)

cc_bal = -CC_START
for r in cc_rows:
    cc_bal += r["credit"] - r["debit"]
    r["balance"] = cc_bal
assert cc_bal == -CC_DRAWN
statement_rows.append((SBIOD, -CC_START, cc_rows))
FILES = {HDFC: "bank_statement_hdfc_4821.csv", SBI: "bank_statement_sbi_0937.csv", SBIOD: "bank_statement_sbi_cc_5512.csv"}
for acct, start_bal, rows in statement_rows:
    name = FILES[acct]
    with open(OUT / name, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["Txn Date", "Value Date", "Description", "Ref No./Cheque No.", "Debit", "Credit", "Balance"])
        w.writerow([STATEMENT_FROM.strftime("%d/%m/%Y"), "", "OPENING BALANCE", "", "", "", rupees(start_bal)])
        for r in rows:
            w.writerow([r["date"].strftime("%d/%m/%Y"), r["date"].strftime("%d/%m/%Y"), r["desc"], r["ref"],
                        rupees(r["debit"]) if r["debit"] else "", rupees(r["credit"]) if r["credit"] else "",
                        rupees(r["balance"])])


# ════════════════════════════════════════════════════════════════════════════
# Reference forecast (rules from ../04_LLD.md §5). Produces the golden output.
# ════════════════════════════════════════════════════════════════════════════
HORIZON = [START + dt.timedelta(days=i) for i in range(HORIZON_DAYS)]
ROLL = {"next_banking_day": next_banking_day, "previous_banking_day": prev_banking_day}


def first_banking_on_or_after(d):
    return next_banking_day(max(d, START))


def percentile(values, q):
    s = sorted(values)
    k = max(0, min(len(s) - 1, -(-len(s) * q // 1) - 1))   # nearest-rank
    return s[int(k)]


# Customer payment profiles from settled history.
delays = {}
for inv in ar_invoices:
    if inv["status"] == "paid" and inv["paid_at"]:
        d_paid = dt.date.fromisoformat(inv["paid_at"][:10])
        delays.setdefault(inv["customer_id"], []).append((d_paid - dt.date.fromisoformat(inv["due_date"])).days)
all_delays = [x for v in delays.values() for x in v]
TENANT_PROFILE = {"median": round(statistics.median(all_delays)), "p80": percentile(all_delays, 0.8), "n": len(all_delays), "basis": "tenant"}
profiles = {}
for c in customers:
    v = delays.get(c["id"], [])
    if len(v) >= SETTINGS["min_customer_history"]:
        profiles[c["id"]] = {"median": round(statistics.median(v)), "p80": percentile(v, 0.8), "n": len(v), "basis": "customer"}
    else:
        profiles[c["id"]] = dict(TENANT_PROFILE)

events, exclusions = [], []


def event(key, source_type, source_id, label, direction, amount, date, confidence, views, category, counterparty=None,
          basis=None, flexible=None):
    events.append({"event_key": key, "source_type": source_type, "source_id": source_id, "label": label,
                   "direction": direction, "amount_paise": amount, "date": date.isoformat(), "confidence": confidence,
                   "views": views, "category": category, "counterparty": counterparty, "date_basis": basis,
                   "payment_window": flexible})


def exclude(source_type, source_id, label, amount, reason, detail):
    exclusions.append({"source_type": source_type, "source_id": source_id, "label": label, "amount_paise": amount,
                       "reason": reason, "detail": detail})


# 1. In-flight and completed disbursements.
paid_by_disbursement = {x["invoice_id"] for x in disbursements if x["status"] == "SUCCESS"}
inflight = {x["invoice_id"]: x for x in disbursements if x["status"] in ("PENDING", "PENDING_OTP", "PROCESSING")}
for x in inflight.values():
    b = next(b for b in ap_bills if b["invoice_id"] == x["invoice_id"])
    event(f"disbursement:{x['disbursement_id']}", "disbursement", x["disbursement_id"], f"Payout in flight · {b['supplier_name']}",
          "out", x["amount_paise"], first_banking_on_or_after(START), "confirmed", ["no_collections", "expected", "downside"],
          "supplier", b["supplier_name"], "in_flight_payout")

# 2. AP bills.
sched_by_bill = {s["stg_bill_id"]: s for s in payment_schedules if s["status"] in ("PENDING", "PARTIAL", "OVERDUE")}
win_by_bill = {w["invoice_id"]: w for w in payment_windows}
for b in ap_bills:
    label = f"{b['supplier_name']} · {b['bill_number']}"
    if b["payment_status"] == "paid" or b["soft_status"] != "active" or b["status"] in ("REJECTED", "VOID", "CANCELLED"):
        if b["status"] == "REJECTED":
            exclude("bill", b["invoice_id"], label, b["net_payable_paise"], "REJECTED", "Bill rejected in approval.")
        continue
    if b["invoice_id"] in inflight:
        exclude("bill", b["invoice_id"], label, b["net_payable_paise"], "PAYOUT_IN_FLIGHT", "Counted once, as the in-flight payout.")
        continue
    if b["invoice_id"] in paid_by_disbursement:
        exclude("bill", b["invoice_id"], label, b["net_payable_paise"], "PAID_VIA_DISBURSEMENT",
                "Disbursement succeeded on 19 Nov and is already in the opening balance; bill status not yet synced.")
        continue
    if b["validation_flag"] == "DUPLICATE":
        exclude("bill", b["invoice_id"], label, b["net_payable_paise"], "SUSPECTED_DUPLICATE", "Held for review; not scheduled.")
        continue
    sch = sched_by_bill.get(b["stg_bill_id"])
    if sch:
        amount = sch["scheduled_amount_paise"] - sch["paid_amount_paise"]
        due, basis = dt.date.fromisoformat(sch["due_date"]), "payment_schedule"
    else:
        amount = b["outstanding_amount_paise"] - (b["tds_amount_paise"] if b["amount_paid_paise"] == 0 else 0)
        due, basis = dt.date.fromisoformat(b["due_date"]), "due_date"
    if due < START:
        date, basis = first_banking_on_or_after(START), "overdue_catch_up"
    else:
        date = next_banking_day(due)
    approved = b["status"] == "APPROVED"
    views = ["no_collections", "expected", "downside"] if approved else ["expected", "downside"]
    w = win_by_bill.get(b["invoice_id"])
    key, stype, sid = (f"schedule:{sch['schedule_id']}", "schedule", sch["schedule_id"]) if sch else (f"bill:{b['invoice_id']}", "bill", b["invoice_id"])
    event(key, stype, sid, label, "out", amount, date,
          "committed" if approved else "pipeline", views, "supplier", b["supplier_name"], basis,
          {"earliest": w["earliest_date"], "latest": w["latest_date"]} if w else None)

# 3. AR invoices.
unapplied = {p["suggestion"]["invoice_id"]: p for p in ar_payments
             if p["status"] in ("unmatched", "needs_review") and p.get("suggestion") and p["suggestion"]["confidence"] >= 0.9}
ptp = {p["invoice_id"]: p for p in promises}
for inv in ar_invoices:
    if inv["status"] not in ("open", "partially_paid", "disputed") or inv["outstanding_paise"] <= 0:
        continue
    label = f"{inv['customer_name']} · {inv['invoice_number']}"
    cust = next(c for c in customers if c["id"] == inv["customer_id"])
    if inv["id"] in unapplied:
        exclude("ar_invoice", inv["id"], label, inv["outstanding_paise"], "SETTLED_PENDING_APPLICATION",
                "Receipt of 20 Nov is already in the bank balance and awaits cash application.")
        continue
    if inv["status"] == "disputed":
        exclude("ar_invoice", inv["id"], label, inv["outstanding_paise"], "DISPUTED", "Disputed invoices are not forecast.")
        continue
    exp_tds = round(inv["taxable_amount_paise"] * (cust["tds_rate_hint"] or 0) / 100) if inv["tds_amount_paise"] == 0 else 0
    amount = inv["outstanding_paise"] - exp_tds
    due = dt.date.fromisoformat(inv["due_date"])
    prof = profiles[inv["customer_id"]]
    overdue_days = (START - due).days
    # Conditional delay: an invoice already `overdue_days` late is dated by the
    # remaining delay of comparable invoices that were at least that late.
    own = delays.get(inv["customer_id"], [])
    d_exp, basis_exp, d_down, basis_down = None, None, None, None
    if overdue_days <= 0:
        d_exp = max(START, due + dt.timedelta(days=prof["median"]))
        basis_exp = f"due + {prof['median']}d median ({prof['basis']}, n={prof['n']})"
        d_down = max(START, due + dt.timedelta(days=prof["p80"]))
        basis_down = f"due + {prof['p80']}d p80 ({prof['basis']}, n={prof['n']})"
    else:
        for pool, basis in ((own, "customer"), (all_delays, "tenant")):
            rest = [x - overdue_days for x in pool if x > overdue_days]
            if len(rest) >= SETTINGS["min_customer_history"]:
                r_med, r_p80 = round(statistics.median(rest)), percentile(rest, 0.8)
                d_exp, d_down = START + dt.timedelta(days=r_med), START + dt.timedelta(days=r_p80)
                basis_exp = f"{overdue_days}d overdue; remaining {r_med}d median ({basis}, n={len(rest)})"
                basis_down = f"{overdue_days}d overdue; remaining {r_p80}d p80 ({basis}, n={len(rest)})"
                break
        if d_exp is None:
            fb = START
            for _ in range(SETTINGS["overdue_fallback_days"]):
                fb = next_banking_day(fb + dt.timedelta(days=1))
            d_exp, d_down = fb, fb + dt.timedelta(days=14)
            basis_exp = basis_down = f"{overdue_days}d overdue; no comparable history"
    if inv["id"] in ptp:
        d_exp, basis_exp = dt.date.fromisoformat(ptp[inv["id"]]["promised_date"]), "promise_to_pay"
    d_exp, d_down = next_banking_day(d_exp), next_banking_day(d_down)
    events.append({"event_key": f"ar:{inv['id']}", "source_type": "ar_invoice", "source_id": inv["id"], "label": label,
                   "direction": "in", "amount_paise": amount, "date": d_exp.isoformat(), "confidence": "expected",
                   "views": ["expected"], "category": "customer", "counterparty": inv["customer_name"],
                   "date_basis": basis_exp, "payment_window": None, "expected_tds_paise": exp_tds})
    if overdue_days > SETTINGS["downside_exclude_overdue_after_days"]:
        exclude("ar_invoice", inv["id"], label, amount, "AGED_OVER_60_DAYS_DOWNSIDE",
                f"{overdue_days} days overdue; counted in expected view only.")
    else:
        events.append({"event_key": f"ar:{inv['id']}", "source_type": "ar_invoice", "source_id": inv["id"], "label": label,
                       "direction": "in", "amount_paise": amount, "date": d_down.isoformat(), "confidence": "expected",
                       "views": ["downside"], "category": "customer", "counterparty": inv["customer_name"],
                       "date_basis": basis_down, "payment_window": None, "expected_tds_paise": exp_tds})

# 4. Recurring items expanded over the horizon.
for r in recurring_items:
    d = START
    while d <= END:
        due = None
        if r["frequency"] == "weekly" and d.weekday() == r["anchor"]:
            due = d
        elif r["frequency"] == "monthly" and r["anchor"] == "last_banking_day":
            if (d + dt.timedelta(days=1)).month != d.month:
                due = d
        elif r["frequency"] == "monthly" and d.day == r["anchor"]:
            due = d
        elif r["frequency"] == "quarterly" and d.month in r["quarter_months"] and d.day == r["anchor"]:
            due = d
        if due:
            pay_on = ROLL[r["business_day_rule"]](due)
            if START <= pay_on <= END:
                views = ["no_collections", "expected", "downside"]
                event(f"recurring:{r['id']}:{due.isoformat()}", "recurring", r["id"], r["name"], "out", r["amount_paise"],
                      pay_on, r["confidence"], views, r["category"], None, f"{r['frequency']} · {r['business_day_rule']}")
        d += dt.timedelta(days=1)

# 5. Manual adjustments.
for a in adjustments:
    # Outflows count in every view; an estimated inflow only in the expected view.
    views = ["expected"] if a["direction"] == "in" and a["confidence"] != "committed" else ["no_collections", "expected", "downside"]
    event(f"adjustment:{a['id']}", "adjustment", a["id"], a["name"], a["direction"], a["amount_paise"],
          next_banking_day(dt.date.fromisoformat(a["date"])), a["confidence"], views, a["category"], None, "manual")

opening_total = sum(OPENING[a["bank_account_id"]] for a in ACCOUNTS if a["include_in_forecast"])


def run(view, overrides=None):
    overrides = overrides or {}
    by_day = {d: {"in": 0, "out": 0, "events": []} for d in HORIZON}
    beyond = {"in": 0, "out": 0}
    for e in events:
        if view not in e["views"]:
            continue
        date = dt.date.fromisoformat(overrides.get(e["event_key"], e["date"]))
        if date > END:
            beyond[e["direction"]] += e["amount_paise"]
            continue
        by_day[date][e["direction"]] += e["amount_paise"]
        by_day[date]["events"].append(e["event_key"])
    bal, days = opening_total, []
    for d in HORIZON:
        b = by_day[d]
        close = bal + b["in"] - b["out"]
        days.append({"date": d.isoformat(), "banking_day": is_banking_day(d), "opening_paise": bal,
                     "inflow_paise": b["in"], "outflow_paise": b["out"], "closing_paise": close,
                     "below_reserve": close < SETTINGS["reserve_paise"], "event_count": len(b["events"])})
        bal = close
    low = min(days, key=lambda x: (x["closing_paise"], x["date"]))
    breach = next((x["date"] for x in days if x["below_reserve"]), None)
    neg = next((x["date"] for x in days if x["closing_paise"] < 0), None)
    return {"view": view, "opening_paise": opening_total, "reserve_paise": SETTINGS["reserve_paise"],
            "total_inflow_paise": sum(x["inflow_paise"] for x in days), "total_outflow_paise": sum(x["outflow_paise"] for x in days),
            "closing_paise": days[-1]["closing_paise"], "minimum_closing_paise": low["closing_paise"], "minimum_date": low["date"],
            "first_reserve_breach_date": breach, "first_negative_date": neg,
            "days_below_reserve": sum(1 for x in days if x["below_reserve"]),
            "beyond_horizon_inflow_paise": beyond["in"], "beyond_horizon_outflow_paise": beyond["out"], "days": days}


views = {v: run(v) for v in ("no_collections", "expected", "downside")}

# Recovery plan used in the demo: move the three windowed bills to the end of
# their agreed windows. The Malabar promise already sits in the expected view.
plan_overrides = {f"bill:{story_ap[k]['invoice_id']}": next_banking_day(dt.date.fromisoformat(w["latest_date"])).isoformat()
                  if is_banking_day(dt.date.fromisoformat(w["latest_date"])) else prev_banking_day(dt.date.fromisoformat(w["latest_date"])).isoformat()
                  for k, w in zip(("ankur_flex", "indus_flex", "raigad_flex"), payment_windows)}
plan_expected = run("expected", plan_overrides)
plan_downside = run("downside", plan_overrides)

# Downside stress: Sahyadri's ₹14.75 L slips a further 10 days.
sah_key = f"ar:{story_ar['sahyadri_big']['id']}"
sah_down = next(e for e in events if e["event_key"] == sah_key and "expected" in e["views"])

scenarios = [
    {"id": uid("scn", "baseline"), "name": "Baseline", "view": "expected", "overrides": [], "description": "No changes."},
    {"id": uid("scn", "plan"), "name": "Defer three windowed supplier payments",
     "view": "expected", "description": "Use the agreed payment windows for Ankur, Indus and Raigad.",
     "overrides": [{"op": "shift_event", "event_key": k, "to_date": v,
                    "reason": "Within supplier-agreed window"} for k, v in plan_overrides.items()]},
    {"id": uid("scn", "sahyadri"), "name": "Sahyadri pays 10 days later than expected",
     "view": "expected", "description": "Stress the single largest receivable.",
     "overrides": [{"op": "shift_event", "event_key": sah_key,
                    "to_date": next_banking_day(dt.date.fromisoformat(sah_down["date"]) + dt.timedelta(days=10)).isoformat(),
                    "reason": "Collections stress test"}]},
]
dump("scenarios.json", scenarios)
sahyadri_expected = run("expected", {o["event_key"]: o["to_date"] for o in scenarios[2]["overrides"]})


def by_category(view):
    out = {}
    for e in events:
        if view in e["views"] and e["date"] <= END.isoformat():
            k = f"{e['direction']}:{e['category']}"
            out[k] = out.get(k, 0) + e["amount_paise"]
    return dict(sorted(out.items()))

snapshot_hash = hashlib.sha256(json.dumps(events, sort_keys=True).encode()).hexdigest()
golden = {
    "generated_for": "Reckon.ai Cash Flow Forecast — golden output for the synthetic tenant",
    "tenant_id": TENANT_ID, "as_of": AS_OF, "horizon_start": START.isoformat(), "horizon_end": END.isoformat(),
    "event_set_sha256": snapshot_hash, "opening_paise": opening_total,
    "od_limit_paise": ACCOUNTS[2]["od_limit_paise"], "od_drawn_paise": CC_DRAWN,
    "od_headroom_paise": ACCOUNTS[2]["od_limit_paise"] - CC_DRAWN,
    "customer_profiles": {c["name"]: profiles[c["id"]] for c in customers}, "tenant_profile": TENANT_PROFILE,
    "views": views,
    "category_totals": {v: by_category(v) for v in ("no_collections", "expected", "downside")},
    "scenarios": {"defer_windowed_bills": {"overrides": plan_overrides, "expected": plan_expected, "downside": plan_downside},
                  "sahyadri_slips_10_days": {"overrides": {o["event_key"]: o["to_date"] for o in scenarios[2]["overrides"]},
                                             "expected": sahyadri_expected}},
    "events": sorted(events, key=lambda e: (e["date"], e["direction"], e["event_key"])),
    "exclusions": exclusions,
}
dump("expected_forecast.json", golden)

# ── Human summary ───────────────────────────────────────────────────────────
open_ar = [i for i in ar_invoices if i["status"] in ("open", "partially_paid")]
open_ap = [b for b in ap_bills if b["payment_status"] != "paid" and b["status"] not in ("REJECTED",)]
print(f"Tenant: {TENANT['legal_name']}  GSTIN {TENANT['gstin']}")
print(f"Opening cash {inr(opening_total)} (HDFC {inr(OPENING[HDFC])}, SBI {inr(OPENING[SBI])}); reserve {inr(SETTINGS['reserve_paise'])}")
print(f"Customers {len(customers)}, AR invoices {len(ar_invoices)} ({len(open_ar)} open, {inr(sum(i['outstanding_paise'] for i in open_ar))})")
print(f"Suppliers {len(suppliers)}, AP bills {len(ap_bills)} (open {inr(sum(b['outstanding_amount_paise'] for b in open_ap))})")
print(f"AR payments {len(ar_payments)}, statement rows HDFC {len(stmt[HDFC])}, SBI {len(stmt[SBI])}")
for acct, sb, rows in statement_rows:
    print(f"  statement {FILES[acct]} start {inr(sb)} min {inr(min([sb] + [r['balance'] for r in rows]))} rows {len(rows)}")
print(f"Cash credit drawn at as-of {inr(CC_DRAWN)} of {inr(ACCOUNTS[2]['od_limit_paise'])}")
print(f"Tenant delay profile {TENANT_PROFILE}")
print(f"Events {len(events)}, exclusions {len(exclusions)}")
for name, v in list(views.items()) + [("plan/expected", plan_expected), ("plan/downside", plan_downside),
                                      ("sahyadri+10d", sahyadri_expected)]:
    print(f"{name:15} in {inr(v['total_inflow_paise']):>14} out {inr(v['total_outflow_paise']):>14} "
          f"close {inr(v['closing_paise']):>14} min {inr(v['minimum_closing_paise']):>14} on {v['minimum_date']} "
          f"breach {v['first_reserve_breach_date']} neg {v['first_negative_date']} days<res {v['days_below_reserve']}")
