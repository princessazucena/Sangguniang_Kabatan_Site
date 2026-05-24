"""
Shared bits for the student blueprint.

The blueprint object lives here so every per-feature module can attach
routes to the same ``student_bp``. Helpers used by more than one module
(application lookups, file-by-slot grouping, requirement config) are
exported from here.
"""
from functools import wraps

from flask import Blueprint, redirect, url_for, flash, session

from services.announcements import schedule_status


student_bp = Blueprint("student", __name__)


# ---------------------------------------------------------------------------
# Requirements config (used by applications.py)
# ---------------------------------------------------------------------------

# Each slot has a label, a "kind" (pdf | image), and which education levels
# require it. Image slots use the camera capture flow on mobile.
REQUIREMENT_SLOTS = {
    "card":      {"label": "Report Card",     "kind": "pdf",   "levels": {"senior_high"}},
    "cor":       {"label": "Certificate of Registration (COR)",
                                              "kind": "pdf",   "levels": {"college"}},
    "id":        {"label": "Valid School ID", "kind": "image", "levels": {"senior_high", "college"}},
    "indigency": {"label": "Certificate of Indigency",
                                              "kind": "pdf",   "levels": {"senior_high", "college"}},
    "psa":       {"label": "PSA Birth Certificate",
                                              "kind": "pdf",   "levels": {"senior_high", "college"}},
}

# Order in which slots are shown for each level.
LEVEL_SLOTS = {
    "senior_high": ["card", "id", "indigency", "psa"],
    "college":     ["cor", "id", "indigency", "psa"],
}

YEAR_OPTIONS = {
    "senior_high": [
        ("grade_11", "Grade 11"),
        ("grade_12", "Grade 12"),
    ],
    "college": [
        ("year_1", "1st Year"),
        ("year_2", "2nd Year"),
        ("year_3", "3rd Year"),
        ("year_4", "4th Year"),
        ("year_5", "5th Year"),
    ],
}

LEVEL_LABELS = {
    "senior_high": "Senior High School",
    "college":     "College",
}

YEAR_LABELS = {y: label for opts in YEAR_OPTIONS.values() for y, label in opts}

# Accepted MIME types per slot kind.
PDF_MIMES   = {"application/pdf"}
IMAGE_MIMES = {"image/jpeg", "image/png", "image/webp", "image/heic", "image/heif"}

MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB


# ---------------------------------------------------------------------------
# Decorator
# ---------------------------------------------------------------------------

def student_required(view):
    """Block non-student sessions and bounce them to the public login page."""
    @wraps(view)
    def wrapper(*args, **kwargs):
        if session.get("role") != "student":
            flash("Please log in as a student.", "error")
            return redirect(url_for("public.login"))
        return view(*args, **kwargs)
    return wrapper


# ---------------------------------------------------------------------------
# Application helpers
# ---------------------------------------------------------------------------

def student_applications(sb, student_id: str) -> list[dict]:
    """All of a student's applications, newest first, with linked registration."""
    rows = (
        sb.table("applications")
        .select("*, registration:announcements!applications_registration_id_fkey("
                "id, title, start_at, end_at, category)")
        .eq("student_id", student_id)
        .order("created_at", desc=True)
        .execute()
    ).data or []
    return rows


def application_for_open_window(rows: list[dict], reg_id) -> dict | None:
    """Return the student's application tied to the given registration, if any."""
    if not reg_id:
        return None
    for r in rows:
        if r.get("registration_id") == reg_id:
            return r
    return None


def get_application(sb, app_id: int, student_id: str) -> dict | None:
    res = (
        sb.table("applications")
        .select("*, registration:announcements!applications_registration_id_fkey("
                "id, title, start_at, end_at, category)")
        .eq("id", app_id)
        .eq("student_id", student_id)
        .limit(1)
        .execute()
    )
    rows = res.data or []
    return rows[0] if rows else None


def files_by_slot(files: list[dict]) -> dict[str, dict]:
    """Latest file per slot."""
    latest: dict[str, dict] = {}
    for f in files:
        slot = f.get("slot")
        if not slot:
            continue
        if slot not in latest:  # files come ordered by uploaded_at desc
            latest[slot] = f
    return latest


def registration_window_active(app_row: dict) -> bool:
    """True when this application's registration window is still open."""
    reg = app_row.get("registration")
    if not reg:
        return False
    return schedule_status(reg) == "open"


def student_has_verified_application(applications: list[dict]) -> bool:
    """True if the student already has *any* verified application.

    Once a student is verified for a registration window, they are
    locked in for that cycle — no new applications, no banners.
    """
    return any(a.get("status") == "verified" for a in applications)
