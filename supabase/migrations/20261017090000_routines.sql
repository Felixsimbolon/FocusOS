-- Recurring activities ("belajar Python tiap Selasa dan Kamis jam 7-8"). A routine is a rule;
-- each occurrence is booked as an ordinary FocusOS block, at most a week ahead, exactly once.
create table public.routines (
 id uuid primary key default gen_random_uuid(),
 user_id uuid not null references auth.users(id) on delete cascade,
 request_key uuid not null,
 title text not null check(char_length(title) between 1 and 120 and position('"' in title)=0),
 weekdays smallint[] not null check(cardinality(weekdays) between 1 and 7 and weekdays <@ array[1,2,3,4,5,6,7]::smallint[]),
 start_minute integer not null check(start_minute between 0 and 1439),
 duration_minutes integer not null check(duration_minutes between 15 and 240 and start_minute+duration_minutes<=1440),
 ends_on date,
 active boolean not null default true,
 created_at timestamptz not null default now(),
 updated_at timestamptz not null default now(),
 unique(user_id,request_key),
 unique(user_id,id)
);
create table public.routine_occurrences (
 user_id uuid not null references auth.users(id) on delete cascade,
 routine_id uuid not null,
 occurs_on date not null,
 run_id uuid,
 status text not null default 'booking' check(status in ('booking','booked','failed')),
 created_at timestamptz not null default now(),
 updated_at timestamptz not null default now(),
 primary key(routine_id,occurs_on),
 foreign key(user_id,routine_id) references public.routines(user_id,id) on delete cascade
);
alter table public.routines enable row level security;
alter table public.routine_occurrences enable row level security;
revoke all on public.routines,public.routine_occurrences from public,anon,authenticated;
grant select on public.routines,public.routine_occurrences to authenticated;
create policy routines_read_owner on public.routines for select to authenticated using(user_id=(select auth.uid()));
create policy routine_occurrences_read_owner on public.routine_occurrences for select to authenticated using(user_id=(select auth.uid()));

create function public.focusos_save_routine(p_request_key uuid,p_title text,p_weekdays smallint[],p_start_minute integer,
  p_duration_minutes integer,p_ends_on date)
returns jsonb language plpgsql security definer set search_path=''
as $$
declare v_owner uuid := (select auth.uid()); v_row public.routines;
begin
 if v_owner is null then raise exception 'Authentication required' using errcode='28000'; end if;
 if p_ends_on is not null and (p_ends_on<current_date or p_ends_on>current_date+366)
 then raise exception 'Invalid routine end' using errcode='22023'; end if;
 select * into v_row from public.routines where user_id=v_owner and request_key=p_request_key;
 if found then return pg_catalog.to_jsonb(v_row); end if;
 if (select count(*) from public.routines where user_id=v_owner and active)>=20
 then raise exception 'Too many routines' using errcode='54000'; end if;
 insert into public.routines(user_id,request_key,title,weekdays,start_minute,duration_minutes,ends_on)
 values(v_owner,p_request_key,pg_catalog.btrim(p_title),(select array_agg(distinct d order by d) from pg_catalog.unnest(p_weekdays) d),
        p_start_minute,p_duration_minutes,p_ends_on)
 returning * into v_row;
 return pg_catalog.to_jsonb(v_row);
end; $$;

create function public.focusos_set_routine_active(p_id uuid,p_active boolean)
returns boolean language plpgsql security definer set search_path=''
as $$
declare v_owner uuid := (select auth.uid());
begin
 if v_owner is null then raise exception 'Authentication required' using errcode='28000'; end if;
 update public.routines set active=p_active,updated_at=now() where id=p_id and user_id=v_owner;
 return found;
end; $$;

-- Claims the dates nobody has booked yet for an active routine; only returned dates may be booked.
create function public.focusos_claim_routine_dates(p_routine_id uuid,p_dates date[],p_run_id uuid)
returns date[] language plpgsql security definer set search_path=''
as $$
declare v_owner uuid := (select auth.uid()); v_claimed date[];
begin
 if v_owner is null then raise exception 'Authentication required' using errcode='28000'; end if;
 if cardinality(p_dates)>7 or exists(select 1 from pg_catalog.unnest(p_dates) d where d<current_date-1 or d>current_date+8)
 then raise exception 'Invalid routine dates' using errcode='22023'; end if;
 if not exists(select 1 from public.routines r where r.id=p_routine_id and r.user_id=v_owner and r.active)
 then raise exception 'Routine not found' using errcode='P0002'; end if;
 insert into public.routine_occurrences(user_id,routine_id,occurs_on,run_id)
 select v_owner,p_routine_id,d,p_run_id from pg_catalog.unnest(p_dates) d
 on conflict(routine_id,occurs_on) do nothing;
 -- A retried request may claim again: dates it already owns count as its own.
 select coalesce(array_agg(o.occurs_on order by o.occurs_on),'{}') into v_claimed from public.routine_occurrences o
 where o.routine_id=p_routine_id and o.user_id=v_owner and o.run_id=p_run_id and o.occurs_on=any(p_dates);
 return v_claimed;
end; $$;

create function public.focusos_finish_routine_date(p_routine_id uuid,p_date date,p_run_id uuid,p_status text)
returns boolean language plpgsql security definer set search_path=''
as $$
declare v_owner uuid := (select auth.uid());
begin
 if v_owner is null then raise exception 'Authentication required' using errcode='28000'; end if;
 if p_status not in ('booked','failed') then raise exception 'Invalid status' using errcode='22023'; end if;
 update public.routine_occurrences set status=p_status,updated_at=now()
 where routine_id=p_routine_id and occurs_on=p_date and user_id=v_owner and run_id=p_run_id;
 return found;
end; $$;

revoke all on function public.focusos_save_routine(uuid,text,smallint[],integer,integer,date) from public,anon;
revoke all on function public.focusos_set_routine_active(uuid,boolean) from public,anon;
revoke all on function public.focusos_claim_routine_dates(uuid,date[],uuid) from public,anon;
revoke all on function public.focusos_finish_routine_date(uuid,date,uuid,text) from public,anon;
grant execute on function public.focusos_save_routine(uuid,text,smallint[],integer,integer,date) to authenticated;
grant execute on function public.focusos_set_routine_active(uuid,boolean) to authenticated;
grant execute on function public.focusos_claim_routine_dates(uuid,date[],uuid) to authenticated;
grant execute on function public.focusos_finish_routine_date(uuid,date,uuid,text) to authenticated;
