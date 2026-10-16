-- A small personal knowledge graph built from confirmed memories. Every entity mention
-- and every relation points at the memory that states it, so graph answers stay cited.
create table public.entities (
 id uuid primary key default gen_random_uuid(),
 user_id uuid not null references auth.users(id) on delete cascade,
 kind text not null check(kind in ('person','project','organization','place','thing')),
 name text not null check(char_length(name) between 1 and 80),
 normalized text not null check(normalized ~ '^[a-z0-9]+( [a-z0-9]+)*$' and char_length(normalized) between 1 and 80),
 created_at timestamptz not null default now(),
 unique(user_id,kind,normalized),
 unique(user_id,id)
);
create table public.entity_mentions (
 user_id uuid not null references auth.users(id) on delete cascade,
 entity_id uuid not null,
 memory_id uuid not null,
 primary key(user_id,entity_id,memory_id),
 foreign key(user_id,entity_id) references public.entities(user_id,id) on delete cascade,
 foreign key(user_id,memory_id) references public.memories(user_id,id) on delete cascade
);
create table public.entity_edges (
 id uuid primary key default gen_random_uuid(),
 user_id uuid not null references auth.users(id) on delete cascade,
 subject_id uuid not null,
 predicate text not null check(predicate ~ '^[a-z][a-z_]{1,39}$'),
 object_id uuid,
 object_text text check(object_text is null or char_length(object_text) between 1 and 120),
 memory_id uuid not null,
 created_at timestamptz not null default now(),
 check((object_id is null)<>(object_text is null)),
 foreign key(user_id,subject_id) references public.entities(user_id,id) on delete cascade,
 foreign key(user_id,object_id) references public.entities(user_id,id) on delete cascade,
 foreign key(user_id,memory_id) references public.memories(user_id,id) on delete cascade
);
create unique index entity_edges_unique on public.entity_edges(user_id,subject_id,predicate,coalesce(object_id::text,object_text),memory_id);
create index entity_edges_subject on public.entity_edges(user_id,subject_id);
create index entity_edges_object on public.entity_edges(user_id,object_id) where object_id is not null;
create index entity_mentions_memory on public.entity_mentions(user_id,memory_id);
create table public.memory_graph_index (
 user_id uuid not null references auth.users(id) on delete cascade,
 memory_id uuid not null,
 indexed_at timestamptz not null default now(),
 primary key(user_id,memory_id),
 foreign key(user_id,memory_id) references public.memories(user_id,id) on delete cascade
);
alter table public.entities enable row level security;
alter table public.entity_mentions enable row level security;
alter table public.entity_edges enable row level security;
alter table public.memory_graph_index enable row level security;
revoke all on public.entities,public.entity_mentions,public.entity_edges,public.memory_graph_index from public,anon,authenticated;
grant select on public.entities,public.entity_mentions,public.entity_edges,public.memory_graph_index to authenticated;
create policy entities_read_owner on public.entities for select to authenticated using(user_id=(select auth.uid()));
create policy entity_mentions_read_owner on public.entity_mentions for select to authenticated using(user_id=(select auth.uid()));
create policy entity_edges_read_owner on public.entity_edges for select to authenticated using(user_id=(select auth.uid()));
create policy memory_graph_index_read_owner on public.memory_graph_index for select to authenticated using(user_id=(select auth.uid()));

-- p_entities: [{key,kind,name}], p_relations: [{subject,predicate,object|object_text}] for ONE memory.
-- Names and object texts must appear in the memory (the server also checks this before calling).
create function public.focusos_save_memory_graph(p_memory_id uuid,p_entities jsonb,p_relations jsonb)
returns jsonb language plpgsql security definer set search_path=''
as $$
declare v_owner uuid := (select auth.uid()); v_text text; v_item jsonb; v_id uuid; v_ids jsonb := '{}'::jsonb;
 v_norm text; v_object uuid; v_edges integer := 0;
begin
 if v_owner is null then raise exception 'Authentication required' using errcode='28000'; end if;
 select pg_catalog.lower(m.text||' '||m.evidence_quote) into v_text from public.memories m
 where m.id=p_memory_id and m.user_id=v_owner and m.status='active';
 if v_text is null then raise exception 'Memory not found' using errcode='P0002'; end if;
 if pg_catalog.jsonb_typeof(p_entities)<>'array' or pg_catalog.jsonb_typeof(p_relations)<>'array'
   or pg_catalog.jsonb_array_length(p_entities)>12 or pg_catalog.jsonb_array_length(p_relations)>12
 then raise exception 'Invalid graph' using errcode='22023'; end if;
 for v_item in select * from pg_catalog.jsonb_array_elements(p_entities) loop
   v_norm := pg_catalog.btrim(pg_catalog.regexp_replace(pg_catalog.lower(v_item->>'name'),'[^a-z0-9]+',' ','g'));
   if v_norm is null or v_norm='' or char_length(v_item->>'name')>80 or pg_catalog.strpos(v_text,pg_catalog.lower(v_item->>'name'))=0
     or coalesce(v_item->>'kind','') not in ('person','project','organization','place','thing')
     or coalesce(v_item->>'key','')!~'^[a-z0-9_-]{1,20}$'
   then raise exception 'Invalid entity' using errcode='22023'; end if;
   insert into public.entities(user_id,kind,name,normalized) values(v_owner,v_item->>'kind',v_item->>'name',v_norm)
   on conflict(user_id,kind,normalized) do update set name=public.entities.name returning id into v_id;
   insert into public.entity_mentions(user_id,entity_id,memory_id) values(v_owner,v_id,p_memory_id) on conflict do nothing;
   v_ids := v_ids||pg_catalog.jsonb_build_object(v_item->>'key',v_id);
 end loop;
 for v_item in select * from pg_catalog.jsonb_array_elements(p_relations) loop
   if not (v_ids ? (v_item->>'subject')) or coalesce(v_item->>'predicate','')!~'^[a-z][a-z_]{1,39}$'
     or ((v_item ? 'object') = (v_item ? 'object_text'))
     or (v_item ? 'object' and not (v_ids ? (v_item->>'object')))
     or (v_item ? 'object_text' and (char_length(v_item->>'object_text') not between 1 and 120
         or pg_catalog.strpos(v_text,pg_catalog.lower(v_item->>'object_text'))=0))
   then raise exception 'Invalid relation' using errcode='22023'; end if;
   v_object := case when v_item ? 'object' then (v_ids->>(v_item->>'object'))::uuid end;
   insert into public.entity_edges(user_id,subject_id,predicate,object_id,object_text,memory_id)
   values(v_owner,(v_ids->>(v_item->>'subject'))::uuid,v_item->>'predicate',v_object,
          case when v_object is null then v_item->>'object_text' end,p_memory_id)
   on conflict do nothing;
   v_edges := v_edges+1;
 end loop;
 insert into public.memory_graph_index(user_id,memory_id) values(v_owner,p_memory_id)
 on conflict(user_id,memory_id) do update set indexed_at=now();
 return pg_catalog.jsonb_build_object('entities',pg_catalog.jsonb_array_length(p_entities),'relations',v_edges);
end; $$;
revoke all on function public.focusos_save_memory_graph(uuid,jsonb,jsonb) from public,anon;
grant execute on function public.focusos_save_memory_graph(uuid,jsonb,jsonb) to authenticated;

-- Memories reachable from entities named in a question, up to p_hops relations away.
-- Hop 0 memories mention a named entity; hop 1-2 memories connect through relations.
create function public.focusos_graph_memories(p_terms text[],p_hops integer,p_limit integer)
returns jsonb language plpgsql stable security definer set search_path=''
as $$
declare v_owner uuid := (select auth.uid()); v_result jsonb;
begin
 if v_owner is null then raise exception 'Authentication required' using errcode='28000'; end if;
 if p_hops not between 0 and 2 or p_limit not between 1 and 10
   or coalesce(pg_catalog.array_length(p_terms,1),0) not between 1 and 16
   or exists(select 1 from pg_catalog.unnest(p_terms) t where t !~ '^[a-z0-9]{2,40}$')
 then raise exception 'Invalid graph search' using errcode='22023'; end if;
 with recursive seeds as (
   select e.id,e.name from public.entities e
   where e.user_id=v_owner and exists(select 1 from pg_catalog.unnest(p_terms) t
     where (' '||e.normalized) like ('% '||t||'%'))
   limit 20
 ), walk(entity_id,hop,path) as (
   select id,0,name::text from seeds
   union
   select case when ed.subject_id=w.entity_id then ed.object_id else ed.subject_id end,w.hop+1,
          w.path||' → '||ed.predicate||' → '||o.name
   from walk w
   join public.entity_edges ed on ed.user_id=v_owner and ed.object_id is not null
     and (ed.subject_id=w.entity_id or ed.object_id=w.entity_id)
   join public.entities o on o.user_id=v_owner
     and o.id=case when ed.subject_id=w.entity_id then ed.object_id else ed.subject_id end
   where w.hop<p_hops
 ), reached as (
   select distinct on (mm.memory_id) mm.memory_id,w.hop,w.path
   from walk w join public.entity_mentions mm on mm.user_id=v_owner and mm.entity_id=w.entity_id
   order by mm.memory_id,w.hop
 )
 select coalesce(pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object('id',m.id,'text',m.text,'evidence_quote',m.evidence_quote,
   'hop',r.hop,'path',pg_catalog.left(r.path,300)) order by r.hop,m.created_at desc),'[]'::jsonb)
 into v_result
 from (select * from reached order by hop limit p_limit) r
 join public.memories m on m.id=r.memory_id and m.user_id=v_owner and m.status='active';
 return v_result;
end; $$;
revoke all on function public.focusos_graph_memories(text[],integer,integer) from public,anon;
grant execute on function public.focusos_graph_memories(text[],integer,integer) to authenticated;
