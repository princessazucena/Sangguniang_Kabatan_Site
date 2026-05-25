"""
Admin → Announcements sidebar button.

Create / list / delete announcements, plus the joiners list for pay-out
announcements.
"""
import threading
from flask import render_template, request, redirect, url_for, flash, session, current_app

from supabase_client import get_supabase, get_bucket_name
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
    """
    Delete an announcement and any data tied to its window.

    For registration windows, this also wipes every application created
    against this announcement — pending, verified, or rejected — together
    with the uploaded files in Supabase storage. That way a deleted
    registration leaves no scholar records behind, so a previously
    verified student stops being a scholar.

    Pay-out / KK assembly joiners are removed automatically by the
    foreign-key cascade on ``announcement_joins``.
    """
    sb = get_supabase()

    anc = (
        sb.table("announcements")
        .select("id, category, title")
        .eq("id", anc_id)
        .single()
        .execute()
    ).data
    if not anc:
        flash("Announcement not found.", "error")
        return redirect(url_for("admin.announcements"))

    summary_bits: list[str] = []

    if anc.get("category") == "registration":
        # Find all applications attached to this registration first so we
        # can clean up storage objects + DB rows in the right order.
        apps = (
            sb.table("applications")
            .select("id")
            .eq("registration_id", anc_id)
            .execute()
        ).data or []
        app_ids = [a["id"] for a in apps]

        deleted_files = 0
        if app_ids:
            files = (
                sb.table("application_files")
                .select("id, storage_path")
                .in_("application_id", app_ids)
                .execute()
            ).data or []
            paths = [f["storage_path"] for f in files if f.get("storage_path")]
            if paths:
                try:
                    sb.storage.from_(get_bucket_name()).remove(paths)
                except Exception:
                    # Don't block the delete on storage hiccups; the
                    # rows are still removed and the blobs become orphans
                    # that we can sweep later.
                    current_app.logger.exception(
                        "Storage cleanup failed during registration delete"
                    )

            # application_files has on-delete cascade from applications,
            # but be explicit so this still works even if the schema ever
            # loses that cascade.
            sb.table("application_files").delete().in_("application_id", app_ids).execute()
            sb.table("applications").delete().in_("id", app_ids).execute()
            deleted_files = len(files)

        if app_ids:
            summary_bits.append(
                f"{len(app_ids)} application{'s' if len(app_ids) != 1 else ''}"
            )
        if deleted_files:
            summary_bits.append(
                f"{deleted_files} uploaded file{'s' if deleted_files != 1 else ''}"
            )

    sb.table("announcements").delete().eq("id", anc_id).execute()

    if summary_bits:
        flash(
            "Announcement deleted, along with " + ", ".join(summary_bits) + ".",
            "success",
        )
    else:
        flash("Announcement deleted.", "success")
    return redirect(url_for("admin.announcements"))
