"""
Render a single Certificate of Attendance as a PDF, sized A4 landscape.

The visual layout mirrors ``templates/admin/certificate_template.html``
so the file the student receives in their inbox feels like the same
document the admin sees in the browser preview.

Implemented with ReportLab (already in requirements). One PDF per call;
the admin route loops to fan-out emails, attaching one PDF each.
"""
from __future__ import annotations

import io
import os
from typing import Mapping

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas


PAGE_SIZE = landscape(A4)
PAGE_W, PAGE_H = PAGE_SIZE  # ~842 x 595 pt

# Brand palette mirroring the HTML template.
GOLD        = colors.HexColor("#b08642")
GOLD_LIGHT  = colors.HexColor("#d8b46d")
PAPER       = colors.HexColor("#fdfaf1")
INK         = colors.HexColor("#2b2b2b")
INK_MUTED   = colors.HexColor("#4a4a4a")

_LOGO_FILENAME = "411138383_122115055322131251_5783589540994116709_n.jpg"


def _logo_path() -> str | None:
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    candidate = os.path.join(here, "static", "images", _LOGO_FILENAME)
    return candidate if os.path.exists(candidate) else None


def _wrap_lines(text: str, font: str, size: int, max_w: float, c: canvas.Canvas) -> list[str]:
    """Greedy word-wrap helper sized in points."""
    words = (text or "").split()
    lines: list[str] = []
    cur = ""
    for w in words:
        candidate = f"{cur} {w}".strip()
        if c.stringWidth(candidate, font, size) <= max_w:
            cur = candidate
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def build_certificate_pdf(ctx: Mapping[str, str]) -> bytes:
    """
    Render one certificate to a PDF byte string.

    ``ctx`` mirrors the template context used by ``certificate_template.html``:
    participant_name, home_purok, event_kind, event_title, event_venue,
    event_theme, event_date, sk_chairperson, title_text, barangay, city,
    province.
    """
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=PAGE_SIZE)

    # --- background ---
    c.setFillColor(PAPER)
    c.rect(0, 0, PAGE_W, PAGE_H, stroke=0, fill=1)

    # --- decorative double border ---
    inset = 16
    c.setStrokeColor(GOLD)
    c.setLineWidth(2.4)
    c.rect(inset, inset, PAGE_W - inset * 2, PAGE_H - inset * 2, stroke=1, fill=0)
    c.setLineWidth(0.7)
    c.rect(inset + 6, inset + 6,
           PAGE_W - (inset + 6) * 2, PAGE_H - (inset + 6) * 2,
           stroke=1, fill=0)
    inset_inner = 28
    c.setStrokeColor(GOLD_LIGHT)
    c.setLineWidth(0.5)
    c.rect(inset_inner, inset_inner,
           PAGE_W - inset_inner * 2, PAGE_H - inset_inner * 2,
           stroke=1, fill=0)

    # --- watermark dots ---
    c.saveState()
    try:
        c.setFillColor(GOLD)
        c.setFillAlpha(0.08)
    except Exception:
        c.setFillColor(GOLD)
    for fx, fy in ((0.12, 0.78), (0.88, 0.78), (0.12, 0.28), (0.88, 0.28)):
        c.circle(PAGE_W * fx, PAGE_H * fy, 18, stroke=0, fill=1)
    c.restoreState()

    # --- header (logo + org name) ---
    header_top_y = PAGE_H - 60
    logo = _logo_path()
    if logo:
        try:
            img = ImageReader(logo)
            iw, ih = img.getSize()
            target_h = 56
            ratio = target_h / ih
            target_w = iw * ratio
            c.drawImage(
                img, 70, header_top_y - target_h + 6,
                width=target_w, height=target_h,
                preserveAspectRatio=True, mask="auto",
            )
        except Exception:
            pass

    c.setFillColor(INK)
    c.setFont("Helvetica-Bold", 18)
    c.drawCentredString(PAGE_W / 2, header_top_y - 14, "SANGGUNIANG KABATAAN")
    c.setFillColor(INK_MUTED)
    c.setFont("Helvetica", 10)
    barangay = ctx.get("barangay") or "Bukal"
    city     = ctx.get("city") or "Majayjay"
    province = ctx.get("province") or "Laguna"
    c.drawCentredString(PAGE_W / 2, header_top_y - 30,
                        f"Barangay {barangay}, {city}, {province}")

    # --- title ---
    title_text = (ctx.get("title_text") or "CERTIFICATE OF ATTENDANCE").upper()
    c.setFillColor(INK)
    c.setFont("Helvetica-Bold", 30)
    c.drawCentredString(PAGE_W / 2, header_top_y - 78, title_text)

    # --- "This is to certify that" ---
    body_top = header_top_y - 116
    c.setFillColor(INK_MUTED)
    c.setFont("Helvetica-Oblique", 12)
    c.drawCentredString(PAGE_W / 2, body_top, "This is to certify that")

    # --- participant name with underline ---
    name = ctx.get("participant_name") or "—"
    c.setFillColor(INK)
    c.setFont("Helvetica-BoldOblique", 26)
    name_y = body_top - 30
    c.drawCentredString(PAGE_W / 2, name_y, name)

    name_w = c.stringWidth(name, "Helvetica-BoldOblique", 26)
    line_w = max(name_w + 80, PAGE_W * 0.55)
    line_x1 = (PAGE_W - line_w) / 2
    line_x2 = line_x1 + line_w
    c.setStrokeColor(INK)
    c.setLineWidth(1.0)
    c.line(line_x1, name_y - 6, line_x2, name_y - 6)

    # --- "of <home>" ---
    home_purok = ctx.get("home_purok") or ""
    if home_purok:
        c.setFillColor(INK_MUTED)
        c.setFont("Helvetica", 12)
        c.drawCentredString(PAGE_W / 2, name_y - 22, f"of {home_purok}")

    # --- narrative paragraph ---
    event_kind  = ctx.get("event_kind") or ctx.get("event_title") or "Event"
    event_venue = ctx.get("event_venue") or ""
    event_theme = ctx.get("event_theme") or ""
    event_date  = ctx.get("event_date") or ""

    parts = [f"has actively attended and participated in the {event_kind}"]
    if event_venue:
        parts.append(f" at {event_venue}")
    if event_theme:
        parts.append(f", with the theme: \u201c{event_theme}\u201d")
    parts.append(".")
    narrative = "".join(parts)

    narrative_y = name_y - 56
    text_max_w = PAGE_W - 220
    c.setFillColor(INK)
    c.setFont("Helvetica", 13)
    lines = _wrap_lines(narrative, "Helvetica", 13, text_max_w, c)
    for i, line in enumerate(lines):
        c.drawCentredString(PAGE_W / 2, narrative_y - i * 16, line)

    if event_date:
        date_y = narrative_y - len(lines) * 16 - 14
        c.setFont("Helvetica", 13)
        c.drawCentredString(PAGE_W / 2, date_y, f"Held on {event_date}.")

    # --- signature block (single SK Chairperson per current template) ---
    sig_y = 150
    chair = ctx.get("sk_chairperson") or ""
    sig_line_w = 220
    sig_x1 = (PAGE_W - sig_line_w) / 2
    sig_x2 = sig_x1 + sig_line_w
    c.setStrokeColor(INK)
    c.setLineWidth(1.0)
    c.line(sig_x1, sig_y, sig_x2, sig_y)
    c.setFillColor(INK)
    c.setFont("Helvetica-Bold", 12)
    c.drawCentredString(PAGE_W / 2, sig_y - 14, chair)
    c.setFillColor(INK_MUTED)
    c.setFont("Helvetica", 10)
    c.drawCentredString(PAGE_W / 2, sig_y - 28, "SK Chairperson")

    # --- ribbon footer ---
    ribbon_h = 28
    ribbon_y = 60
    c.setFillColor(GOLD)
    c.rect(40, ribbon_y, PAGE_W - 80, ribbon_h, stroke=0, fill=1)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 13)
    c.drawCentredString(PAGE_W / 2, ribbon_y + 16, "KATIPUNAN NG KABATAAN")
    c.setFont("Helvetica", 8)
    c.drawCentredString(PAGE_W / 2, ribbon_y + 5,
                        "AKTIBONG KABATAAN, MAUNLAD NA PAMAYANAN")

    c.showPage()
    c.save()
    return buf.getvalue()
