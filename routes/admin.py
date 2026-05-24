"""
Admin routes: dashboard, application review, announcements.
"""
from functools import wraps

from flask import (
    Blueprint, render_template, request, redirect,
    url_for, flash, session,
)

from supabase_client import get_supabase, get_bucket_name

admin_bp = Blueprint("admin", __name__)


def admin_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if session.get("role") != "admin":
            flash("Admins only.", "error")
            return redirect(url_for("public.login"))
        return view(*args, **kwargs)
    return wrapper


@admin_bp.route("/dashboard")
@admin_required
def dashboard():
    sb = get_supabase()
    apps = (
        sb.table("applications")
        .select("id, status, created_at, reviewed_at, notes, "
                "student:profiles!applications_student_id_fkey(id, full_name)")
        .order("created_at", desc=True)
        .execute()
    ).data or []

    counts = {"pending": 0, "verified": 0, "rejected": 0}
    for a in apps:
        counts[a["status"]] = counts.get(a["status"], 0) + 1

    return render_template("admin/dashboard.html", applications=apps, counts=counts)


@admin_bp.route("/applications/<int:app_id>")
@admin_required
def review(app_id: int):
    sb = get_supabase()
    app_res = (
        sb.table("applications")
        .select("id, status, notes, created_at, reviewed_at, "
                "student:profiles!applications_student_id_fkey(id, full_name)")
        .eq("id", app_id)
        .single()
        .execute()
    )
    if not app_res.data:
        flash("Application not found.", "error")
        return redirect(url_for("admin.dashboard"))

    files = (
        sb.table("application_files")
        .select("*")
        .eq("application_id", app_id)
        .order("uploaded_at", desc=True)
        .execute()
    ).data or []

    bucket = get_bucket_name()
    for f in files:
        try:
            signed = sb.storage.from_(bucket).create_signed_url(
                f["storage_path"], 60 * 30  # 30 minutes
            )
            f["signed_url"] = signed.get("signedURL") or signed.get("signed_url")
        except Exception:
            f["signed_url"] = None

    return render_template("admin/review.html", app=app_res.data, files=files)


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

    flash(f"Application marked as {decision}.", "success")
    return redirect(url_for("admin.review", app_id=app_id))


@admin_bp.route("/announcements", methods=["GET", "POST"])
@admin_required
def announcements():
    sb = get_supabase()
    if request.method == "POST":
        title = (request.form.get("title") or "").strip()
        body = (request.form.get("body") or "").strip()
        if not title or not body:
            flash("Title and body are required.", "error")
        else:
            sb.table("announcements").insert({
                "title": title,
                "body": body,
                "posted_by": session["user_id"],
            }).execute()
            flash("Announcement posted.", "success")
        return redirect(url_for("admin.announcements"))

    items = (
        sb.table("announcements")
        .select("*")
        .order("created_at", desc=True)
        .execute()
    ).data or []
    return render_template("admin/announcements.html", announcements=items)
