-- =========================================================
-- Migration 10: login throttling per profile
-- After too many wrong passwords we lock the account for a short
-- window. The countdown is server-side so it keeps running across
-- page refreshes / browser switches.
-- Safe to run multiple times.
-- =========================================================

alter table public.profiles
    add column if not exists failed_login_attempts int not null default 0,
    add column if not exists lockout_until         timestamptz;
