"""
One-shot maintenance script: title-case every name in public.profiles.

Usage (from the project root, with the .venv activated or via the
explicit interpreter path):

    .venv\\Scripts\\python.exe scripts\\titlecase_profile_names.py
    .venv\\Scripts\\python.exe scripts\\titlecase_profile_names.py --apply

Behavior
--------
* Default mode is a DRY RUN — nothing is written to the database. The
  script prints every profile whose stored name differs from the
  title-cased version and writes a full CSV backup so the original
  values can be restored if needed.
* Pass ``--apply`` to actually write the updates. The CSV backup is
  saved either way so we always have a snapshot just before writing.
* The script never touches rows that already match (no writes, no diffs).

Files written
-------------
* ``backup_profiles_<timestamp>.csv`` — backup snapshot of every row
  that would change, with the original ``id, full_name, first_name,
  middle_name, last_name, suffix`` values.
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
from datetime import datetime

# Make the project root importable when running from anywhere.
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from dotenv import load_dotenv

load_dotenv(os.path.join(_ROOT, ".env"))

from supabase_client import get_supabase
from services.names import title_name, build_full_name


NAME_COLUMNS = ("full_name", "first_name", "middle_name", "last_name", "suffix")


def _normalize_row(row: dict) -> dict:
    """Compute the title-cased version of every name field on the row."""
    first  = title_name(row.get("first_name")  or "")
    middle = title_name(row.get("middle_name") or "")
    last   = title_name(row.get("last_name")   or "")
    suffix = title_name(row.get("suffix")      or "")

    if first or last:
        full = build_full_name(first, middle, last, suffix)
    else:
        # No structured name parts on file — fall back to title-casing
        # whatever string sits in full_name so legacy rows still get fixed.
        full = title_name(row.get("full_name") or "")

    return {
        "first_name":  first,
        "middle_name": middle,
        "last_name":   last,
        "suffix":      suffix,
        "full_name":   full,
    }


def _diff(row: dict, fixed: dict) -> dict:
    """Return only the columns whose value would actually change."""
    out: dict = {}
    for col in NAME_COLUMNS:
        old = row.get(col) or ""
        new = fixed.get(col) or ""
        if old != new:
            # Empty middle_name / suffix are stored as NULL in the DB to
            # match how signup writes them. Preserve that convention so
            # we don't introduce empty strings.
            if col in ("middle_name", "suffix") and not new:
                out[col] = None
            else:
                out[col] = new
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply", action="store_true",
        help="Actually write the updates to the database. "
             "Without this flag the script only prints a diff and a CSV backup.",
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Optional cap on how many changed rows are processed. "
             "Useful for a small initial test.",
    )
    args = parser.parse_args()

    sb = get_supabase()
    print("Fetching every profile from Supabase…")
    rows = (
        sb.table("profiles")
        .select("id, full_name, first_name, middle_name, last_name, suffix")
        .execute()
    ).data or []
    print(f"  {len(rows)} profile rows pulled.")

    pending: list[tuple[dict, dict]] = []  # (original_row, updates)
    for row in rows:
        fixed   = _normalize_row(row)
        updates = _diff(row, fixed)
        if updates:
            pending.append((row, updates))

    if args.limit is not None:
        pending = pending[: args.limit]

    if not pending:
        print("All profile names are already title-cased. Nothing to do.")
        return 0

    print(f"\n{len(pending)} profile row(s) need name normalization.\n")

    # Always write a CSV backup before we touch anything.
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = os.path.join(_ROOT, f"backup_profiles_{timestamp}.csv")
    with open(backup_path, "w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["id", *NAME_COLUMNS])
        for row, _ in pending:
            writer.writerow([
                row.get("id"),
                row.get("full_name") or "",
                row.get("first_name") or "",
                row.get("middle_name") or "",
                row.get("last_name") or "",
                row.get("suffix") or "",
            ])
    print(f"Backup of the affected rows saved to: {backup_path}\n")

    # Show the diff so we can eyeball the changes before applying.
    for row, updates in pending:
        print(f"- {row.get('id')}:")
        for col, new_val in updates.items():
            old = row.get(col) or "(blank)"
            shown_new = new_val if new_val is not None else "(blank)"
            print(f"    {col}: {old!r}  ->  {shown_new!r}")

    if not args.apply:
        print("\nDRY RUN — nothing was written. Re-run with --apply to commit.")
        return 0

    # Confirm before writing in case --apply was passed by accident.
    answer = input("\nProceed and apply these changes to the database? [y/N] ")
    if answer.strip().lower() not in ("y", "yes"):
        print("Aborted. No changes written.")
        return 1

    print("\nWriting updates…")
    written = 0
    failed: list[tuple[str, str]] = []
    for row, updates in pending:
        try:
            sb.table("profiles").update(updates).eq("id", row["id"]).execute()
            written += 1
        except Exception as exc:
            failed.append((str(row.get("id")), str(exc)))

    print(f"Done. {written} row(s) updated.")
    if failed:
        print(f"{len(failed)} row(s) failed:")
        for sid, err in failed:
            print(f"  - {sid}: {err}")
        print(f"The backup CSV at {backup_path} can be used to restore.")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
