"""
PSGC (Philippine Standard Geographic Code) lookup helper.

We hit https://psgc.gitlab.io/api/ for region/province/city-municipality/
barangay data. To keep the page snappy and avoid hammering the upstream
on every keystroke during signup, results are cached in-process per
worker for 24 hours.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Optional

import requests

PSGC_BASE = "https://psgc.gitlab.io/api"
_TTL_SECONDS = 24 * 60 * 60   # cache for 24h
_HTTP_TIMEOUT = 10            # seconds

log = logging.getLogger(__name__)

_cache: dict[str, tuple[float, list[dict]]] = {}
_lock = threading.Lock()


def _get_json(path: str) -> Optional[list[dict]]:
    """Cached GET against the PSGC API. Returns ``None`` on failure."""
    now = time.time()
    with _lock:
        cached = _cache.get(path)
        if cached and (now - cached[0]) < _TTL_SECONDS:
            return cached[1]

    try:
        # Use the .json variants — the bare urls return text/html.
        url = f"{PSGC_BASE}/{path}"
        if not url.endswith(".json"):
            url = url + ".json"
        resp = requests.get(url, timeout=_HTTP_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        log.warning("PSGC fetch failed for %s: %s", path, exc)
        return None

    if not isinstance(data, list):
        return None

    # Normalize for the frontend: only keep the bits we need and sort by name.
    cleaned = sorted(
        (
            {
                "code": str(row.get("code") or "").strip(),
                "name": (row.get("name") or "").strip(),
            }
            for row in data
            if row.get("name")
        ),
        key=lambda r: r["name"].lower(),
    )

    with _lock:
        _cache[path] = (now, cleaned)
    return cleaned


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def list_regions() -> list[dict]:
    return _get_json("regions") or []


def list_provinces(region_code: str) -> list[dict]:
    if not region_code:
        return []
    # NCR has no provinces — return empty so the UI knows to skip the level.
    return _get_json(f"regions/{region_code}/provinces") or []


def list_cities_municipalities(region_code: str, province_code: Optional[str]) -> list[dict]:
    if province_code:
        return _get_json(f"provinces/{province_code}/cities-municipalities") or []
    if region_code:
        # Province-less regions (e.g. NCR) — fall back to region scope.
        return _get_json(f"regions/{region_code}/cities-municipalities") or []
    return []


def list_barangays(city_or_municipality_code: str) -> list[dict]:
    if not city_or_municipality_code:
        return []
    return _get_json(f"cities-municipalities/{city_or_municipality_code}/barangays") or []
