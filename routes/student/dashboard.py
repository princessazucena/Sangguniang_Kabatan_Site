"""
Student → Dashboard sidebar button.

Quick-glance overview for the logged-in student: open registration window,
counters for their own applications, latest announcements, and shortcuts
to common actions.
"""
from collections import Counter

from flask import render_template, session

from supabase_client import get_supabase
from services.announcements import (
    annotate, schedule_status, current_open_registration,
    JOINABLE_CATEGORIES,
)

from ._common import (
    student_bp, student_required,
    LEVEL_LABELS, YEAR_LABELS, LEVEL_SLOTS, REQUIREMENT_SLOTS,
    student_applications, application_for_open_window, files_by_slot,
    student_has_verified_application,
)


def _completion_percent(sb, app_row: dict) -> int:
    """Return how many required slots are uploaded, as a 0-100 percentage."""
    level = app_row.get("education_level")
    if not level or level not in LEVEL_SLOTS:
        return 0
    files = (
        sb.table("application_files")
        .select("slot")
        .eq("application_id", app_row["id"])
        .execute()
    ).data or []
    uploaded = {f["slot"] for f in files if f.get("slot")}
    required = LEVEL_SLOTS[level]
    if not required:
        return 0
    have = sum(1 for s in required if s in uploaded)
    return round(have * 100 / len(required))


@student_bp.route("/dashboard")
@student_required
def dashboard():
    sb = get_supabase()
    student_id = session["user_id"]

    applications = student_applications(sb, student_id)
    for a in applications:
        a["level_label"] = LEVEL_LABELS.get(a.get("education_level"), "—")
        a["year_label"]  = YEAR_LABELS.get(a.get("year_level"), "—")

    open_registration = current_open_registration(sb)
    open_app = application_for_open_window(
        applications, open_registration["id"] if open_registration else None,
    )

    # Once verified, the student is locked in for this cycle — hide the
    # open-registration banner and skip the active-application card.
    already_verified = student_has_verified_application(applications)
    if already_verified:
        open_registration = None
        open_app = None

    # Per-student status counts.
    status_counts = Counter(a.get("status") for a in applications)

    # Active application = the one tied to the open window if any,
    # otherwise the most recent. Show progress + missing slots.
    active = None if already_verified else (open_app or (applications[0] if applications else None))
    active_progress = 0
    active_missing: list[str] = []
    if active and active.get("education_level"):
        active_progress = _completion_percent(sb, active)
        # Compute the missing labels for a friendly checklist.
        files = (
            sb.table("application_files")
            .select("slot")
            .eq("application_id", active["id"])
            .execute()
        ).data or []
        uploaded = {f["slot"] for f in files if f.get("slot")}
        for slot in LEVEL_SLOTS[active["education_level"]]:
            if slot not in uploaded:
                active_missing.append(REQUIREMENT_SLOTS[slot]["label"])

    # Latest announcements, plus the student's own join records so we
    # can show a small "joined" badge on events.
    announcements = (
        sb.table("announcements")
        .select("*")
        .order("created_at", desc=True)
        .limit(6)
        .execute()
    ).data or []
    annotate(announcements)

    joinable_ids = [
        a["id"] for a in announcements
        if a.get("category") in JOINABLE_CATEGORIES
    ]
    joined_ids: set[int] = set()
    if joinable_ids:
        rows = (
            sb.table("announcement_joins")
            .select("announcement_id")
            .eq("student_id", student_id)
            .in_("announcement_id", joinable_ids)
            .execute()
        ).data or []
        joined_ids = {r["announcement_id"] for r in rows}

    # The student's own joined events (upcoming first), separately,
    # for the "My events" panel.
    joined_events: list[dict] = []
    join_rows = (
        sb.table("announcement_joins")
        .select("joined_at, "
                "announcement:announcements!announcement_joins_announcement_id_fkey(*)")
        .eq("student_id", student_id)
        .order("joined_at", desc=True)
        .limit(20)
        .execute()
    ).data or []
    for j in join_rows:
        anc = j.get("announcement") or {}
        if not anc:
            continue
        anc["status"] = schedule_status(anc)
        anc["joined_at"] = j.get("joined_at")
        joined_events.append(anc)
    joined_events.sort(
        key=lambda r: (r.get("status") != "open", r.get("start_at") or ""),
    )
    joined_events = joined_events[:4]

    return render_template(
        "student/dashboard.html",
        applications=applications,
        open_registration=open_registration,
        open_application=open_app,
        active_application=active,
        active_progress=active_progress,
        active_missing=active_missing,
        already_verified=already_verified,
        status_counts={
            "pending":  status_counts.get("pending", 0),
            "verified": status_counts.get("verified", 0),
            "rejected": status_counts.get("rejected", 0),
            "total":    len(applications),
        },
        announcements=announcements,
        joined_ids=joined_ids,
        joined_events=joined_events,
    )
