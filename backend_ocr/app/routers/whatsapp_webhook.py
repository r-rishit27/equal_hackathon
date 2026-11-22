"""Public Twilio webhooks for the WhatsApp Agent.

No session auth (see PUBLIC_PREFIXES in security/auth.py): each request is
authenticated by X-Twilio-Signature against the auth token of the connection
its opaque key resolves to.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Request
from fastapi.responses import Response
from psycopg2.extras import RealDictCursor

from ..config import get_conn, put_conn
from ..whatsapp import repo
from ..whatsapp.ingress import handle_inbound
from ..whatsapp.outbox import apply_status_callback
from ..whatsapp.twilio import verify_signature

router = APIRouter(tags=["WhatsApp webhooks"], include_in_schema=False)
log = logging.getLogger("whatsapp.webhook")


def _signed_url(request: Request) -> str:
    url = repo.public_base_url(request) + request.url.path
    if request.url.query:
        url += "?" + request.url.query
    return url


@router.post("/api/webhooks/twilio/whatsapp/{connection_key}/inbound")
async def twilio_inbound(connection_key: str, request: Request):
    form = await request.form()
    items = [(k, str(v)) for k, v in form.multi_items()]
    from starlette.concurrency import run_in_threadpool
    res = await run_in_threadpool(handle_inbound, connection_key, _signed_url(request), items,
                                  request.headers.get("x-twilio-signature"))
    if res.status == 200:
        return Response(content=res.body, media_type="application/xml")
    return Response(status_code=res.status)


@router.post("/api/webhooks/twilio/whatsapp/{connection_key}/status")
async def twilio_status(connection_key: str, request: Request):
    form = await request.form()
    items = [(k, str(v)) for k, v in form.multi_items()]

    def _verify() -> bool:
        conn = get_conn()
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            c = repo.get_connection_by_key(cur, connection_key)
        finally:
            put_conn(conn)
        if not c:
            return False
        return verify_signature(repo.auth_token_for(c) or "", _signed_url(request), items,
                                request.headers.get("x-twilio-signature"))

    from starlette.concurrency import run_in_threadpool
    if not await run_in_threadpool(_verify):
        return Response(status_code=403)
    try:
        await run_in_threadpool(apply_status_callback, connection_key, dict(items))
    except Exception:
        log.exception("whatsapp status callback failed")
        return Response(status_code=500)
    return Response(status_code=204)
