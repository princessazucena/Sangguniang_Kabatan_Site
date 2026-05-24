"""
Student → My applications sidebar button.

Covers the dashboard list, starting a new application against the open
registration window, the per-application requirements page (level select +
upload), and submitting requirements.
"""
import uuid

from flask import (
    render_template, request, redirect, url_for, flash, session, abort,
)

from supabase_client import get_supabase, get_bucket_name
from services.announcements import current_open_registration

from ._common import (
    student_bp, student_required,
    REQUIREMENT_SLOTS, LEVEL_SLOTS, YEAR_OPTIONS, LEVEL_LABELS, YEAR_LABELS,
    PDF_MIMES, IMAGE_MIMES, MAX_UPLOAD_BYTES,
    student_applications, application_for_open_window, get_application,
    files_by_slot, registration_window_active,
)


# ---------------------------------------------------------------------------
# Applications list (sidebar item "My applications")
# ---------------------------------------------------------------------------

@student_bp.route("/applications")
@student_required
def applications_list():
    sb = get_supabase()
    student_id = session["user_id"]

    applications = student_applications(sb, student_id)
    open_registration = current_open_registration(sb)

    # Has the student already applied for the open window?
    open_app = application_for_open_window(
        applications, open_registration["id"] if open_registration else None,
    )

    # Decorate each application for display (level/year labels).
    for a in applications:
        a["level_label"] = LEVEL_LABELS.get(a.get("education_level"), "—")
        a["year_label"]  = YEAR_LABELS.get(a.get("year_level"), "—")

    return render_template(
        "student/applications.html",
        applications=applications,
        open_registration=open_registration,
        open_application=open_app,
    )


@student_bp.route("/apply", methods=["POST"])
@student_required
def apply():
    """Start a new application for the currently open registration window."""
    sb = get_supabase()
    student_id = session["user_id"]

    open_reg = current_open_registration(sb)
    if not open_reg:
        flash("There is no open scholarship registration right now.", "error")
        return redirect(url_for("student.applications_list"))

    # If they already applied for this window, route them to it.
    existing = (
        sb.table("applications")
        .select("id")
        .eq("student_id", student_id)
        .eq("registration_id", open_reg["id"])
        .limit(1)
        .execute()
    ).data or []
    if existing:
        return redirect(url_for("student.application", app_id=existing[0]["id"]))

    inserted = (
        sb.table("applications")
        .insert({
            "student_id":      student_id,
            "registration_id": open_reg["id"],
            "status":          "pending",
        })
        .execute()
    )
    new_id = inserted.data[0]["id"]
    flash("New application started. Pick your level and upload the requirements.", "success")
    return redirect(url_for("student.application", app_id=new_id))


# ---------------------------------------------------------------------------
# Per-application requirements page
# ---------------------------------------------------------------------------

@student_bp.route("/applications/<int:app_id>")
@student_required
def application(app_id: int):
    sb = get_supabase()
    student_id = session["user_id"]

    app_row = get_application(sb, app_id, student_id)
    if not app_row:
        abort(404)

    open_registration = current_open_registration(sb)
    window_open = registration_window_active(app_row)

    # Level not picked yet — show selection screen first.
    if not app_row.get("education_level") or not app_row.get("year_level"):
        return render_template(
            "student/select_level.html",
            application=app_row,
            year_options=YEAR_OPTIONS,
            level_labels=LEVEL_LABELS,
            window_open=window_open,
        )

    files = (
        sb.table("application_files")
        .select("*")
        .eq("application_id", app_row["id"])
        .order("uploaded_at", desc=True)
        .execute()
    ).data or []

    by_slot = files_by_slot(files)
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
    is_complete = all(s["file"] for s in slots)

    return render_template(
        "student/application.html",
        application=app_row,
        slots=slots,
        level_label=LEVEL_LABELS.get(level, level),
        year_label=YEAR_LABELS.get(app_row.get("year_level"), ""),
        window_open=window_open,
        open_registration=open_registration,
        is_complete=is_complete,
    )


@student_bp.route("/applications/<int:app_id>/level", methods=["POST"])
@student_required
def set_level(app_id: int):
    sb = get_supabase()
    student_id = session["user_id"]
    app_row = get_application(sb, app_id, student_id)
    if not app_row:
        abort(404)

    if not registration_window_active(app_row):
        flash("The registration window for this application is closed.", "error")
        return redirect(url_for("student.application", app_id=app_id))

    level = (request.form.get("education_level") or "").strip()
    year  = (request.form.get("year_level") or "").strip()

    if level not in LEVEL_SLOTS:
        flash("Please choose a valid education level.", "error")
        return redirect(url_for("student.application", app_id=app_id))

    valid_years = {y for y, _ in YEAR_OPTIONS[level]}
    if year not in valid_years:
        flash("Please pick the correct year for your level.", "error")
        return redirect(url_for("student.application", app_id=app_id))

    sb.table("applications").update({
        "education_level": level,
        "year_level": year,
    }).eq("id", app_row["id"]).execute()

    flash("Saved. You can now upload your requirements.", "success")
    return redirect(url_for("student.application", app_id=app_id))


@student_bp.route("/applications/<int:app_id>/level/reset", methods=["POST"])
@student_required
def reset_level(app_id: int):
    sb = get_supabase()
    student_id = session["user_id"]
    app_row = get_application(sb, app_id, student_id)
    if not app_row:
        abort(404)

    if not registration_window_active(app_row):
        flash("The registration window for this application is closed.", "error")
        return redirect(url_for("student.application", app_id=app_id))

    sb.table("applications").update({
        "education_level": None,
        "year_level": None,
    }).eq("id", app_row["id"]).execute()
    return redirect(url_for("student.application", app_id=app_id))


# ---------------------------------------------------------------------------
# Upload + submit
# ---------------------------------------------------------------------------

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


@student_bp.route("/applications/<int:app_id>/submit", methods=["POST"])
@student_required
def submit_requirements(app_id: int):
    """
    Single-button submission: process every slot input present in the form
    and save them in one go for the given application.
    """
    sb = get_supabase()
    student_id = session["user_id"]
    app_row = get_application(sb, app_id, student_id)
    if not app_row:
        abort(404)

    if not registration_window_active(app_row):
        flash("The scholarship registration window is not open. "
              "You cannot submit requirements right now.", "error")
        return redirect(url_for("student.application", app_id=app_id))

    level = app_row.get("education_level")
    if not level:
        flash("Please choose your education level first.", "error")
        return redirect(url_for("student.application", app_id=app_id))

    required_slots = LEVEL_SLOTS[level]

    # What's already on file for this application.
    existing_files = (
        sb.table("application_files")
        .select("slot")
        .eq("application_id", app_row["id"])
        .execute()
    ).data or []
    existing_slots = {f["slot"] for f in existing_files if f.get("slot")}

    # Slots the student is uploading right now in this form post.
    incoming_slots: set[str] = set()
    for slot in required_slots:
        f = request.files.get(f"document_{slot}")
        if f and f.filename:
            incoming_slots.add(slot)

    # Every required slot must either already be uploaded, or be present
    # in this submission. Otherwise reject the whole thing — admins should
    # only ever see complete applications.
    final_slots = existing_slots | incoming_slots
    missing = [s for s in required_slots if s not in final_slots]
    if missing:
        labels = [REQUIREMENT_SLOTS[s]["label"] for s in missing]
        flash(
            "You need to upload all requirements before submitting. "
            "Still missing: " + ", ".join(labels) + ".",
            "error",
        )
        return redirect(url_for("student.application", app_id=app_id))

    saved, errors = [], []
    for slot in required_slots:
        f = request.files.get(f"document_{slot}")
        if not f or not f.filename:
            continue
        ok, msg = _upload_one(sb, app_row, student_id, slot, f)
        (saved if ok else errors).append(msg)

    if errors:
        for err in errors:
            flash(err, "error")
        return redirect(url_for("student.application", app_id=app_id))

    # Re-open this application for review after fresh uploads.
    if app_row["status"] != "pending":
        sb.table("applications").update({
            "status": "pending",
            "reviewed_by": None,
            "reviewed_at": None,
        }).eq("id", app_row["id"]).execute()

    if saved:
        flash(
            f"Submitted: {', '.join(saved)}. Sent for review.",
            "success",
        )
    else:
        flash("Application sent for review.", "success")

    return redirect(url_for("student.application", app_id=app_id))
