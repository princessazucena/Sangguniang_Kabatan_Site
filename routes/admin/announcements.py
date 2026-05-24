"""
Admin → Announcements sidebar button.

Create / list / delete announcements, plus the joiners list for pay-out
announcements.
"""
import threading
from flask import render_template, request, redirect, url_for, flash, session, current_app

from supabase_client import get_supabase
from services.announcements import (
    CATEGORIES, CATEGORY_LABELS, JOINABLE_CATEGORIES, SCHEDULED_CATEGORIES,
    annotate, schedule_status,
)
from services.email import broadcast_announcement_email

from ._common import admin_bp, admin_required, parse_dt_local


def _broadcast_in_background(app, announcement: dict) -> None:
    """Email every student about a freshly-posted announcement.

    Runs in a daemon thread so the admin form submit doesn't block on a
    slow mail provider. We push a throwaway app context so any service
    code that calls ``current_app`` keeps working.
    """
    def _run():
        with app.app_context():
            try:
                sb = get_supabase()
                broadcast_announcement_email(sb, announcement)
            except Exception:
                # Never let a broadcast failure crash the worker thread.
                app.logger.exception("Announcement broadcast failed")
    threading.Thread(target=_run, daemon=True).start()


@admin_bp.route("/announcements", methods=["GET", "POST"])
@admin_required
def announcements():
    sb = get_supabase()
    if request.method == "POST":
        title    = (request.form.get("title") or "").strip()
        body     = (request.form.get("body") or "").strip()
        category = (request.form.get("category") or "general").strip()
        start_at = parse_dt_local(request.form.get("start_at") or "")
        end_at   = parse_dt_local(request.form.get("end_at") or "")
        notify_landing = bool(request.form.get("notify_landing"))
        notify_inapp   = bool(request.form.get("notify_inapp"))
        notify_email   = bool(request.form.get("notify_email"))

        if category not in CATEGORIES:
            flash("Invalid category.", "error")
            return redirect(url_for("admin.announcements"))
        if not title or not body:
            flash("Title and body are required.", "error")
            return redirect(url_for("admin.announcements"))
        if category in SCHEDULED_CATEGORIES:
            if not start_at or not end_at:
                flash("Scheduled announcements need both a start and end date.", "error")
                return redirect(url_for("admin.announcements"))
            if start_at >= end_at:
                flash("End date must be after the start date.", "error")
                return redirect(url_for("admin.announcements"))

        if not (notify_landing or notify_inapp or notify_email):
            flash("Pumili ng kahit isang channel para sa announcement.", "error")
            return redirect(url_for("admin.announcements"))

        sb.table("announcements").insert({
            "title":     title,
            "body":      body,
            "category":  category,
            "start_at":  start_at,
            "end_at":    end_at,
            "notify_landing": notify_landing,
            "notify_inapp":   notify_inapp,
            "notify_email":   notify_email,
            "posted_by": session["user_id"],
        }).execute()
        flash("Announcement posted.", "success")

        # Email every student in the background, but only when the email
        # channel is enabled for this announcement.
        if notify_email:
            try:
                latest = (
                    sb.table("announcements")
                    .select("*")
                    .eq("title", title)
                    .order("created_at", desc=True)
                    .limit(1)
                    .execute()
                ).data or []
                if latest:
                    _broadcast_in_background(current_app._get_current_object(), latest[0])
            except Exception:
                # Don't fail the admin flow if we can't kick off the email.
                current_app.logger.exception("Could not start announcement broadcast")

        return redirect(url_for("admin.announcements"))

    items = (
        sb.table("announcements")
        .select("*")
        .order("created_at", desc=True)
        .execute()
    ).data or []
    annotate(items)

    # Attach join counts for joinable announcements (payout + kk_assembly).
    joinable_ids = [
        a["id"] for a in items if a.get("category") in JOINABLE_CATEGORIES
    ]
    counts = {pid: 0 for pid in joinable_ids}
    if joinable_ids:
        joins = (
            sb.table("announcement_joins")
            .select("announcement_id")
            .in_("announcement_id", joinable_ids)
            .execute()
        ).data or []
        for j in joins:
            counts[j["announcement_id"]] = counts.get(j["announcement_id"], 0) + 1
    for a in items:
        a["join_count"] = counts.get(a["id"], 0)

    return render_template(
        "admin/announcements.html",
        announcements=items,
        category_labels=CATEGORY_LABELS,
    )


@admin_bp.route("/announcements/<int:anc_id>/joiners")
@admin_required
def announcement_joiners(anc_id: int):
    sb = get_supabase()
    anc = (
        sb.table("announcements").select("*").eq("id", anc_id).single().execute()
    ).data
    if not anc:
        flash("Announcement not found.", "error")
        return redirect(url_for("admin.announcements"))

    if anc.get("category") not in JOINABLE_CATEGORIES:
        flash("Only pay-out and KK assembly announcements have joiners.", "error")
        return redirect(url_for("admin.announcements"))

    anc["status"] = schedule_status(anc)

    joins = (
        sb.table("announcement_joins")
        .select("joined_at, "
                "student:profiles!announcement_joins_student_id_fkey(id, full_name)")
        .eq("announcement_id", anc_id)
        .order("joined_at", desc=True)
        .execute()
    ).data or []

    return render_template(
        "admin/announcement_joiners.html",
        announcement=anc,
        joins=joins,
    )


@admin_bp.route("/announcements/<int:anc_id>/delete", methods=["POST"])
@admin_required
def delete_announcement(anc_id: int):
    sb = get_supabase()
    sb.table("announcements").delete().eq("id", anc_id).execute()
    flash("Announcement deleted.", "success")
    return redirect(url_for("admin.announcements"))
