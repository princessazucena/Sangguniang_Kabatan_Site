-- =========================================================
-- Migration 12: signatures on Pay-out / General Orientation joins
-- Stores the joiner's e-signature alongside the join record so the
-- admin can verify attendance and export a signed sheet.
-- Safe to run multiple times.
-- =========================================================

alter table public.announcement_joins
    add column if not exists signature_data text,
    add column if not exists signed_at      timestamptz;
