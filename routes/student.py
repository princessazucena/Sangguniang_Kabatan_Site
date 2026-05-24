"""
Student routes: dashboard, level selection, per-requirement uploads.
"""
import uuid
from functools import wraps

from flask import (
    Blueprint, render_template, request, redirect,
    url_for, flash, session,
)

from supabase_client import get_supabase, get_bucket_name

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

@student_bp.route("/dashboard")
@student_required
def dashboard():
    sb = get_supabase()
    student_id = session["user_id"]
    app_row = _get_or_create_application(sb, student_id)

    # Level not picked yet — show selection screen first.
    if not app_row.get("education_level") or not app_row.get("year_level"):
        return render_template(
            "student/select_level.html",
            application=app_row,
            year_options=YEAR_OPTIONS,
            level_labels=LEVEL_LABELS,
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


@student_bp.route("/upload/<slot>", methods=["POST"])
@student_required
def upload(slot: str):
    if slot not in REQUIREMENT_SLOTS:
        flash("Unknown requirement.", "error")
        return redirect(url_for("student.dashboard"))

    sb = get_supabase()
    student_id = session["user_id"]
    app_row = _get_or_create_application(sb, student_id)

    level = app_row.get("education_level")
    if not level:
        flash("Please choose your education level first.", "error")
        return redirect(url_for("student.dashboard"))

    if level not in REQUIREMENT_SLOTS[slot]["levels"]:
        flash("That requirement does not apply to your level.", "error")
        return redirect(url_for("student.dashboard"))

    f = request.files.get("document")
    if not f or not f.filename:
        flash("Please choose a file to upload.", "error")
        return redirect(url_for("student.dashboard"))

    kind = REQUIREMENT_SLOTS[slot]["kind"]
    mime = (f.mimetype or "").lower()
    label = REQUIREMENT_SLOTS[slot]["label"]

    if kind == "pdf" and mime not in PDF_MIMES:
        flash(f"{label} must be a PDF file.", "error")
        return redirect(url_for("student.dashboard"))
    if kind == "image" and mime not in IMAGE_MIMES:
        flash(f"{label} must be an image (JPG, PNG, or HEIC).", "error")
        return redirect(url_for("student.dashboard"))

    data = f.read()
    if len(data) > MAX_UPLOAD_BYTES:
        flash("File is too large (max 10 MB).", "error")
        return redirect(url_for("student.dashboard"))

    safe_name = f.filename.replace("/", "_").replace("\\", "_")
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
        flash(f"Upload failed: {exc}", "error")
        return redirect(url_for("student.dashboard"))

    sb.table("application_files").insert({
        "application_id": app_row["id"],
        "student_id":     student_id,
        "slot":           slot,
        "file_name":      safe_name,
        "storage_path":   storage_path,
        "mime_type":      mime,
        "size_bytes":     len(data),
    }).execute()

    # Re-open the application for review after a new upload.
    if app_row["status"] != "pending":
        sb.table("applications").update({
            "status": "pending",
            "reviewed_by": None,
            "reviewed_at": None,
        }).eq("id", app_row["id"]).execute()

    flash(f"{label} uploaded.", "success")
    return redirect(url_for("student.dashboard"))
