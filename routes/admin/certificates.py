"""
Admin → Certificates sidebar button.

Lets the admin pick an event (currently KK Assemblies) and preview the
certificate template that will be used to generate documents for the
participants. Generation logic itself lives in a follow-up task — this
module only wires up the picker and the design preview.
"""
from flask import render_template, request

from supabase_client import get_supabase
from services.announcements import (
    CATEGORY_LABELS, JOINABLE_CATEGORIES, annotate,
)

from ._common import admin_bp, admin_required


# Categories the admin can pick from when generating certificates.
# Today, only KK assemblies issue certificates of attendance, but the
# picker is structured so we can add more event types later.
CERTIFICATE_EVENT_CATEGORIES = ("kk_assembly",)


@admin_bp.route("/certificates")
@admin_required
def certificates():
    """
    List events that can have certificates generated for them, plus a
    preview of the certificate design.
    """
    sb = get_supabase()

    events = (
        sb.table("announcements")
        .select("*")
        .in_("category", list(CERTIFICATE_EVENT_CATEGORIES))
        .order("start_at", desc=True)
        .execute()
    ).data or []
    annotate(events)

    # Joiner counts so the admin can see who's eligible for each event.
    counts: dict[int, int] = {e["id"]: 0 for e in events}
    if events:
        rows = (
            sb.table("announcement_joins")
            .select("announcement_id")
            .in_("announcement_id", [e["id"] for e in events])
            .execute()
        ).data or []
        for r in rows:
            aid = r["announcement_id"]
            counts[aid] = counts.get(aid, 0) + 1
    for e in events:
        e["join_count"] = counts.get(e["id"], 0)

    selected_id = request.args.get("event_id", type=int)
    selected = next((e for e in events if e["id"] == selected_id), None)

    return render_template(
        "admin/certificates.html",
        events=events,
        selected=selected,
        category_labels=CATEGORY_LABELS,
    )


@admin_bp.route("/certificates/preview")
@admin_required
def certificate_preview():
    """
    Render the certificate template alone, with placeholder text or with
    overrides supplied via querystring. The follow-up generator will
    call this same template to produce per-student documents.
    """
    ctx = {
        "barangay":         request.args.get("barangay") or "[Barangay Name]",
        "city":             request.args.get("city") or "[City/Municipality]",
        "province":         request.args.get("province") or "[Province]",
        "participant_name": request.args.get("participant_name") or "[NAME OF PARTICIPANT]",
        "home_purok":       request.args.get("home_purok") or "[Home Barangay/Purok]",
        "event_title":      request.args.get("event_title") or "[NAME/TITLE OF THE KK ASSEMBLY]",
        "event_theme":      request.args.get("event_theme") or "[Theme of the Assembly]",
        "event_date":       request.args.get("event_date") or "[Date, Year]",
        "event_venue":      request.args.get("event_venue") or "[Location/Venue, Barangay Name]",
        "sk_chairperson":   request.args.get("sk_chairperson") or "[Name of SK Chairperson]",
        "sk_secretary":     request.args.get("sk_secretary") or "[Name of SK Secretary]",
        "brgy_chairperson": request.args.get("brgy_chairperson") or "[Name of Barangay Chairperson]",
    }
    return render_template("admin/certificate_template.html", **ctx)
