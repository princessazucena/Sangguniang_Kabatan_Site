"""
Build a single PDF that contains every uploaded document for an
application: PDFs are appended page-by-page, and image files (e.g.
school IDs) are placed on a generated PDF page.
"""
import io
from typing import Iterable

from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas
from pypdf import PdfWriter, PdfReader


PAGE_W, PAGE_H = letter
MARGIN = 0.5 * inch


def _image_to_pdf(image_bytes: bytes, label: str, student_name: str) -> bytes:
    """
    Create a single-page PDF showing the given image fitted within
    the printable area, with a small caption above it.
    """
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)

    # Header
    c.setFont("Helvetica-Bold", 14)
    c.drawString(MARGIN, PAGE_H - MARGIN - 4, label)
    c.setFont("Helvetica", 10)
    if student_name:
        c.drawString(MARGIN, PAGE_H - MARGIN - 22, student_name)
    c.line(MARGIN, PAGE_H - MARGIN - 30, PAGE_W - MARGIN, PAGE_H - MARGIN - 30)

    # Image area below the header
    top = PAGE_H - MARGIN - 40
    bottom = MARGIN
    avail_w = PAGE_W - 2 * MARGIN
    avail_h = top - bottom

    try:
        img = ImageReader(io.BytesIO(image_bytes))
        iw, ih = img.getSize()
        ratio = min(avail_w / iw, avail_h / ih)
        draw_w = iw * ratio
        draw_h = ih * ratio
        x = MARGIN + (avail_w - draw_w) / 2
        y = bottom + (avail_h - draw_h) / 2
        c.drawImage(img, x, y, width=draw_w, height=draw_h,
                    preserveAspectRatio=True, mask="auto")
    except Exception as exc:
        c.setFont("Helvetica", 11)
        c.drawString(MARGIN, top - 30, f"[Image could not be rendered: {exc}]")

    c.showPage()
    c.save()
    return buf.getvalue()


def _cover_page(student_name: str, level_label: str, year_label: str,
                slot_labels: list[str]) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)

    c.setFont("Helvetica-Bold", 18)
    c.drawString(MARGIN, PAGE_H - MARGIN, "Scholarship Application Packet")

    c.setFont("Helvetica", 12)
    y = PAGE_H - MARGIN - 30
    c.drawString(MARGIN, y, f"Applicant: {student_name or '—'}")
    y -= 18
    c.drawString(MARGIN, y, f"Level: {level_label or '—'}    Year: {year_label or '—'}")
    y -= 30

    c.setFont("Helvetica-Bold", 12)
    c.drawString(MARGIN, y, "Documents in this packet:")
    y -= 20
    c.setFont("Helvetica", 11)
    for label in slot_labels:
        c.drawString(MARGIN + 12, y, f"• {label}")
        y -= 16
        if y < MARGIN + 40:
            break

    c.showPage()
    c.save()
    return buf.getvalue()


def build_packet(
    student_name: str,
    level_label: str,
    year_label: str,
    documents: Iterable[dict],
) -> bytes:
    """
    documents: iterable of dicts with keys:
        label   - human readable name (e.g. "Report Card")
        kind    - "pdf" or "image"
        bytes   - file content
    """
    docs = list(documents)
    writer = PdfWriter()

    # Cover page
    cover = _cover_page(
        student_name, level_label, year_label,
        [d["label"] for d in docs],
    )
    for page in PdfReader(io.BytesIO(cover)).pages:
        writer.add_page(page)

    # Each document
    for doc in docs:
        label = doc["label"]
        kind  = doc["kind"]
        data  = doc["bytes"]
        if not data:
            continue
        try:
            if kind == "pdf":
                reader = PdfReader(io.BytesIO(data))
                for page in reader.pages:
                    writer.add_page(page)
            else:
                pdf_bytes = _image_to_pdf(data, label, student_name)
                for page in PdfReader(io.BytesIO(pdf_bytes)).pages:
                    writer.add_page(page)
        except Exception as exc:
            # Failure page so the admin still sees something useful.
            buf = io.BytesIO()
            c = canvas.Canvas(buf, pagesize=letter)
            c.setFont("Helvetica-Bold", 14)
            c.drawString(MARGIN, PAGE_H - MARGIN, label)
            c.setFont("Helvetica", 11)
            c.drawString(MARGIN, PAGE_H - MARGIN - 20,
                         f"[This file could not be embedded: {exc}]")
            c.showPage()
            c.save()
            for page in PdfReader(io.BytesIO(buf.getvalue())).pages:
                writer.add_page(page)

    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()
