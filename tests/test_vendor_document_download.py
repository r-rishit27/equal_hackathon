"""A recon document that points at a bill already in the app ("bill-upload:<upload_id>") opens the bill's
own file — the invoice viewer showed "Couldn't load the original" because the route didn't follow it."""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from backend_ocr.app.routers import vendor_documents as vd

TENANT = "11111111-1111-1111-1111-111111111111"
PDF = b"%PDF-1.4 the bill"


class _Cur:
    def __init__(self, rows):
        self.rows, self.q = rows, None

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, q, params):
        self.q, self.params = q, params

    def fetchone(self):
        for key, row in self.rows.items():
            if key in self.q and (key != "raw_invoice_uploads" or self.params[1] == TENANT):
                return row
        return None


class _Conn:
    def __init__(self, rows):
        self.rows = rows

    def cursor(self):
        return _Cur(self.rows)


@pytest.fixture
def route(monkeypatch):
    def setup(rows, stored=None):
        monkeypatch.setattr(vd, "require_tenant", lambda: TENANT)
        monkeypatch.setattr(vd, "get_conn", lambda: _Conn(rows))
        monkeypatch.setattr(vd, "put_conn", lambda c, **k: None)
        monkeypatch.setattr(vd.object_store, "load", lambda ref: (stored or {}).get(ref))
        return vd.download_vendor_document
    return setup


def test_bill_upload_ref_serves_the_bills_file(route):
    s3 = "s3://onsumm-assets-dev/invoices/t/u/Main Invoice.pdf"
    dl = route({"vendor_documents": ("Invoice IS-HO-26-27-120.pdf", "bill-upload:b4c3fec7"),
                "raw_invoice_uploads": (s3, None)}, stored={s3: PDF})
    r = dl("sup", "doc", preview=True, signed=False)
    assert r.body == PDF and r.media_type == "application/pdf"
    assert r.headers["content-disposition"].startswith("inline")


def test_bill_upload_kept_in_the_row_is_served(route):
    dl = route({"vendor_documents": ("Invoice.pdf", "bill-upload:b4c3fec7"),
                "raw_invoice_uploads": (None, memoryview(PDF))})
    assert dl("sup", "doc", preview=True, signed=False).body == PDF


def test_another_tenants_upload_is_not_found(route, monkeypatch):
    dl = route({"vendor_documents": ("Invoice.pdf", "bill-upload:b4c3fec7"),
                "raw_invoice_uploads": ("s3://x/y.pdf", None)})
    monkeypatch.setattr(vd, "require_tenant", lambda: "22222222-2222-2222-2222-222222222222")
    with pytest.raises(HTTPException) as e:
        dl("sup", "doc", preview=True, signed=False)
    assert e.value.status_code == 404


def test_ordinary_file_unchanged(route):
    dl = route({"vendor_documents": ("po.pdf", "s3://b/po.pdf")}, stored={"s3://b/po.pdf": PDF})
    assert dl("sup", "doc", preview=False, signed=False).headers["content-disposition"].startswith("attachment")
