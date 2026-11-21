"""Remittance read-out sanity (no LLM): a guessed year must not survive."""
from backend_ocr.app.receivables.remittance import clean


def _r(paid):
    return clean({"payment_date": paid, "total_amount": 29500,
                  "lines": [{"invoice_number": "2014", "invoice_date": "16/10/2026", "amount_paid": 29500}]})


def test_year_guessed_before_the_invoice_is_dropped():
    # "paid on 27/10" — the model once filled in 2023 and the advice never linked.
    assert _r("27-10-2023")["payment_date"] is None


def test_real_payment_date_kept():
    assert str(_r("27-10-2026")["payment_date"]) == "2026-10-27"


def test_future_date_dropped():
    assert _r("27-10-2031")["payment_date"] is None
