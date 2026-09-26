-- Phase 3.1: persistent tasks with database-enforced ownership and deadline shape.
create table public.tasks (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  title text not null check (char_length(btrim(title)) between 1 and 200),
  description text check (description is null or char_length(description) <= 2000),
  status text not null default 'open' check (status in ('open', 'done', 'archived')),
  priority text not null default 'normal' check (priority in ('low', 'normal', 'high')),
  due_kind text not null default 'none' check (due_kind in ('none', 'date', 'datetime')),
  due_date date,
  due_at timestamptz,
  due_timezone text,
  estimate_minutes integer,
  estimate_origin text,
  version integer not null default 1 check (version > 0),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint tasks_due_shape check (
    (due_kind = 'none' and due_date is null and due_at is null and due_timezone is null)
    or (due_kind = 'date' and due_date is not null and due_at is null and due_timezone is null)
    or (
      due_kind = 'datetime' and due_date is null and due_at is not null
      and due_timezone is not null and public.focusos_valid_timezone(due_timezone)
    )
  ),
  constraint tasks_estimate_shape check (
    (estimate_minutes is null and estimate_origin is null)
    or (
      estimate_minutes between 1 and 1440
      and estimate_origin in ('explicit', 'suggested', 'unknown')
    )
  ),
  constraint tasks_user_id_id_unique unique (user_id, id)
);

create index tasks_user_status_due_at_idx on public.tasks (user_id, status, due_at);
create index tasks_user_status_due_date_idx on public.tasks (user_id, status, due_date);

create function public.focusos_touch_task_updated_at()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  new.updated_at := pg_catalog.now();
  return new;
end;
$$;

revoke execute on function public.focusos_touch_task_updated_at() from public, anon, authenticated;
create trigger focusos_task_updated_at
before update on public.tasks
for each row execute function public.focusos_touch_task_updated_at();

alter table public.tasks enable row level security;
revoke all on table public.tasks from public, anon, authenticated;
grant select (
  id, user_id, title, description, status, priority, due_kind, due_date, due_at,
  due_timezone, estimate_minutes, estimate_origin, version, created_at, updated_at
) on public.tasks to authenticated;

create policy focusos_tasks_select_own
on public.tasks for select to authenticated
using ((select auth.uid()) = user_id);
