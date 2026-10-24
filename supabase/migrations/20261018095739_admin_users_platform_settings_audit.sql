create table public.admin_users (
    user_id uuid primary key references public.profiles(id) on delete cascade,
    created_at timestamptz not null default now()
);

create table public.platform_telegram_settings (
    id smallint primary key default 1 check (id = 1),
    api_id integer not null check (api_id > 0),
    api_hash_ciphertext text not null check (btrim(api_hash_ciphertext) <> ''),
    updated_by uuid references public.profiles(id) on delete set null,
    updated_at timestamptz not null default now()
);

create table public.admin_audit_log (
    id uuid primary key default gen_random_uuid(),
    actor_user_id uuid not null,
    action text not null check (action in (
        'preset.created', 'preset.updated', 'preset.visibility_changed',
        'telegram.settings_updated'
    )),
    object_type text not null check (object_type in ('preset', 'telegram_settings')),
    object_id uuid,
    metadata jsonb not null default '{}'::jsonb check (jsonb_typeof(metadata) = 'object'),
    created_at timestamptz not null default now(),
    constraint admin_audit_object_identity check (
        (object_type = 'preset' and object_id is not null)
        or (object_type = 'telegram_settings' and object_id is null)
    )
);

create index platform_telegram_settings_updated_by_idx
    on public.platform_telegram_settings(updated_by);

create index admin_audit_log_actor_created_idx
    on public.admin_audit_log(actor_user_id, created_at desc);

alter table public.admin_users enable row level security;

alter table public.platform_telegram_settings enable row level security;

alter table public.admin_audit_log enable row level security;

revoke all on public.admin_users, public.platform_telegram_settings,
    public.admin_audit_log from public, anon, authenticated;

grant select, insert, update, delete on public.admin_users to service_role;

grant select, insert, update on public.platform_telegram_settings to service_role;

grant select, insert on public.admin_audit_log to service_role;
