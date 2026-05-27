"""
Admin → Certificates sidebar button.

For each Pay-out and General Orientation announcement, the admin can:

* Browse the design preview.
* Open a print-ready batch page — one Certificate of Attendance per
  joiner, automatically pre-filled from the event details. The browser's
  Print → Save as PDF flow then produces the final document.
* Email each joiner an individual PDF copy of their certificate, either
  one at a time or for the whole event in one click.
"""
from datetime import datetime, timedelta, timezone

from flask import (
    render_template, request, abort, flash, redirect, url_for, jsonify,
    current_app,
)

from supabase_client import get_supabase
from services.announcements import CATEGORY_LABELS, annotate, schedule_status
from services.certificate_pdf import build_certificate_pdf
from services.email import get_student_email, send_certificate_email

from ._common import admin_bp, admin_required


# Categories that issue Certificates of Attendance. Joiners on these
# announcements are the eligible recipients.
CERTIFICATE_EVENT_CATEGORIES = ("payout", "general_orientation")

PH_TZ = timezone(timedelta(hours=8))

# Default text we splash on placeholders. The admin can wire actual
# values in later via env / settings.
DEFAULT_BARANGAY = "Bukal"
DEFAULT_CITY     = "Majayjay"
DEFAULT_PROVINCE = "Laguna"

# Default SK officials shown on the signature lines. The admin can
# override any of these via querystring (?sk_chairperson=...&...).
DEFAULT_SK_CHAIRPERSON   = "Alex Jene B. Azucena"
DEFAULT_SK_SECRETARY     = "[Name of SK Secretary]"
DEFAULT_BRGY_CHAIRPERSON = "[Name of Barangay Chairperson]"


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
        "event_venue": f"Brgy. {DEFAULT_BARANGAY}, {DEFAULT_CITY}, {DEFAULT_PROVINCE}",
        "title_text":  _TITLE_BY_CATEGORY.get(event.get("category"), "CERTIFICATE OF ATTENDANCE"),
        "sk_chairperson":   request.args.get("sk_chairperson") or DEFAULT_SK_CHAIRPERSON,
        "sk_secretary":     request.args.get("sk_secretary") or DEFAULT_SK_SECRETARY,
        "brgy_chairperson": request.args.get("brgy_chairperson") or DEFAULT_BRGY_CHAIRPERSON,
    }


def _participant_home() -> str:
    """The 'home' line is fixed for every joiner: residents of Brgy. Bukal."""
    return f"Barangay {DEFAULT_BARANGAY}"


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
        "home_purok":       request.args.get("home_purok") or _participant_home(),
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
        ctx["home_purok"]       = _participant_home()
        ctx["student_id"]       = student.get("id")
        certificates.append(ctx)

    return render_template(
        "admin/certificate_template.html",
        certificates=certificates,
        single=False,
        event=event,
        event_label=CATEGORY_LABELS.get(event.get("category"), "Event"),
    )


# ---------------------------------------------------------------------------
# Send-by-email actions
# ---------------------------------------------------------------------------


def _safe_filename(name: str) -> str:
    """Build a download-safe filename like 'Juan_Dela_Cruz_Certificate.pdf'."""
    cleaned = "".join(ch if ch.isalnum() else "_" for ch in (name or "").strip())
    cleaned = cleaned.strip("_") or "certificate"
    return f"{cleaned}_Certificate.pdf"


def _load_event_or_404(sb, event_id: int) -> dict:
    event = (
        sb.table("announcements")
        .select("*")
        .eq("id", event_id)
        .single()
        .execute()
    ).data
    if not event:
        abort(404, description="Event not found.")
    if event.get("category") not in CERTIFICATE_EVENT_CATEGORIES:
        abort(400, description="Certificates only available for "
                               "Pay-out or General Orientation events.")
    return event


def _build_ctx_for_student(event: dict, student: dict) -> dict:
    ctx = dict(_event_context(event))
    ctx["participant_name"] = student.get("full_name") or "—"
    ctx["home_purok"]       = _participant_home()
    return ctx


@admin_bp.route("/certificates/<int:event_id>/send/<student_id>", methods=["POST"])
@admin_required
def send_certificate_to_student(event_id: int, student_id: str):
    """Email a single joiner their Certificate of Attendance."""
    sb = get_supabase()
    event = _load_event_or_404(sb, event_id)

    join = (
        sb.table("announcement_joins")
        .select("student:profiles!announcement_joins_student_id_fkey("
                "id, full_name)")
        .eq("announcement_id", event_id)
        .eq("student_id", student_id)
        .limit(1)
        .execute()
    ).data or []
    student = (join[0].get("student") if join else None) or None
    if not student:
        return jsonify({"ok": False, "error": "Student is not a joiner of this event."}), 404

    email = get_student_email(sb, student_id)
    if not email:
        return jsonify({
            "ok": False,
            "error": "Walang nakitang email address para sa scholar na ito.",
        }), 422

    ctx = _build_ctx_for_student(event, student)
    try:
        pdf_bytes = build_certificate_pdf(ctx)
    except Exception:
        current_app.logger.exception("certificate PDF render failed")
        return jsonify({"ok": False, "error": "Hindi ma-render ang PDF."}), 500

    ok = send_certificate_email(
        to_email     = email,
        student_name = student.get("full_name") or "",
        event_title  = event.get("title") or "",
        event_kind   = ctx.get("event_kind") or "",
        pdf_bytes    = pdf_bytes,
        filename     = _safe_filename(student.get("full_name") or "certificate"),
    )
    if not ok:
        return jsonify({"ok": False, "error": "Hindi tinanggap ng mail provider."}), 502

    return jsonify({
        "ok": True,
        "email": email,
        "student": student.get("full_name") or "",
    })


@admin_bp.route("/certificates/<int:event_id>/send-all", methods=["POST"])
@admin_required
def send_certificates_bulk(event_id: int):
    """Email every joiner of an event their personal certificate PDF."""
    sb = get_supabase()
    event = _load_event_or_404(sb, event_id)

    joins = (
        sb.table("announcement_joins")
        .select("student:profiles!announcement_joins_student_id_fkey("
                "id, full_name)")
        .eq("announcement_id", event_id)
        .order("joined_at", desc=False)
        .execute()
    ).data or []

    sent: list[str] = []
    skipped: list[dict] = []

    for j in joins:
        student = j.get("student") or {}
        sid     = student.get("id")
        name    = student.get("full_name") or "Student"
        if not sid:
            skipped.append({"student": name, "reason": "missing id"})
            continue

        email = get_student_email(sb, sid)
        if not email:
            skipped.append({"student": name, "reason": "no email"})
            continue

        try:
            ctx = _build_ctx_for_student(event, student)
            pdf_bytes = build_certificate_pdf(ctx)
        except Exception:
            current_app.logger.exception("certificate PDF render failed for %s", sid)
            skipped.append({"student": name, "reason": "pdf error"})
            continue

        ok = send_certificate_email(
            to_email     = email,
            student_name = name,
            event_title  = event.get("title") or "",
            event_kind   = ctx.get("event_kind") or "",
            pdf_bytes    = pdf_bytes,
            filename     = _safe_filename(name),
        )
        if ok:
            sent.append(name)
        else:
            skipped.append({"student": name, "reason": "send failed"})

    return jsonify({
        "ok":      True,
        "sent":    len(sent),
        "skipped": skipped,
        "total":   len(joins),
    })
