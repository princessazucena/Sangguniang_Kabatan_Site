"""
Shared helpers for announcement categories + scheduling windows.

Categories
----------
- 'registration' : students may apply / upload requirements while
                   start_at <= now <= end_at.
- 'payout'       : students may join while start_at <= now <= end_at.
- 'kk_assembly'  : KK assembly event students may join while
                   start_at <= now <= end_at.
- 'general'      : informational only.
"""
from datetime import datetime, timezone
from typing import Optional

CATEGORIES = ("registration", "payout", "kk_assembly", "general")
CATEGORY_LABELS = {
    "registration": "Scholarship Registration",
    "payout":       "Scholarship Pay Out",
    "kk_assembly":  "KK Assembly",
    "general":      "General",
}

# Categories that need a start/end window and accept "joiners".
JOINABLE_CATEGORIES = {"payout", "kk_assembly"}
SCHEDULED_CATEGORIES = {"registration", "payout", "kk_assembly"}


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
