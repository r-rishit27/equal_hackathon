"""What a flow leaves behind: a filed document, an email, a notification.

Everything written here goes through the same `store_vendor_document` the
upload dialog uses, so a generated report lands in the vendor's Documents like
any other file — same storage, same brand stamping, same listing — rather than
in a parallel place that only this feature knows about.
"""
from __future__ import annotations

import datetime as _dt
import io
import json
import logging
from typing import Any

log = logging.getLogger(__name__)


def _fmt(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, float):
        return f"{v:,.2f}" if v % 1 else f"{v:,.0f}"
    return str(v)


def fill(template: str, *, file: str = "", vendor: str = "") -> str:
    today = _dt.date.today().strftime("%d-%b-%Y")
    stem = file.rsplit(".", 1)[0] if "." in file else file
    return (template or "").replace("{file}", stem).replace("{date}", today).replace("{vendor}", vendor)


# ── the amended / copied spreadsheet ────────────────────────────────────────

def build_spreadsheet(columns: list[str], rows: list[dict], totals: dict,
                      sheet_name: str = "Data") -> bytes:
    """The source rows with the calculated columns appended, plus a Totals
    sheet when there are any.

    Totals go on their own sheet rather than under the data: a column of
    numbers with a total glued to the bottom stops being a table — it no
    longer filters, sorts or reads back cleanly into this system.
    """
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    wb = Workbook()
    ws = wb.active
    ws.title = (sheet_name or "Data")[:31]

    head_fill = PatternFill("solid", fgColor="FF1F6E78")
    head_font = Font(bold=True, color="FFFFFFFF")

    ws.append([str(c) for c in columns])
    for cell in ws[1]:
        cell.fill = head_fill
        cell.font = head_font
        cell.alignment = Alignment(vertical="center")
    ws.freeze_panes = "A2"

    for r in rows:
        ws.append([r.get(c) for c in columns])

    for i, c in enumerate(columns, start=1):
        width = max(len(str(c)) + 2, *(len(_fmt(r.get(c))) + 2 for r in rows[:200])) if rows else len(str(c)) + 2
        ws.column_dimensions[ws.cell(1, i).column_letter].width = min(40, max(10, width))

    if totals:
        tw = wb.create_sheet("Totals")
        tw.append(["Measure", "Value"])
        for cell in tw[1]:
            cell.fill = head_fill
            cell.font = head_font
        for k, v in totals.items():
            tw.append([k, v])
        tw.column_dimensions["A"].width = 32
        tw.column_dimensions["B"].width = 20

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def build_markdown(title: str, sections: list[tuple[str, str]], totals: dict) -> bytes:
    out = [f"# {title}", "", f"*Generated {_dt.date.today().strftime('%d %b %Y')}*", ""]
    if totals:
        out += ["## Totals", "", "| Measure | Value |", "| --- | ---: |"]
        out += [f"| {k} | {_fmt(v)} |" for k, v in totals.items()]
        out.append("")
    for heading, body in sections:
        out += [f"## {heading}", "", body, ""]
    return "\n".join(out).encode("utf-8")


def build_pdf(title: str, sections: list[tuple[str, str]], totals: dict) -> bytes:
    """A plain text-flow PDF via the same engine the payment receipt uses, when
    it is available; otherwise the caller falls back to Markdown rather than
    failing the whole run over a file format."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    from reportlab.lib import colors

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, title=title)
    st = getSampleStyleSheet()
    story: list[Any] = [Paragraph(title, st["Title"]),
                        Paragraph(_dt.date.today().strftime("%d %b %Y"), st["Normal"]),
                        Spacer(1, 14)]
    if totals:
        data = [["Measure", "Value"]] + [[k, _fmt(v)] for k, v in totals.items()]
        t = Table(data, hAlign="LEFT")
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F6E78")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#9FC8D6")),
            ("ALIGN", (1, 1), (1, -1), "RIGHT"),
        ]))
        story += [t, Spacer(1, 14)]
    for heading, body in sections:
        story.append(Paragraph(heading, st["Heading2"]))
        for line in (body or "").split("\n"):
            story.append(Paragraph(line.replace("&", "&amp;").replace("<", "&lt;"), st["BodyText"]))
        story.append(Spacer(1, 10))
    doc.build(story)
    return buf.getvalue()


# ── filing it on the vendor ─────────────────────────────────────────────────

def file_on_vendor(tenant: str, supplier: str, brand_id: str | None, file_name: str,
                   contents: bytes, actor: str | None, doc_label: str) -> str:
    """Store a generated file as a vendor document and return its id."""
    from ...routers.vendor_documents import store_vendor_document
    return store_vendor_document(
        tenant=tenant, supplier_id=supplier, brand_id=brand_id, file_name=file_name,
        contents=contents, uploaded_by=actor, doc_type="other", doc_label=doc_label,
    )


def send_email(tenant: str, supplier: str, to: str, subject: str, body: str,
               attachments: list[tuple[str, bytes, str]], actor: str | None) -> dict:
    """Send through the system mailbox, logged to vendor_outreach_log like any
    other vendor mail so the vendor's history stays complete."""
    from ...config import get_conn, put_conn
    from ..payments.notify import _send_via_smtp

    conn = get_conn()
    try:
        with conn.cursor() as cur:
            html = "<pre style='font:13px/1.5 ui-monospace,monospace'>" + \
                   (body or "").replace("&", "&amp;").replace("<", "&lt;") + "</pre>"
            return _send_via_smtp(cur, conn, tenant_id=tenant, supplier_id=supplier,
                                  to_email=to, subject=subject, text=body or "", html=html,
                                  attachments=attachments, actor_username=actor)
    except Exception as e:
        # _send_via_smtp raises on a rejected send. Reported rather than
        # propagated, so a failure here reads as "SMTP could not send" beside
        # whatever the connected-mailbox attempt said, instead of replacing it.
        log.warning("[playground] SMTP send failed: %s", e)
        return {"status": "failed", "error": str(e)}
    finally:
        put_conn(conn)


def sender_for(username: str | None) -> str | None:
    """Which connected mailbox should send, or None to fall back to SMTP.

    The admin address wins when it is connected, so vendor-facing mail carries
    one identity however many people run flows; the person running it is used
    only when admin has no mailbox of its own. Both beat the SMTP account,
    because an OAuth connection refreshes itself while an app password dies
    silently the day it is regenerated.
    """
    from ...config import SMTP_ADMIN_EMAIL, get_conn, put_conn
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT username, email FROM user_email_connections
                    WHERE status='active' AND COALESCE(scopes,'') ILIKE '%%gmail.send%%'""",
            )
            rows = [(r[0], (r[1] or "").lower()) for r in cur.fetchall()]
        conn.commit()
    except Exception:
        log.exception("[playground] looking up a connected mailbox failed")
        return None
    finally:
        put_conn(conn)

    admin = (SMTP_ADMIN_EMAIL or "").strip().lower()
    if admin:
        for user, email in rows:
            if email == admin:
                return user
    for user, _ in rows:
        if username and user == username:
            return user
    return None


def can_send_as(username: str | None) -> bool:
    """Kept for callers that only need a yes/no."""
    return sender_for(username) is not None


def send_as_user(tenant: str, supplier: str, contact_id: str, username: str | None,
                 subject: str, body: str, attachments: list[tuple[str, bytes, str]]) -> dict:
    """Send from the caller's own connected mailbox to a vendor contact.

    Routed through the same helper the vendor card's Email button uses, so the
    mail threads, logs to vendor_outreach_log and reaches the fact graph
    exactly as a hand-written one does — rather than arriving from the system
    address with no history attached to it.
    """
    import psycopg2.extras
    from ...config import get_conn, put_conn
    from ...routers.email_connection import send_vendor_contact_email

    conn = get_conn()
    try:
        # A dict cursor, because that helper reads its rows by column name.
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            return send_vendor_contact_email(
                cur, conn, tenant_id=tenant, supplier_id=supplier, contact_id=contact_id,
                username=username or "", subject=subject, message=body,
                attachments=attachments or None,
            )
    finally:
        put_conn(conn)
