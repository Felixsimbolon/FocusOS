-- User-owned scheduling preferences. Public API roles never receive a table-wide grant.
create function public.focusos_valid_timezone(zone_name text)
returns boolean
language sql
stable
security invoker
set search_path = ''
as $$
  select exists (
    select 1
    from pg_catalog.pg_timezone_names
    where name = zone_name
  );
$$;

create function public.focusos_valid_working_hours(hours jsonb)
returns boolean
language plpgsql
immutable
security invoker
set search_path = ''
as $$
declare
  key_count integer;
  day_value jsonb;
  seen_days integer[] := '{}';
  start_value integer;
  end_value integer;
begin
  if pg_catalog.jsonb_typeof(hours) is distinct from 'object' then
    return false;
  end if;

  select count(*) into key_count from pg_catalog.jsonb_object_keys(hours);
  if key_count <> 3
    or pg_catalog.jsonb_typeof(hours -> 'days') is distinct from 'array'
    or pg_catalog.jsonb_typeof(hours -> 'start_minute') is distinct from 'number'
    or pg_catalog.jsonb_typeof(hours -> 'end_minute') is distinct from 'number'
  then
    return false;
  end if;

  if (hours ->> 'start_minute') !~ '^(0|[1-9][0-9]{0,3})$'
    or (hours ->> 'end_minute') !~ '^(0|[1-9][0-9]{0,3})$'
  then
    return false;
  end if;

  start_value := (hours ->> 'start_minute')::integer;
  end_value := (hours ->> 'end_minute')::integer;
  if start_value < 0 or start_value > 1439
    or end_value < 1 or end_value > 1440
    or start_value >= end_value
  then
    return false;
  end if;

  if pg_catalog.jsonb_array_length(hours -> 'days') not between 1 and 7 then
    return false;
  end if;

  for day_value in select value from pg_catalog.jsonb_array_elements(hours -> 'days') loop
    if pg_catalog.jsonb_typeof(day_value) is distinct from 'number'
      or day_value::text !~ '^[1-7]$'
    then
      return false;
    end if;

    if (day_value::text)::integer = any(seen_days) then
      return false;
    end if;
    seen_days := pg_catalog.array_append(seen_days, (day_value::text)::integer);
  end loop;

  return true;
end;
$$;

revoke execute on function public.focusos_valid_timezone(text) from public, anon;
revoke execute on function public.focusos_valid_working_hours(jsonb) from public, anon;
grant execute on function public.focusos_valid_timezone(text) to authenticated;
grant execute on function public.focusos_valid_working_hours(jsonb) to authenticated;

create table public.profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  timezone text not null check (public.focusos_valid_timezone(timezone)),
  working_hours jsonb not null check (public.focusos_valid_working_hours(working_hours)),
  is_allowlisted boolean not null default false,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create function public.focusos_touch_profile_updated_at()
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

revoke execute on function public.focusos_touch_profile_updated_at() from public, anon, authenticated;

create trigger focusos_profile_updated_at
before update on public.profiles
for each row execute function public.focusos_touch_profile_updated_at();

alter table public.profiles enable row level security;

-- New public-schema objects may inherit broad grants on hosted projects.
revoke all on table public.profiles from public, anon, authenticated;
grant select (id, timezone, working_hours) on public.profiles to authenticated;
grant insert (id, timezone, working_hours) on public.profiles to authenticated;
grant update (timezone, working_hours) on public.profiles to authenticated;

create policy focusos_profile_select_own
on public.profiles for select to authenticated
using ((select auth.uid()) = id);

create policy focusos_profile_insert_own
on public.profiles for insert to authenticated
with check ((select auth.uid()) = id);

create policy focusos_profile_update_own
on public.profiles for update to authenticated
using ((select auth.uid()) = id)
with check ((select auth.uid()) = id);

-- Atomic first save and subsequent edits; the caller's JWT supplies the owner.
create function public.focusos_save_profile(
  p_timezone text,
  p_working_hours jsonb
)
returns table (id uuid, timezone text, working_hours jsonb)
language sql
volatile
security invoker
set search_path = ''
as $$
  insert into public.profiles as p (id, timezone, working_hours)
  values ((select auth.uid()), p_timezone, p_working_hours)
  on conflict (id) do update
    set timezone = excluded.timezone,
        working_hours = excluded.working_hours
  returning p.id, p.timezone, p.working_hours;
$$;

revoke execute on function public.focusos_save_profile(text, jsonb) from public, anon;
grant execute on function public.focusos_save_profile(text, jsonb) to authenticated;
