"""
Build a one-file PDF attendance sheet for a Pay-out / General Orientation
announcement: branded header with the SK logo, event details, and a
table of every joiner — name, joined-on, and their captured signature.
"""
from __future__ import annotations

import base64
import io
import os
from datetime import datetime, timedelta, timezone
from typing import Iterable

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image,
)


PH_TZ = timezone(timedelta(hours=8))

PAGE_SIZE = landscape(letter)
PAGE_W, PAGE_H = PAGE_SIZE
LEFT_MARGIN  = 0.6 * inch
RIGHT_MARGIN = 0.6 * inch
TOP_MARGIN   = 0.6 * inch
BOT_MARGIN   = 0.6 * inch

BARANGAY_LINE = "Sangguniang Kabataan ng Barangay Bukal, Majayjay, Laguna"
ORG_TAGLINE   = "Aktibong Kabataan, Maunlad na Pamayanan"

# Resolve the logo from the static folder so we can embed it in the PDF.
_LOGO_FILENAME = "411138383_122115055322131251_5783589540994116709_n.jpg"


def _logo_path() -> str | None:
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    candidate = os.path.join(here, "static", "images", _LOGO_FILENAME)
    return candidate if os.path.exists(candidate) else None


def _format_ph(value, fmt: str = "%Y-%m-%d %H:%M") -> str:
    if not value:
        return ""
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(PH_TZ).strftime(fmt)


def _decode_signature(value: str) -> bytes | None:
    """Pull the raw image bytes out of a data URL."""
    if not value or not isinstance(value, str):
        return None
    marker = ";base64,"
    idx = value.find(marker)
    if idx < 0:
        return None
    try:
        return base64.b64decode(value[idx + len(marker):], validate=True)
    except Exception:
        return None


def _draw_header(canv: canvas.Canvas, doc):
    """Branded header drawn on every page."""
    canv.saveState()

    logo = _logo_path()
    y_top = PAGE_H - TOP_MARGIN

    if logo:
        try:
            img = ImageReader(logo)
            iw, ih = img.getSize()
            target_h = 0.9 * inch
            ratio = target_h / ih
            target_w = iw * ratio
            canv.drawImage(
                img, LEFT_MARGIN, y_top - target_h,
                width=target_w, height=target_h,
                preserveAspectRatio=True, mask="auto",
            )
            text_x = LEFT_MARGIN + target_w + 0.18 * inch
        except Exception:
            text_x = LEFT_MARGIN
    else:
        text_x = LEFT_MARGIN

    canv.setFont("Helvetica-Bold", 13)
    canv.setFillColor(colors.HexColor("#283b25"))
    canv.drawString(text_x, y_top - 14, "Republic of the Philippines")
    canv.setFont("Helvetica-Bold", 15)
    canv.drawString(text_x, y_top - 32, BARANGAY_LINE)
    canv.setFont("Helvetica-Oblique", 10)
    canv.setFillColor(colors.HexColor("#5a8550"))
    canv.drawString(text_x, y_top - 48, ORG_TAGLINE)

    # Underline rule
    canv.setStrokeColor(colors.HexColor("#84b179"))
    canv.setLineWidth(1.2)
    canv.line(LEFT_MARGIN, y_top - 56,
              PAGE_W - RIGHT_MARGIN, y_top - 56)

    # Footer page number
    canv.setFont("Helvetica", 9)
    canv.setFillColor(colors.HexColor("#64748b"))
    canv.drawRightString(
        PAGE_W - RIGHT_MARGIN, BOT_MARGIN - 0.2 * inch,
        f"Page {canv.getPageNumber()}",
    )
    canv.drawString(
        LEFT_MARGIN, BOT_MARGIN - 0.2 * inch,
        f"Generated: {_format_ph(datetime.now(timezone.utc))}",
    )

    canv.restoreState()


def _build_signature_image(sig_bytes: bytes | None, max_w: float, max_h: float) -> Image | str:
    """Return a Platypus Image (or '—' string) sized for the table cell."""
    if not sig_bytes:
        return "—"
    try:
        ir = ImageReader(io.BytesIO(sig_bytes))
        iw, ih = ir.getSize()
        if iw <= 0 or ih <= 0:
            return "—"
        ratio = min(max_w / iw, max_h / ih)
        return Image(
            io.BytesIO(sig_bytes),
            width=iw * ratio,
            height=ih * ratio,
        )
    except Exception:
        return "—"


def build_joiner_sheet(
    *,
    event_title: str,
    event_kind: str,
    event_start: str | None,
    event_end:   str | None,
    joins: Iterable[dict],
) -> bytes:
    """
    Render the attendance sheet PDF.

    ``joins`` is an iterable of dicts containing:
        student.full_name (or 'name' fallback), joined_at, signed_at,
        signature_data (base64 data URL).
    """
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=PAGE_SIZE,
        leftMargin=LEFT_MARGIN,
        rightMargin=RIGHT_MARGIN,
        topMargin=TOP_MARGIN + 0.9 * inch,   # leave room for the header
        bottomMargin=BOT_MARGIN + 0.4 * inch,
        title=f"{event_title} — Attendance",
    )

    styles = getSampleStyleSheet()
    h1 = ParagraphStyle(
        "H1", parent=styles["Heading1"],
        fontSize=18, leading=22,
        textColor=colors.HexColor("#283b25"),
        spaceAfter=2,
    )
    sub = ParagraphStyle(
        "Sub", parent=styles["BodyText"],
        fontSize=10, leading=14,
        textColor=colors.HexColor("#475569"),
    )
    cell = ParagraphStyle(
        "Cell", parent=styles["BodyText"],
        fontSize=10, leading=13,
        textColor=colors.HexColor("#0f172a"),
    )

    story: list = []

    title_label = "Pay-Out" if event_kind.lower() == "payout" else "General Orientation"
    story.append(Paragraph(f"{title_label} Attendance Sheet", h1))
    story.append(Paragraph(event_title or "—", sub))
    schedule = ""
    if event_start and event_end:
        schedule = f"Schedule: {_format_ph(event_start)} → {_format_ph(event_end)}"
    elif event_start:
        schedule = f"Schedule: {_format_ph(event_start)}"
    if schedule:
        story.append(Paragraph(schedule, sub))
    story.append(Spacer(1, 0.18 * inch))

    # Build the table.
    rows = [["#", "Name", "Date of join", "Signature"]]
    join_list = list(joins)

    avail_w = PAGE_W - LEFT_MARGIN - RIGHT_MARGIN
    col_widths = [
        0.5 * inch,                   # row number
        2.6 * inch,                   # name
        1.7 * inch,                   # joined_at
        avail_w - (0.5 + 2.6 + 1.7) * inch,  # signature fills the rest
    ]
    sig_max_w = col_widths[3] - 8
    sig_max_h = 0.7 * inch

    for idx, j in enumerate(join_list, start=1):
        student = j.get("student") or {}
        name    = student.get("full_name") or j.get("name") or "—"
        joined  = _format_ph(j.get("signed_at") or j.get("joined_at"))
        sig     = _build_signature_image(
            _decode_signature(j.get("signature_data")),
            sig_max_w, sig_max_h,
        )
        rows.append([
            Paragraph(str(idx), cell),
            Paragraph(name, cell),
            Paragraph(joined or "—", cell),
            sig,
        ])

    if len(rows) == 1:
        rows.append([Paragraph("Wala pang sumali sa event na ito.", cell), "", "", ""])
        rowspan_style = [("SPAN", (0, 1), (3, 1))]
    else:
        rowspan_style = []

    table = Table(rows, colWidths=col_widths, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#476a40")),
        ("TEXTCOLOR",  (0, 0), (-1, 0), colors.white),
        ("FONTNAME",   (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",   (0, 0), (-1, 0), 10),
        ("ALIGN",      (0, 0), (-1, 0), "LEFT"),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
        ("TOPPADDING",    (0, 0), (-1, 0), 6),

        ("FONTNAME",   (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE",   (0, 1), (-1, -1), 10),
        ("VALIGN",     (0, 1), (-1, -1), "MIDDLE"),
        ("ALIGN",      (3, 1), (3, -1), "CENTER"),
        ("ALIGN",      (0, 1), (0, -1), "CENTER"),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 8),
        ("TOPPADDING",    (0, 1), (-1, -1), 8),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1),
            [colors.white, colors.HexColor("#f8fafc")]),
        ("LINEBELOW",  (0, 0), (-1, -1), 0.4, colors.HexColor("#cbd5e1")),
        ("BOX",        (0, 0), (-1, -1), 0.6, colors.HexColor("#cbd5e1")),
    ] + rowspan_style))

    story.append(table)

    doc.build(story, onFirstPage=_draw_header, onLaterPages=_draw_header)

    return buf.getvalue()
