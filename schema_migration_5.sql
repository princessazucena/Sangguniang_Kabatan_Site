-- =========================================================
-- Migration 5: account activation flag for student management
-- Safe to run multiple times.
-- =========================================================

-- Whether the account is allowed to log in. Admins can flip this
-- from the user-management page to lock a student out without
-- destroying their data.
alter table public.profiles
    add column if not exists is_active boolean not null default true;

create index if not exists idx_profiles_role_is_active
    on public.profiles(role, is_active);
