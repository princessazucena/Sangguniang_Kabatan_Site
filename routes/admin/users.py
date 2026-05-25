"""
Admin → User management sidebar button.

Lists every student profile, shows a per-student detail page (profile,
applications, pay-out joins), and provides activate / deactivate / delete
actions.
"""
from flask import render_template, request, redirect, url_for, flash

from supabase_client import get_supabase, get_bucket_name

from ._common import (
    admin_bp, admin_required, LEVEL_LABELS, YEAR_LABELS,
    submitted_application_ids,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _auth_emails_by_id(sb) -> dict[str, str]:
    """
    Pull every auth user's email and index them by id so we can stitch
    emails into the profile rows. Supabase paginates the admin list, so we
    walk pages until we run out.
    """
    out: dict[str, str] = {}
    page = 1
    while True:
        try:
            res = sb.auth.admin.list_users(page=page, per_page=200)
        except TypeError:
            # Older client signature: list_users() returns everything at once.
            res = sb.auth.admin.list_users()
            users = getattr(res, "users", None) or res or []
            for u in users:
                if getattr(u, "id", None):
                    out[u.id] = (u.email or "").lower()
            return out
        users = getattr(res, "users", None) or res or []
        if not users:
            break
        for u in users:
            if getattr(u, "id", None):
                out[u.id] = (u.email or "").lower()
        if len(users) < 200:
            break
        page += 1
    return out


def _get_student_profile(sb, student_id: str) -> dict | None:
    res = (
        sb.table("profiles")
        .select("id, full_name, first_name, middle_name, last_name, suffix, "
                "facebook_url, role, is_active, email_verified, created_at, "
                "address_house_no, address_street, address_purok, "
                "address_barangay, address_city, address_province, address_zip")
        .eq("id", student_id)
        .eq("role", "student")
        .limit(1)
        .execute()
    )
    rows = res.data or []
    return rows[0] if rows else None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@admin_bp.route("/users")
@admin_required
def users():
    """List every student account with status + quick actions."""
    sb = get_supabase()

    profiles = (
        sb.table("profiles")
        .select("id, full_name, first_name, last_name, role, is_active, "
                "email_verified, created_at")
        .eq("role", "student")
        .order("created_at", desc=True)
        .execute()
    ).data or []

    emails = _auth_emails_by_id(sb)

    # Application counts in one shot so we don't issue N queries.
    # Only count fully-submitted applications (level chosen + every
    # required slot uploaded), so empty drafts and partial uploads don't
    # inflate the per-student count.
    app_counts: dict[str, int] = {}
    if profiles:
        student_ids = [p["id"] for p in profiles]
        app_rows = (
            sb.table("applications")
            .select("id, student_id")
            .in_("student_id", student_ids)
            .execute()
        ).data or []
        if app_rows:
            complete_ids = submitted_application_ids(sb, [r["id"] for r in app_rows])
            for r in app_rows:
                if r["id"] in complete_ids:
                    sid = r["student_id"]
                    app_counts[sid] = app_counts.get(sid, 0) + 1

    counts = {"total": len(profiles), "active": 0, "deactivated": 0}
    for p in profiles:
        p["email"]      = emails.get(p["id"], "")
        p["app_count"]  = app_counts.get(p["id"], 0)
        # Treat missing flag as active for legacy rows.
        p["is_active"]  = p.get("is_active") if p.get("is_active") is not None else True
        if p["is_active"]:
            counts["active"] += 1
        else:
            counts["deactivated"] += 1

    q = (request.args.get("q") or "").strip().lower()
    if q:
        def _hit(p):
            haystack = " ".join([
                p.get("full_name") or "",
                p.get("first_name") or "",
                p.get("last_name") or "",
                p.get("email") or "",
            ]).lower()
            return q in haystack
        filtered = [p for p in profiles if _hit(p)]
    else:
        filtered = profiles

    return render_template(
        "admin/users.html",
        students=filtered,
        counts=counts,
        query=q,
    )


@admin_bp.route("/users/<student_id>")
@admin_required
def user_detail(student_id: str):
    """Full detail page for a single student."""
    sb = get_supabase()
    prof = _get_student_profile(sb, student_id)
    if not prof:
        flash("Student not found.", "error")
        return redirect(url_for("admin.users"))

    # Email straight from auth so we always show the address they log in with.
    email = ""
    try:
        user_res = sb.auth.admin.get_user_by_id(student_id)
        email = (user_res.user.email if getattr(user_res, "user", None) else "") or ""
    except Exception:
        email = ""
    prof["email"] = email
    if prof.get("is_active") is None:
        prof["is_active"] = True

    applications = (
        sb.table("applications")
        .select("id, status, education_level, year_level, notes, "
                "created_at, reviewed_at, registration_id, "
                "registration:announcements!applications_registration_id_fkey("
                "id, title, start_at, end_at)")
        .eq("student_id", student_id)
        .order("created_at", desc=True)
        .execute()
    ).data or []

    # Drop orphan applications (registration was deleted) so they don't
    # show up here either.
    applications = [a for a in applications if a.get("registration_id") is not None]

    # Only show applications the student has fully submitted (every
    # required slot uploaded for the chosen level).
    if applications:
        complete_ids = submitted_application_ids(sb, [a["id"] for a in applications])
        applications = [a for a in applications if a["id"] in complete_ids]

    for a in applications:
        a["level_label"] = LEVEL_LABELS.get(a.get("education_level"), "—")
        a["year_label"]  = YEAR_LABELS.get(a.get("year_level"), "—")

    payout_joins = (
        sb.table("announcement_joins")
        .select("joined_at, "
                "announcement:announcements!announcement_joins_announcement_id_fkey("
                "id, title, start_at, end_at, category)")
        .eq("student_id", student_id)
        .order("joined_at", desc=True)
        .execute()
    ).data or []

    return render_template(
        "admin/user_detail.html",
        student=prof,
        applications=applications,
        payout_joins=payout_joins,
    )


@admin_bp.route("/users/<student_id>/status", methods=["POST"])
@admin_required
def user_set_status(student_id: str):
    """Activate or deactivate a student account."""
    sb = get_supabase()
    prof = _get_student_profile(sb, student_id)
    if not prof:
        flash("Student not found.", "error")
        return redirect(url_for("admin.users"))

    action = (request.form.get("action") or "").strip().lower()
    if action not in {"activate", "deactivate"}:
        flash("Invalid action.", "error")
        return redirect(url_for("admin.user_detail", student_id=student_id))

    new_value = action == "activate"
    sb.table("profiles").update({"is_active": new_value}).eq("id", student_id).execute()

    flash(
        "Account activated." if new_value else "Account deactivated. They can no longer log in.",
        "success",
    )
    return redirect(url_for("admin.user_detail", student_id=student_id))


@admin_bp.route("/users/<student_id>/delete", methods=["POST"])
@admin_required
def user_delete(student_id: str):
    """Permanently delete a student account, profile + auth user."""
    sb = get_supabase()
    prof = _get_student_profile(sb, student_id)
    if not prof:
        flash("Student not found.", "error")
        return redirect(url_for("admin.users"))

    # Profiles cascade-delete applications + uploads via FKs. Best-effort
    # cleanup of stored files first so the bucket doesn't keep orphans.
    try:
        files = (
            sb.table("application_files")
            .select("storage_path")
            .eq("student_id", student_id)
            .execute()
        ).data or []
        if files:
            bucket = get_bucket_name()
            paths = [f["storage_path"] for f in files if f.get("storage_path")]
            if paths:
                try:
                    sb.storage.from_(bucket).remove(paths)
                except Exception:
                    # Don't block the delete if bucket cleanup hiccups.
                    pass
    except Exception:
        pass

    # Drop the auth user; the profile row goes with it via ON DELETE CASCADE.
    try:
        sb.auth.admin.delete_user(student_id)
    except Exception as exc:
        # If the auth side fails, fall back to deleting the profile so the
        # student at least disappears from admin views.
        sb.table("profiles").delete().eq("id", student_id).execute()
        flash(f"Profile removed, but auth deletion warning: {exc}", "error")
        return redirect(url_for("admin.users"))

    flash(f"Deleted student account ({prof.get('full_name') or student_id}).", "success")
    return redirect(url_for("admin.users"))
