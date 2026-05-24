"""
Student routes: dashboard, announcements, level selection, per-requirement uploads.
"""
import uuid
from functools import wraps

from flask import (
    Blueprint, render_template, request, redirect,
    url_for, flash, session,
)

from supabase_client import get_supabase, get_bucket_name
from services.announcements import (
    annotate, current_open_registration, schedule_status,
)

student_bp = Blueprint("student", __name__)


# ---------------------------------------------------------------------------
# Requirements config
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


def student_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if session.get("role") != "student":
            flash("Please log in as a student.", "error")
            return redirect(url_for("public.login"))
        return view(*args, **kwargs)
    return wrapper


def _get_or_create_application(sb, student_id: str) -> dict:
    """Return the student's application row, creating it on first visit."""
    existing = (
        sb.table("applications").select("*").eq("student_id", student_id).execute()
    )
    if existing.data:
        return existing.data[0]
    inserted = (
        sb.table("applications")
        .insert({"student_id": student_id, "status": "pending"})
        .execute()
    )
    return inserted.data[0]


def _files_by_slot(files: list[dict]) -> dict[str, dict]:
    """Latest file per slot."""
    latest: dict[str, dict] = {}
    for f in files:
        slot = f.get("slot")
        if not slot:
            continue
        if slot not in latest:  # files come ordered by uploaded_at desc
            latest[slot] = f
    return latest


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@student_bp.route("/announcements")
@student_required
def announcements():
    sb = get_supabase()
    items = (
        sb.table("announcements")
        .select("*")
        .order("created_at", desc=True)
        .limit(50)
        .execute()
    ).data or []
    annotate(items)

    student_id = session["user_id"]
    joined_ids = set()
    payout_ids = [a["id"] for a in items if a.get("category") == "payout"]
    if payout_ids:
        rows = (
            sb.table("announcement_joins")
            .select("announcement_id")
            .eq("student_id", student_id)
            .in_("announcement_id", payout_ids)
            .execute()
        ).data or []
        joined_ids = {r["announcement_id"] for r in rows}

    return render_template(
        "student/announcements.html",
        announcements=items,
        joined_ids=joined_ids,
    )


@student_bp.route("/announcements/<int:anc_id>/join", methods=["POST"])
@student_required
def join_payout(anc_id: int):
    sb = get_supabase()
    anc = (
        sb.table("announcements").select("*").eq("id", anc_id).single().execute()
    ).data
    if not anc or anc.get("category") != "payout":
        flash("That announcement does not accept joiners.", "error")
        return redirect(url_for("student.announcements"))

    if schedule_status(anc) != "open":
        flash("Hindi pa o tapos na ang join window para sa announcement na ito.", "error")
        return redirect(url_for("student.announcements"))

    student_id = session["user_id"]
    try:
        sb.table("announcement_joins").insert({
            "announcement_id": anc_id,
            "student_id":      student_id,
        }).execute()
        flash("You're on the list. Check announcements again on the payout date.", "success")
    except Exception:
        # likely a duplicate (unique constraint) — treat as success.
        flash("You already joined this pay-out.", "success")

    return redirect(url_for("student.announcements"))


@student_bp.route("/dashboard")
@student_required
def dashboard():
    sb = get_supabase()
    student_id = session["user_id"]
    app_row = _get_or_create_application(sb, student_id)

    open_registration = current_open_registration(sb)

    # Level not picked yet — show selection screen first.
    if not app_row.get("education_level") or not app_row.get("year_level"):
        return render_template(
            "student/select_level.html",
            application=app_row,
            year_options=YEAR_OPTIONS,
            level_labels=LEVEL_LABELS,
            open_registration=open_registration,
        )

    files = (
        sb.table("application_files")
        .select("*")
        .eq("application_id", app_row["id"])
        .order("uploaded_at", desc=True)
        .execute()
    ).data or []

    by_slot = _files_by_slot(files)
    level = app_row["education_level"]
    slots = [
        {
            "key":   key,
            "label": REQUIREMENT_SLOTS[key]["label"],
            "kind":  REQUIREMENT_SLOTS[key]["kind"],
            "file":  by_slot.get(key),
        }
        for key in LEVEL_SLOTS[level]
    ]

    return render_template(
        "student/dashboard.html",
        application=app_row,
        slots=slots,
        level_label=LEVEL_LABELS.get(level, level),
        year_label=YEAR_LABELS.get(app_row.get("year_level"), ""),
        open_registration=open_registration,
    )


@student_bp.route("/level", methods=["POST"])
@student_required
def set_level():
    sb = get_supabase()
    student_id = session["user_id"]
    app_row = _get_or_create_application(sb, student_id)

    level = (request.form.get("education_level") or "").strip()
    year  = (request.form.get("year_level") or "").strip()

    if level not in LEVEL_SLOTS:
        flash("Please choose a valid education level.", "error")
        return redirect(url_for("student.dashboard"))

    valid_years = {y for y, _ in YEAR_OPTIONS[level]}
    if year not in valid_years:
        flash("Please pick the correct year for your level.", "error")
        return redirect(url_for("student.dashboard"))

    sb.table("applications").update({
        "education_level": level,
        "year_level": year,
    }).eq("id", app_row["id"]).execute()

    flash("Saved. You can now upload your requirements.", "success")
    return redirect(url_for("student.dashboard"))


@student_bp.route("/level/reset", methods=["POST"])
@student_required
def reset_level():
    sb = get_supabase()
    student_id = session["user_id"]
    app_row = _get_or_create_application(sb, student_id)
    sb.table("applications").update({
        "education_level": None,
        "year_level": None,
    }).eq("id", app_row["id"]).execute()
    return redirect(url_for("student.dashboard"))


def _upload_one(sb, app_row, student_id, slot, file_storage):
    """Validate & store a single file; returns (ok, message)."""
    kind  = REQUIREMENT_SLOTS[slot]["kind"]
    label = REQUIREMENT_SLOTS[slot]["label"]
    mime  = (file_storage.mimetype or "").lower()

    if kind == "pdf" and mime not in PDF_MIMES:
        return False, f"{label} must be a PDF file."
    if kind == "image" and mime not in IMAGE_MIMES:
        return False, f"{label} must be an image (JPG, PNG, or HEIC)."

    data = file_storage.read()
    if not data:
        return False, f"{label} is empty."
    if len(data) > MAX_UPLOAD_BYTES:
        return False, f"{label} is too large (max 10 MB)."

    safe_name = file_storage.filename.replace("/", "_").replace("\\", "_")
    storage_path = f"{student_id}/{slot}/{uuid.uuid4().hex}_{safe_name}"

    bucket = get_bucket_name()
    try:
        sb.storage.from_(bucket).upload(
            path=storage_path,
            file=data,
            file_options={
                "content-type": mime or "application/octet-stream",
                "upsert": "false",
            },
        )
    except Exception as exc:
        return False, f"{label} upload failed: {exc}"

    sb.table("application_files").insert({
        "application_id": app_row["id"],
        "student_id":     student_id,
        "slot":           slot,
        "file_name":      safe_name,
        "storage_path":   storage_path,
        "mime_type":      mime,
        "size_bytes":     len(data),
    }).execute()
    return True, label


@student_bp.route("/submit", methods=["POST"])
@student_required
def submit_requirements():
    """
    Single-button submission: process every slot input present in the form
    and save them in one go.
    """
    sb = get_supabase()
    student_id = session["user_id"]
    app_row = _get_or_create_application(sb, student_id)

    if not current_open_registration(sb):
        flash("Sarado pa o tapos na ang scholarship registration window. "
              "Hindi ka pwedeng mag-submit ng requirements ngayon.", "error")
        return redirect(url_for("student.dashboard"))

    level = app_row.get("education_level")
    if not level:
        flash("Please choose your education level first.", "error")
        return redirect(url_for("student.dashboard"))

    saved, errors = [], []
    for slot in LEVEL_SLOTS[level]:
        f = request.files.get(f"document_{slot}")
        if not f or not f.filename:
            continue
        ok, msg = _upload_one(sb, app_row, student_id, slot, f)
        (saved if ok else errors).append(msg)

    if not saved and not errors:
        flash("Walang napiling file. Pumili muna ng dokumentong i-uupload.", "error")
        return redirect(url_for("student.dashboard"))

    if saved:
        # Re-open the application for review after fresh uploads.
        if app_row["status"] != "pending":
            sb.table("applications").update({
                "status": "pending",
                "reviewed_by": None,
                "reviewed_at": None,
            }).eq("id", app_row["id"]).execute()
        flash(f"Saved: {', '.join(saved)}.", "success")
    for err in errors:
        flash(err, "error")

    return redirect(url_for("student.dashboard"))


@student_bp.route("/profile")
@student_required
def profile():
    sb = get_supabase()
    student_id = session["user_id"]

    prof = (
        sb.table("profiles")
        .select("first_name, middle_name, last_name, suffix, full_name, "
                "facebook_url, role, created_at")
        .eq("id", student_id)
        .single()
        .execute()
    ).data or {}

    # Pull the auth email so we can show it on the profile.
    try:
        user_res = sb.auth.admin.get_user_by_id(student_id)
        email = (user_res.user.email if getattr(user_res, "user", None) else None) or ""
    except Exception:
        email = ""

    app_row = _get_or_create_application(sb, student_id)
    files = (
        sb.table("application_files")
        .select("*")
        .eq("application_id", app_row["id"])
        .order("uploaded_at", desc=True)
        .execute()
    ).data or []

    by_slot = _files_by_slot(files)
    level   = app_row.get("education_level")
    slots   = []
    if level:
        slots = [
            {
                "key":   key,
                "label": REQUIREMENT_SLOTS[key]["label"],
                "kind":  REQUIREMENT_SLOTS[key]["kind"],
                "file":  by_slot.get(key),
            }
            for key in LEVEL_SLOTS[level]
        ]

    return render_template(
        "student/profile.html",
        profile=prof,
        email=email,
        application=app_row,
        slots=slots,
        level_label=LEVEL_LABELS.get(level, "—") if level else "—",
        year_label=YEAR_LABELS.get(app_row.get("year_level"), "—"),
    )
