"""
Notification feed builder.

The feed is generated on-demand from existing tables — no new storage
needed. Items combine:

  * Announcements (latest 50, all categories) — open to everyone.
  * Application status updates for the student (approved / rejected),
    only when the application has actually been reviewed.
  * For admins: counts of pending applications.

Each item has:
    {
        "id":         <stable string id>,
        "kind":       "announcement" | "status",
        "title":      str,
        "body":       str,
        "category":   announcement category or status,
        "created_at": iso string,
        "url":        click-through target,
        "icon":       fa-icon class name,
        "tone":       "brand" | "blue" | "green" | "red" | "slate",
    }
"""
from typing import List, Dict, Any, Optional

from services.announcements import annotate, filter_visible


_CATEGORY_META = {
    "registration":        {"icon": "fa-clipboard-list",     "tone": "brand"},
    "payout":              {"icon": "fa-hand-holding-dollar","tone": "blue"},
    "general_orientation": {"icon": "fa-people-group",       "tone": "purple"},
    "general":             {"icon": "fa-bullhorn",           "tone": "slate"},
}


def _truncate(text: str, limit: int = 140) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _announcement_items(sb, role: str) -> List[Dict[str, Any]]:
    rows = (
        sb.table("announcements")
        .select("*")
        .eq("notify_inapp", True)
        .order("created_at", desc=True)
        .limit(50)
        .execute()
    ).data or []
    rows = filter_visible(rows)
    annotate(rows)

    target_endpoint = (
        "student.announcements" if role == "student"
        else "admin.announcements" if role == "admin"
        else "public.home"
    )

    items: List[Dict[str, Any]] = []
    for r in rows:
        meta = _CATEGORY_META.get(r.get("category") or "general",
                                  _CATEGORY_META["general"])
        # Route general announcements to the dedicated admin page so
        # the bell icon takes admins to the right list.
        endpoint = target_endpoint
        if role == "admin" and (r.get("category") or "general") == "general":
            endpoint = "admin.general_announcements"
        items.append({
            "id":         f"anc-{r['id']}",
            "kind":       "announcement",
            "title":      r.get("title") or "Event",
            "body":       _truncate(r.get("body") or ""),
            "category":   r.get("category") or "general",
            "status":     r.get("status"),
            "created_at": r.get("created_at"),
            "endpoint":   endpoint,
            "anchor":     f"anc-{r['id']}",
            "icon":       meta["icon"],
            "tone":       meta["tone"],
        })
    return items


def _student_status_item(sb, student_id: str) -> Optional[Dict[str, Any]]:
    """Return a status notification only when the application has been reviewed."""
    res = (
        sb.table("applications")
        .select("id, status, notes, reviewed_at")
        .eq("student_id", student_id)
        .order("reviewed_at", desc=True)
        .limit(1)
        .execute()
    )
    rows = res.data or []
    if not rows:
        return None
    row = rows[0]
    status = row.get("status")
    reviewed_at = row.get("reviewed_at")
    if status not in ("verified", "rejected") or not reviewed_at:
        return None

    if status == "verified":
        return {
            "id":         f"app-{row['id']}-verified-{reviewed_at}",
            "kind":       "status",
            "title":      "Application approved",
            "body":       "Your scholarship application has been approved. "
                          "Watch out for the next pay-out event.",
            "category":   "verified",
            "status":     "verified",
            "created_at": reviewed_at,
            "endpoint":   "student.applications_list",
            "anchor":     None,
            "icon":       "fa-circle-check",
            "tone":       "green",
        }
    # rejected
    body = "The admin left feedback on your application — please review and resubmit."
    if row.get("notes"):
        body = f"Admin notes: {_truncate(row['notes'], 200)}"
    return {
        "id":         f"app-{row['id']}-rejected-{reviewed_at}",
        "kind":       "status",
        "title":      "Application needs updates",
        "body":       body,
        "category":   "rejected",
        "status":     "rejected",
        "created_at": reviewed_at,
        "endpoint":   "student.applications_list",
        "anchor":     None,
        "icon":       "fa-circle-exclamation",
        "tone":       "red",
    }


def _admin_pending_item(sb) -> Optional[Dict[str, Any]]:
    rows = (
        sb.table("applications")
        .select("id, created_at")
        .eq("status", "pending")
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    ).data or []
    if not rows:
        return None
    # Use a fresh count for the body.
    count_res = (
        sb.table("applications")
        .select("id", count="exact")
        .eq("status", "pending")
        .execute()
    )
    count = getattr(count_res, "count", None) or len(rows)
    latest_at = rows[0].get("created_at")
    return {
        "id":         f"admin-pending-{count}",
        "kind":       "status",
        "title":      f"{count} pending application{'s' if count != 1 else ''}",
        "body":       "Tap to review the queue.",
        "category":   "pending",
        "status":     "pending",
        "created_at": latest_at,
        "endpoint":   "admin.applications",
        "anchor":     None,
        "icon":       "fa-folder-open",
        "tone":       "brand",
    }


def build_feed(sb, *, role: str, user_id: Optional[str]) -> List[Dict[str, Any]]:
    """
    Produce a sorted (newest first) list of notification items
    appropriate for the current user.
    """
    items: List[Dict[str, Any]] = []

    if role == "student" and user_id:
        s = _student_status_item(sb, user_id)
        if s:
            items.append(s)
    elif role == "admin":
        a = _admin_pending_item(sb)
        if a:
            items.append(a)

    items.extend(_announcement_items(sb, role))

    items.sort(key=lambda x: x.get("created_at") or "", reverse=True)
    return items
