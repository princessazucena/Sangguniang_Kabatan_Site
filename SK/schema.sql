-- =========================================================
-- Scholarship Website schema for Supabase
-- Run this in the Supabase SQL editor (one-shot).
-- =========================================================

-- Profiles: one row per auth user, with a role flag.
create table if not exists public.profiles (
    id uuid primary key references auth.users(id) on delete cascade,
    full_name text not null,
    role text not null default 'student' check (role in ('student','admin')),
    created_at timestamptz not null default now()
);

-- Announcements posted by admins, shown on the public page.
create table if not exists public.announcements (
    id bigserial primary key,
    title text not null,
    body text not null,
    posted_by uuid references public.profiles(id) on delete set null,
    created_at timestamptz not null default now()
);

-- One scholarship application per student (extend as you like).
create table if not exists public.applications (
    id bigserial primary key,
    student_id uuid not null references public.profiles(id) on delete cascade,
    status text not null default 'pending'
        check (status in ('pending','verified','rejected')),
    notes text,
    reviewed_by uuid references public.profiles(id) on delete set null,
    reviewed_at timestamptz,
    created_at timestamptz not null default now(),
    unique (student_id)
);

-- Files uploaded by students for their application.
create table if not exists public.application_files (
    id bigserial primary key,
    application_id bigint not null references public.applications(id) on delete cascade,
    student_id uuid not null references public.profiles(id) on delete cascade,
    file_name text not null,
    storage_path text not null,
    mime_type text,
    size_bytes bigint,
    uploaded_at timestamptz not null default now()
);

create index if not exists idx_app_files_app on public.application_files(application_id);
create index if not exists idx_announcements_created on public.announcements(created_at desc);

-- Storage bucket for the uploaded documents.
insert into storage.buckets (id, name, public)
values ('scholarship-files', 'scholarship-files', false)
on conflict (id) do nothing;

-- =========================================================
-- Row Level Security
-- The Flask backend uses the service-role/secret key, which
-- bypasses RLS. These policies are here so that if you ever
-- expose the anon key to a browser, the data stays safe.
-- =========================================================
alter table public.profiles            enable row level security;
alter table public.announcements       enable row level security;
alter table public.applications        enable row level security;
alter table public.application_files   enable row level security;

-- profiles: a user can read/update their own profile
drop policy if exists "profiles self read"   on public.profiles;
drop policy if exists "profiles self update" on public.profiles;
create policy "profiles self read"   on public.profiles for select using (auth.uid() = id);
create policy "profiles self update" on public.profiles for update using (auth.uid() = id);

-- announcements: anyone signed in can read
drop policy if exists "announcements read" on public.announcements;
create policy "announcements read" on public.announcements for select using (true);

-- applications: a student can see/insert/update their own
drop policy if exists "apps self read"   on public.applications;
drop policy if exists "apps self insert" on public.applications;
drop policy if exists "apps self update" on public.applications;
create policy "apps self read"   on public.applications for select using (auth.uid() = student_id);
create policy "apps self insert" on public.applications for insert with check (auth.uid() = student_id);
create policy "apps self update" on public.applications for update using (auth.uid() = student_id);

-- application_files: a student can see/insert their own
drop policy if exists "files self read"   on public.application_files;
drop policy if exists "files self insert" on public.application_files;
create policy "files self read"   on public.application_files for select using (auth.uid() = student_id);
create policy "files self insert" on public.application_files for insert with check (auth.uid() = student_id);
