-- =========================================================
-- Migration: add detailed name parts and Facebook URL to profiles
-- Safe to run multiple times.
-- =========================================================
alter table public.profiles
    add column if not exists first_name   text,
    add column if not exists middle_name  text,
    add column if not exists last_name    text,
    add column if not exists suffix       text,
    add column if not exists facebook_url text;
