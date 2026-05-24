-- =========================================================
-- Migration 2: education level + per-document slot
-- Safe to run multiple times.
-- =========================================================

-- Track which level the student is applying for.
alter table public.applications
    add column if not exists education_level text
        check (education_level in ('senior_high', 'college')),
    add column if not exists year_level text
        check (year_level in (
            'grade_11', 'grade_12',
            'year_1', 'year_2', 'year_3', 'year_4', 'year_5'
        ));

-- Tag each uploaded file with the requirement slot it fills
-- (card, id, indigency, psa, cor).
alter table public.application_files
    add column if not exists slot text
        check (slot in ('card', 'id', 'indigency', 'psa', 'cor'));

create index if not exists idx_app_files_slot
    on public.application_files(application_id, slot);
