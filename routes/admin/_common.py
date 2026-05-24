"""
Shared bits for the admin blueprint.

The blueprint itself lives here so every per-feature module can attach its
routes to the same ``admin_bp``. Helpers and constants used by more than one
module are exported from here as well.
"""
from datetime import datetime, timezone, timedelta
from functools import wraps

from flask import Blueprint, redirect, url_for, flash, session


# Philippine time is UTC+8 with no DST changes.
PH_TZ = timezone(timedelta(hours=8))

admin_bp = Blueprint("admin", __name__)


def admin_required(view):
    """Block non-admin sessions and bounce them to the public login page."""
    @wraps(view)
    def wrapper(*args, **kwargs):
        if session.get("role") != "admin":
            flash("Admins only.", "error")
            return redirect(url_for("public.login"))
        return view(*args, **kwargs)
    return wrapper


def parse_dt_local(value: str):
    """
    Parse an HTML ``datetime-local`` string as Philippine time (UTC+8) and
    return a UTC ISO timestamp string for storage. Returns ``None`` for
    blank or unparsable input.
    """
    if not value:
        return None
    try:
        # datetime-local format: YYYY-MM-DDTHH:MM (no tz)
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=PH_TZ)
        return dt.astimezone(timezone.utc).isoformat()
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Label maps shared across admin views (review, print packet, monitoring,
# user management). Keep these in one place so the wording stays consistent.
# ---------------------------------------------------------------------------

LEVEL_LABELS = {
    "senior_high": "Senior High School",
    "college":     "College",
}

YEAR_LABELS = {
    "grade_11": "Grade 11",
    "grade_12": "Grade 12",
    "year_1":   "1st Year",
    "year_2":   "2nd Year",
    "year_3":   "3rd Year",
    "year_4":   "4th Year",
    "year_5":   "5th Year",
}

# Slot labels mirror what the student side uses.
SLOT_LABELS = {
    "card":      "Report Card",
    "cor":       "Certificate of Registration (COR)",
    "id":        "Valid School ID",
    "indigency": "Certificate of Indigency",
    "psa":       "PSA Birth Certificate",
}

# Required slots per education level. Mirrors student/_common.LEVEL_SLOTS so
# the admin can decide whether an application has been fully submitted
# without importing across blueprints.
LEVEL_SLOTS = {
    "senior_high": ["card", "id", "indigency", "psa"],
    "college":     ["cor", "id", "indigency", "psa"],
}


def submitted_application_ids(sb, app_ids: list[int] | None = None) -> set[int]:
    """
    Return the ids of applications that are fully submitted — meaning the
    student has chosen an education level *and* uploaded a file for every
    required slot for that level.

    Pass ``app_ids`` to scope the check to a known set; otherwise this
    walks every application in the database.
    """
    if app_ids is not None and not app_ids:
        return set()

    q = sb.table("applications").select("id, education_level")
    if app_ids is not None:
        q = q.in_("id", app_ids)
    apps = q.execute().data or []
    apps = [a for a in apps if a.get("education_level") in LEVEL_SLOTS]
    if not apps:
        return set()

    ids = [a["id"] for a in apps]
    files = (
        sb.table("application_files")
        .select("application_id, slot")
        .in_("application_id", ids)
        .execute()
    ).data or []

    slots_by_app: dict[int, set[str]] = {}
    for f in files:
        aid  = f.get("application_id")
        slot = f.get("slot")
        if aid and slot:
            slots_by_app.setdefault(aid, set()).add(slot)

    complete: set[int] = set()
    for a in apps:
        required = set(LEVEL_SLOTS[a["education_level"]])
        if required.issubset(slots_by_app.get(a["id"], set())):
            complete.add(a["id"])
    return complete
