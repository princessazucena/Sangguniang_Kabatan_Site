"""
Admin → Monitoring sidebar button.

Aggregates verified scholars (with level / year / registration breakdowns)
and the joiner counts of every pay-out announcement.
"""
from flask import render_template

from supabase_client import get_supabase
from services.announcements import annotate

from ._common import admin_bp, admin_required, LEVEL_LABELS, YEAR_LABELS


@admin_bp.route("/monitoring")
@admin_required
def monitoring():
    sb = get_supabase()

    # ----- Verified scholars -----
    verified = (
        sb.table("applications")
        .select("id, status, education_level, year_level, reviewed_at, created_at, "
                "student:profiles!applications_student_id_fkey(id, full_name), "
                "registration:announcements!applications_registration_id_fkey("
                "id, title, start_at, end_at)")
        .eq("status", "verified")
        .order("reviewed_at", desc=True)
        .execute()
    ).data or []

    by_level: dict[str, int] = {}
    by_year:  dict[str, int] = {}
    by_reg:   dict[str, int] = {}
    unique_students: set[str] = set()
    for v in verified:
        lvl = v.get("education_level") or "—"
        yr  = v.get("year_level") or "—"
        by_level[lvl] = by_level.get(lvl, 0) + 1
        by_year[yr]   = by_year.get(yr, 0) + 1
        reg = (v.get("registration") or {}).get("title") or "Unscheduled"
        by_reg[reg] = by_reg.get(reg, 0) + 1
        sid = (v.get("student") or {}).get("id")
        if sid:
            unique_students.add(sid)

        v["level_label"] = LEVEL_LABELS.get(v.get("education_level"), "—")
        v["year_label"]  = YEAR_LABELS.get(v.get("year_level"), "—")

    level_breakdown = [
        {"label": LEVEL_LABELS.get(k, k), "count": c}
        for k, c in sorted(by_level.items(), key=lambda kv: -kv[1])
    ]
    year_breakdown = [
        {"label": YEAR_LABELS.get(k, k), "count": c}
        for k, c in sorted(by_year.items(), key=lambda kv: -kv[1])
    ]
    registration_breakdown = [
        {"label": k, "count": c}
        for k, c in sorted(by_reg.items(), key=lambda kv: -kv[1])
    ]

    # ----- Pay-out announcements + joiner counts -----
    payouts = (
        sb.table("announcements")
        .select("*")
        .eq("category", "payout")
        .order("start_at", desc=True)
        .execute()
    ).data or []
    annotate(payouts)

    joiner_counts: dict[int, int] = {p["id"]: 0 for p in payouts}
    if payouts:
        join_rows = (
            sb.table("announcement_joins")
            .select("announcement_id")
            .in_("announcement_id", [p["id"] for p in payouts])
            .execute()
        ).data or []
        for r in join_rows:
            aid = r["announcement_id"]
            joiner_counts[aid] = joiner_counts.get(aid, 0) + 1
    for p in payouts:
        p["join_count"] = joiner_counts.get(p["id"], 0)

    return render_template(
        "admin/monitoring.html",
        verified=verified,
        verified_total=len(verified),
        verified_unique_students=len(unique_students),
        level_breakdown=level_breakdown,
        year_breakdown=year_breakdown,
        registration_breakdown=registration_breakdown,
        payouts=payouts,
        total_joins=sum(joiner_counts.values()),
    )
