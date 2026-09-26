-- Phase 4.6: one reviewed candidate becomes one provenance-backed task.
alter table public.extraction_results
  add constraint extraction_results_user_id_id_unique unique (user_id,id);
alter table public.agent_runs
  add constraint agent_runs_user_id_id_unique unique (user_id,id);
alter table public.extraction_results drop constraint extraction_run_fk;
alter table public.extraction_results add constraint extraction_owned_run_fk
  foreign key (user_id,run_id) references public.agent_runs(user_id,id) on delete set null (run_id);

alter table public.tasks
  add column source_id uuid,
  add column extraction_result_id uuid,
  add column extraction_item_key text,
  add column evidence jsonb,
  add column confidence double precision,
  add column review_hash text,
  add constraint task_owned_source_fk foreign key (user_id,source_id)
    references public.source_items(user_id,id) on delete set null (source_id),
  add constraint task_owned_extraction_fk foreign key (user_id,extraction_result_id)
    references public.extraction_results(user_id,id) on delete set null (extraction_result_id),
  add constraint task_extraction_identity check (
    (extraction_result_id is null and extraction_item_key is null)
    or (extraction_result_id is not null and extraction_item_key is not null)),
  add constraint task_confidence_bounds check (confidence is null or confidence between 0 and 1),
  add constraint task_review_hash_shape check (review_hash is null or review_hash ~ '^[0-9a-f]{64}$');
create unique index task_extraction_candidate_unique
  on public.tasks (extraction_result_id,extraction_item_key)
  where extraction_result_id is not null;
grant select (source_id,extraction_result_id,extraction_item_key,evidence,confidence)
  on public.tasks to authenticated;

create or replace function public.focusos_task_json(p_task public.tasks)
returns jsonb language sql immutable security invoker set search_path=''
as $$
 select pg_catalog.jsonb_build_object(
   'id',p_task.id,'title',p_task.title,'description',p_task.description,
   'status',p_task.status,'priority',p_task.priority,'due_kind',p_task.due_kind,
   'due_date',p_task.due_date,'due_at',p_task.due_at,'due_timezone',p_task.due_timezone,
   'estimate_minutes',p_task.estimate_minutes,'estimate_origin',p_task.estimate_origin,
   'project_id',p_task.project_id,'source_id',p_task.source_id,
   'extraction_result_id',p_task.extraction_result_id,
   'extraction_item_key',p_task.extraction_item_key,'evidence',p_task.evidence,
   'confidence',p_task.confidence,'version',p_task.version,
   'created_at',p_task.created_at,'updated_at',p_task.updated_at);
$$;

create function public.focusos_confirm_extraction_task(
 p_extraction_id uuid,p_local_ref text,p_review_hash text,p_title text,
 p_description text,p_priority text,p_due_kind text,p_due_date date,
 p_due_at timestamptz,p_due_timezone text,p_estimate_minutes integer,
 p_project_id uuid,p_evidence jsonb,p_confidence double precision
) returns jsonb language plpgsql security definer set search_path=''
as $$
declare v_owner uuid := (select auth.uid()); v_extraction public.extraction_results;
declare v_source public.source_items; v_task public.tasks; v_replayed boolean := false;
begin
 if v_owner is null then raise exception 'Authentication required' using errcode='28000'; end if;
 select * into v_extraction from public.extraction_results
   where id=p_extraction_id and user_id=v_owner and status='ready';
 if v_extraction.id is null then return jsonb_build_object('outcome','not_found'); end if;
 select * into v_source from public.source_items
   where id=v_extraction.source_id and user_id=v_owner and deleted_at is null;
 if v_source.id is null or v_source.body_hash<>v_extraction.content_hash
   or v_source.normalized_body is null or v_source.body_expires_at<=now() then
   return jsonb_build_object('outcome','stale');
 end if;
 if not exists(select 1 from pg_catalog.jsonb_array_elements(v_extraction.validated_payload->'tasks') as c
               where c->>'local_ref'=p_local_ref) then
   return jsonb_build_object('outcome','candidate_not_found');
 end if;
 if p_project_id is not null and not exists(select 1 from public.projects
     where id=p_project_id and user_id=v_owner) then
   return jsonb_build_object('outcome','project_not_found');
 end if;
 if p_review_hash !~ '^[0-9a-f]{64}$' then raise exception 'Invalid review hash' using errcode='22023'; end if;
 insert into public.tasks
   (user_id,title,description,priority,due_kind,due_date,due_at,due_timezone,
    estimate_minutes,estimate_origin,project_id,source_id,extraction_result_id,
    extraction_item_key,evidence,confidence,review_hash)
 values(v_owner,p_title,p_description,p_priority,p_due_kind,p_due_date,p_due_at,
   p_due_timezone,p_estimate_minutes,
   case when p_estimate_minutes is null then null else 'explicit' end,
   p_project_id,v_source.id,v_extraction.id,p_local_ref,p_evidence,p_confidence,p_review_hash)
 on conflict (extraction_result_id,extraction_item_key) where extraction_result_id is not null
 do nothing returning * into v_task;
 if v_task.id is null then
   v_replayed := true;
   select * into v_task from public.tasks
    where extraction_result_id=p_extraction_id and extraction_item_key=p_local_ref and user_id=v_owner;
 end if;
 if v_task.review_hash<>p_review_hash then
   return jsonb_build_object('outcome','conflict');
 end if;
 update public.extraction_results set reviewed_at=coalesce(reviewed_at,now())
   where id=p_extraction_id and user_id=v_owner;
 return jsonb_build_object('outcome','confirmed','task',public.focusos_task_json(v_task),
   'replayed',v_replayed);
end;
$$;
revoke all on function public.focusos_confirm_extraction_task(
 uuid,text,text,text,text,text,text,date,timestamptz,text,integer,uuid,jsonb,double precision)
 from public,anon;
grant execute on function public.focusos_confirm_extraction_task(
 uuid,text,text,text,text,text,text,date,timestamptz,text,integer,uuid,jsonb,double precision)
 to authenticated;
