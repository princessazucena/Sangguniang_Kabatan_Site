"""
Admin → Dashboard sidebar button.

Top-of-the-funnel overview: at-a-glance counters, quick actions, and a
handful of analytics charts driven by the data already in Supabase.
This is the landing page after an admin logs in.
"""
from collections import Counter
from datetime import datetime, timedelta, timezone

from flask import render_template

from supabase_client import get_supabase
from services.announcements import (
    annotate, schedule_status, current_open_registration,
    JOINABLE_CATEGORIES,
)

from ._common import (
    admin_bp, admin_required,
    LEVEL_LABELS, YEAR_LABELS,
    submitted_application_ids,
)


def _parse_iso(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


@admin_bp.route("/dashboard")
@admin_required
def dashboard():
    sb = get_supabase()

    # ---------------- Students -----------------------------------------
    student_rows = (
        sb.table("profiles")
        .select("id, role, is_active, created_at")
        .eq("role", "student")
        .execute()
    ).data or []
    students_total      = len(student_rows)
    students_active     = sum(
        1 for s in student_rows
        if s.get("is_active") in (True, None)
    )
    students_deactivated = students_total - students_active

    # ---------------- Applications (full set, with files) --------------
    all_apps = (
        sb.table("applications")
        .select("id, status, education_level, year_level, created_at, reviewed_at, "
                "registration_id")
        .order("created_at", desc=True)
        .execute()
    ).data or []
    submitted_ids = submitted_application_ids(sb)
    # Drop orphans (registration deleted) and keep only fully submitted.
    apps = [
        a for a in all_apps
        if a["id"] in submitted_ids and a.get("registration_id") is not None
    ]

    status_counts = Counter(a["status"] for a in apps)
    pending_count   = status_counts.get("pending", 0)
    verified_count  = status_counts.get("verified", 0)
    rejected_count  = status_counts.get("rejected", 0)

    level_counts = Counter(
        LEVEL_LABELS.get(a.get("education_level"), "Unknown") for a in apps
    )
    year_counts  = Counter(
        YEAR_LABELS.get(a.get("year_level"), "Unknown") for a in apps
    )

    # ---------------- Trend: applications submitted in last 14 days -----
    today_ph = datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=8)))
    today_ph = today_ph.replace(hour=0, minute=0, second=0, microsecond=0)
    days = [today_ph - timedelta(days=i) for i in range(13, -1, -1)]
    bucket: dict[str, int] = {d.strftime("%Y-%m-%d"): 0 for d in days}
    for a in apps:
        dt = _parse_iso(a.get("created_at"))
        if not dt:
            continue
        ph = dt.astimezone(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")
        if ph in bucket:
            bucket[ph] += 1
    trend_labels = [d.strftime("%b %d") for d in days]
    trend_values = [bucket[d.strftime("%Y-%m-%d")] for d in days]

    # ---------------- Announcements + joiners --------------------------
    announcements = (
        sb.table("announcements")
        .select("*")
        .order("created_at", desc=True)
        .execute()
    ).data or []
    annotate(announcements)

    cat_counts = Counter(a.get("category") or "general" for a in announcements)

    join_rows = (
        sb.table("announcement_joins")
        .select("announcement_id")
        .execute()
    ).data or []
    join_per_anc: dict[int, int] = Counter(r["announcement_id"] for r in join_rows)

    joinable_announcements = [
        a for a in announcements
        if a.get("category") in JOINABLE_CATEGORIES
    ]
    for a in joinable_announcements:
        a["join_count"] = join_per_anc.get(a["id"], 0)

    upcoming_events = sorted(
        [a for a in announcements
         if a.get("category") in JOINABLE_CATEGORIES
         and schedule_status(a) in ("open", "upcoming")],
        key=lambda r: r.get("start_at") or "",
    )[:4]

    # Most-joined events (top 5 by joiners count) for a quick chart.
    top_events = sorted(
        joinable_announcements,
        key=lambda r: r.get("join_count", 0),
        reverse=True,
    )[:5]

    # ---------------- Recent activity ----------------------------------
    recent_apps = sorted(
        [a for a in apps if a.get("created_at")],
        key=lambda r: r["created_at"],
        reverse=True,
    )[:5]
    if recent_apps:
        student_ids = list({a.get("student_id") for a in recent_apps if a.get("student_id")})
        # ``apps`` query above didn't include student_id — fetch a hydrated
        # set just for the recent slice.
        ids = [a["id"] for a in recent_apps]
        hydrated = (
            sb.table("applications")
            .select("id, status, created_at, "
                    "student:profiles!applications_student_id_fkey(id, full_name), "
                    "registration:announcements!applications_registration_id_fkey("
                    "id, title)")
            .in_("id", ids)
            .execute()
        ).data or []
        # Preserve order from recent_apps.
        order = {aid: idx for idx, aid in enumerate(ids)}
        recent_apps = sorted(hydrated, key=lambda r: order.get(r["id"], 999))

    open_registration = current_open_registration(sb)

    return render_template(
        "admin/dashboard.html",
        # quick stats
        students_total=students_total,
        students_active=students_active,
        students_deactivated=students_deactivated,
        applications_total=len(apps),
        pending_count=pending_count,
        verified_count=verified_count,
        rejected_count=rejected_count,
        announcements_total=len(announcements),
        events_total=len(joinable_announcements),
        joiners_total=sum(join_per_anc.values()),
        # data for charts (use neutral key names so they don't clash with
        # built-in dict methods when accessed as `chart.values` in Jinja)
        status_chart={
            "categories": ["Pending", "Verified", "Rejected"],
            "series":     [pending_count, verified_count, rejected_count],
        },
        level_chart={
            "categories": list(level_counts.keys()),
            "series":     list(level_counts.values()),
        },
        year_chart={
            "categories": list(year_counts.keys()),
            "series":     list(year_counts.values()),
        },
        trend_chart={
            "categories": trend_labels,
            "series":     trend_values,
        },
        category_chart={
            "categories": [c.replace("_", " ").title() for c in cat_counts.keys()],
            "series":     list(cat_counts.values()),
        },
        top_events_chart={
            "categories": [e.get("title", "")[:24] for e in top_events],
            "series":     [e.get("join_count", 0) for e in top_events],
        },
        # lists
        recent_apps=recent_apps,
        upcoming_events=upcoming_events,
        open_registration=open_registration,
    )
