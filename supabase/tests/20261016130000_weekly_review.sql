-- Synthetic rows only. All fixture changes are rolled back.
begin;
do $$
declare o uuid:=gen_random_uuid();
begin
 insert into auth.users(id,aud,role,email) values(o,'authenticated','authenticated',o::text||'@review-test.invalid');
 insert into public.tasks(user_id,title) values(o,'Review probe created');
 insert into public.tasks(user_id,title,status) values(o,'Review probe done','done');
 insert into public.tasks(user_id,title,due_kind,due_date) values(o,'Review probe overdue','date',current_date-2);
 perform set_config('focusos.review.owner',o::text,true);
end $$;
set local role authenticated;
select set_config('request.jwt.claim.sub',current_setting('focusos.review.owner'),true);
do $$
declare monday date:=current_date-(extract(isodow from current_date)::int-1); v jsonb;
begin
 v:=public.focusos_week_stats(monday,'Asia/Jakarta');
 if (v->>'tasks_created')::int<3 or (v->>'tasks_completed')::int<1 then raise exception 'Task counts wrong: %',v; end if;
 if (v->>'tasks_overdue')::int<>1 or v->'overdue_titles'->>0<>'Review probe overdue' then raise exception 'Overdue wrong: %',v; end if;
 if (v->>'focus_minutes')::int<>0 or (v->>'blocks_scheduled')::int<>0 then raise exception 'Phantom focus time: %',v; end if;
 if not public.focusos_save_weekly_review(monday,'Asia/Jakarta',v,'A quiet week.','["Plan one block."]','model') then raise exception 'Save failed'; end if;
 perform public.focusos_save_weekly_review(monday,'Asia/Jakarta',v,'Rewritten.','[]','template');
 if (select count(*) from public.weekly_reviews)<>1 or (select narrative from public.weekly_reviews)<>'Rewritten.' then raise exception 'Review not idempotent per week'; end if;
 begin
  perform public.focusos_week_stats(monday+1,'Asia/Jakarta');
  raise exception 'Non-Monday week accepted';
 exception when sqlstate '22023' then null; end;
 begin
  perform public.focusos_week_stats(monday,'Mars/Olympus');
  raise exception 'Unknown timezone accepted';
 exception when sqlstate '22023' then null; end;
end $$;
select set_config('request.jwt.claim.sub','00000000-0000-4000-8000-000000000004',true);
do $$
declare monday date:=current_date-(extract(isodow from current_date)::int-1); v jsonb;
begin
 if exists(select 1 from public.weekly_reviews) then raise exception 'Another user can read reviews'; end if;
 v:=public.focusos_week_stats(monday,'Asia/Jakarta');
 if (v->>'tasks_created')::int<>0 then raise exception 'Another user sees task counts'; end if;
end $$;
rollback;
