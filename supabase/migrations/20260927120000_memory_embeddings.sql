-- Phase 7.5: one selected memory embedding with a durable lease.
create extension if not exists vector with schema extensions;
alter table public.memories
 add column embedding extensions.vector(256),
 add column embedding_model text,
 add column embedding_dim integer,
 add column embedding_hash text,
 add column embedding_status text not null default 'pending'
   check(embedding_status in ('pending','processing','ready','failed')),
 add column embedding_error text,
 add column embedding_lease_token uuid,
 add column embedding_lease_until timestamptz,
 add column embedding_updated_at timestamptz,
 add constraint memory_embedding_shape check(
   (embedding_status='ready' and embedding is not null and embedding_model='text-embedding-3-small'
    and embedding_dim=256 and embedding_hash ~ '^[0-9a-f]{64}$')
   or (embedding_status<>'ready' and embedding is null)
 );
grant select(embedding_status,embedding_model,embedding_dim,embedding_hash,embedding_error,embedding_updated_at)
 on public.memories to authenticated;

create function public.focusos_claim_memory_embedding(
 p_memory_id uuid,p_model text,p_dim integer,p_content_hash text
) returns jsonb language plpgsql security definer set search_path=''
as $$
declare v_owner uuid := (select auth.uid()); v_row public.memories; v_lease uuid;
begin
 if v_owner is null then raise exception 'Authentication required' using errcode='28000'; end if;
 if p_model<>'text-embedding-3-small' or p_dim<>256 or p_content_hash !~ '^[0-9a-f]{64}$'
 then raise exception 'Invalid embedding contract' using errcode='22023'; end if;
 select * into v_row from public.memories where id=p_memory_id and user_id=v_owner for update;
 if v_row.id is null or v_row.status<>'active' or not exists(
   select 1 from public.source_items s where s.id=v_row.source_id and s.user_id=v_owner
      and s.deleted_at is null and s.body_hash=v_row.source_hash)
 then return jsonb_build_object('state','unavailable'); end if;
 if v_row.embedding_status='ready' and v_row.embedding_model=p_model
    and v_row.embedding_dim=p_dim and v_row.embedding_hash=p_content_hash
 then return jsonb_build_object('state','reused'); end if;
 if v_row.embedding_status='processing' and v_row.embedding_lease_until>now()
 then return jsonb_build_object('state','busy'); end if;
 v_lease:=gen_random_uuid();
 update public.memories set embedding_status='processing',embedding=null,
   embedding_model=null,embedding_dim=null,embedding_hash=null,embedding_error=null,
   embedding_lease_token=v_lease,embedding_lease_until=now()+interval '45 seconds',
   embedding_updated_at=now()
 where id=p_memory_id and user_id=v_owner;
 return jsonb_build_object('state','claimed','lease_token',v_lease,
   'text',v_row.text,'quote',v_row.evidence_quote,'source_hash',v_row.source_hash);
end; $$;
revoke all on function public.focusos_claim_memory_embedding(uuid,text,integer,text) from public,anon;
grant execute on function public.focusos_claim_memory_embedding(uuid,text,integer,text) to authenticated;

create function public.focusos_finish_memory_embedding(
 p_memory_id uuid,p_lease_token uuid,p_content_hash text,p_vector text,p_error text
) returns boolean language plpgsql security definer set search_path=''
as $$
declare v_owner uuid := (select auth.uid());
begin
 if v_owner is null then raise exception 'Authentication required' using errcode='28000'; end if;
 if p_error is not null and p_error not in ('provider_unconfigured','provider_unavailable','invalid_vector')
 then raise exception 'Invalid embedding error' using errcode='22023'; end if;
 if p_error is null and (p_vector is null or p_content_hash !~ '^[0-9a-f]{64}$')
 then raise exception 'Invalid embedding result' using errcode='22023'; end if;
 if p_error is null then
   update public.memories m set embedding=p_vector::extensions.vector(256),
     embedding_model='text-embedding-3-small',embedding_dim=256,
     embedding_hash=p_content_hash,embedding_status='ready',embedding_error=null,
     embedding_lease_token=null,embedding_lease_until=null,embedding_updated_at=now()
   where m.id=p_memory_id and m.user_id=v_owner and m.status='active'
     and m.embedding_status='processing' and m.embedding_lease_token=p_lease_token
     and m.embedding_lease_until>now()
     and exists(select 1 from public.source_items s where s.id=m.source_id
       and s.user_id=v_owner and s.deleted_at is null and s.body_hash=m.source_hash);
 else
   update public.memories m set embedding_status='failed',embedding_error=p_error,
     embedding_lease_token=null,embedding_lease_until=null,embedding_updated_at=now()
   where m.id=p_memory_id and m.user_id=v_owner and m.status='active'
     and m.embedding_status='processing' and m.embedding_lease_token=p_lease_token
     and m.embedding_lease_until>now();
 end if;
 return found;
end; $$;
revoke all on function public.focusos_finish_memory_embedding(uuid,uuid,text,text,text) from public,anon;
grant execute on function public.focusos_finish_memory_embedding(uuid,uuid,text,text,text) to authenticated;
