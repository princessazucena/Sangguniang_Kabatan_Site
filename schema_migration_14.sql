-- =========================================================
-- Migration 14: required orientation prerequisite
--
-- Adds a required_orientation_id column to announcements table.
-- When creating a Registration or Pay-Out event, admin can select
-- which General Orientation event(s) are required. Only students
-- who joined those orientation events can apply for scholarship
-- or join the pay-out event.
--
-- Safe to run multiple times.
-- =========================================================

alter table public.announcements
    add column if not exists required_orientation_id bigint;

-- Drop the old constraint if it lingered from a previous attempt.
alter table public.announcements
    drop constraint if exists announcements_required_orientation_fk;

-- Add foreign key constraint to ensure required_orientation_id
-- references another announcement (should be category='general_orientation')
alter table public.announcements
    add constraint announcements_required_orientation_fk
    foreign key (required_orientation_id)
    references public.announcements(id)
    on delete set null;

-- Create index for faster lookups
create index if not exists idx_announcements_required_orientation
    on public.announcements(required_orientation_id)
    where required_orientation_id is not null;
