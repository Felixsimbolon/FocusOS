-- Notes (free-form writing per project, searchable when asking questions) and assignments
-- (a PDF brief analysed into concepts to study and subtasks to schedule).
create table public.notes (
 id uuid primary key,
 user_id uuid not null references auth.users(id) on delete cascade,
 project_id uuid,
 title text not null check(char_length(btrim(title)) between 1 and 200),
 body text not null default '' check(char_length(body)<=50000),
 version integer not null default 1 check(version>0),
 embedding extensions.vector(256),
 embedded_version integer,
 created_at timestamptz not null default now(),
 updated_at timestamptz not null default now(),
 unique(user_id,id),
 foreign key(user_id,project_id) references public.projects(user_id,id) on delete set null (project_id)
);
create index notes_owner_updated on public.notes(user_id,updated_at desc);
alter table public.notes enable row level security;
revoke all on public.notes from public,anon,authenticated;
grant select(id,user_id,project_id,title,body,version,created_at,updated_at) on public.notes to authenticated;
create policy notes_read_owner on public.notes for select to authenticated using(user_id=(select auth.uid()));

-- Create (p_expected_version 0, the client chooses the id) or update with an optimistic version check.
create function public.focusos_save_note(p_id uuid,p_project_id uuid,p_title text,p_body text,p_expected_version integer)
returns jsonb language plpgsql security definer set search_path=''
as $$
declare v_owner uuid := (select auth.uid()); v_row public.notes;
begin
 if v_owner is null then raise exception 'Authentication required' using errcode='28000'; end if;
 if p_project_id is not null and not exists(select 1 from public.projects where id=p_project_id and user_id=v_owner)
 then raise exception 'Project not found' using errcode='P0002'; end if;
 if (select count(*) from public.notes where user_id=v_owner)>=2000 and p_expected_version=0
 then raise exception 'Too many notes' using errcode='54000'; end if;
 select * into v_row from public.notes where id=p_id;
 if found and v_row.user_id<>v_owner then raise exception 'Note not found' using errcode='P0002'; end if;
 if not found then
   if p_expected_version<>0 then raise exception 'Note not found' using errcode='P0002'; end if;
   insert into public.notes(id,user_id,project_id,title,body) values(p_id,v_owner,p_project_id,pg_catalog.btrim(p_title),p_body)
   returning * into v_row;
 else
   if v_row.version<>p_expected_version then
     -- Replaying the save that produced this version is fine; anything else changed elsewhere.
     if not (v_row.version=p_expected_version+1 and v_row.title=pg_catalog.btrim(p_title) and v_row.body=p_body
             and v_row.project_id is not distinct from p_project_id)
     then raise exception 'Note changed elsewhere' using errcode='40001'; end if;
   else
     update public.notes set project_id=p_project_id,title=pg_catalog.btrim(p_title),body=p_body,version=version+1,updated_at=now()
     where id=p_id returning * into v_row;
   end if;
 end if;
 return pg_catalog.jsonb_build_object('id',v_row.id,'project_id',v_row.project_id,'title',v_row.title,'body',v_row.body,
   'version',v_row.version,'updated_at',v_row.updated_at);
end; $$;

create function public.focusos_delete_note(p_id uuid)
returns boolean language plpgsql security definer set search_path=''
as $$
begin
 if (select auth.uid()) is null then raise exception 'Authentication required' using errcode='28000'; end if;
 delete from public.notes where id=p_id and user_id=(select auth.uid());
 return found;
end; $$;

-- The vector of one exact version; a newer save makes it stale (it is then ignored).
create function public.focusos_set_note_embedding(p_id uuid,p_version integer,p_vector text)
returns boolean language plpgsql security definer set search_path=''
as $$
begin
 if (select auth.uid()) is null then raise exception 'Authentication required' using errcode='28000'; end if;
 if extensions.vector_dims(p_vector::extensions.vector)<>256 then raise exception 'Invalid vector' using errcode='22023'; end if;
 update public.notes set embedding=p_vector::extensions.vector(256),embedded_version=p_version
 where id=p_id and user_id=(select auth.uid()) and version=p_version;
 return found;
end; $$;

-- Hybrid search over notes, same shape as memories: keyword match plus vector, fused by rank.
create function public.focusos_search_notes(p_terms text[],p_vector text,p_limit integer)
returns jsonb language plpgsql stable security definer set search_path=''
as $$
declare v_owner uuid := (select auth.uid()); v_query tsquery; v_result jsonb;
begin
 if v_owner is null then raise exception 'Authentication required' using errcode='28000'; end if;
 if p_limit not between 1 and 10 or coalesce(pg_catalog.array_length(p_terms,1),0)>16
   or exists(select 1 from pg_catalog.unnest(coalesce(p_terms,'{}'::text[])) t where t !~ '^[a-z0-9]{2,40}$')
 then raise exception 'Invalid note search' using errcode='22023'; end if;
 if coalesce(pg_catalog.array_length(p_terms,1),0)>0 then
   select pg_catalog.to_tsquery('pg_catalog.simple'::regconfig,pg_catalog.string_agg(t||':*',' | ')) into v_query from pg_catalog.unnest(p_terms) t;
 end if;
 with scored as (
   select n.id,n.title,n.body,n.project_id,
     case when p_vector is not null and n.embedding is not null and n.embedded_version=n.version
       then 1-(n.embedding OPERATOR(extensions.<=>) p_vector::extensions.vector(256)) end as semantic,
     case when v_query is not null and pg_catalog.to_tsvector('pg_catalog.simple'::regconfig,n.title||' '||n.body) @@ v_query
       then pg_catalog.ts_rank(pg_catalog.to_tsvector('pg_catalog.simple'::regconfig,n.title||' '||n.body),v_query) else 0::real end as lexical
   from public.notes n where n.user_id=v_owner
 ), ranked as (
   select *, case when semantic>=0.6 then pg_catalog.row_number() over (order by semantic desc nulls last,id) end as srank,
     case when lexical>0 then pg_catalog.row_number() over (order by lexical desc,id) end as lrank from scored
 )
 select coalesce(pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object('id',r.id,'title',r.title,'excerpt',pg_catalog.left(r.body,700),'project_id',r.project_id)
   order by r.score desc),'[]'::jsonb) into v_result
 from (select *, coalesce(1.0/(60+srank),0)+coalesce(1.0/(60+lrank),0) as score from ranked
       where srank is not null or lrank is not null order by score desc,id limit p_limit) r;
 return v_result;
end; $$;

create table public.assignments (
 id uuid primary key default gen_random_uuid(),
 user_id uuid not null references auth.users(id) on delete cascade,
 request_key uuid not null,
 source_id uuid not null,
 project_id uuid,
 title text not null default 'Assignment' check(char_length(title) between 1 and 200),
 status text not null default 'transcribed' check(status in ('transcribed','questions','planned')),
 analysis jsonb check(analysis is null or (pg_catalog.jsonb_typeof(analysis)='object' and pg_column_size(analysis)<=32768)),
 understanding jsonb not null default '{}'::jsonb check(pg_catalog.jsonb_typeof(understanding)='object'),
 plan_run_id uuid,
 version integer not null default 1,
 created_at timestamptz not null default now(),
 updated_at timestamptz not null default now(),
 unique(user_id,request_key),
 unique(user_id,id),
 foreign key(user_id,source_id) references public.source_items(user_id,id) on delete cascade,
 foreign key(user_id,project_id) references public.projects(user_id,id) on delete set null (project_id)
);
alter table public.assignments enable row level security;
revoke all on public.assignments from public,anon,authenticated;
grant select on public.assignments to authenticated;
create policy assignments_read_owner on public.assignments for select to authenticated using(user_id=(select auth.uid()));

create function public.focusos_create_assignment(p_request_key uuid,p_source_id uuid,p_title text)
returns jsonb language plpgsql security definer set search_path=''
as $$
declare v_owner uuid := (select auth.uid()); v_row public.assignments;
begin
 if v_owner is null then raise exception 'Authentication required' using errcode='28000'; end if;
 select * into v_row from public.assignments where user_id=v_owner and request_key=p_request_key;
 if found then return pg_catalog.to_jsonb(v_row); end if;
 if not exists(select 1 from public.source_items where id=p_source_id and user_id=v_owner and deleted_at is null)
 then raise exception 'Source not found' using errcode='P0002'; end if;
 insert into public.assignments(user_id,request_key,source_id,title) values(v_owner,p_request_key,p_source_id,pg_catalog.left(pg_catalog.btrim(p_title),200))
 returning * into v_row;
 return pg_catalog.to_jsonb(v_row);
end; $$;

-- Only these fields may change, each step guarded by the version the caller last read.
create function public.focusos_update_assignment(p_id uuid,p_expected_version integer,p_fields jsonb)
returns jsonb language plpgsql security definer set search_path=''
as $$
declare v_owner uuid := (select auth.uid()); v_row public.assignments;
begin
 if v_owner is null then raise exception 'Authentication required' using errcode='28000'; end if;
 if pg_catalog.jsonb_typeof(p_fields)<>'object' or exists(select 1 from pg_catalog.jsonb_object_keys(p_fields) k
     where k not in ('title','status','analysis','understanding','project_id','plan_run_id'))
 then raise exception 'Invalid assignment change' using errcode='22023'; end if;
 if p_fields ? 'project_id' and p_fields->>'project_id' is not null
   and not exists(select 1 from public.projects where id=(p_fields->>'project_id')::uuid and user_id=v_owner)
 then raise exception 'Project not found' using errcode='P0002'; end if;
 update public.assignments set
   title=coalesce(p_fields->>'title',title),
   status=coalesce(p_fields->>'status',status),
   analysis=case when p_fields ? 'analysis' then p_fields->'analysis' else analysis end,
   understanding=case when p_fields ? 'understanding' then p_fields->'understanding' else understanding end,
   project_id=case when p_fields ? 'project_id' then (p_fields->>'project_id')::uuid else project_id end,
   plan_run_id=case when p_fields ? 'plan_run_id' then (p_fields->>'plan_run_id')::uuid else plan_run_id end,
   version=version+1,updated_at=now()
 where id=p_id and user_id=v_owner and version=p_expected_version
 returning * into v_row;
 if not found then
   if exists(select 1 from public.assignments where id=p_id and user_id=v_owner)
   then raise exception 'Assignment changed elsewhere' using errcode='40001'; end if;
   raise exception 'Assignment not found' using errcode='P0002';
 end if;
 return pg_catalog.to_jsonb(v_row);
end; $$;

revoke all on function public.focusos_save_note(uuid,uuid,text,text,integer) from public,anon;
revoke all on function public.focusos_delete_note(uuid) from public,anon;
revoke all on function public.focusos_set_note_embedding(uuid,integer,text) from public,anon;
revoke all on function public.focusos_search_notes(text[],text,integer) from public,anon;
revoke all on function public.focusos_create_assignment(uuid,uuid,text) from public,anon;
revoke all on function public.focusos_update_assignment(uuid,integer,jsonb) from public,anon;
grant execute on function public.focusos_save_note(uuid,uuid,text,text,integer) to authenticated;
grant execute on function public.focusos_delete_note(uuid) to authenticated;
grant execute on function public.focusos_set_note_embedding(uuid,integer,text) to authenticated;
grant execute on function public.focusos_search_notes(text[],text,integer) to authenticated;
grant execute on function public.focusos_create_assignment(uuid,uuid,text) to authenticated;
grant execute on function public.focusos_update_assignment(uuid,integer,jsonb) to authenticated;
