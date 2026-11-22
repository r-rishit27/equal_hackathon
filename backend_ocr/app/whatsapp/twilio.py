"""Twilio WhatsApp adapter. No Twilio SDK: the four calls we need are small and
this keeps the dependency surface (and the deploy) unchanged.

  * verify_signature — X-Twilio-Signature (HMAC-SHA1 over URL + sorted params)
  * fetch_media      — authenticated, host-allowlisted, size-capped, redirect-checked
  * send_message     — Messages API create, with a status callback
  * list_recent      — used to reconcile an outbound send whose result is unknown
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
from dataclasses import dataclass
from urllib.parse import urlparse, urlunparse

import httpx

API_BASE = "https://api.twilio.com/2010-04-01"
MEDIA_MAX_BYTES = int(os.getenv("WA_MEDIA_MAX_BYTES", str(16 * 1024 * 1024)))
MEDIA_TIMEOUT_S = float(os.getenv("WA_MEDIA_TIMEOUT_S", "30"))
SEND_TIMEOUT_S = float(os.getenv("WA_SEND_TIMEOUT_S", "15"))

# Credentials are only ever sent to api.twilio.com. Redirect targets must be on
# this allowlist and are fetched without credentials.
_CRED_HOSTS = {"api.twilio.com"}
_MEDIA_HOST_SUFFIXES = (".twilio.com", ".twiliocdn.com")
_MEDIA_HOSTS = {"api.twilio.com", "media.twiliocdn.com"}
_S3_MEDIA_HOSTS = {"s3-external-1.amazonaws.com", "s3.amazonaws.com"}


class MediaError(Exception):
    def __init__(self, code: str, retryable: bool, msg: str = ""):
        super().__init__(msg or code)
        self.code = code
        self.retryable = retryable


class SendError(Exception):
    def __init__(self, code: str, msg: str, unknown: bool = False):
        super().__init__(msg)
        self.code = code
        self.unknown = unknown   # True => request may have reached Twilio


# ── Phone numbers ─────────────────────────────────────────────────────────────

def normalize_e164(raw: str | None, default_cc: str = "91") -> str | None:
    """'whatsapp:+91 98765-43210' / '09876543210' / '9876543210' -> '+919876543210'."""
    if not raw:
        return None
    s = str(raw).strip()
    if s.lower().startswith("whatsapp:"):
        s = s[9:]
    plus = s.startswith("+")
    digits = re.sub(r"\D", "", s)
    if not digits:
        return None
    if not plus:
        if digits.startswith("00"):
            digits = digits[2:]
        elif len(digits) == 11 and digits.startswith("0"):
            digits = default_cc + digits[1:]
        elif len(digits) == 10:
            digits = default_cc + digits
    if not 8 <= len(digits) <= 15:
        return None
    return "+" + digits


def mask_phone(e164: str | None) -> str | None:
    if not e164:
        return None
    if len(e164) <= 6:
        return e164
    return f"{e164[:5]}•••••{e164[-3:]}"


# ── Signature ─────────────────────────────────────────────────────────────────

def _compute(auth_token: str, url: str, params: list[tuple[str, str]]) -> str:
    grouped: dict[str, set[str]] = {}
    for k, v in params:
        grouped.setdefault(k, set()).add(v)
    data = url
    for k in sorted(grouped):
        for v in sorted(grouped[k]):
            data += k + v
    mac = hmac.new(auth_token.encode(), data.encode("utf-8"), hashlib.sha1).digest()
    return base64.b64encode(mac).decode()


def _url_variants(url: str) -> list[str]:
    """Twilio may sign with or without the default port; accept both."""
    p = urlparse(url)
    out = [url]
    if p.port is None:
        port = 443 if p.scheme == "https" else 80
        out.append(urlunparse(p._replace(netloc=f"{p.hostname}:{port}")))
    else:
        out.append(urlunparse(p._replace(netloc=p.hostname or "")))
    return out


def verify_signature(auth_token: str, url: str, params: list[tuple[str, str]], signature: str | None) -> bool:
    if not signature or not auth_token:
        return False
    return any(hmac.compare_digest(_compute(auth_token, u, params), signature) for u in _url_variants(url))


def sign(auth_token: str, url: str, params: list[tuple[str, str]]) -> str:
    """Test helper: produce the signature Twilio would send."""
    return _compute(auth_token, url, params)


# ── Media ─────────────────────────────────────────────────────────────────────

@dataclass
class FetchedMedia:
    data: bytes
    content_type: str


def _host_allowed(url: str) -> bool:
    p = urlparse(url)
    if p.scheme != "https" or not p.hostname:
        return False
    h = p.hostname.lower()
    if h in _MEDIA_HOSTS or h.endswith(_MEDIA_HOST_SUFFIXES):
        return True
    # Legacy Twilio media redirect: s3-external-1.amazonaws.com/media.twiliocdn.com/...
    return h in _S3_MEDIA_HOSTS and p.path.startswith("/media.twiliocdn.com/")


def fetch_media(url: str, account_sid: str, auth_token: str, max_bytes: int = MEDIA_MAX_BYTES) -> FetchedMedia:
    if not _host_allowed(url):
        raise MediaError("MEDIA_HOST_BLOCKED", False, f"media host not allowed: {urlparse(url).hostname}")
    # Twilio's trial "Try out WhatsApp" sender is owned by a Twilio account, so its
    # MediaUrl points there and our credentials get 401 forever. Fail fast, clearly.
    owner = re.search(r"/Accounts/(AC[0-9a-fA-F]{32})/", urlparse(url).path or "")
    if owner and account_sid and owner.group(1) != account_sid:
        raise MediaError("MEDIA_FOREIGN_ACCOUNT", False,
                         "Twilio stores this attachment under a different account (the trial "
                         "'Try out WhatsApp' number), so it can't be downloaded. Use the classic "
                         "WhatsApp Sandbox or your own WhatsApp sender.")
    current = url
    with httpx.Client(timeout=MEDIA_TIMEOUT_S, follow_redirects=False) as client:
        for _ in range(4):
            host = (urlparse(current).hostname or "").lower()
            auth = (account_sid, auth_token) if host in _CRED_HOSTS else None
            try:
                with client.stream("GET", current, auth=auth) as r:
                    if r.status_code in (301, 302, 303, 307, 308):
                        nxt = r.headers.get("location") or ""
                        if nxt.startswith("/"):
                            p = urlparse(current)
                            nxt = f"{p.scheme}://{p.netloc}{nxt}"
                        if not _host_allowed(nxt):
                            raise MediaError("MEDIA_HOST_BLOCKED", False, "redirect to non-allowlisted host")
                        current = nxt
                        continue
                    if r.status_code == 404:
                        raise MediaError("MEDIA_EXPIRED", False, "media not found (expired or deleted)")
                    if r.status_code in (401, 403):
                        raise MediaError("MEDIA_AUTH_FAILED", True, f"media fetch HTTP {r.status_code}")
                    if r.status_code >= 500 or r.status_code == 429:
                        raise MediaError("MEDIA_FETCH_FAILED", True, f"media fetch HTTP {r.status_code}")
                    if r.status_code != 200:
                        raise MediaError("MEDIA_FETCH_FAILED", False, f"media fetch HTTP {r.status_code}")
                    declared = int(r.headers.get("content-length") or 0)
                    if declared > max_bytes:
                        raise MediaError("MEDIA_TOO_LARGE", False, f"{declared} bytes")
                    buf = bytearray()
                    for chunk in r.iter_bytes():
                        buf.extend(chunk)
                        if len(buf) > max_bytes:
                            raise MediaError("MEDIA_TOO_LARGE", False, f">{max_bytes} bytes")
                    return FetchedMedia(bytes(buf), (r.headers.get("content-type") or "").split(";")[0].strip())
            except httpx.TimeoutException as e:
                raise MediaError("MEDIA_FETCH_TIMEOUT", True, str(e)) from e
            except httpx.TransportError as e:
                raise MediaError("MEDIA_FETCH_FAILED", True, str(e)) from e
    raise MediaError("MEDIA_FETCH_FAILED", False, "too many redirects")


def is_pdf(data: bytes) -> bool:
    return data[:1024].lstrip().startswith(b"%PDF-")


# ── Messages API ──────────────────────────────────────────────────────────────

def send_message(account_sid: str, auth_token: str, from_e164: str, to_e164: str, body: str,
                 status_callback: str | None = None) -> dict:
    form = {"From": f"whatsapp:{from_e164}", "To": f"whatsapp:{to_e164}", "Body": body}
    if status_callback:
        form["StatusCallback"] = status_callback
    try:
        r = httpx.post(f"{API_BASE}/Accounts/{account_sid}/Messages.json", data=form,
                       auth=(account_sid, auth_token), timeout=SEND_TIMEOUT_S)
    except httpx.ConnectError as e:
        raise SendError("SEND_CONNECT_FAILED", str(e)) from e          # never reached Twilio
    except (httpx.TimeoutException, httpx.TransportError) as e:
        raise SendError("SEND_TIMEOUT", str(e), unknown=True) from e     # may have been sent
    if r.status_code >= 500:
        raise SendError("SEND_PROVIDER_5XX", f"HTTP {r.status_code}", unknown=True)
    data = r.json() if r.content else {}
    if r.status_code >= 400:
        raise SendError(str(data.get("code") or r.status_code), data.get("message") or f"HTTP {r.status_code}")
    return data


def list_recent(account_sid: str, auth_token: str, to_e164: str, from_e164: str, page_size: int = 20) -> list[dict]:
    r = httpx.get(f"{API_BASE}/Accounts/{account_sid}/Messages.json",
                  params={"To": f"whatsapp:{to_e164}", "From": f"whatsapp:{from_e164}", "PageSize": page_size},
                  auth=(account_sid, auth_token), timeout=SEND_TIMEOUT_S)
    r.raise_for_status()
    return r.json().get("messages", [])


def check_account(account_sid: str, auth_token: str) -> dict:
    r = httpx.get(f"{API_BASE}/Accounts/{account_sid}.json", auth=(account_sid, auth_token), timeout=10)
    if r.status_code == 401:
        raise SendError("AUTH_FAILED", "Twilio rejected the Account SID / Auth token")
    r.raise_for_status()
    d = r.json()
    return {"status": d.get("status"), "type": d.get("type"), "friendly_name": d.get("friendly_name")}


# ── Outbound status ordering ──────────────────────────────────────────────────

_RANK = {"QUEUED": 0, "UNKNOWN": 0, "SENT": 1, "DELIVERED": 2, "READ": 3}
_TERMINAL_FAIL = {"FAILED", "UNDELIVERED", "REJECTED"}


def map_status(twilio_status: str | None) -> str:
    s = (twilio_status or "").upper()
    return {"ACCEPTED": "QUEUED", "SCHEDULED": "QUEUED", "SENDING": "SENT", "UNDELIVERED": "FAILED",
            "CANCELED": "FAILED", "RECEIVED": "DELIVERED"}.get(s, s or "UNKNOWN")


def next_status(current: str | None, incoming: str) -> str:
    """Status never regresses; failures are terminal; READ beats DELIVERED."""
    cur = (current or "QUEUED").upper()
    inc = incoming.upper()
    if cur in _TERMINAL_FAIL or cur == "READ":
        return cur
    if inc in _TERMINAL_FAIL:
        return "FAILED"
    return inc if _RANK.get(inc, 0) >= _RANK.get(cur, 0) else cur
