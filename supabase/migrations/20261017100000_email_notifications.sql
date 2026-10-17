-- Email notifications sent from the user's own Gmail to the same address: a morning brief and
-- reminders before FocusOS blocks. They must go out while nobody is signed in, so the worker
-- (service role, behind the worker secret) plans and claims them here. Those functions return
-- only what one email needs, for owners who switched notifications on, and nothing else.
create table public.notification_settings (
 user_id uuid primary key references auth.users(id) on delete cascade,
 morning_brief boolean not null default false,
 brief_minute integer not null default 420 check(brief_minute between 0 and 1439),
 block_reminders boolean not null default false,
 reminder_minutes integer not null default 10 check(reminder_minutes in (5,10,15,30)),
 updated_at timestamptz not null default now()
);
create table public.email_outbox (
 id uuid primary key default gen_random_uuid(),
 user_id uuid not null references auth.users(id) on delete cascade,
 kind text not null check(kind in ('morning_brief','block_reminder')),
 dedupe_key text not null check(char_length(dedupe_key) between 1 and 120),
 approval_id uuid references public.approval_requests(id) on delete cascade,
 send_after timestamptz not null,
 status text not null default 'pending' check(status in ('pending','sending','sent','failed')),
 attempts integer not null default 0 check(attempts between 0 and 5),
 lease_until timestamptz,
 sent_at timestamptz,
 safe_error text check(safe_error is null or safe_error ~ '^[a-z_]{1,60}$'),
 created_at timestamptz not null default now(),
 unique(user_id,dedupe_key)
);
create index email_outbox_due on public.email_outbox(status,send_after);
alter table public.notification_settings enable row level security;
alter table public.email_outbox enable row level security;
revoke all on public.notification_settings,public.email_outbox from public,anon,authenticated;
grant select on public.notification_settings to authenticated;
grant select(id,user_id,kind,send_after,status,attempts,sent_at,safe_error,created_at) on public.email_outbox to authenticated;
create policy notification_settings_read_owner on public.notification_settings for select to authenticated using(user_id=(select auth.uid()));
create policy email_outbox_read_owner on public.email_outbox for select to authenticated using(user_id=(select auth.uid()));

create function public.focusos_save_notification_settings(p_morning_brief boolean,p_brief_minute integer,
  p_block_reminders boolean,p_reminder_minutes integer)
returns jsonb language plpgsql security definer set search_path=''
as $$
declare v_owner uuid := (select auth.uid()); v_row public.notification_settings;
begin
 if v_owner is null then raise exception 'Authentication required' using errcode='28000'; end if;
 insert into public.notification_settings(user_id,morning_brief,brief_minute,block_reminders,reminder_minutes)
 values(v_owner,p_morning_brief,p_brief_minute,p_block_reminders,p_reminder_minutes)
 on conflict(user_id) do update set morning_brief=excluded.morning_brief,brief_minute=excluded.brief_minute,
   block_reminders=excluded.block_reminders,reminder_minutes=excluded.reminder_minutes,updated_at=now()
 returning * into v_row;
 return pg_catalog.to_jsonb(v_row);
end; $$;

-- A test brief for the signed-in user, sent on the next worker tick (or right away by the API).
create function public.focusos_queue_test_brief()
returns uuid language plpgsql security definer set search_path=''
as $$
declare v_owner uuid := (select auth.uid()); v_id uuid;
begin
 if v_owner is null then raise exception 'Authentication required' using errcode='28000'; end if;
 if (select count(*) from public.email_outbox where user_id=v_owner and dedupe_key like 'test:%' and created_at>now()-interval '1 hour')>=3
 then raise exception 'Too many test emails' using errcode='54000'; end if;
 insert into public.email_outbox(user_id,kind,dedupe_key,send_after)
 values(v_owner,'morning_brief','test:'||pg_catalog.gen_random_uuid(),now()) returning id into v_id;
 return v_id;
end; $$;

-- Worker only: add due reminders and briefs to the outbox. Returns how many were added.
create function public.focusos_plan_notifications(p_now timestamptz)
returns integer language plpgsql security definer set search_path=''
as $$
declare v_added integer := 0; v_count integer;
begin
 insert into public.email_outbox(user_id,kind,dedupe_key,approval_id,send_after)
 select a.user_id,'block_reminder','reminder:'||a.id,a.id,(a.payload->>'start')::timestamptz-make_interval(mins=>s.reminder_minutes)
 from public.approval_requests a join public.notification_settings s on s.user_id=a.user_id and s.block_reminders
 where a.status='succeeded' and a.cancellation_status is distinct from 'cancelled'
   and (a.payload->>'start')::timestamptz>p_now
   and (a.payload->>'start')::timestamptz<=p_now+make_interval(mins=>s.reminder_minutes+15)
 on conflict(user_id,dedupe_key) do nothing;
 get diagnostics v_count = row_count; v_added := v_added+v_count;
 -- One brief per local day, only within three hours after the chosen time (a stalled worker skips the day).
 insert into public.email_outbox(user_id,kind,dedupe_key,send_after)
 select s.user_id,'morning_brief','brief:'||(p_now at time zone p.timezone)::date,p_now
 from public.notification_settings s join public.profiles p on p.id=s.user_id
 where s.morning_brief
   and extract(hour from p_now at time zone p.timezone)*60+extract(minute from p_now at time zone p.timezone)
       between s.brief_minute and s.brief_minute+180
 on conflict(user_id,dedupe_key) do nothing;
 get diagnostics v_count = row_count;
 return v_added+v_count;
end; $$;

-- Worker only: lease due emails and return exactly what each one needs (p_owner limits it to one user).
create function public.focusos_claim_notifications(p_now timestamptz,p_limit integer,p_owner uuid)
returns jsonb language plpgsql security definer set search_path=''
as $$
declare v_result jsonb;
begin
 if p_limit not between 1 and 50 then raise exception 'Invalid limit' using errcode='22023'; end if;
 with due as (
   select o.id from public.email_outbox o
   where (o.status='pending' or (o.status='sending' and o.lease_until<p_now)) and o.send_after<=p_now and o.attempts<3
     and (p_owner is null or o.user_id=p_owner)
   order by o.send_after limit p_limit for update skip locked
 ), leased as (
   update public.email_outbox o set status='sending',attempts=o.attempts+1,lease_until=p_now+interval '5 minutes'
   from due where o.id=due.id returning o.*
 )
 select coalesce(pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
   'id',l.id,'user_id',l.user_id,'kind',l.kind,'dedupe_key',l.dedupe_key,
   'timezone',coalesce(p.timezone,'UTC'),
   'connection',(select pg_catalog.jsonb_build_object('id',c.id,'email',c.display_email,'scopes',c.granted_scopes)
                 from public.connections c where c.user_id=l.user_id and c.provider='google' and c.status='connected' limit 1),
   'block',(select pg_catalog.jsonb_build_object('title',a.payload->>'title','start',a.payload->>'start','end',a.payload->>'end',
                   'cancelled',a.cancellation_status='cancelled')
            from public.approval_requests a where a.id=l.approval_id and a.user_id=l.user_id),
   'brief',case when l.kind='morning_brief' then pg_catalog.jsonb_build_object(
     'blocks',(select coalesce(pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object('title',a.payload->>'title','start',a.payload->>'start','end',a.payload->>'end')
                      order by (a.payload->>'start')),'[]'::jsonb)
               from public.approval_requests a where a.user_id=l.user_id and a.status='succeeded'
                 and a.cancellation_status is distinct from 'cancelled'
                 and ((a.payload->>'start')::timestamptz at time zone coalesce(p.timezone,'UTC'))::date=(p_now at time zone coalesce(p.timezone,'UTC'))::date),
     'due_today',(select coalesce(pg_catalog.jsonb_agg(t.title order by t.priority='high' desc,t.title),'[]'::jsonb) from (
               select title,priority from public.tasks t where t.user_id=l.user_id and t.status='open'
                 and ((t.due_kind='date' and t.due_date=(p_now at time zone coalesce(p.timezone,'UTC'))::date)
                   or (t.due_kind='datetime' and (t.due_at at time zone coalesce(p.timezone,'UTC'))::date=(p_now at time zone coalesce(p.timezone,'UTC'))::date))
               limit 10) t),
     'overdue',(select coalesce(pg_catalog.jsonb_agg(t.title),'[]'::jsonb) from (
               select title from public.tasks t where t.user_id=l.user_id and t.status='open'
                 and ((t.due_kind='date' and t.due_date<(p_now at time zone coalesce(p.timezone,'UTC'))::date) or (t.due_kind='datetime' and t.due_at<p_now))
               limit 10) t),
     'urgent_email',(select coalesce(pg_catalog.jsonb_agg(s.title),'[]'::jsonb) from (
               select si.title from public.email_triage e join public.source_items si on si.id=e.source_id and si.user_id=e.user_id
               where e.user_id=l.user_id and e.priority='urgent' and e.updated_at>p_now-interval '3 days' order by e.updated_at desc limit 5) s)
   ) end)),'[]'::jsonb) into v_result
 from leased l left join public.profiles p on p.id=l.user_id;
 return v_result;
end; $$;

create function public.focusos_finish_notification(p_id uuid,p_status text,p_error text)
returns boolean language plpgsql security definer set search_path=''
as $$
begin
 if p_status not in ('sent','failed','pending') then raise exception 'Invalid status' using errcode='22023'; end if;
 update public.email_outbox set status=p_status,lease_until=null,safe_error=p_error,
   sent_at=case when p_status='sent' then now() else sent_at end
 where id=p_id and status='sending';
 return found;
end; $$;

revoke all on function public.focusos_save_notification_settings(boolean,integer,boolean,integer) from public,anon;
revoke all on function public.focusos_queue_test_brief() from public,anon;
grant execute on function public.focusos_save_notification_settings(boolean,integer,boolean,integer) to authenticated;
grant execute on function public.focusos_queue_test_brief() to authenticated;
revoke all on function public.focusos_plan_notifications(timestamptz) from public,anon,authenticated;
revoke all on function public.focusos_claim_notifications(timestamptz,integer,uuid) from public,anon,authenticated;
revoke all on function public.focusos_finish_notification(uuid,text,text) from public,anon,authenticated;
grant execute on function public.focusos_plan_notifications(timestamptz) to service_role;
grant execute on function public.focusos_claim_notifications(timestamptz,integer,uuid) to service_role;
grant execute on function public.focusos_finish_notification(uuid,text,text) to service_role;
