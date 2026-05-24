-- =========================================================
-- Scholarship Website schema for Supabase
-- Run this in the Supabase SQL editor (one-shot).
-- =========================================================

-- Profiles: one row per auth user, with a role flag.
create table if not exists public.profiles (
    id uuid primary key references auth.users(id) on delete cascade,
    full_name text not null,
    first_name   text,
    middle_name  text,
    last_name    text,
    suffix       text,
    facebook_url text,
    role text not null default 'student' check (role in ('student','admin')),
    created_at timestamptz not null default now()
);

-- Announcements posted by admins, shown on the public page.
create table if not exists public.announcements (
    id bigserial primary key,
    title text not null,
    body text not null,
    category text check (category in ('registration','payout','general')),
    start_at timestamptz,
    end_at   timestamptz,
    posted_by uuid references public.profiles(id) on delete set null,
    created_at timestamptz not null default now()
);

-- Payout joiners (students who tap "Join" on a payout announcement).
create table if not exists public.announcement_joins (
    id bigserial primary key,
    announcement_id bigint not null references public.announcements(id) on delete cascade,
    student_id      uuid   not null references public.profiles(id)      on delete cascade,
    joined_at       timestamptz not null default now(),
    unique (announcement_id, student_id)
);

create index if not exists idx_anc_joins_anc on public.announcement_joins(announcement_id);
create index if not exists idx_anc_joins_student on public.announcement_joins(student_id);

-- One scholarship application per student (extend as you like).
create table if not exists public.applications (
    id bigserial primary key,
    student_id uuid not null references public.profiles(id) on delete cascade,
    status text not null default 'pending'
        check (status in ('pending','verified','rejected')),
    education_level text
        check (education_level in ('senior_high','college')),
    year_level text
        check (year_level in (
            'grade_11','grade_12',
            'year_1','year_2','year_3','year_4','year_5'
        )),
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
    slot text check (slot in ('card','id','indigency','psa','cor')),
    file_name text not null,
    storage_path text not null,
    mime_type text,
    size_bytes bigint,
    uploaded_at timestamptz not null default now()
);

create index if not exists idx_app_files_app on public.application_files(application_id);
create index if not exists idx_app_files_slot on public.application_files(application_id, slot);
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
alter table public.announcement_joins  enable row level security;

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

-- announcement_joins: a student can see/insert/delete their own joins
drop policy if exists "joins self read"   on public.announcement_joins;
drop policy if exists "joins self insert" on public.announcement_joins;
drop policy if exists "joins self delete" on public.announcement_joins;
create policy "joins self read"   on public.announcement_joins for select using (auth.uid() = student_id);
create policy "joins self insert" on public.announcement_joins for insert with check (auth.uid() = student_id);
create policy "joins self delete" on public.announcement_joins for delete using (auth.uid() = student_id);
