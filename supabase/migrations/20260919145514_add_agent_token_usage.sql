-- Пожизненные счётчики токенов агента (issue #81). Живут отдельно от строки
-- agents: каждый вызов модели инкрементит их upsert-ом и не трогает
-- agents.updated_at/его триггер.
create table public.agent_token_usage (
    agent_id uuid primary key references public.agents(id) on delete cascade,
    input_tokens bigint not null default 0,
    output_tokens bigint not null default 0,
    updated_at timestamptz not null default now()
);

alter table public.agent_token_usage enable row level security;

-- (select auth.uid()) — initplan: функция вычисляется один раз на запрос,
-- а не на каждую строку (Supabase advisor auth_rls_initplan).
create policy "Users can read token usage of their agents"
on public.agent_token_usage
for select
to authenticated
using (
    exists (
        select 1
        from public.agents
        where agents.id = agent_token_usage.agent_id
            and agents.owner_id = (select auth.uid())
    )
);
