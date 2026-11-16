-- Issue #41: режим атаки. Кампания на один пост канала, участия мимиков,
-- общий лимит и резерв отправки. См. design.md, раздел «Данные».

create type public.attack_status as enum (
    'draft',
    'running',
    'cancelled',
    'finished'
);

create type public.attack_limit_type as enum (
    'messages',
    'minutes'
);

create type public.attack_agent_status as enum (
    'assigned',
    'active',
    'exited'
);

create table public.attacks (
    id uuid primary key default gen_random_uuid(),
    owner_id uuid not null references public.profiles(id) on delete cascade,
    title text,
    target_link text not null,
    target_channel_peer text not null,
    target_message_id bigint not null,
    target_channel_id bigint,
    anchor_message_id bigint,
    slowmode_seconds integer,
    texts jsonb not null,
    media_paths jsonb not null default '[]'::jsonb,
    limit_type public.attack_limit_type not null,
    limit_value integer not null,
    status public.attack_status not null default 'draft',
    sent_count integer not null default 0,
    claimed_count integer not null default 0,
    version integer not null default 1,
    started_at timestamptz,
    deadline_at timestamptz,
    finished_at timestamptz,
    end_reason text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint attacks_target_link_not_blank check (btrim(target_link) <> ''),
    constraint attacks_target_channel_peer_not_blank check (btrim(target_channel_peer) <> ''),
    constraint attacks_texts_is_array check (jsonb_typeof(texts) = 'array'),
    constraint attacks_texts_not_empty check (jsonb_array_length(texts) > 0),
    constraint attacks_media_paths_is_array check (jsonb_typeof(media_paths) = 'array'),
    constraint attacks_limit_value_positive check (limit_value > 0),
    constraint attacks_slowmode_seconds_not_negative check (
        slowmode_seconds is null or slowmode_seconds >= 0
    ),
    constraint attacks_counters_not_negative check (sent_count >= 0 and claimed_count >= 0),
    constraint attacks_sent_within_claim check (sent_count <= claimed_count),
    constraint attacks_running_has_started_at check (
        status <> 'running' or started_at is not null
    ),
    constraint attacks_closed_has_end check (
        status not in ('finished', 'cancelled')
        or (finished_at is not null and end_reason is not null)
    )
);

create index attacks_owner_id_status_created_at_idx
    on public.attacks(owner_id, status, created_at desc);

create table public.attack_agents (
    id uuid primary key default gen_random_uuid(),
    attack_id uuid not null references public.attacks(id) on delete cascade,
    agent_id uuid not null references public.agents(id) on delete cascade,
    status public.attack_agent_status not null default 'assigned',
    sent_count integer not null default 0,
    next_at timestamptz,
    pending_random_id bigint,
    pending_text text,
    pending_media jsonb,
    pending_attempts integer not null default 0,
    last_comment_message_id bigint,
    last_error_code text,
    last_error text,
    exit_reason text,
    note_written_at timestamptz,
    memory_synced_at timestamptz,
    joined_at timestamptz not null default now(),
    exited_at timestamptz,
    constraint attack_agents_sent_count_not_negative check (sent_count >= 0),
    constraint attack_agents_pending_attempts_not_negative check (pending_attempts >= 0),
    constraint attack_agents_pending_media_is_array check (
        pending_media is null or jsonb_typeof(pending_media) = 'array'
    ),
    constraint attack_agents_pending_pair check (
        (pending_random_id is null) = (pending_text is null)
    ),
    constraint attack_agents_exited_has_reason check (
        status <> 'exited' or (exit_reason is not null and exited_at is not null)
    )
);

create index attack_agents_agent_id_status_idx on public.attack_agents(agent_id, status);
create index attack_agents_attack_id_status_idx on public.attack_agents(attack_id, status);
create unique index attack_agents_active_agent_idx
    on public.attack_agents(agent_id)
    where status in ('assigned', 'active');

create trigger attacks_set_updated_at
before update on public.attacks
for each row execute function public.set_updated_at();

alter table public.attacks enable row level security;
alter table public.attack_agents enable row level security;

revoke all on public.attacks from public, anon, authenticated, service_role;
revoke all on public.attack_agents from public, anon, authenticated, service_role;

grant select, insert, update, delete on public.attacks to authenticated, service_role;
grant select, insert, update, delete on public.attack_agents to authenticated, service_role;

create policy "Users can read their attacks"
on public.attacks
for select
to authenticated
using (owner_id = auth.uid());

create policy "Users can create their attacks"
on public.attacks
for insert
to authenticated
with check (owner_id = auth.uid());

create policy "Users can update their attacks"
on public.attacks
for update
to authenticated
using (owner_id = auth.uid())
with check (owner_id = auth.uid());

create policy "Users can delete their attacks"
on public.attacks
for delete
to authenticated
using (owner_id = auth.uid());

create policy "Users can manage their attack participations"
on public.attack_agents
for all
to authenticated
using (
    exists (
        select 1
        from public.attacks
        where attacks.id = attack_agents.attack_id
            and attacks.owner_id = auth.uid()
    )
    and exists (
        select 1
        from public.agents
        where agents.id = attack_agents.agent_id
            and agents.owner_id = auth.uid()
    )
)
with check (
    exists (
        select 1
        from public.attacks
        where attacks.id = attack_agents.attack_id
            and attacks.owner_id = auth.uid()
    )
    and exists (
        select 1
        from public.agents
        where agents.id = attack_agents.agent_id
            and agents.owner_id = auth.uid()
    )
);
