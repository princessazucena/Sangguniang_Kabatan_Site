"""
Admin → Monitoring sidebar button.

Lists every verified application, grouped per registration window, plus
the joiner roster of every pay-out and General Orientation event. Both tabs
support a free-text search filter and are segregated per event so an old
window's data doesn't bleed into a new one.
"""
from flask import render_template, request

from supabase_client import get_supabase
from services.announcements import annotate, JOINABLE_CATEGORIES

from ._common import admin_bp, admin_required, LEVEL_LABELS, YEAR_LABELS


def _matches(haystacks: list[str], needle: str) -> bool:
    """Case-insensitive substring search across any provided field."""
    if not needle:
        return True
    n = needle.lower()
    return any(n in (s or "").lower() for s in haystacks)


@admin_bp.route("/monitoring")
@admin_required
def monitoring():
    sb = get_supabase()

    q_scholars = (request.args.get("q") or "").strip()
    q_joiners  = (request.args.get("qj") or "").strip()

    # ============================================================
    # Verified scholars — grouped per registration window
    # ============================================================
    verified = (
        sb.table("applications")
        .select("id, status, education_level, year_level, reviewed_at, created_at, "
                "registration_id, "
                "student:profiles!applications_student_id_fkey(id, full_name), "
                "registration:announcements!applications_registration_id_fkey("
                "id, title, start_at, end_at)")
        .eq("status", "verified")
        .order("reviewed_at", desc=True)
        .execute()
    ).data or []

    # Drop orphans: verified rows whose registration was deleted. They no
    # longer count toward scholar totals.
    verified = [v for v in verified if v.get("registration_id") is not None]

    # Decorate every row with display labels so the template stays clean.
    for v in verified:
        v["level_label"] = LEVEL_LABELS.get(v.get("education_level"), "—")
        v["year_label"]  = YEAR_LABELS.get(v.get("year_level"), "—")

    # Aggregates over the full set (ignored by search so the totals stay
    # honest — search only narrows what's *displayed* in each group).
    by_level: dict[str, int] = {}
    by_year:  dict[str, int] = {}
    unique_students: set[str] = set()
    for v in verified:
        by_level[v.get("education_level") or "—"] = (
            by_level.get(v.get("education_level") or "—", 0) + 1
        )
        by_year[v.get("year_level") or "—"] = (
            by_year.get(v.get("year_level") or "—", 0) + 1
        )
        sid = (v.get("student") or {}).get("id")
        if sid:
            unique_students.add(sid)

    # Group by registration. Use the registration id as the key so
    # different windows with the same title still get their own bucket.
    groups: dict = {}
    for v in verified:
        reg = v.get("registration") or {}
        key = reg.get("id") if reg else "_unscheduled"
        if key not in groups:
            groups[key] = {
                "id":         reg.get("id"),
                "title":      reg.get("title") or "Unscheduled",
                "start_at":   reg.get("start_at"),
                "end_at":     reg.get("end_at"),
                "items":      [],
                "total":      0,
            }
        groups[key]["total"] += 1

        # Apply the search filter only to what's listed inside the group.
        if _matches(
            [
                (v.get("student") or {}).get("full_name") or "",
                v.get("level_label"),
                v.get("year_label"),
            ],
            q_scholars,
        ):
            groups[key]["items"].append(v)

    # Sort groups by registration start date (newest first), then put
    # any "_unscheduled" bucket at the end.
    scholar_groups = sorted(
        groups.values(),
        key=lambda g: (g["id"] is None, g.get("start_at") or "0000"),
        reverse=True,
    )

    level_breakdown = [
        {"label": LEVEL_LABELS.get(k, k), "count": c}
        for k, c in sorted(by_level.items(), key=lambda kv: -kv[1])
    ]
    year_breakdown = [
        {"label": YEAR_LABELS.get(k, k), "count": c}
        for k, c in sorted(by_year.items(), key=lambda kv: -kv[1])
    ]

    # ============================================================
    # Joiners — pay-out + General Orientation events, each its own roster
    # ============================================================
    events = (
        sb.table("announcements")
        .select("*")
        .in_("category", list(JOINABLE_CATEGORIES))
        .order("start_at", desc=True)
        .execute()
    ).data or []
    annotate(events)

    event_ids = [e["id"] for e in events]
    join_rows = []
    if event_ids:
        join_rows = (
            sb.table("announcement_joins")
            .select("announcement_id, joined_at, "
                    "student:profiles!announcement_joins_student_id_fkey(id, full_name)")
            .in_("announcement_id", event_ids)
            .order("joined_at", desc=True)
            .execute()
        ).data or []

    joins_by_event: dict[int, list[dict]] = {eid: [] for eid in event_ids}
    for r in join_rows:
        joins_by_event.setdefault(r["announcement_id"], []).append(r)

    # Apply the joiners search to each event's roster, but always keep
    # the event card so admins can still see the count.
    event_groups: list[dict] = []
    for e in events:
        roster = joins_by_event.get(e["id"], [])
        filtered = [
            j for j in roster
            if _matches([(j.get("student") or {}).get("full_name") or ""], q_joiners)
        ]
        event_groups.append({
            "id":         e["id"],
            "title":      e.get("title") or "Untitled event",
            "category":   e.get("category"),
            "status":     e.get("status"),
            "start_at":   e.get("start_at"),
            "end_at":     e.get("end_at"),
            "join_count": len(roster),
            "joiners":    filtered,
        })

    total_joins = sum(g["join_count"] for g in event_groups)
    open_now    = sum(1 for g in event_groups if g["status"] == "open")
    payouts_count       = sum(1 for g in event_groups if g["category"] == "payout")
    orientation_count   = sum(1 for g in event_groups if g["category"] == "general_orientation")

    return render_template(
        "admin/monitoring.html",
        # Verified scholars
        scholar_groups=scholar_groups,
        verified_total=len(verified),
        verified_unique_students=len(unique_students),
        level_breakdown=level_breakdown,
        year_breakdown=year_breakdown,
        registration_count=len([g for g in scholar_groups if g["id"] is not None]),
        q_scholars=q_scholars,
        # Joiners
        event_groups=event_groups,
        total_joins=total_joins,
        events_total=len(event_groups),
        events_open=open_now,
        payouts_count=payouts_count,
        orientation_count=orientation_count,
        q_joiners=q_joiners,
    )
