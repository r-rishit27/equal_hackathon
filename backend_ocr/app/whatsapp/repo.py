"""Connection, watch and scope helpers shared by ingress, worker and API.

Scope rule (HLD §1.3): the tenant comes ONLY from the connection row the opaque
connection_key resolves to — never from the sender number, the message text or
anything a client sends.
"""
from __future__ import annotations

import os
import secrets

from ..integrations import email_oauth

SERVICE_KEY = "whatsapp_agent"
WEBHOOK_PREFIX = "/api/webhooks/twilio/whatsapp/"


def public_base_url(request=None) -> str:
    """The exact public origin Twilio signs. PUBLIC_BASE_URL wins; otherwise the
    forwarded headers are used (still safe — a forged header can only make a
    genuine signature fail, never make a forged one pass)."""
    env = (os.getenv("PUBLIC_BASE_URL") or "").strip().rstrip("/")
    if env:
        return env
    if request is None:
        return ""
    h = request.headers
    proto = (h.get("x-forwarded-proto") or request.url.scheme).split(",")[0].strip()
    host = (h.get("x-forwarded-host") or h.get("host") or request.url.netloc).split(",")[0].strip()
    return f"{proto}://{host}"


def webhook_urls(connection_key: str, request=None) -> dict:
    base = public_base_url(request)
    return {
        "inbound": f"{base}{WEBHOOK_PREFIX}{connection_key}/inbound",
        "status": f"{base}{WEBHOOK_PREFIX}{connection_key}/status",
    }


def new_connection_key() -> str:
    return secrets.token_urlsafe(24)


def seal_secret(auth_token: str | None) -> str:
    if not auth_token:
        return "env"
    return "enc:" + (email_oauth.encrypt_token(auth_token) or "")


def auth_token_for(conn_row: dict) -> str | None:
    ref = conn_row.get("secret_ref") or ""
    if ref == "env":
        return os.getenv("TWILIO_AUTH_TOKEN") or None
    if ref.startswith("enc:"):
        return email_oauth.decrypt_token(ref[4:])
    return None


def get_connection_by_key(cur, key: str) -> dict | None:
    cur.execute("""
        SELECT * FROM whatsapp_connections
        WHERE connection_key=%s AND state <> 'DISCONNECTED'
    """, (key,))
    return cur.fetchone()


def get_connection_for_tenant(cur, tenant_id: str) -> dict | None:
    cur.execute("""
        SELECT * FROM whatsapp_connections
        WHERE tenant_id=%s AND state <> 'DISCONNECTED'
        ORDER BY created_at DESC LIMIT 1
    """, (tenant_id,))
    return cur.fetchone()


def get_connection_by_id(cur, conn_id: str) -> dict | None:
    cur.execute("SELECT * FROM whatsapp_connections WHERE id=%s", (conn_id,))
    return cur.fetchone()


def active_watches_for_phone(cur, tenant_id: str, phone: str) -> list[dict]:
    cur.execute("""
        SELECT w.id::text, w.supplier_id::text, w.contact_id::text, w.phone_e164, w.consent
        FROM whatsapp_contact_watches w
        JOIN supplier_contacts c ON c.id = w.contact_id AND c.tenant_id = w.tenant_id
        WHERE w.tenant_id=%s AND w.phone_e164=%s AND w.watch_enabled
    """, (tenant_id, phone))
    return cur.fetchall()


def licensed(tenant_id: str) -> bool:
    """Entitlement check for code paths with no request (webhook, worker).
    Honors LICENSE_ENFORCEMENT the same way the request gate does."""
    from ..security import licensing
    if licensing.ENFORCEMENT != "enforce":
        return True
    try:
        return licensing.has_service(tenant_id, SERVICE_KEY)
    except Exception:
        return False
