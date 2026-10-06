-- Durable, bounded jobs. Session bearer is encrypted and never readable by browsers.
create table public.work_jobs (
 id uuid primary key, user_id uuid not null references auth.users(id) on delete cascade,
 request_key uuid not null, kind text not null check(kind in ('planning','gmail','source','embedding')),
 subject_id uuid, status text not null default 'queued' check(status in ('queued','running','succeeded','failed','cancelled','expired')),
 checkpoint jsonb not null default '{}', result jsonb, safe_error text,
 steps integer not null default 0, failures integer not null default 0,
 available_at timestamptz not null default now(), expires_at timestamptz not null,
 lease_token uuid, lease_until timestamptz, created_at timestamptz not null default now(), updated_at timestamptz not null default now(),
 unique(user_id,request_key), check((kind='gmail')=(subject_id is null)),
 check(octet_length(checkpoint::text)<=8192), check(result is null or octet_length(result::text)<=8192)
);
create index work_jobs_ready on public.work_jobs(available_at,created_at) where status in ('queued','running');
alter table public.work_jobs enable row level security;
revoke all on public.work_jobs from public,anon,authenticated;
create policy work_jobs_read_owner on public.work_jobs for select to authenticated using(user_id=(select auth.uid()));
grant select(id,user_id,request_key,kind,subject_id,status,result,safe_error,steps,failures,available_at,expires_at,created_at,updated_at) on public.work_jobs to authenticated;
create table private.work_job_tokens (
 job_id uuid primary key references public.work_jobs(id) on delete cascade,
 ciphertext text not null check(length(ciphertext)<=24000), key_version integer not null check(key_version>0)
);
alter table private.work_job_tokens enable row level security;
revoke all on private.work_job_tokens from public,anon,authenticated,service_role;

create function public.focusos_enqueue_job(p_id uuid,p_owner uuid,p_request_key uuid,p_kind text,p_subject_id uuid,p_ciphertext text,p_key_version integer,p_expires_at timestamptz)
returns jsonb language plpgsql security definer set search_path='' as $$
declare j public.work_jobs;
begin
 if p_owner is null or p_id is null or p_request_key is null or p_expires_at<=now()+interval '30 seconds' or p_expires_at>now()+interval '16 minutes' then raise exception 'Invalid job' using errcode='22023'; end if;
 perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(p_owner::text,17));
 select * into j from public.work_jobs where user_id=p_owner and request_key=p_request_key for update;
 if j.id is not null then
   if j.kind is distinct from p_kind or j.subject_id is distinct from p_subject_id then raise exception 'Job request conflict' using errcode='23505'; end if;
   return to_jsonb(j)-'checkpoint'-'lease_token'-'lease_until';
 end if;
 if (select count(*) from public.work_jobs where user_id=p_owner and status in ('queued','running') and expires_at>now())>=10
 or (select count(*) from public.work_jobs where user_id=p_owner and created_at>now()-interval '1 day')>=100 then raise exception 'Job limit reached' using errcode='54000'; end if;
 if p_kind='planning' and not exists(select 1 from public.command_runs where id=p_subject_id and user_id=p_owner)
 or p_kind='source' and not exists(select 1 from public.source_items where id=p_subject_id and user_id=p_owner and deleted_at is null)
 or p_kind='embedding' and not exists(select 1 from public.memories where id=p_subject_id and user_id=p_owner and status='active') then raise exception 'Job subject unavailable' using errcode='22023'; end if;
 insert into public.work_jobs(id,user_id,request_key,kind,subject_id,expires_at) values(p_id,p_owner,p_request_key,p_kind,p_subject_id,p_expires_at) returning * into j;
 insert into private.work_job_tokens values(p_id,p_ciphertext,p_key_version);
 return to_jsonb(j)-'checkpoint'-'lease_token'-'lease_until';
end; $$;
revoke all on function public.focusos_enqueue_job(uuid,uuid,uuid,text,uuid,text,integer,timestamptz) from public,anon,authenticated;
grant execute on function public.focusos_enqueue_job(uuid,uuid,uuid,text,uuid,text,integer,timestamptz) to service_role;

create function public.focusos_claim_job(p_id uuid default null,p_owner uuid default null) returns jsonb
language plpgsql security definer set search_path='' as $$
declare j public.work_jobs; t private.work_job_tokens;
begin
 update public.work_jobs set status='expired',safe_error='session_expired',lease_token=null,lease_until=null,updated_at=now()
 where status in ('queued','running') and expires_at<=now();
 delete from private.work_job_tokens tok using public.work_jobs job where tok.job_id=job.id and job.status in ('expired','cancelled','failed','succeeded');
 select * into j from public.work_jobs
 where (p_id is null or id=p_id) and (p_owner is null or user_id=p_owner) and expires_at>now()
   and (status='queued' and available_at<=now() or status='running' and lease_until<=now())
 order by available_at,created_at for update skip locked limit 1;
 if j.id is null then return null; end if;
 if j.steps>=64 then
   update public.work_jobs set status='failed',safe_error='step_limit',updated_at=now() where id=j.id;
   delete from private.work_job_tokens where job_id=j.id; return null;
 end if;
 select * into t from private.work_job_tokens where job_id=j.id;
 if t.job_id is null then
   update public.work_jobs set status='failed',safe_error='session_unavailable',updated_at=now() where id=j.id; return null;
 end if;
 update public.work_jobs set status='running',lease_token=gen_random_uuid(),lease_until=now()+interval '180 seconds',steps=steps+1,updated_at=now() where id=j.id returning * into j;
 return to_jsonb(j)||jsonb_build_object('ciphertext',t.ciphertext,'key_version',t.key_version);
end; $$;
revoke all on function public.focusos_claim_job(uuid,uuid) from public,anon,authenticated;
grant execute on function public.focusos_claim_job(uuid,uuid) to service_role;

create function public.focusos_finish_job(p_id uuid,p_lease uuid,p_status text,p_checkpoint jsonb,p_result jsonb,p_error text,p_delay integer default 0,p_failure boolean default false) returns boolean
language plpgsql security definer set search_path='' as $$
declare j public.work_jobs; v_status text;
begin
 if p_status not in ('queued','succeeded','failed','expired') or p_delay not between 0 and 900 or octet_length(p_checkpoint::text)>8192
 or p_error is not null and p_error !~ '^[a-z_]{1,64}$' then raise exception 'Invalid job completion' using errcode='22023'; end if;
 select * into j from public.work_jobs where id=p_id and status='running' and lease_token=p_lease and lease_until>now() for update;
 if j.id is null then return false; end if;
 v_status:=case when j.expires_at<=now() then 'expired' when p_failure and j.failures>=4 then 'failed' else p_status end;
 update public.work_jobs set status=v_status,checkpoint=p_checkpoint,result=p_result,safe_error=p_error,
   failures=failures+case when p_failure then 1 else 0 end,available_at=now()+pg_catalog.make_interval(secs=>p_delay),lease_token=null,lease_until=null,updated_at=now() where id=j.id;
 if v_status in ('succeeded','failed','expired') then delete from private.work_job_tokens where job_id=j.id; end if;
 return true;
end; $$;
revoke all on function public.focusos_finish_job(uuid,uuid,text,jsonb,jsonb,text,integer,boolean) from public,anon,authenticated;
grant execute on function public.focusos_finish_job(uuid,uuid,text,jsonb,jsonb,text,integer,boolean) to service_role;

create function public.focusos_cancel_job(p_id uuid) returns boolean language plpgsql security definer set search_path='' as $$
declare n integer;
begin
 if (select auth.uid()) is null then raise exception 'Authentication required' using errcode='28000'; end if;
 update public.work_jobs set status='cancelled',lease_token=null,lease_until=null,updated_at=now()
 where id=p_id and user_id=(select auth.uid()) and status in ('queued','running');
 get diagnostics n=row_count;
 delete from private.work_job_tokens where job_id=p_id and exists(select 1 from public.work_jobs where id=p_id and user_id=(select auth.uid()) and status='cancelled');
 return n=1;
end; $$;
revoke all on function public.focusos_cancel_job(uuid) from public,anon;
grant execute on function public.focusos_cancel_job(uuid) to authenticated;
