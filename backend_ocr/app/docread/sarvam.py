"""Sarvam client: Document AI (page → markdown) and chat (text → JSON). The fallback when OpenAI fails.

Document AI is an async job: submit the file, poll its status, download a ZIP holding the markdown.
It is processed in India and costs ₹0.50 a page, but takes ~1 minute a page (p95 ~7.5 min in the
evaluation), so it never runs first.
"""
from __future__ import annotations

import asyncio
import io
import json
import logging
import re
import time
import zipfile

from . import config as C

logger = logging.getLogger(__name__)

_IMG_MD = re.compile(r"!\[[^\]]*\]\(data:[^)]*\)")
_IMG_HTML = re.compile(r"<img[^>]*src=\"data:[^\"]*\"[^>]*>")


class SarvamError(RuntimeError):
    pass


def available() -> bool:
    return C.SARVAM_FALLBACK and bool(C.sarvam_key())


def _headers() -> dict:
    key = C.sarvam_key()
    if not key:
        raise SarvamError("SARVAM_API_KEY is not set")
    return {"api-subscription-key": key}


def strip_images(md: str) -> str:
    """Sarvam's markdown embeds page images as base64: they carry no text and can be megabytes."""
    return _IMG_HTML.sub("", _IMG_MD.sub("", md or ""))


async def parse(data: bytes, filename: str = "page.pdf", mime: str = "application/pdf",
                language: str = "en-IN") -> str:
    """One file (a single page, ideally) → markdown text."""
    import httpx
    h = _headers()
    async with httpx.AsyncClient(base_url=C.SARVAM_BASE, timeout=120) as cli:
        r = await cli.post("/doc-ai/v1/job/parse", headers=h, files={"file": (filename, data, mime)},
                           data={"language": language, "output_format": "md"})
        if r.status_code >= 400:
            raise SarvamError(f"submit {r.status_code}: {r.text[:300]}")
        job = r.json().get("job_id")
        if not job:
            raise SarvamError(f"no job id: {r.text[:300]}")
        deadline = time.monotonic() + C.SARVAM_JOB_TIMEOUT_S
        delay, status = 2.0, ""
        while time.monotonic() < deadline:
            await asyncio.sleep(delay)
            delay = min(delay * 1.5, 10.0)
            s = (await cli.get(f"/doc-ai/v1/job/{job}/status", headers=h)).json()
            status = str(s.get("status", "")).lower()
            if status in ("completed", "partially_completed"):
                break
            if status in ("failed", "rejected"):
                raise SarvamError(f"job {job} {status}: {str(s)[:300]}")
        else:
            raise SarvamError(f"job {job} still {status or 'pending'} after {C.SARVAM_JOB_TIMEOUT_S:.0f}s")
        url = (await cli.get(f"/doc-ai/v1/job/{job}/download-url", headers=h)).json().get("url")
        if not url:
            raise SarvamError(f"job {job}: no download url")
        z = zipfile.ZipFile(io.BytesIO((await cli.get(url, timeout=300)).content))
    md = "\n\n".join(z.read(n).decode("utf-8", "replace") for n in sorted(z.namelist()) if n.endswith(".md"))
    return strip_images(md).strip()


def _first_json_object(raw: str) -> dict:
    raw = (raw or "").strip()
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw)
    try:
        out = json.loads(raw)
        if isinstance(out, dict):
            return out
    except json.JSONDecodeError:
        pass
    start = raw.find("{")
    while start != -1:                      # the widest balanced {...} that parses
        depth = 0
        for i in range(start, len(raw)):
            depth += raw[i] == "{"
            depth -= raw[i] == "}"
            if depth == 0:
                try:
                    out = json.loads(raw[start:i + 1])
                    if isinstance(out, dict):
                        return out
                except json.JSONDecodeError:
                    break
                break
        start = raw.find("{", start + 1)
    raise SarvamError("sarvam chat did not return a JSON object")


async def chat_json(system: str, user: str, max_tokens: int = 16000) -> dict:
    """Text → one JSON object, with Sarvam's chat model (used only when OpenAI cannot be reached)."""
    import httpx
    body = {"model": C.SARVAM_CHAT_MODEL, "temperature": 0, "max_tokens": max_tokens,
            "messages": [{"role": "system", "content": system + "\n\nReply with one JSON object only, no prose."},
                         {"role": "user", "content": user}]}
    async with httpx.AsyncClient(base_url=C.SARVAM_BASE, timeout=300) as cli:
        r = await cli.post("/v1/chat/completions", headers=_headers(), json=body)
    if r.status_code >= 400:
        raise SarvamError(f"chat {r.status_code}: {r.text[:300]}")
    return _first_json_object(r.json()["choices"][0]["message"].get("content") or "")


def image_to_pdf(img: bytes) -> bytes:
    """A page image as a one-page PDF (Sarvam's parser takes PDFs and PNGs; ours are JPEG)."""
    import fitz
    kind = "png" if img[:4] == b"\x89PNG" else "jpeg"
    with fitz.open(stream=img, filetype=kind) as d:
        return d.convert_to_pdf()
