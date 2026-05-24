"""
Admin routes: dashboard, application review, announcements + joiners.
"""
import io
from datetime import datetime, timezone
from functools import wraps

from flask import (
    Blueprint, render_template, request, redirect,
    url_for, flash, session, send_file, Response, abort,
)

from supabase_client import get_supabase, get_bucket_name
from services.announcements import (
    CATEGORIES, CATEGORY_LABELS, annotate, schedule_status,
)
from services.print_packet import build_packet

admin_bp = Blueprint("admin", __name__)


def admin_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if session.get("role") != "admin":
            flash("Admins only.", "error")
            return redirect(url_for("public.login"))
        return view(*args, **kwargs)
    return wrapper


def _parse_dt_local(value: str):
    """Parse an HTML datetime-local string into a UTC ISO timestamp.
    Treats the input as the local timezone of the server clock."""
    if not value:
        return None
    try:
        # datetime-local format: YYYY-MM-DDTHH:MM (no tz)
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.isoformat()
    except ValueError:
        return None


@admin_bp.route("/dashboard")
@admin_required
def dashboard():
    sb = get_supabase()
    apps = (
        sb.table("applications")
        .select("id, status, created_at, reviewed_at, notes, "
                "student:profiles!applications_student_id_fkey(id, full_name)")
        .order("created_at", desc=True)
        .execute()
    ).data or []

    counts = {"pending": 0, "verified": 0, "rejected": 0}
    for a in apps:
        counts[a["status"]] = counts.get(a["status"], 0) + 1

    return render_template("admin/dashboard.html", applications=apps, counts=counts)


@admin_bp.route("/applications/<int:app_id>")
@admin_required
def review(app_id: int):
    sb = get_supabase()
    app_res = (
        sb.table("applications")
        .select("id, status, notes, created_at, reviewed_at, "
                "student:profiles!applications_student_id_fkey(id, full_name)")
        .eq("id", app_id)
        .single()
        .execute()
    )
    if not app_res.data:
        flash("Application not found.", "error")
        return redirect(url_for("admin.dashboard"))

    files = (
        sb.table("application_files")
        .select("*")
        .eq("application_id", app_id)
        .order("uploaded_at", desc=True)
        .execute()
    ).data or []

    bucket = get_bucket_name()
    for f in files:
        try:
            signed = sb.storage.from_(bucket).create_signed_url(
                f["storage_path"], 60 * 30  # 30 minutes
            )
            f["signed_url"] = signed.get("signedURL") or signed.get("signed_url")
        except Exception:
            f["signed_url"] = None

    return render_template("admin/review.html", app=app_res.data, files=files)


@admin_bp.route("/applications/<int:app_id>/decision", methods=["POST"])
@admin_required
def decide(app_id: int):
    decision = request.form.get("decision")
    notes = request.form.get("notes") or None
    if decision not in ("verified", "rejected"):
        flash("Invalid decision.", "error")
        return redirect(url_for("admin.review", app_id=app_id))

    sb = get_supabase()
    sb.table("applications").update({
        "status": decision,
        "notes": notes,
        "reviewed_by": session["user_id"],
        "reviewed_at": "now()",
    }).eq("id", app_id).execute()

    flash(f"Application marked as {decision}.", "success")
    return redirect(url_for("admin.review", app_id=app_id))


# ---------------------------------------------------------------------------
# Inline document viewer + print packet
# ---------------------------------------------------------------------------

# Slot labels mirror what the student side uses.
_SLOT_LABELS = {
    "card":      "Report Card",
    "cor":       "Certificate of Registration (COR)",
    "id":        "Valid School ID",
    "indigency": "Certificate of Indigency",
    "psa":       "PSA Birth Certificate",
}

_LEVEL_LABELS = {
    "senior_high": "Senior High School",
    "college":     "College",
}

_YEAR_LABELS = {
    "grade_11": "Grade 11",
    "grade_12": "Grade 12",
    "year_1":   "1st Year",
    "year_2":   "2nd Year",
    "year_3":   "3rd Year",
    "year_4":   "4th Year",
    "year_5":   "5th Year",
}


def _is_image_mime(mime: str) -> bool:
    return (mime or "").lower().startswith("image/")


def _download_file(sb, storage_path: str) -> bytes:
    """Download a file's bytes from storage."""
    bucket = get_bucket_name()
    return sb.storage.from_(bucket).download(storage_path)


@admin_bp.route("/applications/<int:app_id>/files/<int:file_id>/view")
@admin_required
def view_file(app_id: int, file_id: int):
    """
    Stream a file inline so it renders inside an iframe / <img> on the
    review page (no new tab needed).
    """
    sb = get_supabase()
    row = (
        sb.table("application_files")
        .select("*")
        .eq("id", file_id)
        .eq("application_id", app_id)
        .single()
        .execute()
    ).data
    if not row:
        abort(404)

    try:
        data = _download_file(sb, row["storage_path"])
    except Exception:
        abort(404)

    mime = row.get("mime_type") or "application/octet-stream"
    resp = Response(data, mimetype=mime)
    resp.headers["Content-Disposition"] = (
        f'inline; filename="{row.get("file_name","document")}"'
    )
    # Allow embedding in our own iframe.
    resp.headers["X-Frame-Options"] = "SAMEORIGIN"
    return resp


@admin_bp.route("/applications/<int:app_id>/print-packet")
@admin_required
def print_packet(app_id: int):
    """
    Build and return a single PDF containing every uploaded document
    for this application, with images rendered onto generated pages.
    """
    sb = get_supabase()
    app_row = (
        sb.table("applications")
        .select("id, education_level, year_level, "
                "student:profiles!applications_student_id_fkey(id, full_name)")
        .eq("id", app_id)
        .single()
        .execute()
    ).data
    if not app_row:
        abort(404)

    files = (
        sb.table("application_files")
        .select("*")
        .eq("application_id", app_id)
        .order("uploaded_at", desc=False)
        .execute()
    ).data or []

    # Latest file per slot, in a stable order matching the student page.
    latest_by_slot: dict[str, dict] = {}
    for f in sorted(files, key=lambda r: r.get("uploaded_at") or ""):
        slot = f.get("slot")
        if slot:
            latest_by_slot[slot] = f

    slot_order = list(_SLOT_LABELS.keys())
    docs = []
    for slot in slot_order:
        f = latest_by_slot.get(slot)
        if not f:
            continue
        try:
            data = _download_file(sb, f["storage_path"])
        except Exception:
            continue
        mime = (f.get("mime_type") or "").lower()
        kind = "image" if _is_image_mime(mime) else "pdf"
        docs.append({
            "label": _SLOT_LABELS.get(slot, slot),
            "kind":  kind,
            "bytes": data,
        })

    if not docs:
        flash("No documents to print yet.", "error")
        return redirect(url_for("admin.review", app_id=app_id))

    student_name = (app_row.get("student") or {}).get("full_name") or "Student"
    pdf_bytes = build_packet(
        student_name=student_name,
        level_label=_LEVEL_LABELS.get(app_row.get("education_level"), ""),
        year_label=_YEAR_LABELS.get(app_row.get("year_level"), ""),
        documents=docs,
    )

    safe_name = student_name.replace(" ", "_") or "applicant"
    return send_file(
        io.BytesIO(pdf_bytes),
        mimetype="application/pdf",
        as_attachment=False,
        download_name=f"{safe_name}_application_packet.pdf",
    )


# ---------------------------------------------------------------------------
# Announcements
# ---------------------------------------------------------------------------

@admin_bp.route("/announcements", methods=["GET", "POST"])
@admin_required
def announcements():
    sb = get_supabase()
    if request.method == "POST":
        title    = (request.form.get("title") or "").strip()
        body     = (request.form.get("body") or "").strip()
        category = (request.form.get("category") or "general").strip()
        start_at = _parse_dt_local(request.form.get("start_at") or "")
        end_at   = _parse_dt_local(request.form.get("end_at") or "")

        if category not in CATEGORIES:
            flash("Invalid category.", "error")
            return redirect(url_for("admin.announcements"))
        if not title or not body:
            flash("Title and body are required.", "error")
            return redirect(url_for("admin.announcements"))
        if category in ("registration", "payout"):
            if not start_at or not end_at:
                flash("Scheduled announcements need both a start and end date.", "error")
                return redirect(url_for("admin.announcements"))
            if start_at >= end_at:
                flash("End date must be after the start date.", "error")
                return redirect(url_for("admin.announcements"))

        sb.table("announcements").insert({
            "title":     title,
            "body":      body,
            "category":  category,
            "start_at":  start_at,
            "end_at":    end_at,
            "posted_by": session["user_id"],
        }).execute()
        flash("Announcement posted.", "success")
        return redirect(url_for("admin.announcements"))

    items = (
        sb.table("announcements")
        .select("*")
        .order("created_at", desc=True)
        .execute()
    ).data or []
    annotate(items)

    # Attach join counts for payout announcements.
    payout_ids = [a["id"] for a in items if a.get("category") == "payout"]
    counts = {pid: 0 for pid in payout_ids}
    if payout_ids:
        joins = (
            sb.table("announcement_joins")
            .select("announcement_id")
            .in_("announcement_id", payout_ids)
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

    if anc.get("category") != "payout":
        flash("Only pay-out announcements have joiners.", "error")
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
