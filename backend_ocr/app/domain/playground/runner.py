"""Working a flow's nodes in order, and recording what each one did."""
from __future__ import annotations

import datetime as _dt
import json
import logging
import mimetypes
import uuid
from typing import Any

from ...config import get_conn, put_conn
from . import checks, outputs
from .engine import RunError, _run_formula, _run_source, as_text

log = logging.getLogger(__name__)


def run_order(nodes: list[dict], edges: list[dict]) -> list[str]:
    """Sources first. Returns [] when the graph has a cycle, which the caller
    treats as a refusal rather than running something that never settles."""
    ids = {n["id"] for n in nodes}
    deps: dict[str, set[str]] = {i: set() for i in ids}
    for e in edges:
        if e.get("to") in ids and e.get("from") in ids:
            deps[e["to"]].add(e["from"])

    done: list[str] = []
    left = set(ids)
    while left:
        ready = sorted(i for i in left if deps[i] <= set(done))
        if not ready:
            return []
        done.extend(ready)
        left -= set(ready)
    return done


def run_flow(*, tenant: str, supplier: str, vendor_name: str, brand_id: str | None,
             graph: dict, actor: str | None, flow_id: str | None = None) -> dict:
    """Work every node, then return the run record.

    Each node's outcome is kept whether it succeeded or not. A node that fails
    marks everything downstream of it skipped rather than failing the run as a
    whole, so one broken branch does not hide what the other branches did —
    including anything they already wrote outside this system.
    """
    nodes = {n["id"]: n for n in graph.get("nodes") or []}
    edges = [e for e in graph.get("edges") or [] if e.get("from") and e.get("to")]
    order = run_order(list(nodes.values()), edges)
    if not order and nodes:
        raise RunError("this flow loops back on itself, so it would never finish")

    incoming: dict[str, list[str]] = {i: [] for i in nodes}
    for e in edges:
        if e["to"] in incoming:
            incoming[e["to"]].append(e["from"])

    values: dict[str, dict] = {}
    steps: list[dict] = []
    produced: list[dict] = []
    failed: set[str] = set()

    conn = get_conn()
    try:
        with conn.cursor() as cur:
            ctx = {"tenant": tenant, "supplier": supplier, "vendor": vendor_name,
                   "brand_id": brand_id, "actor": actor}
            # Contract terms are held on a saved flow (see checks.py). An unsaved
            # canvas has nowhere to hold them, so it reads the contract as-is.
            wanted = checks.referenced_terms(list(nodes.values())) if flow_id else set()
            terms = checks.load_terms(cur, flow_id) if wanted else {}
            terms_before = json.dumps(terms, sort_keys=True)
            term_notes: list[dict] = []

            for nid in order:
                node = nodes[nid]
                kind = node.get("kind")
                label = kind
                upstream = [p for p in incoming.get(nid, [])]

                if any(p in failed for p in upstream):
                    steps.append({"node": nid, "kind": kind, "status": "skipped",
                                  "detail": "something it depends on did not finish"})
                    failed.add(nid)
                    continue

                ins = {nodes[p]["kind"]: values[p] for p in upstream if p in values}
                started = _dt.datetime.now(_dt.timezone.utc)
                try:
                    if kind in ("contract", "ratecard", "document", "bills"):
                        val = _run_source(cur, ctx, node)
                        if kind == "contract" and wanted:
                            notes = checks.settle_terms(terms, val, wanted)
                            term_notes.extend(notes)
                            val["summary"] = (val.get("summary") or "") + _terms_summary(notes)
                    elif kind == "formula":
                        val = _run_formula(node, ins)
                        val = _writeback(ctx, val, produced)
                    elif kind == "llm":
                        val = _run_llm(node, ins)
                    elif kind == "mcp":
                        val = _run_mcp(node, ins)
                    elif kind == "report":
                        val = _run_report(ctx, node, ins, produced)
                    elif kind == "email":
                        val = _run_email(ctx, node, ins, produced)
                    elif kind == "notify":
                        val = {"type": "text", "text": _fill_tokens(
                            (node.get("config") or {}).get("text") or "", ctx, ins),
                            "summary": "notification raised"}
                    else:
                        raise RunError(f"{kind} is not something this can run")

                    values[nid] = val
                    steps.append({"node": nid, "kind": kind, "status": "ok",
                                  "detail": val.get("summary") or "",
                                  "ms": int((_dt.datetime.now(_dt.timezone.utc) - started).total_seconds() * 1000)})
                except RunError as e:
                    failed.add(nid)
                    steps.append({"node": nid, "kind": kind, "status": "failed", "detail": str(e)})
                except Exception as e:                       # noqa: BLE001 - reported, not swallowed
                    failed.add(nid)
                    log.exception("[playground] %s node blew up", kind)
                    steps.append({"node": nid, "kind": kind, "status": "failed",
                                  "detail": f"unexpected: {e}"})

            recon = None
            try:
                recon = checks.reconcile(cur, tenant, supplier, values, order, term_notes, produced)
            except Exception:                                # noqa: BLE001 - a check, not the run
                conn.rollback()
                log.exception("[playground] reconciling against the bill failed")
            # After the check, so its rollback cannot take the held terms with it.
            if wanted and json.dumps(terms, sort_keys=True) != terms_before:
                checks.save_terms(cur, flow_id, terms)

        conn.commit()
    finally:
        put_conn(conn)

    status = "failed" if failed and len(failed) == len(order) else ("partial" if failed else "ok")
    record = {"run_id": str(uuid.uuid4()), "status": status, "steps": steps, "outputs": produced,
              "checks": {"terms": term_notes, "recon": recon}}
    _save_run(tenant, supplier, flow_id, record, actor)
    return record


def _terms_summary(notes: list[dict]) -> str:
    """The contract step's line in the run panel, naming any term it held back."""
    changed = [n for n in notes if n["status"] == "changed"]
    if not changed:
        return ""
    return "; " + "; ".join(
        f"{n['field'].replace('_', ' ')}: used {n['value']} — {n['contract_file'] or 'the new contract'} "
        f"says {n['contract_value']}, decide in Review Hub" for n in changed)


# ── the output nodes ────────────────────────────────────────────────────────

def _fill_tokens(text: str, ctx: dict, ins: dict) -> str:
    out = (text or "").replace("{vendor}", ctx.get("vendor") or "")
    out = out.replace("{date}", _dt.date.today().strftime("%d-%b-%Y"))
    return out


def _writeback(ctx: dict, val: dict, produced: list[dict]) -> dict:
    """Save the calculated columns where the node was told to put them."""
    choice = (val.get("writeback") or "").lower()
    if not val.get("added") or "flow only" in choice or not choice:
        return val

    doc = val.get("doc") or {}
    src_name = doc.get("file_name") or "rate card.xlsx"
    data = outputs.build_spreadsheet(val["columns"], val["rows"], val.get("totals") or {},
                                     sheet_name="Data")

    if "in place" in choice:
        if not doc.get("doc_id"):
            raise RunError("there is no stored file to amend")
        _replace_doc(doc, data)
        produced.append({"kind": "spreadsheet", "doc_id": doc["doc_id"], "name": src_name,
                         "how": "amended in place"})
        val["summary"] = (val.get("summary") or "") + f"; amended {src_name}"
        return val

    tmpl = val.get("copy_name") or "{file} — calculated {date}"
    name = outputs.fill(tmpl, file=src_name, vendor=ctx.get("vendor") or "") + ".xlsx"
    doc_id = outputs.file_on_vendor(ctx["tenant"], ctx["supplier"], ctx.get("brand_id"),
                                    name, data, ctx.get("actor"), "Calculated")
    produced.append({"kind": "spreadsheet", "doc_id": doc_id, "name": name, "how": "saved as a copy"})
    val["summary"] = (val.get("summary") or "") + f"; saved {name}"
    return val


def _replace_doc(doc: dict, data: bytes) -> None:
    from ...core import object_store
    from ...core.vendor_doc_tables import store_tables_in_background
    object_store.replace(doc["file_path"], data,
                         "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("UPDATE vendor_documents SET file_size=%s, data_status='PENDING' WHERE id=%s",
                        (len(data), doc["doc_id"]))
        conn.commit()
    finally:
        put_conn(conn)


def _run_report(ctx: dict, node: dict, ins: dict, produced: list[dict]) -> dict:
    cfg = node.get("config") or {}
    title = _fill_tokens(cfg.get("title") or "Report", ctx, ins) or "Report"
    fmt = (cfg.get("format") or "PDF").lower()

    totals: dict[str, Any] = {}
    sections: list[tuple[str, str]] = []
    for name, v in ins.items():
        totals.update(v.get("totals") or {})
        sections.append((name.title(), as_text(v)))

    if fmt == "excel":
        table = next((v for v in ins.values() if v.get("type") == "table"), None)
        if table is None:
            raise RunError("an Excel report needs a table connected to it")
        data = outputs.build_spreadsheet(table.get("columns") or [], table.get("rows") or [], totals)
        ext, label = ".xlsx", "Report"
    elif fmt == "markdown":
        data, ext, label = outputs.build_markdown(title, sections, totals), ".md", "Report"
    else:
        try:
            data = outputs.build_pdf(title, sections, totals)
            ext = ".pdf"
        except Exception:
            # A missing PDF engine must not lose the report that was asked for.
            log.exception("[playground] PDF build failed — filing Markdown instead")
            data, ext = outputs.build_markdown(title, sections, totals), ".md"
        label = "Report"

    name = f"{title}{ext}"
    doc_id = outputs.file_on_vendor(ctx["tenant"], ctx["supplier"], ctx.get("brand_id"),
                                    name, data, ctx.get("actor"), label)
    produced.append({"kind": "report", "doc_id": doc_id, "name": name, "how": "filed on the vendor"})
    return {"type": "file", "doc_id": doc_id, "name": name, "bytes": data,
            "totals": totals, "summary": f"filed {name}"}


def _vendor_poc(tenant: str, supplier: str) -> list[tuple[str, str, str]]:
    """The vendor's point of contact, primary first.

    Same ordering as the payment receipt's own lookup
    (domain/payments/notify.py): primary flag, then oldest, and only contacts
    that actually have an address — so both paths mail the same person and a
    vendor's history reads consistently.
    """
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT id::text, name, email FROM supplier_contacts
                    WHERE tenant_id=%s AND supplier_id=%s
                      AND email IS NOT NULL AND btrim(email) <> ''
                    ORDER BY is_primary DESC, created_at ASC""",
                (tenant, supplier),
            )
            rows = [(r[0], r[1] or "", r[2].strip()) for r in cur.fetchall()]
        conn.commit()
        return rows
    finally:
        put_conn(conn)


def _run_email(ctx: dict, node: dict, ins: dict, produced: list[dict]) -> dict:
    cfg = node.get("config") or {}
    to = (cfg.get("to") or "").strip()
    poc_name = ""
    contact_id = None
    if not to:
        # Left blank, the mail goes to the vendor's configured contact. That is
        # the common case — a report about this vendor, sent to this vendor —
        # and typing the address into the node would quietly go stale the day
        # the POC changes on the record.
        poc = _vendor_poc(ctx["tenant"], ctx["supplier"])
        if not poc:
            raise RunError("no recipient, and this vendor has no contact with an email address")
        contact_id, poc_name, to = poc[0]
    else:
        # An address typed into the node is still usually one of this vendor's
        # contacts. Matching it back to that contact is what lets the mail go
        # out through the connected mailbox — without this, filling in "To"
        # silently downgraded the send to the system SMTP account.
        first = to.replace(";", ",").split(",")[0].strip().lower()
        for cid, nm, em in _vendor_poc(ctx["tenant"], ctx["supplier"]):
            if em.lower() == first:
                contact_id, poc_name = cid, nm
                break
    subject = _fill_tokens(cfg.get("subject") or "", ctx, ins) or "Report"
    body = _fill_tokens(cfg.get("body") or "", ctx, ins)
    if not body:
        # A covering note nobody wrote still has to read like one, and the
        # report itself is attached, so this stays short rather than tipping
        # the whole table into the message.
        greeting = f"Hi {poc_name.split()[0]}," if poc_name else "Hi,"
        made = [v["name"] for v in ins.values() if v.get("type") == "file" and v.get("name")]
        sep = chr(10) + chr(10)
        body = (greeting + sep + "Please find attached " + ", ".join(made) + "."
                if made else
                greeting + sep + sep.join(f"{k.title()}:" + chr(10) + as_text(v, 2000)
                                          for k, v in ins.items()))

    # Whatever a Report node upstream produced travels with the mail. The media
    # type comes from the name so a .xlsx opens as a workbook rather than
    # arriving as an unnamed blob.
    attachments: list[tuple[str, bytes, str]] = []
    for v in ins.values():
        if v.get("type") == "file" and v.get("bytes"):
            guessed = mimetypes.guess_type(v["name"])[0] or "application/octet-stream"
            attachments.append((v["name"], v["bytes"], guessed))

    # Prefer the caller's own connected mailbox over the system SMTP account.
    # OAuth refresh tokens renew themselves; an app password dies silently the
    # day it is regenerated, which is exactly how the SMTP path broke on
    # 6 November and went unnoticed until something tried to send.
    sent, detail, via = 0, [], "smtp"
    sender = outputs.sender_for(ctx.get("actor")) if contact_id else None
    if sender:
        try:
            outputs.send_as_user(ctx["tenant"], ctx["supplier"], contact_id,
                                 sender, subject, body, attachments)
            sent, via = 1, "connected mailbox"
        except Exception as e:                               # noqa: BLE001
            detail.append(f"connected mailbox: {e}")

    if not sent:
        for one in [a.strip() for a in to.replace(";", ",").split(",") if a.strip()]:
            res = outputs.send_email(ctx["tenant"], ctx["supplier"], one, subject, body,
                                     attachments, ctx.get("actor"))
            if (res or {}).get("status") == "sent":
                sent += 1
            else:
                detail.append(f"{one}: {(res or {}).get('error') or 'not sent'}")
    if not sent:
        raise RunError("; ".join(detail) or "the mail could not be sent")
    who = f"{poc_name} <{to}>" if poc_name else to
    produced.append({"kind": "email", "name": subject,
                     "how": f"sent to {who} via {via}"
                            + (f" with {len(attachments)} attachment(s)" if attachments else "")})
    return {"type": "text", "text": body, "summary": f"emailed {sent} recipient(s)"}


def _run_llm(node: dict, ins: dict) -> dict:
    from ...config import OPENAI_API_KEY
    cfg = node.get("config") or {}
    prompt = (cfg.get("prompt") or "").strip()
    if not prompt:
        raise RunError("no instruction")
    if not OPENAI_API_KEY:
        raise RunError("no OpenAI key is configured on this server")

    context = "\n\n".join(f"### {k}\n{as_text(v)}" for k, v in ins.items()) or "(nothing connected)"
    import httpx
    r = httpx.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
        json={"model": cfg.get("model") or "gpt-4o-mini", "temperature": 0,
              "messages": [
                  {"role": "system", "content": "You are given a vendor's data. Answer only from it."},
                  {"role": "user", "content": f"{prompt}\n\n{context}"}]},
        timeout=120,
    )
    if r.status_code >= 300:
        raise RunError(f"the model refused the request ({r.status_code})")
    text = (r.json().get("choices") or [{}])[0].get("message", {}).get("content", "")
    return {"type": "text", "text": text, "summary": f"{len(text)} characters"}


def _run_mcp(node: dict, ins: dict) -> dict:
    cfg = node.get("config") or {}
    url = (cfg.get("url") or "").strip()
    if not url:
        raise RunError("no server URL")
    if not url.lower().startswith("https://"):
        # The payload carries this vendor's data off this system.
        raise RunError("an MCP server must be https")
    import httpx
    headers = {"Content-Type": "application/json"}
    if (cfg.get("auth") or "").strip():
        headers["Authorization"] = cfg["auth"].strip()
    payload = {"tool": cfg.get("tool") or None,
               "input": {k: as_text(v, 2000) for k, v in ins.items()}}
    r = httpx.post(url, headers=headers, json=payload, timeout=60)
    if r.status_code >= 300:
        raise RunError(f"the server answered {r.status_code}")
    try:
        text = json.dumps(r.json(), indent=2)[:8000]
    except Exception:
        text = r.text[:8000]
    return {"type": "text", "text": text, "summary": f"{len(text)} characters"}


# ── the record ──────────────────────────────────────────────────────────────

def _save_run(tenant: str, supplier: str, flow_id: str | None, rec: dict, actor: str | None) -> None:
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO vendor_flow_runs
                       (run_id, flow_id, tenant_id, supplier_id, status, steps, outputs, run_by,
                        checks, invoice_id, finished_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s, now())""",
                (rec["run_id"], flow_id, tenant, supplier, rec["status"],
                 json.dumps(rec["steps"]),
                 json.dumps([{k: v for k, v in o.items() if k != "bytes"} for o in rec["outputs"]]),
                 actor, json.dumps(rec.get("checks") or {}),
                 ((rec.get("checks") or {}).get("recon") or {}).get("invoice_id")),
            )
            # A held-back term or a sheet that disagrees with the bill belongs in
            # Review Hub now, not on the adapters' next safety poll.
            cur.execute("SELECT pg_notify('ch_review_adapters', '')")
        conn.commit()
    except Exception:
        conn.rollback()
        log.exception("[playground] could not record the run")
    finally:
        put_conn(conn)
