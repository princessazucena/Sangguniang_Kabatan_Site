"""
Student → My profile sidebar button.

Read-only profile view with email pulled from the auth user and a list
of past applications for context.
"""
from flask import render_template, session

from supabase_client import get_supabase

from ._common import (
    student_bp, student_required,
    LEVEL_LABELS, YEAR_LABELS, student_applications,
)


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

    applications = student_applications(sb, student_id)
    for a in applications:
        a["level_label"] = LEVEL_LABELS.get(a.get("education_level"), "—")
        a["year_label"]  = YEAR_LABELS.get(a.get("year_level"), "—")

    return render_template(
        "student/profile.html",
        profile=prof,
        email=email,
        applications=applications,
    )
