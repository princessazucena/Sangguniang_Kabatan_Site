"""
Admin → Certificates sidebar button.

For each Pay-out and General Orientation announcement, the admin can:

* Browse the design preview.
* Open a print-ready batch page — one Certificate of Attendance per
  joiner, automatically pre-filled from the event details. The browser's
  Print → Save as PDF flow then produces the final document.
"""
from datetime import datetime, timedelta, timezone

from flask import render_template, request, abort, flash, redirect, url_for

from supabase_client import get_supabase
from services.announcements import CATEGORY_LABELS, annotate, schedule_status

from ._common import admin_bp, admin_required


# Categories that issue Certificates of Attendance. Joiners on these
# announcements are the eligible recipients.
CERTIFICATE_EVENT_CATEGORIES = ("payout", "general_orientation")

PH_TZ = timezone(timedelta(hours=8))

# Default text we splash on placeholders. The admin can wire actual
# values in later via env / settings.
DEFAULT_BARANGAY = "Bukal"
DEFAULT_CITY     = "Tayabas City"
DEFAULT_PROVINCE = "Quezon"


_TITLE_BY_CATEGORY = {
    "payout":              "CERTIFICATE OF ATTENDANCE",
    "general_orientation": "CERTIFICATE OF ATTENDANCE",
}

_NARRATIVE_KIND_BY_CATEGORY = {
    "payout":              "Scholarship Pay-Out",
    "general_orientation": "General Orientation",
}


def _format_event_date(start_at, end_at) -> str:
    """Render the event date(s) in PH local time, e.g. 'April 27, 2026'."""
    def to_ph(value):
        if not value:
            return None
        try:
            dt = (value if isinstance(value, datetime)
                  else datetime.fromisoformat(str(value).replace("Z", "+00:00")))
        except ValueError:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(PH_TZ)

    s = to_ph(start_at)
    e = to_ph(end_at)
    if s and e:
        if s.date() == e.date():
            return s.strftime("%B %d, %Y")
        # multi-day event
        if s.year == e.year and s.month == e.month:
            return f"{s.strftime('%B %d')}–{e.strftime('%d, %Y')}"
        return f"{s.strftime('%B %d, %Y')} – {e.strftime('%B %d, %Y')}"
    if s:
        return s.strftime("%B %d, %Y")
    return ""


def _event_context(event: dict) -> dict:
    """Build the placeholder map that fills the certificate template."""
    return {
        "barangay":   DEFAULT_BARANGAY,
        "city":       DEFAULT_CITY,
        "province":   DEFAULT_PROVINCE,
        "event_title": event.get("title") or _NARRATIVE_KIND_BY_CATEGORY.get(
            event.get("category"), "Event"),
        "event_kind":  _NARRATIVE_KIND_BY_CATEGORY.get(event.get("category"), "Event"),
        "event_theme": "",  # admin can extend the schema later
        "event_date":  _format_event_date(event.get("start_at"), event.get("end_at")),
        "event_venue": f"{DEFAULT_BARANGAY}, {DEFAULT_CITY}",
        "title_text":  _TITLE_BY_CATEGORY.get(event.get("category"), "CERTIFICATE OF ATTENDANCE"),
        "sk_chairperson":   request.args.get("sk_chairperson") or "[Name of SK Chairperson]",
        "sk_secretary":     request.args.get("sk_secretary") or "[Name of SK Secretary]",
        "brgy_chairperson": request.args.get("brgy_chairperson") or "[Name of Barangay Chairperson]",
    }


def _participant_home(profile: dict) -> str:
    """Build a friendly 'home' line for the certificate body."""
    if not profile:
        return f"{DEFAULT_BARANGAY}, {DEFAULT_CITY}"
    parts = []
    if profile.get("address_purok"):
        parts.append(profile["address_purok"])
    bgy = profile.get("address_barangay") or DEFAULT_BARANGAY
    city = profile.get("address_city") or DEFAULT_CITY
    parts.append(bgy)
    parts.append(city)
    return ", ".join(parts)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@admin_bp.route("/certificates")
@admin_required
def certificates():
    """List events that can have certificates generated for them."""
    sb = get_supabase()

    events = (
        sb.table("announcements")
        .select("*")
        .in_("category", list(CERTIFICATE_EVENT_CATEGORIES))
        .order("start_at", desc=True)
        .execute()
    ).data or []
    annotate(events)

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
    Render a single certificate using the design template. Used both for
    the standalone preview link and the iframe inside the picker page.
    """
    ctx = _event_context({"category": "general_orientation"})
    ctx.update({
        "participant_name": request.args.get("participant_name") or "[NAME OF PARTICIPANT]",
        "home_purok":       request.args.get("home_purok") or "[Home Barangay/Purok]",
    })

    # Allow query-string overrides for the demo page.
    for key in ("event_title", "event_theme", "event_date",
                "event_venue", "barangay", "city", "province",
                "sk_chairperson", "sk_secretary", "brgy_chairperson",
                "title_text"):
        v = request.args.get(key)
        if v:
            ctx[key] = v

    return render_template("admin/certificate_template.html",
                           certificates=[ctx], single=True)


@admin_bp.route("/certificates/<int:event_id>/generate")
@admin_required
def generate_certificates(event_id: int):
    """
    Build a print-ready page with one certificate per joiner. The admin
    triggers the browser's Print dialog to save the batch as a PDF.
    """
    sb = get_supabase()
    event = (
        sb.table("announcements")
        .select("*")
        .eq("id", event_id)
        .single()
        .execute()
    ).data
    if not event:
        flash("Event not found.", "error")
        return redirect(url_for("admin.certificates"))

    if event.get("category") not in CERTIFICATE_EVENT_CATEGORIES:
        flash("Certificates can only be generated for Pay-out or "
              "General Orientation events.", "error")
        return redirect(url_for("admin.certificates"))

    event["status"] = schedule_status(event)
    base_ctx = _event_context(event)

    joins = (
        sb.table("announcement_joins")
        .select("joined_at, "
                "student:profiles!announcement_joins_student_id_fkey("
                "id, full_name, address_purok, address_barangay, "
                "address_city, address_province)")
        .eq("announcement_id", event_id)
        .order("joined_at", desc=False)
        .execute()
    ).data or []

    if not joins:
        flash("Walang sumali sa event na ito. Walang certificate na ma-generate.", "error")
        return redirect(url_for("admin.certificates", event_id=event_id))

    certificates = []
    for j in joins:
        student = j.get("student") or {}
        ctx = dict(base_ctx)
        ctx["participant_name"] = student.get("full_name") or "—"
        ctx["home_purok"]       = _participant_home(student)
        certificates.append(ctx)

    return render_template(
        "admin/certificate_template.html",
        certificates=certificates,
        single=False,
        event=event,
        event_label=CATEGORY_LABELS.get(event.get("category"), "Event"),
    )
