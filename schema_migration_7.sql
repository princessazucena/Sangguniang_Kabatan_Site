-- =========================================================
-- Migration 7: split address fields on profiles
-- Adds structured address columns so we capture house number,
-- street, purok, barangay, city/municipality, province and ZIP
-- separately at sign-up time.
-- Safe to run multiple times.
-- =========================================================

alter table public.profiles
    add column if not exists address_house_no text,
    add column if not exists address_street   text,
    add column if not exists address_purok    text,
    add column if not exists address_barangay text,
    add column if not exists address_city     text,
    add column if not exists address_province text,
    add column if not exists address_zip      text;
