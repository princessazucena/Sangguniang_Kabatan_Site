"""
Shared helpers for announcement categories + scheduling windows.

Categories
----------
- 'registration'        : students may apply / upload requirements while
                          start_at <= now <= end_at.
- 'payout'              : students may join while start_at <= now <= end_at.
- 'general_orientation' : SK general orientation event students may join
                          while start_at <= now <= end_at.
- 'general'             : informational only.
"""
from datetime import datetime, timezone
from typing import Optional

CATEGORIES = ("registration", "payout", "general_orientation", "general")
CATEGORY_LABELS = {
    "registration":        "Scholarship Registration",
    "payout":              "Scholarship Pay Out",
    "general_orientation": "General Orientation",
    "general":             "General",
}

# Categories handled by the Events page (admin + student).
EVENT_CATEGORIES = {"registration", "payout", "general_orientation"}
# Plain informational posts shown on the Announcements page.
GENERAL_CATEGORY = "general"

# Categories that need a start/end window and accept "joiners".
JOINABLE_CATEGORIES = {"payout", "general_orientation"}
SCHEDULED_CATEGORIES = {"registration", "payout", "general_orientation"}


def _parse_ts(value) -> Optional[datetime]:
    """Parse an ISO-8601 timestamp string from Supabase into aware UTC datetime."""
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def schedule_status(row: dict, now: Optional[datetime] = None) -> str:
    """
    Returns one of: 'upcoming', 'open', 'closed', 'unscheduled'.
    A 'general' announcement (or one missing dates) is 'unscheduled'.
    """
    if (row.get("category") or "general") not in SCHEDULED_CATEGORIES:
        return "unscheduled"

    start = _parse_ts(row.get("start_at"))
    end   = _parse_ts(row.get("end_at"))
    if not start or not end:
        return "unscheduled"

    now = now or datetime.now(timezone.utc)
    if now < start:
        return "upcoming"
    if now > end:
        return "closed"
    return "open"


def annotate(rows: list[dict]) -> list[dict]:
    """Attach a 'status' field to each row in-place and return it."""
    for r in rows:
        r["status"] = schedule_status(r)
    return rows


def is_general_visible(row: dict, now: Optional[datetime] = None) -> bool:
    """
    Decide whether a 'general' announcement should still appear on the
    feed. The admin's "Display until" date lives in ``end_at``; once it
    passes the post is hidden from the public/student views (but still
    kept in the database).
    """
    if (row.get("category") or "general") != GENERAL_CATEGORY:
        return True
    end = _parse_ts(row.get("end_at"))
    if not end:
        # No expiry set means it stays visible.
        return True
    return (now or datetime.now(timezone.utc)) <= end


def filter_visible(rows: list[dict], now: Optional[datetime] = None) -> list[dict]:
    """Drop expired general announcements from a list of rows."""
    now = now or datetime.now(timezone.utc)
    return [r for r in rows if is_general_visible(r, now)]


def current_open_registration(sb) -> Optional[dict]:
    """Return the active registration window, if any."""
    res = (
        sb.table("announcements")
        .select("*")
        .eq("category", "registration")
        .order("start_at", desc=True)
        .limit(20)
        .execute()
    )
    rows = res.data or []
    for r in rows:
        if schedule_status(r) == "open":
            return r
    return None
