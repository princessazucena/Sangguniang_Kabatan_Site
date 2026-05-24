-- =========================================================
-- Migration 4: tie each application to a specific registration
-- announcement so a student can apply once per registration window.
-- Safe to run multiple times.
-- =========================================================

-- Link the application to the registration announcement it was created for.
-- Old rows keep registration_id = NULL (treated as legacy applications).
alter table public.applications
    add column if not exists registration_id bigint
        references public.announcements(id) on delete set null;

-- Drop the previous "one application per student, ever" rule.
alter table public.applications
    drop constraint if exists applications_student_id_key;

-- Enforce one application per student per registration window. NULLs are
-- distinct in Postgres unique constraints, so legacy rows are unaffected.
do $$
begin
    if not exists (
        select 1 from pg_constraint
         where conname = 'applications_student_registration_key'
    ) then
        alter table public.applications
            add constraint applications_student_registration_key
            unique (student_id, registration_id);
    end if;
end$$;

create index if not exists idx_applications_student_created
    on public.applications(student_id, created_at desc);
create index if not exists idx_applications_registration
    on public.applications(registration_id);
