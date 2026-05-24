-- =========================================================
-- Migration 8: per-channel delivery flags for announcements
-- Lets the admin choose which channels each announcement reaches:
-- the public landing page, the in-app notification feed, and email.
-- All three default to true so existing posts behave the same.
-- Safe to run multiple times.
-- =========================================================

alter table public.announcements
    add column if not exists notify_landing boolean not null default true,
    add column if not exists notify_inapp   boolean not null default true,
    add column if not exists notify_email   boolean not null default true;
