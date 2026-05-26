"""
Admin → Announcements sidebar button.

Plain informational posts (category = ``general``). Each post has a title,
body, the channels it should reach, and an optional "Display until" date
that hides it from public/student feeds once the date passes.

Events (Registration / Pay-out / General Orientation) live in their own
sidebar button — see ``announcements.py``.
"""
import threading
from flask import (
    render_template, request, redirect, url_for, flash, session, current_app,
)

from supabase_client import get_supabase
from services.announcements import GENERAL_CATEGORY, filter_visible
from services.email import broadcast_announcement_email

from ._common import admin_bp, admin_required, parse_dt_local


def _broadcast_in_background(app, announcement: dict) -> None:
    """Email every active student about a freshly-posted announcement."""
    def _run():
        with app.app_context():
            try:
                sb = get_supabase()
                broadcast_announcement_email(sb, announcement)
            except Exception:
                app.logger.exception("Announcement broadcast failed")
    threading.Thread(target=_run, daemon=True).start()


@admin_bp.route("/general-announcements", methods=["GET", "POST"])
@admin_required
def general_announcements():
    sb = get_supabase()

    if request.method == "POST":
        title = (request.form.get("title") or "").strip()
        body  = (request.form.get("body") or "").strip()
        # "Display until" — optional, repurposes end_at.
        display_until = parse_dt_local(request.form.get("display_until") or "")
        notify_landing = bool(request.form.get("notify_landing"))
        notify_inapp   = bool(request.form.get("notify_inapp"))
        notify_email   = bool(request.form.get("notify_email"))

        if not title or not body:
            flash("Title and body are required.", "error")
            return redirect(url_for("admin.general_announcements"))

        if not (notify_landing or notify_inapp or notify_email):
            flash("Pumili ng kahit isang channel para sa announcement.", "error")
            return redirect(url_for("admin.general_announcements"))

        inserted = sb.table("announcements").insert({
            "title":          title,
            "body":           body,
            "category":       GENERAL_CATEGORY,
            "start_at":       None,
            "end_at":         display_until,
            "notify_landing": notify_landing,
            "notify_inapp":   notify_inapp,
            "notify_email":   notify_email,
            "posted_by":      session["user_id"],
        }).execute()
        new_id = (inserted.data or [{}])[0].get("id")

        flash("Announcement posted.", "success")

        if notify_email and new_id:
            try:
                latest = (
                    sb.table("announcements")
                    .select("*")
                    .eq("id", new_id)
                    .single()
                    .execute()
                ).data
                if latest:
                    _broadcast_in_background(
                        current_app._get_current_object(), latest,
                    )
            except Exception:
                current_app.logger.exception("Could not start announcement broadcast")

        return redirect(url_for("admin.general_announcements"))

    items = (
        sb.table("announcements")
        .select("*")
        .eq("category", GENERAL_CATEGORY)
        .order("created_at", desc=True)
        .execute()
    ).data or []

    # Mark whether each post is still within its display window so the
    # admin sees an "Expired" badge instead of having to read the date.
    visible_ids = {a["id"] for a in filter_visible(items)}
    for a in items:
        a["is_visible"] = a["id"] in visible_ids

    return render_template(
        "admin/general_announcements.html",
        announcements=items,
    )


@admin_bp.route("/general-announcements/<int:anc_id>/delete", methods=["POST"])
@admin_required
def delete_general_announcement(anc_id: int):
    sb = get_supabase()
    row = (
        sb.table("announcements")
        .select("id, category")
        .eq("id", anc_id)
        .single()
        .execute()
    ).data
    if not row:
        flash("Announcement not found.", "error")
        return redirect(url_for("admin.general_announcements"))
    if row.get("category") != GENERAL_CATEGORY:
        flash("This post is an event, not an announcement.", "error")
        return redirect(url_for("admin.general_announcements"))

    sb.table("announcements").delete().eq("id", anc_id).execute()
    flash("Announcement deleted.", "success")
    return redirect(url_for("admin.general_announcements"))
