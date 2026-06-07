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
from services.announcements import current_open_registration, student_joined_orientation

from ._common import (
    student_bp, student_required,
    REQUIREMENT_SLOTS, LEVEL_SLOTS, YEAR_OPTIONS, LEVEL_LABELS, YEAR_LABELS,
    PDF_MIMES, IMAGE_MIMES, MAX_UPLOAD_BYTES,
    student_applications, application_for_open_window, get_application,
    files_by_slot, registration_window_active, student_has_verified_application,
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

    # Once verified, a student is locked in — hide any open-registration
    # call-to-action so they can't start a new application this cycle.
    already_verified = student_has_verified_application(applications)
    if already_verified:
        open_registration = None
        open_app = None
    
    # Check if the open registration requires attendance at a specific orientation
    orientation_required = None
    orientation_attended = True
    if open_registration:
        required_orientation_id = open_registration.get("required_orientation_id")
        if required_orientation_id:
            orientation_attended = student_joined_orientation(sb, student_id, required_orientation_id)
            if not orientation_attended:
                # Fetch the orientation details to show to the student
                try:
                    orientation_required = (
                        sb.table("announcements")
                        .select("id, title")
                        .eq("id", required_orientation_id)
                        .single()
                        .execute()
                    ).data
                except Exception:
                    orientation_required = {"id": required_orientation_id, "title": "General Orientation"}

    # Decorate each application for display (level/year labels).
    for a in applications:
        a["level_label"] = LEVEL_LABELS.get(a.get("education_level"), "—")
        a["year_label"]  = YEAR_LABELS.get(a.get("year_level"), "—")

    return render_template(
        "student/applications.html",
        applications=applications,
        open_registration=open_registration,
        open_application=open_app,
        already_verified=already_verified,
        orientation_required=orientation_required,
        orientation_attended=orientation_attended,
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

    # Check if orientation attendance is required
    required_orientation_id = open_reg.get("required_orientation_id")
    if required_orientation_id:
        if not student_joined_orientation(sb, student_id, required_orientation_id):
            flash("You must attend the required General Orientation event before applying for this scholarship.", "error")
            return redirect(url_for("student.applications_list"))

    # Block applying if any earlier application is already verified.
    existing_apps = student_applications(sb, student_id)
    if student_has_verified_application(existing_apps):
        flash("Verified ka na sa nakaraang registration. Hindi ka na pwedeng mag-apply muli.", "error")
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

    # If the student is already verified anywhere, suppress the "another
    # registration is open — go apply again" hint.
    if student_has_verified_application(student_applications(sb, student_id)):
        open_registration = None

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

# Compress big phone photos before pushing to Supabase Storage. Real IDs
# rarely need more than ~2000 px on the long edge to stay readable.
_IMAGE_MAX_DIM     = 2000
_IMAGE_JPEG_QUALITY = 82


def _compress_image(data: bytes, mime: str) -> tuple[bytes, str, str]:
    """
    Resize + re-encode an image so it doesn't gobble Supabase storage.

    Returns ``(new_bytes, new_mime, suggested_extension)``. Falls back to
    the original bytes if Pillow can't read it (e.g. unusual HEIC builds
    on the server) so the upload still goes through.
    """
    try:
        from io import BytesIO
        from PIL import Image, ImageOps
    except Exception:
        return data, mime, ""

    try:
        img = Image.open(BytesIO(data))
        # Honor EXIF orientation so portrait phone photos don't end up sideways.
        img = ImageOps.exif_transpose(img)

        # Drop alpha for JPEG output.
        if img.mode in ("RGBA", "LA", "P"):
            img = img.convert("RGB")
        elif img.mode != "RGB":
            img = img.convert("RGB")

        img.thumbnail((_IMAGE_MAX_DIM, _IMAGE_MAX_DIM), Image.LANCZOS)

        out = BytesIO()
        img.save(out, format="JPEG",
                 quality=_IMAGE_JPEG_QUALITY,
                 optimize=True,
                 progressive=True)
        return out.getvalue(), "image/jpeg", ".jpg"
    except Exception:
        # If we can't process it, fall back to the original.
        return data, mime, ""


def _delete_existing_slot_file(sb, application_id: int, slot: str) -> None:
    """
    Remove the previous file for this (application, slot) — both the
    storage object and the application_files row — so re-uploads don't
    leave orphans in Supabase.
    """
    try:
        rows = (
            sb.table("application_files")
            .select("id, storage_path")
            .eq("application_id", application_id)
            .eq("slot", slot)
            .execute()
        ).data or []
        if not rows:
            return
        bucket = get_bucket_name()
        paths = [r["storage_path"] for r in rows if r.get("storage_path")]
        if paths:
            try:
                sb.storage.from_(bucket).remove(paths)
            except Exception:
                # If storage cleanup fails, still drop the rows so the
                # student isn't blocked. The blob becomes an orphan but
                # an admin can clean up later.
                pass
        sb.table("application_files").delete().in_(
            "id", [r["id"] for r in rows]
        ).execute()
    except Exception:
        # Never let cleanup failures block the new upload.
        pass


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
        return False, f"{label} is too large (max 5 MB)."

    safe_name = file_storage.filename.replace("/", "_").replace("\\", "_")

    # For images, compress + re-encode as JPEG before uploading. This
    # cuts typical 4-5 MB phone photos down to ~300-700 KB without
    # hurting readability of an ID, indigency cert, etc.
    if kind == "image":
        data, mime, new_ext = _compress_image(data, mime)
        if new_ext:
            base = safe_name.rsplit(".", 1)[0] or "photo"
            safe_name = f"{base}{new_ext}"

    # Replace any existing upload for this slot so the student doesn't
    # accumulate dead copies in Supabase storage.
    _delete_existing_slot_file(sb, app_row["id"], slot)

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

    if app_row.get("status") == "verified":
        flash("Verified na ang application mo, hindi na pwedeng baguhin.", "error")
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
