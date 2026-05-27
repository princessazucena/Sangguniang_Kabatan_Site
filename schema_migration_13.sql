-- =========================================================
-- Migration 13: manual override for event status
--
-- Lets the admin force an event into "open" or "closed" state from the
-- Events page, ignoring the start_at / end_at window. NULL means "no
-- override — use the schedule" (default).
-- Safe to run multiple times.
-- =========================================================

alter table public.announcements
    add column if not exists manual_status text;

-- Drop the old constraint if it lingered from a previous attempt.
alter table public.announcements
    drop constraint if exists announcements_manual_status_check;

alter table public.announcements
    add constraint announcements_manual_status_check
    check (manual_status is null or manual_status in ('open', 'closed'));
