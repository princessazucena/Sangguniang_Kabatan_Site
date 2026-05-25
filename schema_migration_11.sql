-- =========================================================
-- Migration 11: rename 'kk_assembly' announcement category to 'general_orientation'
-- The certificate workflow now treats General Orientation and Pay-Out
-- as the only events that issue Certificates of Attendance, so the
-- old KK Assembly category no longer fits.
-- Safe to run multiple times.
-- =========================================================

-- Rebuild the check constraint with the new category.
alter table public.announcements
    drop constraint if exists announcements_category_check;

-- Migrate any existing rows over to the new label.
update public.announcements
   set category = 'general_orientation'
 where category = 'kk_assembly';

alter table public.announcements
    add constraint announcements_category_check
    check (category in ('registration','payout','general_orientation','general'));
