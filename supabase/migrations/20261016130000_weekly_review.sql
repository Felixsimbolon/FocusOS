-- Weekly review: every number comes from this SQL; the model only writes prose around them.
create table public.weekly_reviews (
 user_id uuid not null references auth.users(id) on delete cascade,
 week_start date not null,
 timezone text not null check(char_length(timezone) between 1 and 64),
 stats jsonb not null check(pg_catalog.jsonb_typeof(stats)='object' and pg_column_size(stats)<=16384),
 narrative text check(narrative is null or char_length(narrative) between 1 and 1200),
 suggestions jsonb not null default '[]'::jsonb check(pg_catalog.jsonb_typeof(suggestions)='array' and pg_catalog.jsonb_array_length(suggestions)<=3),
 narrative_source text not null check(narrative_source in ('model','template')),
 created_at timestamptz not null default now(),
 updated_at timestamptz not null default now(),
 primary key(user_id,week_start)
);
alter table public.weekly_reviews enable row level security;
revoke all on public.weekly_reviews from public,anon,authenticated;
grant select on public.weekly_reviews to authenticated;
create policy weekly_reviews_read_owner on public.weekly_reviews for select to authenticated using(user_id=(select auth.uid()));

-- Aggregates for one local week (Monday p_week_start 00:00 to the next Monday 00:00 in p_timezone).
-- Task completion time is approximated by the task's last update while done.
create function public.focusos_week_stats(p_week_start date,p_timezone text)
returns jsonb language plpgsql stable security definer set search_path=''
as $$
declare v_owner uuid := (select auth.uid()); v_from timestamptz; v_to timestamptz; v jsonb;
begin
 if v_owner is null then raise exception 'Authentication required' using errcode='28000'; end if;
 if p_week_start is null or extract(isodow from p_week_start)<>1 or p_week_start<current_date-371 or p_week_start>current_date+7
   or not exists(select 1 from pg_catalog.pg_timezone_names where name=p_timezone)
 then raise exception 'Invalid week' using errcode='22023'; end if;
 v_from := (p_week_start::timestamp) at time zone p_timezone;
 v_to := ((p_week_start+7)::timestamp) at time zone p_timezone;
 with blocks as (
   select a.id,a.task_id,(a.payload->>'start')::timestamptz as starts_at,(a.payload->>'end')::timestamptz as ends_at,
          a.cancellation_status
   from public.approval_requests a
   where a.user_id=v_owner and a.status='succeeded'
     and (a.payload->>'start')::timestamptz>=v_from and (a.payload->>'start')::timestamptz<v_to
 ), kept as (
   select * from blocks where cancellation_status is distinct from 'cancelled'
 ), by_project as (
   select coalesce(p.name,'No project') as project,
          (sum(extract(epoch from (k.ends_at-k.starts_at))/60))::integer as minutes
   from kept k left join public.tasks t on t.id=k.task_id and t.user_id=v_owner
   left join public.projects p on p.id=t.project_id and p.user_id=v_owner
   group by 1 order by 2 desc limit 5
 ), sessions as (
   select w.* from public.work_sessions w join kept k on k.id=w.approval_id where w.user_id=v_owner
 ), slipping as (
   select t.title from public.tasks t
   where t.user_id=v_owner and t.status='open'
     and ((t.due_kind='date' and t.due_date<(v_to at time zone p_timezone)::date and t.due_date<(now() at time zone p_timezone)::date)
       or (t.due_kind='datetime' and t.due_at<least(v_to,now())))
   order by coalesce(t.due_at,(t.due_date::timestamp at time zone p_timezone)) limit 5
 )
 select pg_catalog.jsonb_build_object(
   'week_start',p_week_start,'week_end',p_week_start+6,'timezone',p_timezone,
   'tasks_created',(select count(*) from public.tasks t where t.user_id=v_owner and t.created_at>=v_from and t.created_at<v_to),
   'tasks_completed',(select count(*) from public.tasks t where t.user_id=v_owner and t.status='done' and t.updated_at>=v_from and t.updated_at<v_to),
   'tasks_overdue',(select count(*) from slipping),
   'overdue_titles',(select coalesce(pg_catalog.jsonb_agg(pg_catalog.left(title,80)),'[]'::jsonb) from slipping),
   'blocks_scheduled',(select count(*) from kept),
   'blocks_cancelled',(select count(*) from blocks where cancellation_status='cancelled'),
   'focus_minutes',(select coalesce(sum(extract(epoch from (ends_at-starts_at))/60),0)::integer from kept),
   'focus_by_project',(select coalesce(pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object('project',pg_catalog.left(project,80),'minutes',minutes)),'[]'::jsonb) from by_project),
   'check_ins',(select count(*) from sessions),
   'check_ins_done',(select count(*) from sessions where outcome='done'),
   'check_ins_partial',(select count(*) from sessions where outcome='partial'),
   'check_ins_skipped',(select count(*) from sessions where outcome='skipped'),
   'planned_minutes_checked',(select coalesce(sum(planned_minutes),0) from sessions where outcome<>'skipped'),
   'actual_minutes_checked',(select coalesce(sum(actual_minutes),0) from sessions where outcome<>'skipped'),
   'model_calls',(select count(*) from public.llm_calls c where c.user_id=v_owner and c.created_at>=v_from and c.created_at<v_to),
   'model_tokens',(select coalesce(sum(coalesce(prompt_tokens,0)+coalesce(output_tokens,0)),0) from public.llm_calls c
                   where c.user_id=v_owner and c.created_at>=v_from and c.created_at<v_to)
 ) into v;
 return v;
end; $$;
revoke all on function public.focusos_week_stats(date,text) from public,anon;
grant execute on function public.focusos_week_stats(date,text) to authenticated;

create function public.focusos_save_weekly_review(p_week_start date,p_timezone text,p_stats jsonb,p_narrative text,
  p_suggestions jsonb,p_source text)
returns boolean language plpgsql security definer set search_path=''
as $$
declare v_owner uuid := (select auth.uid());
begin
 if v_owner is null then raise exception 'Authentication required' using errcode='28000'; end if;
 if extract(isodow from p_week_start)<>1 then raise exception 'Invalid week' using errcode='22023'; end if;
 insert into public.weekly_reviews(user_id,week_start,timezone,stats,narrative,suggestions,narrative_source)
 values(v_owner,p_week_start,p_timezone,p_stats,p_narrative,p_suggestions,p_source)
 on conflict(user_id,week_start) do update set timezone=excluded.timezone,stats=excluded.stats,narrative=excluded.narrative,
   suggestions=excluded.suggestions,narrative_source=excluded.narrative_source,updated_at=now();
 return true;
end; $$;
revoke all on function public.focusos_save_weekly_review(date,text,jsonb,text,jsonb,text) from public,anon;
grant execute on function public.focusos_save_weekly_review(date,text,jsonb,text,jsonb,text) to authenticated;
