"""
Transactional email sender (Brevo / Sendinblue).

Uses the Brevo HTTP API directly so we don't need to add another SDK.
Configuration comes from .env:

    BREVO_API_KEY        — required
    BREVO_SENDER_EMAIL   — required (must be a verified sender on Brevo)
    BREVO_SENDER_NAME    — optional, defaults to a generic label
"""
import os
import logging
from typing import Optional

import requests

BREVO_ENDPOINT = "https://api.brevo.com/v3/smtp/email"

log = logging.getLogger(__name__)


def send_email(
    to_email: str,
    to_name: str,
    subject: str,
    html_content: str,
    text_content: Optional[str] = None,
) -> bool:
    """
    Fire-and-forget transactional email. Returns True on a 2xx response.
    Errors are logged but never raised — admin actions should not fail
    just because the mail provider hiccuped.
    """
    api_key      = os.environ.get("BREVO_API_KEY")
    sender_email = os.environ.get("BREVO_SENDER_EMAIL")
    sender_name  = (os.environ.get("BREVO_SENDER_NAME")
                    or "Scholarship Portal").strip()
    if not api_key or not sender_email or not to_email:
        log.warning("send_email skipped — missing Brevo config or recipient")
        return False

    payload = {
        "sender":      {"email": sender_email, "name": sender_name},
        "to":          [{"email": to_email, "name": to_name or to_email}],
        "subject":     subject,
        "htmlContent": html_content,
    }
    if text_content:
        payload["textContent"] = text_content

    headers = {
        "api-key":      api_key,
        "accept":       "application/json",
        "content-type": "application/json",
    }
    try:
        r = requests.post(BREVO_ENDPOINT, json=payload,
                          headers=headers, timeout=10)
        if r.status_code in (200, 201, 202):
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
            "<p>Please watch the Announcements page in the portal "
            "for the schedule of the next pay-out.</p>"
            "<p>Thank you,<br/>SK ng Bukal Scholarship Portal</p>"
        )
        text = (
            f"Hi {name},\n\n"
            "Your scholarship application has been approved / verified.\n"
            "Please watch the Announcements page for the next pay-out schedule.\n\n"
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
