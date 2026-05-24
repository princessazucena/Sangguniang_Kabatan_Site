-- =========================================================
-- Migration 3: announcement categories + scheduled windows
--              + payout joiners
-- Safe to run multiple times.
-- =========================================================

alter table public.announcements
    add column if not exists category text
        check (category in ('registration','payout','general')),
    add column if not exists start_at  timestamptz,
    add column if not exists end_at    timestamptz;

-- Existing rows default to 'general' so they keep showing up.
update public.announcements
   set category = 'general'
 where category is null;

-- Joiners for a payout announcement.
create table if not exists public.announcement_joins (
    id bigserial primary key,
    announcement_id bigint not null references public.announcements(id) on delete cascade,
    student_id      uuid   not null references public.profiles(id)      on delete cascade,
    joined_at       timestamptz not null default now(),
    unique (announcement_id, student_id)
);

create index if not exists idx_anc_joins_anc
    on public.announcement_joins(announcement_id);
create index if not exists idx_anc_joins_student
    on public.announcement_joins(student_id);

-- RLS on the join table (matches the rest of the app).
alter table public.announcement_joins enable row level security;

drop policy if exists "joins self read"   on public.announcement_joins;
drop policy if exists "joins self insert" on public.announcement_joins;
drop policy if exists "joins self delete" on public.announcement_joins;
create policy "joins self read"   on public.announcement_joins
    for select using (auth.uid() = student_id);
create policy "joins self insert" on public.announcement_joins
    for insert with check (auth.uid() = student_id);
create policy "joins self delete" on public.announcement_joins
    for delete using (auth.uid() = student_id);
