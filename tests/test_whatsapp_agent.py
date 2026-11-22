"""WhatsApp Agent — pure-logic tests (no DB, no network).

Covers the edge cases from docs/whatsapp-agent/05-edge-case-simulation.md that
don't need Postgres: signature checks (A1, A2, A4, A5), number normalisation
(B4), media host allowlist (C5), outbound status ordering (H4, H5), triage
(B1, B2, C1, C2, C7) and the duplicate/correction diff (E4, E6, E7).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend_ocr"))

from app.whatsapp import twilio as tw  # noqa: E402
from app.whatsapp.intake import _diff, _summary, norm_invoice_number  # noqa: E402

TOKEN = "test_auth_token_123"
URL = "https://equal.example.com/api/webhooks/twilio/whatsapp/key123/inbound"
FORM = [
    ("AccountSid", "AC" + "a" * 32),
    ("MessageSid", "SM" + "b" * 32),
    ("From", "whatsapp:+919305654811"),
    ("To", "whatsapp:+14155238886"),
    ("Body", "Invoice for October"),
    ("NumMedia", "1"),
    ("MediaUrl0", "https://api.twilio.com/2010-04-01/Accounts/AC/Messages/SM/Media/ME1"),
    ("MediaContentType0", "application/pdf"),
]


# ── Signature ─────────────────────────────────────────────────────────────────

def test_signature_roundtrip():
    sig = tw.sign(TOKEN, URL, FORM)
    assert tw.verify_signature(TOKEN, URL, FORM, sig)


def test_signature_rejects_tampering():
    sig = tw.sign(TOKEN, URL, FORM)
    tampered = [(k, "whatsapp:+910000000000" if k == "From" else v) for k, v in FORM]
    assert not tw.verify_signature(TOKEN, URL, tampered, sig)          # A1 forged body
    assert not tw.verify_signature("other-token", URL, FORM, sig)      # wrong tenant token
    assert not tw.verify_signature(TOKEN, URL.replace("equal.", "evil."), FORM, sig)  # A4 host
    assert not tw.verify_signature(TOKEN, URL, FORM, None)
    assert not tw.verify_signature("", URL, FORM, sig)


def test_signature_accepts_default_port_variant():
    sig = tw.sign(TOKEN, URL.replace(".com/", ".com:443/"), FORM)
    assert tw.verify_signature(TOKEN, URL, FORM, sig)


def test_signature_matches_official_twilio_sdk():
    validator_mod = pytest.importorskip("twilio.request_validator")
    v = validator_mod.RequestValidator(TOKEN)
    params = dict(FORM)
    sdk_sig = v.compute_signature(URL, params)
    assert tw.verify_signature(TOKEN, URL, FORM, sdk_sig)
    assert tw.sign(TOKEN, URL, FORM) == sdk_sig


def test_signature_multi_valued_params_deterministic():          # A5
    form = FORM + [("MediaUrl0", "https://api.twilio.com/x")]
    assert tw.sign(TOKEN, URL, form) == tw.sign(TOKEN, URL, list(reversed(form)))


# ── Phone numbers ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("whatsapp:+919305654811", "+919305654811"),
    ("+91 93056-54811", "+919305654811"),
    ("09305654811", "+919305654811"),
    ("9305654811", "+919305654811"),
    ("+1 (415) 523-8886", "+14155238886"),
    ("0014155238886", "+14155238886"),
    ("abc", None),
    ("", None),
    (None, None),
    ("12345", None),
])
def test_normalize_e164(raw, expected):                           # B4
    assert tw.normalize_e164(raw) == expected


def test_mask_phone():
    assert tw.mask_phone("+919305654811") == "+9193•••••811"
    assert "05654" not in tw.mask_phone("+919305654811")


# ── Media ─────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("url,ok", [
    ("https://api.twilio.com/2010-04-01/Accounts/AC/Messages/SM/Media/ME", True),
    ("https://media.twiliocdn.com/AC/abc", True),
    ("https://mms.twiliocdn.com/x", True),
    ("https://s3-external-1.amazonaws.com/media.twiliocdn.com/AC/abc", True),
    ("https://s3-external-1.amazonaws.com/evil-bucket/abc", False),
    ("http://api.twilio.com/insecure", False),
    ("https://169.254.169.254/latest/meta-data", False),
    ("https://twilio.com.evil.io/x", False),
])
def test_media_host_allowlist(url, ok):                           # C5
    assert tw._host_allowed(url) is ok


def test_fetch_media_blocks_disallowed_host_without_network():
    with pytest.raises(tw.MediaError) as e:
        tw.fetch_media("https://169.254.169.254/x", "AC", "tok")
    assert e.value.code == "MEDIA_HOST_BLOCKED" and not e.value.retryable


def test_is_pdf():
    assert tw.is_pdf(b"%PDF-1.7\n...")
    assert not tw.is_pdf(b"MZ\x90\x00 fake exe")                  # C3


# ── Outbound status ordering ──────────────────────────────────────────────────

@pytest.mark.parametrize("cur,inc,expected", [
    ("QUEUED", "SENT", "SENT"),
    ("SENT", "DELIVERED", "DELIVERED"),
    ("DELIVERED", "SENT", "DELIVERED"),       # H4 out of order
    ("DELIVERED", "DELIVERED", "DELIVERED"),  # H5 duplicate
    ("READ", "DELIVERED", "READ"),
    ("SENT", "FAILED", "FAILED"),
    ("FAILED", "DELIVERED", "FAILED"),        # terminal
    ("UNKNOWN", "SENT", "SENT"),
    (None, "QUEUED", "QUEUED"),
])
def test_next_status(cur, inc, expected):
    assert tw.next_status(cur, inc) == expected


def test_map_status():
    assert tw.map_status("undelivered") == "FAILED"
    assert tw.map_status("delivered") == "DELIVERED"
    assert tw.map_status("accepted") == "QUEUED"


# ── Triage ────────────────────────────────────────────────────────────────────

class _Cur:
    def __init__(self, watches):
        self._watches = watches

    def execute(self, *_a, **_k):
        pass

    def fetchall(self):
        return self._watches


@pytest.fixture
def triage(monkeypatch):
    from app.whatsapp import ingress, repo
    monkeypatch.setattr(repo, "licensed", lambda t: True)
    conn_row = {"inbound_enabled": True}

    def run(watches, params, num_media):
        return ingress._triage(_Cur(watches), conn_row, "t1", "+919305654811", params.get("Body", ""),
                               num_media, params)
    return run


W1 = {"id": "w1", "supplier_id": "s1", "contact_id": "c1", "phone_e164": "+919305654811", "consent": "UNKNOWN"}
W2 = {"id": "w2", "supplier_id": "s2", "contact_id": "c2", "phone_e164": "+919305654811", "consent": "UNKNOWN"}


def test_triage_unwatched_fetches_nothing(triage):                # B1
    outcome, _, watch, jobs = triage([], dict(FORM), 1)
    assert outcome == "UNWATCHED" and watch is None and jobs == []


def test_triage_ambiguous(triage):                                # B2
    outcome, _, _, jobs = triage([W1, W2], dict(FORM), 1)
    assert outcome == "AMBIGUOUS_CONTACT" and jobs == []


def test_triage_text_only(triage):                                # C1
    outcome, _, watch, jobs = triage([W1], {"Body": "hi"}, 0)
    assert outcome == "TEXT_ONLY" and watch == W1 and jobs == []


def test_triage_image_unsupported(triage):                        # C2
    p = {"MediaUrl0": "https://api.twilio.com/m", "MediaContentType0": "image/jpeg"}
    outcome, reason, _, jobs = triage([W1], p, 1)
    assert outcome == "UNSUPPORTED_MEDIA" and "PDF" in reason and jobs == []


def test_triage_mixed_media_one_job_per_pdf(triage):              # C7
    p = {"MediaUrl0": "https://api.twilio.com/a", "MediaContentType0": "application/pdf",
         "MediaUrl1": "https://api.twilio.com/b", "MediaContentType1": "image/png",
         "MediaUrl2": "https://api.twilio.com/c", "MediaContentType2": "application/pdf"}
    outcome, _, _, jobs = triage([W1], p, 3)
    assert outcome == "QUEUED" and [j[0] for j in jobs] == [0, 2]


def test_triage_paused_keeps_jobs(monkeypatch):
    from app.whatsapp import ingress, repo
    monkeypatch.setattr(repo, "licensed", lambda t: True)
    outcome, _, _, jobs = ingress._triage(_Cur([W1]), {"inbound_enabled": False}, "t1", "+919305654811", "",
                                          1, dict(FORM))
    assert outcome == "PAUSED" and len(jobs) == 1


def test_triage_unlicensed(monkeypatch):
    from app.whatsapp import ingress, repo
    monkeypatch.setattr(repo, "licensed", lambda t: False)
    outcome, _, _, jobs = ingress._triage(_Cur([W1]), {"inbound_enabled": True}, "t1", "+919305654811", "",
                                          1, dict(FORM))
    assert outcome == "LICENSE_INACTIVE" and jobs == []


# ── Duplicate / correction ────────────────────────────────────────────────────

def test_norm_invoice_number():
    assert norm_invoice_number(" inv-2026/077 ") == "INV2026077"
    assert norm_invoice_number(None) == ""


def test_diff_same_invoice_is_empty():                            # E1/E2
    a = _summary({"invoice_number": "INV-1", "invoice_date": "2026-11-01", "total_amount": "11800.00"})
    b = _summary({"invoice_number": "INV-1", "invoice_date": "2026-11-01", "total_amount": 11800})
    assert _diff(a, b) == {}


def test_diff_revised_amount_is_correction():                     # E4
    a = _summary({"invoice_number": "INV-1", "total_amount": 10000})
    b = _summary({"invoice_number": "INV-1", "total_amount": 11800})
    assert _diff(a, b) == {"total_amount": {"from": 10000.0, "to": 11800.0}}


def test_diff_ignores_missing_fields():                           # D4
    a = _summary({"invoice_number": "INV-1", "total_amount": 100})
    b = _summary({"invoice_number": "INV-1", "total_amount": 100, "tax_amount": 18})
    assert _diff(a, b) == {}


# ── Worker ────────────────────────────────────────────────────────────────────

def test_backoff_bounded():
    from app.whatsapp.worker import backoff
    assert 20 <= backoff(1).total_seconds() <= 40
    assert backoff(20).total_seconds() <= 1800 * 1.2
