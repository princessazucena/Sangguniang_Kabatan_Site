"""
Student → Announcements sidebar button.

Lists every announcement and lets students join a pay-out window.
"""
from flask import render_template, redirect, url_for, flash, session

from supabase_client import get_supabase
from services.announcements import annotate, schedule_status, JOINABLE_CATEGORIES

from ._common import student_bp, student_required, student_applications, student_has_verified_application


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
    joined_ids: set[int] = set()
    joinable_ids = [
        a["id"] for a in items if a.get("category") in JOINABLE_CATEGORIES
    ]
    if joinable_ids:
        rows = (
            sb.table("announcement_joins")
            .select("announcement_id")
            .eq("student_id", student_id)
            .in_("announcement_id", joinable_ids)
            .execute()
        ).data or []
        joined_ids = {r["announcement_id"] for r in rows}

    already_verified = student_has_verified_application(
        student_applications(sb, student_id)
    )

    return render_template(
        "student/announcements.html",
        announcements=items,
        joined_ids=joined_ids,
        already_verified=already_verified,
    )


@student_bp.route("/announcements/<int:anc_id>/join", methods=["POST"])
@student_required
def join_payout(anc_id: int):
    sb = get_supabase()
    anc = (
        sb.table("announcements").select("*").eq("id", anc_id).single().execute()
    ).data
    if not anc or anc.get("category") not in JOINABLE_CATEGORIES:
        flash("That announcement does not accept joiners.", "error")
        return redirect(url_for("student.announcements"))

    if schedule_status(anc) != "open":
        flash("The join window for this announcement is not open.", "error")
        return redirect(url_for("student.announcements"))

    student_id = session["user_id"]
    try:
        sb.table("announcement_joins").insert({
            "announcement_id": anc_id,
            "student_id":      student_id,
        }).execute()
        if anc.get("category") == "kk_assembly":
            flash("You're on the list. See you at the KK assembly.", "success")
        else:
            flash("You're on the list. Check announcements again on the payout date.", "success")
    except Exception:
        # Likely a duplicate (unique constraint) — treat as success.
        flash("You already joined this event.", "success")

    return redirect(url_for("student.announcements"))
