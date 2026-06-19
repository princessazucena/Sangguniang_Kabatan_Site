"""
Transactional email sender (Brevo / Sendinblue).

Uses the Brevo HTTP API directly so we don't need to add another SDK.
Configuration comes from .env:

    BREVO_API_KEY        — required
    BREVO_SENDER_EMAIL   — required (must be a verified sender on Brevo)
    BREVO_SENDER_NAME    — optional, defaults to a generic label
"""
import base64
import os
import logging
from typing import Iterable, Mapping, Optional

import requests

BREVO_ENDPOINT = "https://api.brevo.com/v3/smtp/email"

log = logging.getLogger(__name__)


def send_email(
    to_email: str,
    to_name: str,
    subject: str,
    html_content: str,
    text_content: Optional[str] = None,
    attachments: Optional[Iterable[Mapping[str, object]]] = None,
) -> bool:
    """
    Fire-and-forget transactional email. Returns True on a 2xx response.
    Errors are logged but never raised — admin actions should not fail
    just because the mail provider hiccuped.

    ``attachments`` is an optional iterable of mappings shaped like
    ``{"name": "file.pdf", "content": <bytes>}``. The bytes are
    base64-encoded for Brevo's ``attachment`` array.
    """
    api_key      = os.environ.get("BREVO_API_KEY")
    sender_email = os.environ.get("BREVO_SENDER_EMAIL")
    sender_name  = (os.environ.get("BREVO_SENDER_NAME")
                    or "Scholarship Portal").strip()
    if not api_key or not sender_email or not to_email:
        log.warning("send_email skipped — missing Brevo config or recipient")
        return False

    log.info(f"Sending email: FROM '{sender_name} <{sender_email}>' TO '{to_name} <{to_email}>' SUBJECT '{subject}'")

    payload = {
        "sender":      {"email": sender_email, "name": sender_name},
        "to":          [{"email": to_email, "name": to_name or to_email}],
        "subject":     subject,
        "htmlContent": html_content,
    }
    if text_content:
        payload["textContent"] = text_content

    if attachments:
        encoded = []
        for att in attachments:
            content = att.get("content")
            name    = att.get("name") or "attachment"
            if not content:
                continue
            if isinstance(content, bytes):
                b64 = base64.b64encode(content).decode("ascii")
            else:
                b64 = str(content)
            encoded.append({"name": str(name), "content": b64})
        if encoded:
            payload["attachment"] = encoded

    headers = {
        "api-key":      api_key,
        "accept":       "application/json",
        "content-type": "application/json",
    }
    try:
        r = requests.post(BREVO_ENDPOINT, json=payload,
                          headers=headers, timeout=10)
        if r.status_code in (200, 201, 202):
            response_data = r.json()
            message_id = response_data.get("messageId", "unknown")
            log.info(f"Email sent successfully to {to_email} (Message ID: {message_id})")
            return True
        log.warning("Brevo send failed (%s): %s", r.status_code, r.text[:300])
    except Exception as exc:
        log.warning("Brevo request errored: %s", exc)
    return False


def _student_email(sb, student_id: str) -> Optional[str]:
    """Look up the student's auth email; returns None on failure."""
    try:
        res = sb.auth.admin.get_user_by_id(student_id)
        user = getattr(res, "user", None)
        return getattr(user, "email", None) if user else None
    except Exception as exc:
        log.warning("auth.admin.get_user_by_id failed: %s", exc)
        return None


def get_student_email(sb, student_id: str) -> Optional[str]:
    """Public wrapper around the auth-email lookup."""
    return _student_email(sb, student_id)


def send_certificate_email(
    *,
    to_email: str,
    student_name: str,
    event_title: str,
    event_kind: str,
    pdf_bytes: bytes,
    filename: str = "certificate.pdf",
) -> bool:
    """
    Send a single Certificate of Attendance to a student as a PDF
    attachment. The HTML body greets them by name and references the
    event so the message reads as a personal copy, not a generic blast.
    """
    if not to_email or not pdf_bytes:
        return False

    name  = student_name or "Student"
    label = (event_kind or "event").strip() or "event"
    title = (event_title or "").strip()

    subject = f"Your Certificate of Attendance — {title}" if title \
              else "Your Certificate of Attendance"

    html = (
        "<div style='font-family: Arial, sans-serif; max-width: 560px; color:#1f2937;'>"
        f"<p>Hi {name},</p>"
        f"<p>Maraming salamat sa pagsali sa <strong>{title or label}</strong>. "
        "Nakalakip dito ang iyong <strong>Certificate of Attendance</strong> "
        "bilang opisyal na kopya mo.</p>"
        "<p>Maaari mong i-save o i-print ang attached PDF para sa records mo.</p>"
        "<hr style='border:none; border-top:1px solid #e2e8f0; margin:18px 0;'/>"
        "<p style='color:#6b7280; font-size:12px; margin:0;'>"
        "Sangguniang Kabataan ng Barangay Bukal · Scholarship Portal"
        "</p>"
        "</div>"
    )
    text = (
        f"Hi {name},\n\n"
        f"Salamat sa pagsali sa {title or label}. "
        "Nakalakip dito ang iyong Certificate of Attendance bilang "
        "opisyal na kopya mo.\n\n"
        "— SK ng Bukal Scholarship Portal"
    )

    return send_email(
        to_email,
        name,
        subject,
        html,
        text,
        attachments=[{"name": filename, "content": pdf_bytes}],
    )


def send_application_decision_email(
    sb,
    student_id: str,
    student_name: str,
    decision: str,
    notes: Optional[str] = None,
) -> bool:
    """
    Notify a student that their application was verified or rejected.
    """
    email = _student_email(sb, student_id)
    if not email:
        return False

    name = student_name or "Student"

    if decision == "verified":
        subject = "Your scholarship application has been approved"
        html = (
            f"<p>Hi {name},</p>"
            "<p>Good news — your scholarship application has been "
            "<strong>approved / verified</strong> by the Sangguniang "
            "Kabataan ng Bukal.</p>"
            "<p>Please watch the Events page in the portal "
            "for the schedule of the next pay-out.</p>"
            "<p>Thank you,<br/>SK ng Bukal Scholarship Portal</p>"
        )
        text = (
            f"Hi {name},\n\n"
            "Your scholarship application has been approved / verified.\n"
            "Please watch the Events page for the next pay-out schedule.\n\n"
            "— SK ng Bukal Scholarship Portal"
        )
    elif decision == "rejected":
        subject = "Update on your scholarship application"
        notes_html = ""
        notes_text = ""
        if notes:
            notes_html = (
                "<p><strong>Admin notes:</strong><br/>"
                f"{notes}</p>"
            )
            notes_text = f"\nAdmin notes:\n{notes}\n"
        html = (
            f"<p>Hi {name},</p>"
            "<p>Unfortunately, your scholarship application was "
            "<strong>rejected and needs updates</strong>.</p>"
            f"{notes_html}"
            "<p>Please log in to the portal and update your "
            "requirements so an admin can review them again.</p>"
            "<p>Thank you,<br/>SK ng Bukal Scholarship Portal</p>"
        )
        text = (
            f"Hi {name},\n\n"
            "Your scholarship application was rejected and needs updates.\n"
            f"{notes_text}"
            "Please log in to the portal and re-submit your requirements.\n\n"
            "— SK ng Bukal Scholarship Portal"
        )
    else:
        return False

    return send_email(email, name, subject, html, text)


# ---------------------------------------------------------------------------
# Announcement broadcast
# ---------------------------------------------------------------------------

PH_OFFSET_HOURS = 8


def _format_ph_dt(value) -> str:
    """Render a timestamp string in Philippine local time, e.g. '2026-04-15 13:00'."""
    if not value:
        return ""
    from datetime import datetime, timedelta, timezone as _tz
    try:
        if isinstance(value, datetime):
            dt = value
        else:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_tz.utc)
    ph = dt.astimezone(_tz(timedelta(hours=PH_OFFSET_HOURS)))
    return ph.strftime("%Y-%m-%d %H:%M")


_CATEGORY_PRETTY = {
    "registration":        "Scholarship Registration",
    "payout":              "Scholarship Pay Out",
    "general_orientation": "General Orientation",
    "general":             "General event",
}


def _build_announcement_email(announcement: dict) -> tuple[str, str, str]:
    """Return (subject, html, text) for a given announcement record."""
    title    = (announcement.get("title") or "Event").strip()
    body     = (announcement.get("body") or "").strip()
    category = announcement.get("category") or "general"
    cat_label = _CATEGORY_PRETTY.get(category, "Event")
    start    = _format_ph_dt(announcement.get("start_at"))
    end      = _format_ph_dt(announcement.get("end_at"))

    subject = f"[SK Bukal] {title}"

    body_html_para = (body or "").replace("\n", "<br/>")
    schedule_html = ""
    schedule_text = ""
    if start and end:
        schedule_html = (
            "<p style='color:#475569; font-size:13px;'>"
            f"<strong>Schedule:</strong> {start} → {end} (Philippine time)"
            "</p>"
        )
        schedule_text = f"\nSchedule: {start} → {end} (Philippine time)\n"

    html = (
        "<div style='font-family: Arial, sans-serif; max-width: 560px; color:#1f2937;'>"
        f"<p style='display:inline-block; padding:2px 10px; border-radius:9999px; "
        f"background:#f1f7ef; color:#476a40; font-size:11px; "
        f"font-weight:600; letter-spacing:.05em;'>{cat_label.upper()}</p>"
        f"<h2 style='color:#476a40; margin:8px 0 4px;'>{title}</h2>"
        f"{schedule_html}"
        f"<div style='font-size:14px; line-height:1.55; white-space:pre-line;'>{body_html_para}</div>"
        "<hr style='border:none; border-top:1px solid #e2e8f0; margin:18px 0;'/>"
        "<p style='color:#6b7280; font-size:12px; margin:0;'>"
        "Mag-log in sa Sangguniang Kabataan ng Bukal Scholarship Portal "
        "para makita ang buong detalye, mag-apply, o mag-join ng event."
        "</p>"
        "</div>"
    )

    text = (
        f"[{cat_label}] {title}\n"
        f"{schedule_text}\n"
        f"{body}\n\n"
        "— SK ng Bukal Scholarship Portal"
    )
    return subject, html, text


def _list_student_recipients(sb) -> list[dict]:
    """Return list of dicts with email + full_name for all reachable students.

    Reachable = role student, account active, email verified.
    """
    profiles = (
        sb.table("profiles")
        .select("id, full_name, email_verified, is_active, role")
        .eq("role", "student")
        .execute()
    ).data or []

    keep: list[dict] = []
    for p in profiles:
        if p.get("email_verified") is False:
            continue
        if p.get("is_active") is False:
            continue
        keep.append(p)
    if not keep:
        return []

    # Pull emails from the auth admin API (handles pagination).
    emails: dict[str, str] = {}
    page = 1
    while True:
        try:
            res = sb.auth.admin.list_users(page=page, per_page=200)
        except TypeError:
            # Older client signature: returns everything in one call.
            res = sb.auth.admin.list_users()
            users = getattr(res, "users", None) or res or []
            for u in users:
                if getattr(u, "id", None) and u.email:
                    emails[u.id] = u.email
            break
        users = getattr(res, "users", None) or res or []
        if not users:
            break
        for u in users:
            if getattr(u, "id", None) and u.email:
                emails[u.id] = u.email
        if len(users) < 200:
            break
        page += 1

    out = []
    for p in keep:
        email = emails.get(p["id"])
        if not email:
            continue
        out.append({"email": email, "full_name": p.get("full_name") or ""})
    return out


def broadcast_announcement_email(sb, announcement: dict) -> int:
    """
    Email every active student about a new announcement. Synchronous —
    intended to be called from a daemon thread by the route handler.

    Returns the number of emails actually accepted by the provider.
    """
    recipients = _list_student_recipients(sb)
    if not recipients:
        return 0

    subject, html, text = _build_announcement_email(announcement)

    sent = 0
    for r in recipients:
        try:
            ok = send_email(r["email"], r["full_name"], subject, html, text)
            if ok:
                sent += 1
        except Exception as exc:
            log.warning("broadcast email to %s failed: %s", r["email"], exc)
    log.info("Announcement %s emailed to %s/%s recipients",
             announcement.get("id"), sent, len(recipients))
    return sent
