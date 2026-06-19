-- =========================================================
-- Migration 15: Add verification_code columns for password reset
--
-- Adds verification_code and verification_code_expires_at columns
-- to profiles table to support password reset functionality.
-- These columns store the 6-digit reset code and its expiration time.
--
-- Safe to run multiple times.
-- =========================================================

-- Add verification_code column if it doesn't exist
alter table public.profiles
    add column if not exists verification_code text;

-- Add verification_code_expires_at column if it doesn't exist
alter table public.profiles
    add column if not exists verification_code_expires_at timestamptz;

-- Add email_verified column if it doesn't exist (for email verification flow)
alter table public.profiles
    add column if not exists email_verified boolean default true;

-- Create index for faster lookups when validating codes
create index if not exists idx_profiles_verification_code
    on public.profiles(verification_code)
    where verification_code is not null;
