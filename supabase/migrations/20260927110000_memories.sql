-- Phase 7.4: only user-confirmed, source-backed facts.
create table public.memories (
 id uuid primary key default gen_random_uuid(),
 user_id uuid not null references auth.users(id) on delete cascade,
 request_key uuid not null,
 project_id uuid,
 source_id uuid not null,
 source_hash text not null check(source_hash ~ '^[0-9a-f]{64}$'),
 text text not null check(char_length(text) between 1 and 500),
 evidence_quote text not null check(char_length(evidence_quote) between 1 and 500),
 status text not null default 'active' check(status in ('active','superseded')),
 created_at timestamptz not null default now(),
 updated_at timestamptz not null default now(),
 unique(user_id,request_key),
 unique(user_id,id),
 constraint memory_owned_source foreign key(user_id,source_id)
   references public.source_items(user_id,id) on delete cascade,
 constraint memory_owned_project foreign key(user_id,project_id)
   references public.projects(user_id,id) on delete set null (project_id)
);
create index memories_active_owner_idx on public.memories(user_id,created_at desc) where status='active';
alter table public.memories enable row level security;
revoke all on public.memories from public,anon,authenticated;
grant select(id,user_id,request_key,project_id,source_id,source_hash,text,evidence_quote,status,created_at,updated_at)
 on public.memories to authenticated;
create policy memories_read_own on public.memories for select to authenticated
 using ((select auth.uid())=user_id);

create function public.focusos_confirm_memory(
 p_request_key uuid,p_source_id uuid,p_project_id uuid,p_text text,p_quote text
) returns jsonb language plpgsql security definer set search_path=''
as $$
declare v_owner uuid := (select auth.uid()); v_source public.source_items; v_row public.memories;
begin
 if v_owner is null then raise exception 'Authentication required' using errcode='28000'; end if;
 if p_request_key is null or char_length(btrim(p_text)) not between 1 and 500
   or char_length(btrim(p_quote)) not between 1 and 500
 then raise exception 'Invalid memory' using errcode='22023'; end if;
 select * into v_source from public.source_items
 where id=p_source_id and user_id=v_owner and deleted_at is null
   and normalized_body is not null and body_expires_at>now();
 if v_source.id is null or strpos(v_source.normalized_body,btrim(p_quote))=0
 then raise exception 'Source evidence unavailable' using errcode='22023'; end if;
 if p_project_id is not null and not exists(select 1 from public.projects
   where id=p_project_id and user_id=v_owner)
 then raise exception 'Project unavailable' using errcode='22023'; end if;
 insert into public.memories(user_id,request_key,project_id,source_id,source_hash,text,evidence_quote)
 values(v_owner,p_request_key,p_project_id,p_source_id,v_source.body_hash,btrim(p_text),btrim(p_quote))
 on conflict(user_id,request_key) do nothing;
 select * into v_row from public.memories where user_id=v_owner and request_key=p_request_key;
 if v_row.source_id<>p_source_id or v_row.project_id is distinct from p_project_id
    or v_row.text<>btrim(p_text) or v_row.evidence_quote<>btrim(p_quote)
 then raise exception 'Memory request conflict' using errcode='23505'; end if;
 return to_jsonb(v_row);
end; $$;
revoke all on function public.focusos_confirm_memory(uuid,uuid,uuid,text,text) from public,anon;
grant execute on function public.focusos_confirm_memory(uuid,uuid,uuid,text,text) to authenticated;

create function public.focusos_supersede_memory(p_memory_id uuid)
returns boolean language plpgsql security definer set search_path=''
as $$
declare v_owner uuid := (select auth.uid());
begin
 if v_owner is null then raise exception 'Authentication required' using errcode='28000'; end if;
 update public.memories set status='superseded',updated_at=now()
 where id=p_memory_id and user_id=v_owner and status='active';
 return found;
end; $$;
revoke all on function public.focusos_supersede_memory(uuid) from public,anon;
grant execute on function public.focusos_supersede_memory(uuid) to authenticated;
