-- =========================================================
-- Migration 9: address_region column on profiles
-- We added a Region select to the signup address fields (PSGC).
-- Safe to run multiple times.
-- =========================================================

alter table public.profiles
    add column if not exists address_region text;
