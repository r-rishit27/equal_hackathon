"""Deep links into the app, built in one place.

A broken deep link is the most damaging bug this feature can ship: the finding
is right, the user clicks, and lands nowhere. These mirror
frontend/src/routes/paths.ts exactly and are snapshot-tested in
tests/test_review_adapters.py so a route rename fails the build here too.

`focus` is the field to highlight once the page opens; the frontend scrolls to
[data-focus-key="<focus>"] and pulses the focus ring.
"""
from __future__ import annotations

from urllib.parse import urlencode


def _with_focus(path: str, focus: str | None) -> str:
    return f"{path}?{urlencode({'focus': focus})}" if focus else path


def bill(invoice_id: str, focus: str | None = None) -> str:
    return _with_focus(f"/bills/{invoice_id}", focus)


def vendor(supplier_id: str, tab: str | None = None, focus: str | None = None) -> str:
    path = f"/vendors/{supplier_id}/{tab}" if tab else f"/vendors/{supplier_id}"
    return _with_focus(path, focus)


def vendor_thread(supplier_id: str, thread_id: str) -> str:
    """Vendor card → Conversations, with one email thread open."""
    return f"/vendors/{supplier_id}/conversations?{urlencode({'thread': thread_id})}"


def vendor_recon(supplier_id: str, case_id: str | None = None) -> str:
    """Vendor card → Documents → Recon, with one case's reconciliation card open over it."""
    base = f"/vendors/{supplier_id}/documents?folder=recon"
    # The card param keeps ':' unescaped, the way the app writes it (components/records/recordLinks.ts).
    return f"{base}&open=recon:{case_id}" if case_id else base


def pay(supplier_id: str, invoice_id: str | None = None) -> str:
    base = f"/bills/pay/{supplier_id}"
    return f"{base}?{urlencode({'bill': invoice_id})}" if invoice_id else base


def settings(section: str, focus: str | None = None) -> str:
    return _with_focus(f"/settings/{section}", focus)


def bills_list() -> str:
    return "/bills"


def nova() -> str:
    return "/nova"


def agent_hub() -> str:
    return "/agent-hub"


def data_extraction() -> str:
    return "/data-extraction"
