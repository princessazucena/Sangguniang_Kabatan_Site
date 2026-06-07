"""
Student → Announcements sidebar button.

Lists every announcement and lets students join a pay-out / general
orientation window. Joining requires an e-signature so the admin's
monitoring sheet doubles as an attendance proof.
"""
from datetime import datetime, timezone

from flask import render_template, request, redirect, url_for, flash, session

from supabase_client import get_supabase
from services.announcements import (
    annotate, schedule_status, JOINABLE_CATEGORIES, filter_visible,
    student_joined_orientation,
)

from ._common import student_bp, student_required, student_applications, student_has_verified_application


# Reasonable upper bound on a base64-encoded signature image. The pad
# in the modal produces small PNGs (~10–40 KB), but we leave room for
# tablets with larger canvases.
_MAX_SIGNATURE_BYTES = 200 * 1024  # 200 KB


def _is_valid_signature(value: str) -> bool:
    """A signature is a data URL of a PNG/JPEG image, capped in size."""
    if not value or not isinstance(value, str):
        return False
    if not value.startswith("data:image/"):
        return False
    if len(value) > _MAX_SIGNATURE_BYTES:
        return False
    return ";base64," in value


@student_bp.route("/announcements")
@student_required
def announcements():
    sb = get_supabase()
    items = (
        sb.table("announcements")
        .select("*")
        .order("created_at", desc=True)
        .limit(50)
        .execute()
    ).data or []
    items = filter_visible(items)
    annotate(items)

    student_id = session["user_id"]
    joined_ids: set[int] = set()
    joinable_ids = [
        a["id"] for a in items if a.get("category") in JOINABLE_CATEGORIES
    ]
    if joinable_ids:
        rows = (
            sb.table("announcement_joins")
            .select("announcement_id")
            .eq("student_id", student_id)
            .in_("announcement_id", joinable_ids)
            .execute()
        ).data or []
        joined_ids = {r["announcement_id"] for r in rows}

    already_verified = student_has_verified_application(
        student_applications(sb, student_id)
    )
    
    # Build a map of event_id -> required_orientation attendance status
    orientation_status = {}
    for a in items:
        required_orientation_id = a.get("required_orientation_id")
        if required_orientation_id and a.get("category") == "payout":
            # Check if student attended the required orientation
            attended = student_joined_orientation(sb, student_id, required_orientation_id)
            orientation_status[a["id"]] = {
                "required_id": required_orientation_id,
                "attended": attended,
            }

    return render_template(
        "student/announcements.html",
        announcements=items,
        joined_ids=joined_ids,
        already_verified=already_verified,
        orientation_status=orientation_status,
    )


@student_bp.route("/announcements/<int:anc_id>/join", methods=["POST"])
@student_required
def join_payout(anc_id: int):
    sb = get_supabase()
    anc = (
        sb.table("announcements").select("*").eq("id", anc_id).single().execute()
    ).data
    if not anc or anc.get("category") not in JOINABLE_CATEGORIES:
        flash("That event does not accept joiners.", "error")
        return redirect(url_for("student.announcements"))

    if schedule_status(anc) != "open":
        flash("The join window for this event is not open.", "error")
        return redirect(url_for("student.announcements"))
    
    # Check if orientation attendance is required for payout events
    student_id = session["user_id"]
    required_orientation_id = anc.get("required_orientation_id")
    if required_orientation_id and anc.get("category") == "payout":
        if not student_joined_orientation(sb, student_id, required_orientation_id):
            flash("You must attend the required General Orientation event before joining this pay-out.", "error")
            return redirect(url_for("student.announcements"))

    signature = (request.form.get("signature") or "").strip()
    if not _is_valid_signature(signature):
        flash("Pumirma muna sa signature pad bago mag-join.", "error")
        return redirect(url_for("student.announcements"))

    now_iso = datetime.now(timezone.utc).isoformat()
    try:
        sb.table("announcement_joins").insert({
            "announcement_id": anc_id,
            "student_id":      student_id,
            "signature_data":  signature,
            "signed_at":       now_iso,
        }).execute()
        if anc.get("category") == "general_orientation":
            flash("You're on the list. See you at the General Orientation.", "success")
        else:
            flash("You're on the list. Check events again on the payout date.", "success")
    except Exception:
        # Likely a duplicate (unique constraint) — backfill the signature
        # so old rows that joined before signatures were required also
        # get one.
        try:
            sb.table("announcement_joins").update({
                "signature_data": signature,
                "signed_at":      now_iso,
            }).eq("announcement_id", anc_id).eq("student_id", student_id).execute()
            flash("Signature na-update. Naroon ka pa rin sa list.", "success")
        except Exception:
            flash("You already joined this event.", "success")

    return redirect(url_for("student.announcements"))
