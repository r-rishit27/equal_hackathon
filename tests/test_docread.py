"""Shared document reader (backend_ocr/app/docread): routing, fallback, checks, and the per-kind
contract prompts. No network: OpenAI and Sarvam are replaced by fakes."""
from __future__ import annotations

import pytest

fitz = pytest.importorskip("fitz")

from backend_ocr.app.docread import checks, reader  # noqa: E402
from backend_ocr.app.docread import config as DC  # noqa: E402
from backend_ocr.app.docread import sarvam  # noqa: E402

WORDS = " ".join(f"word{i}" for i in range(40))


def _png() -> bytes:
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 60, 40), 0)
    pix.set_rect(pix.irect, (200, 30, 30))
    return pix.tobytes("png")


def _pdf(*kinds: str) -> bytes:
    """Pages: 'text' (a full text layer), 'scan' (only an image), 'short' (3 words, no image)."""
    doc = fitz.open()
    for k in kinds:
        p = doc.new_page()
        if k == "text":
            p.insert_textbox(fitz.Rect(36, 36, 560, 800), WORDS)
        elif k == "scan":
            p.insert_image(fitz.Rect(36, 36, 400, 300), stream=_png())
        elif k == "short":
            p.insert_text((72, 72), "Signed and sealed")
    return doc.tobytes()


# ── checks ──────────────────────────────────────────────────────────────────

def test_gstin_check_character():
    assert checks.gstin_valid("29AABCB1043Q1ZI")          # Bata Karnataka
    assert checks.gstin_valid("07AAQCA8977K1ZP")
    assert not checks.gstin_valid("29AABCB1043Q1Z1")      # the I→1 misread parsers made
    assert not checks.gstin_valid("244ABCA2392K1ZR")      # 15 chars, wrong shape
    assert not checks.gstin_valid(None)
    found = checks.find_gstins("Vendor GSTIN 29AKRPP8699K1ZO / Buyer 29AABCB1043Q1Z1 and 29AKRPP8699K1ZO")
    assert found == [("29AKRPP8699K1ZO", True), ("29AABCB1043Q1Z1", False)]


# ── reader routing ──────────────────────────────────────────────────────────

async def test_text_layer_first_vision_only_for_scanned_pages():
    calls = []

    async def transcribe(img):
        calls.append(len(img))
        return "| Item | Qty |\n|---|---|\n| Rack | 4 |", 0.02, "fake-vision"

    read = await reader.read_document(_pdf("text", "scan", "short"), "mixed.pdf", transcribe=transcribe,
                                      fallback=None)
    assert [p.source for p in read.pages] == ["text_layer", "openai", "text_layer"]
    assert len(calls) == 1                                  # only the scanned page cost anything
    assert read.from_scan and read.cost_usd == pytest.approx(0.02)
    assert "--- Page 2 ---\n| Item" in read.text


async def test_digital_document_never_calls_vision():
    async def transcribe(img):
        raise AssertionError("vision must not run on a digital document")

    read = await reader.read_document(_pdf("text", "short"), "contract.pdf", transcribe=transcribe, fallback=None)
    assert not read.from_scan and read.cost_usd == 0
    assert read.sources == {"text_layer": 2}


async def test_sarvam_reads_the_page_when_openai_fails():
    async def transcribe(img):
        raise RuntimeError("openai gpt-5.4: RateLimitError: insufficient_quota")

    got = []

    async def fallback(pdf: bytes):
        got.append(fitz.open(stream=pdf, filetype="pdf").page_count)
        return "Vendor Qty 48"

    read = await reader.read_document(_pdf("scan"), "scan.pdf", transcribe=transcribe, fallback=fallback)
    assert got == [1]                                       # one page at a time, as its own PDF
    p = read.pages[0]
    assert (p.source, p.text, p.model) == ("sarvam", "Vendor Qty 48", "sarvam-doc-ai")
    assert "insufficient_quota" in p.error


async def test_both_readers_failing_marks_the_page_failed():
    async def transcribe(img):
        raise RuntimeError("openai down")

    async def fallback(pdf):
        raise RuntimeError("sarvam down")

    read = await reader.read_document(_pdf("text", "scan"), "x.pdf", transcribe=transcribe, fallback=fallback)
    assert [p.source for p in read.pages] == ["text_layer", "failed"]
    assert "openai down" in read.pages[1].error and "sarvam down" in read.pages[1].error


async def test_an_image_file_is_one_scanned_page():
    async def transcribe(img):
        return "POD 1000 4128 4608", 0.01, "fake"

    read = await reader.read_document(_png(), "pod.png", transcribe=transcribe, fallback=None)
    assert [p.source for p in read.pages] == ["openai"]


def test_spent_quota_is_not_retried():
    assert not reader.retryable(RuntimeError("Error code: 429 insufficient_quota credit_balance_exhausted"))
    assert reader.retryable(RuntimeError("RateLimitError: rate_limit_exceeded"))
    assert reader.retryable(TimeoutError("APITimeoutError timeout"))
    assert not reader.retryable(ValueError("BadRequestError: invalid image"))


def test_gpt5_sampling_has_no_temperature():
    assert "temperature" not in DC.sampling("gpt-5.4", 100)
    assert DC.sampling("gpt-4o", 100) == {"temperature": 0, "max_tokens": 100}


def test_sarvam_json_is_taken_from_chatter():
    assert sarvam._first_json_object('Sure!\n```json\n{"a": {"b": 1}}\n```') == {"a": {"b": 1}}
    assert sarvam._first_json_object('<think>x</think>\n{"invoice_no": "IS-1"} done') == {"invoice_no": "IS-1"}
    assert sarvam.strip_images("a ![x](data:image/png;base64,AAAA) b") == "a  b"


# ── Recon falls back to Sarvam, but never for a check read ──────────────────

async def test_recon_llm_falls_back_to_sarvam(monkeypatch):
    from backend_ocr.app.recon.llm import ReconLLM

    llm = ReconLLM(api_key="x", fallback=True)

    async def boom(*a, **k):
        raise RuntimeError("insufficient_quota")

    monkeypatch.setattr(llm, "_openai_json", boom)
    monkeypatch.setattr(sarvam, "available", lambda: True)
    seen = {}

    async def parse(pdf, *a, **k):
        return "| Item | Vendor Qty |\n| Rack | 48 |"

    async def chat_json(system, user, max_tokens=0):
        seen["user"] = user
        return {"rows": [{"item": "Rack", "vendor_qty": 48}]}

    monkeypatch.setattr(sarvam, "parse", parse)
    monkeypatch.setattr(sarvam, "chat_json", chat_json)
    out = await llm.json("sheet_rows", "Read the rows.", images=[_png()])
    assert out["rows"][0]["vendor_qty"] == 48
    assert "Vendor Qty" in seen["user"] and llm.fallback_calls == 1

    with pytest.raises(RuntimeError, match="insufficient_quota"):
        await llm.json("sheet_rows_check", "Read the rows.", images=[_png()])


# ── contracts: one prompt per kind ──────────────────────────────────────────

def test_document_kind_picks_the_prompt():
    from backend_ocr.app.review.comm_extract import CONTRACT_SYSTEMS, detect_document_kind

    assert detect_document_kind("INSERTION ORDER\nCampaign Name: Loans\nModel: CPA  Payout: 700", "IO-123.pdf") == "io"
    assert detect_document_kind("PURCHASE ORDER\nPO No: PPO00024378\nUnit Pr. Qty Amt", "Show purchase order.pdf") == "po"
    assert detect_document_kind("This Agreement is made ... WHEREAS ... termination ... governing law",
                                "Aforv agreement.pdf") == "contract"
    assert detect_document_kind("", "") == "contract"
    assert set(CONTRACT_SYSTEMS) == {"contract", "io", "po"}


def test_kind_prompts_share_the_two_party_and_output_rules():
    from backend_ocr.app.review.comm_extract import CONTRACT_SYSTEM, IO_SYSTEM, PO_SYSTEM

    for p in (IO_SYSTEM, PO_SYSTEM):
        assert "A CONTRACT HAS TWO PARTIES" in p
        assert "WHERE THE VENDOR'S SIDE IS BLANK, REPORT NOTHING FOR IT" in p
        assert "the bank account THE VENDOR IS PAID INTO" in p
        assert p.endswith(CONTRACT_SYSTEM[CONTRACT_SYSTEM.index("RULES YOU MUST FOLLOW"):])
    assert "payout_per_event" in IO_SYSTEM and "flight_start" in IO_SYSTEM
    assert "EVERY ORDERED LINE ITEM'S RATE" in PO_SYSTEM


def test_complete_json_sampling_for_gpt5():
    from backend_ocr.app.ai.llm import _sampling, price

    assert _sampling("gpt-5.4-mini", 0.0, 100)["max_completion_tokens"] == 100
    assert "temperature" not in _sampling("gpt-5.4-mini", 0.0, 100)
    assert _sampling("gpt-4o-mini", 0.0, 100) == {"temperature": 0.0, "max_tokens": 100}
    assert price("gpt-5.4-mini", 1_000_000, 0) == pytest.approx(0.75)
