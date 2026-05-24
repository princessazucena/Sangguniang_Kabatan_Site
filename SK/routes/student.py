"""
Student routes: dashboard, file upload, application status.
"""
import uuid
from functools import wraps

from flask import (
    Blueprint, render_template, request, redirect,
    url_for, flash, session,
)

from supabase_client import get_supabase, get_bucket_name

student_bp = Blueprint("student", __name__)


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


@student_bp.route("/dashboard")
@student_required
def dashboard():
    sb = get_supabase()
    student_id = session["user_id"]
    app_row = _get_or_create_application(sb, student_id)

    files = (
        sb.table("application_files")
        .select("*")
        .eq("application_id", app_row["id"])
        .order("uploaded_at", desc=True)
        .execute()
    ).data or []

    return render_template(
        "student/dashboard.html",
        application=app_row,
        files=files,
    )


@student_bp.route("/upload", methods=["POST"])
@student_required
def upload():
    sb = get_supabase()
    student_id = session["user_id"]
    app_row = _get_or_create_application(sb, student_id)

    f = request.files.get("document")
    if not f or not f.filename:
        flash("Please choose a file to upload.", "error")
        return redirect(url_for("student.dashboard"))

    safe_name = f.filename.replace("/", "_").replace("\\", "_")
    storage_path = f"{student_id}/{uuid.uuid4().hex}_{safe_name}"
    data = f.read()

    bucket = get_bucket_name()
    try:
        sb.storage.from_(bucket).upload(
            path=storage_path,
            file=data,
            file_options={
                "content-type": f.mimetype or "application/octet-stream",
                "upsert": "false",
            },
        )
    except Exception as exc:
        flash(f"Upload failed: {exc}", "error")
        return redirect(url_for("student.dashboard"))

    sb.table("application_files").insert({
        "application_id": app_row["id"],
        "student_id": student_id,
        "file_name": safe_name,
        "storage_path": storage_path,
        "mime_type": f.mimetype,
        "size_bytes": len(data),
    }).execute()

    # Re-open the application for review after a new upload.
    if app_row["status"] != "pending":
        sb.table("applications").update({
            "status": "pending",
            "reviewed_by": None,
            "reviewed_at": None,
        }).eq("id", app_row["id"]).execute()

    flash("File uploaded. An admin will review your application.", "success")
    return redirect(url_for("student.dashboard"))
