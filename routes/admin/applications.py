"""
Admin → Applications sidebar button.

Lists every submission, opens a per-application review page, records
verify / reject decisions, streams documents inline, and builds the
single-PDF print packet.
"""
import io

from flask import (
    render_template, request, redirect, url_for, flash,
    session, send_file, Response, abort,
)

from supabase_client import get_supabase, get_bucket_name
from services.email import send_application_decision_email
from services.print_packet import build_packet

from ._common import (
    admin_bp, admin_required,
    LEVEL_LABELS, YEAR_LABELS, SLOT_LABELS, LEVEL_SLOTS,
    submitted_application_ids,
)


# ---------------------------------------------------------------------------
# Applications list (formerly the admin dashboard)
# ---------------------------------------------------------------------------

@admin_bp.route("/applications")
@admin_required
def applications():
    sb = get_supabase()

    # Only show applications the student has fully submitted: education
    # level chosen *and* a file uploaded for every required slot.
    complete_ids = submitted_application_ids(sb)

    counts = {"pending": 0, "verified": 0, "rejected": 0}
    apps: list[dict] = []
    if complete_ids:
        apps = (
            sb.table("applications")
            .select("id, status, created_at, reviewed_at, notes, "
                    "student:profiles!applications_student_id_fkey(id, full_name)")
            .in_("id", list(complete_ids))
            .order("created_at", desc=True)
            .execute()
        ).data or []

        for a in apps:
            counts[a["status"]] = counts.get(a["status"], 0) + 1

    return render_template("admin/applications.html", applications=apps, counts=counts)


# ---------------------------------------------------------------------------
# Per-application review + decision
# ---------------------------------------------------------------------------

@admin_bp.route("/applications/<int:app_id>")
@admin_required
def review(app_id: int):
    sb = get_supabase()
    app_res = (
        sb.table("applications")
        .select("id, status, notes, created_at, reviewed_at, "
                "education_level, year_level, "
                "student:profiles!applications_student_id_fkey("
                "id, full_name, first_name, middle_name, last_name, suffix, "
                "facebook_url, created_at)")
        .eq("id", app_id)
        .single()
        .execute()
    )
    if not app_res.data:
        flash("Application not found.", "error")
        return redirect(url_for("admin.applications"))

    files = (
        sb.table("application_files")
        .select("*")
        .eq("application_id", app_id)
        .order("uploaded_at", desc=True)
        .execute()
    ).data or []

    # Hide applications the student hasn't fully submitted yet.
    if app_id not in submitted_application_ids(sb, [app_id]):
        flash("This student has not completed their requirements yet.", "error")
        return redirect(url_for("admin.applications"))

    bucket = get_bucket_name()
    for f in files:
        try:
            signed = sb.storage.from_(bucket).create_signed_url(
                f["storage_path"], 60 * 30  # 30 minutes
            )
            f["signed_url"] = signed.get("signedURL") or signed.get("signed_url")
        except Exception:
            f["signed_url"] = None

    # Stitch the auth email onto the student profile so the admin sees
    # the address the student logs in with.
    app_data = app_res.data
    student = app_data.get("student") or {}
    if student.get("id"):
        try:
            user_res = sb.auth.admin.get_user_by_id(student["id"])
            student["email"] = (
                user_res.user.email if getattr(user_res, "user", None) else ""
            ) or ""
        except Exception:
            student["email"] = ""
        app_data["student"] = student

    # Pretty labels for the level + year so the template stays readable.
    app_data["level_label"] = LEVEL_LABELS.get(app_data.get("education_level"), "—")
    app_data["year_label"]  = YEAR_LABELS.get(app_data.get("year_level"), "—")

    return render_template("admin/review.html", app=app_data, files=files)


@admin_bp.route("/applications/<int:app_id>/decision", methods=["POST"])
@admin_required
def decide(app_id: int):
    decision = request.form.get("decision")
    notes = request.form.get("notes") or None
    if decision not in ("verified", "rejected"):
        flash("Invalid decision.", "error")
        return redirect(url_for("admin.review", app_id=app_id))

    sb = get_supabase()
    sb.table("applications").update({
        "status": decision,
        "notes": notes,
        "reviewed_by": session["user_id"],
        "reviewed_at": "now()",
    }).eq("id", app_id).execute()

    # Email the student best-effort — never fail the admin action just
    # because mail delivery hiccups.
    try:
        app_row = (
            sb.table("applications")
            .select("student:profiles!applications_student_id_fkey(id, full_name)")
            .eq("id", app_id)
            .single()
            .execute()
        ).data or {}
        student = app_row.get("student") or {}
        if student.get("id"):
            send_application_decision_email(
                sb,
                student_id=student["id"],
                student_name=student.get("full_name") or "",
                decision=decision,
                notes=notes,
            )
    except Exception:
        pass

    flash(f"Application marked as {decision}.", "success")
    return redirect(url_for("admin.review", app_id=app_id))


# ---------------------------------------------------------------------------
# Inline document viewer + print packet
# ---------------------------------------------------------------------------

def _is_image_mime(mime: str) -> bool:
    return (mime or "").lower().startswith("image/")


def _download_file(sb, storage_path: str) -> bytes:
    """Download a file's bytes from storage."""
    bucket = get_bucket_name()
    return sb.storage.from_(bucket).download(storage_path)


@admin_bp.route("/applications/<int:app_id>/files/<int:file_id>/view")
@admin_required
def view_file(app_id: int, file_id: int):
    """
    Stream a file inline so it renders inside an iframe / <img> on the
    review page (no new tab needed).
    """
    sb = get_supabase()
    row = (
        sb.table("application_files")
        .select("*")
        .eq("id", file_id)
        .eq("application_id", app_id)
        .single()
        .execute()
    ).data
    if not row:
        abort(404)

    try:
        data = _download_file(sb, row["storage_path"])
    except Exception:
        abort(404)

    mime = row.get("mime_type") or "application/octet-stream"
    resp = Response(data, mimetype=mime)
    resp.headers["Content-Disposition"] = (
        f'inline; filename="{row.get("file_name","document")}"'
    )
    # Allow embedding in our own iframe.
    resp.headers["X-Frame-Options"] = "SAMEORIGIN"
    return resp


@admin_bp.route("/applications/<int:app_id>/print-packet")
@admin_required
def print_packet(app_id: int):
    """
    Build and return a single PDF containing every uploaded document
    for this application, with images rendered onto generated pages.
    """
    sb = get_supabase()
    app_row = (
        sb.table("applications")
        .select("id, education_level, year_level, "
                "student:profiles!applications_student_id_fkey(id, full_name)")
        .eq("id", app_id)
        .single()
        .execute()
    ).data
    if not app_row:
        abort(404)

    files = (
        sb.table("application_files")
        .select("*")
        .eq("application_id", app_id)
        .order("uploaded_at", desc=False)
        .execute()
    ).data or []

    # Latest file per slot, in a stable order matching the student page.
    latest_by_slot: dict[str, dict] = {}
    for f in sorted(files, key=lambda r: r.get("uploaded_at") or ""):
        slot = f.get("slot")
        if slot:
            latest_by_slot[slot] = f

    docs = []
    for slot in SLOT_LABELS.keys():
        f = latest_by_slot.get(slot)
        if not f:
            continue
        try:
            data = _download_file(sb, f["storage_path"])
        except Exception:
            continue
        mime = (f.get("mime_type") or "").lower()
        kind = "image" if _is_image_mime(mime) else "pdf"
        docs.append({
            "label": SLOT_LABELS.get(slot, slot),
            "kind":  kind,
            "bytes": data,
        })

    if not docs:
        flash("No documents to print yet.", "error")
        return redirect(url_for("admin.review", app_id=app_id))

    student_name = (app_row.get("student") or {}).get("full_name") or "Student"
    pdf_bytes = build_packet(
        student_name=student_name,
        level_label=LEVEL_LABELS.get(app_row.get("education_level"), ""),
        year_label=YEAR_LABELS.get(app_row.get("year_level"), ""),
        documents=docs,
    )

    safe_name = student_name.replace(" ", "_") or "applicant"
    return send_file(
        io.BytesIO(pdf_bytes),
        mimetype="application/pdf",
        as_attachment=False,
        download_name=f"{safe_name}_application_packet.pdf",
    )
