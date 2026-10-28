-- Each passage belongs to one Supabase Auth user. The exposed table is guarded
-- by RLS; helper functions run with the caller's rights, never service role.
create table public.rag_passages (
    id bigint generated always as identity primary key,
    user_id uuid not null references auth.users(id) on delete cascade,
    source text not null check (char_length(source) between 1 and 200),
    chunk_index integer not null check (chunk_index >= 0),
    content text not null check (char_length(content) between 1 and 2000),
    search_vector tsvector generated always as
        (to_tsvector('english'::regconfig, content)) stored,
    unique (user_id, source, chunk_index)
);

create index rag_passages_owner_source on public.rag_passages (user_id, source);
create index rag_passages_search on public.rag_passages using gin (search_vector);
alter table public.rag_passages enable row level security;

grant select, insert, delete on public.rag_passages to authenticated;
grant usage, select on sequence public.rag_passages_id_seq to authenticated;

create policy rag_select_own on public.rag_passages for select to authenticated
    using ((select auth.uid()) = user_id);
create policy rag_insert_own on public.rag_passages for insert to authenticated
    with check ((select auth.uid()) = user_id);
create policy rag_delete_own on public.rag_passages for delete to authenticated
    using ((select auth.uid()) = user_id);

-- The quota also covers direct Data API inserts, not only the convenience RPC.
create function public.rag_enforce_quota()
returns trigger language plpgsql security invoker set search_path = '' as $$
begin
    perform pg_catalog.pg_advisory_xact_lock(
        pg_catalog.hashtextextended(new.user_id::text, 20261028)
    );
    if (select count(*) from public.rag_passages where user_id = new.user_id) >= 2000 then
        raise exception 'passage quota exceeded';
    end if;
    if (select count(*) from public.rag_passages
        where user_id = new.user_id and source = new.source) >= 100 then
        raise exception 'source quota exceeded';
    end if;
    return new;
end;
$$;
create trigger rag_passage_quota before insert on public.rag_passages
for each row execute function public.rag_enforce_quota();

create function public.rag_replace_source(p_source text, p_chunks text[])
returns integer language plpgsql security invoker set search_path = '' as $$
declare
    v_user uuid := auth.uid();
    v_count integer := coalesce(cardinality(p_chunks), 0);
begin
    if v_user is null then
        raise exception 'sign in required';
    end if;
    if p_source is null or char_length(p_source) not between 1 and 200
       or v_count > 100 or exists (
           select 1 from unnest(p_chunks) as input(chunk)
           where chunk is null or char_length(chunk) not between 1 and 2000
       ) then
        raise exception 'invalid source or chunks';
    end if;

    perform pg_catalog.pg_advisory_xact_lock(
        pg_catalog.hashtextextended(v_user::text, 20261028)
    );
    delete from public.rag_passages
    where user_id = v_user and source = p_source;
    if (select count(*) from public.rag_passages where user_id = v_user) + v_count > 2000 then
        raise exception 'passage quota exceeded';
    end if;
    insert into public.rag_passages (user_id, source, chunk_index, content)
    select v_user, p_source, ordinality::integer - 1, chunk
    from unnest(p_chunks) with ordinality as input(chunk, ordinality);
    return v_count;
end;
$$;

create function public.rag_sources()
returns table(source text, chunks bigint)
language sql stable security invoker set search_path = '' as $$
    select p.source, count(*) from public.rag_passages p
    where p.user_id = (select auth.uid())
    group by p.source order by p.source;
$$;

create function public.rag_delete_source(p_source text)
returns integer language plpgsql security invoker set search_path = '' as $$
declare
    v_deleted integer;
begin
    if auth.uid() is null then
        raise exception 'sign in required';
    end if;
    delete from public.rag_passages
    where user_id = (select auth.uid()) and source = p_source;
    get diagnostics v_deleted = row_count;
    return v_deleted;
end;
$$;

create function public.rag_search(p_query text, p_limit integer default 5)
returns table(id bigint, source text, content text, score real)
language sql stable security invoker set search_path = '' as $$
    select p.id, p.source, p.content,
           pg_catalog.ts_rank(p.search_vector, q.query)::real as score
    from public.rag_passages p,
         pg_catalog.websearch_to_tsquery('english'::regconfig, left(p_query, 300)) as q(query)
    where p.user_id = (select auth.uid()) and p.search_vector @@ q.query
    order by score desc, p.id
    limit least(greatest(coalesce(p_limit, 5), 1), 20);
$$;

revoke all on function public.rag_replace_source(text, text[]) from public, anon;
revoke all on function public.rag_enforce_quota() from public, anon;
revoke all on function public.rag_sources() from public, anon;
revoke all on function public.rag_delete_source(text) from public, anon;
revoke all on function public.rag_search(text, integer) from public, anon;
grant execute on function public.rag_replace_source(text, text[]) to authenticated;
grant execute on function public.rag_sources() to authenticated;
grant execute on function public.rag_delete_source(text) to authenticated;
grant execute on function public.rag_search(text, integer) to authenticated;
