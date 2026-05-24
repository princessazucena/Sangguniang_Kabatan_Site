-- =========================================================
-- Migration 6: KK Assembly announcements
-- Adds the 'kk_assembly' category so admins can post Katipunan ng
-- Kabataan assembly events that students can join, similar to pay-outs.
-- Safe to run multiple times.
-- =========================================================

alter table public.announcements
    drop constraint if exists announcements_category_check;

alter table public.announcements
    add constraint announcements_category_check
    check (category in ('registration','payout','kk_assembly','general'));
