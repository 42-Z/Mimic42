-- Issue #137: пул прокси, через которые мимики ходят в Telegram.
--
-- Прокси назначает администратор или автовыдача при онбординге; адрес и
-- пароль не должны быть видны клиенту. Пароль хранится шифртекстом, как
-- HASH общего Telegram-приложения.

create table public.telegram_proxies (
    id uuid primary key default gen_random_uuid(),
    label text not null check (btrim(label) <> ''),
    protocol text not null check (protocol in ('socks5', 'http')),
    host text not null check (btrim(host) <> ''),
    port integer not null check (port between 1 and 65535),
    username text,
    password_ciphertext text check (
        password_ciphertext is null or btrim(password_ciphertext) <> ''
    ),
    is_active boolean not null default true,
    created_by uuid references public.profiles(id) on delete set null,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index telegram_proxies_active_created_idx
    on public.telegram_proxies(is_active, created_at, id);

create trigger telegram_proxies_set_updated_at
before update on public.telegram_proxies
for each row execute function public.set_updated_at();

-- Прокси закрепляется до запроса кода и переносится в рабочую сессию, поэтому
-- ссылки стоят в обеих таблицах. Удаление прокси отвязывает его; сервер не
-- удаляет занятый прокси, чтобы не менять сеть работающего мимика.
alter table public.agent_onboarding_sessions
    add column proxy_id uuid references public.telegram_proxies(id) on delete set null;

alter table public.telegram_sessions
    add column proxy_id uuid references public.telegram_proxies(id) on delete set null;

create index agent_onboarding_sessions_proxy_id_idx
    on public.agent_onboarding_sessions(proxy_id);

create index telegram_sessions_proxy_id_idx
    on public.telegram_sessions(proxy_id);

alter table public.telegram_proxies enable row level security;

revoke all on public.telegram_proxies from public, anon, authenticated, service_role;

grant select, insert, update, delete on public.telegram_proxies to service_role;

-- Клиент только читает Telegram-сессию для дэшборда. Раньше у authenticated
-- оставались широкие права на запись, через которые можно было бы подменить
-- proxy_id агента (и его сетевой адрес) в обход админ-панели.
revoke insert, update, delete on public.telegram_sessions from anon, authenticated;

-- Аудит админских действий пополняется прокси и сменой прокси у мимика.
alter table public.admin_audit_log
    drop constraint admin_audit_action_object_consistency;

alter table public.admin_audit_log
    drop constraint admin_audit_object_identity;

alter table public.admin_audit_log
    drop constraint admin_audit_log_action_check;

alter table public.admin_audit_log
    drop constraint admin_audit_log_object_type_check;

alter table public.admin_audit_log
    add constraint admin_audit_log_action_check check (action in (
        'preset.created',
        'preset.updated',
        'preset.visibility_changed',
        'telegram.settings_updated',
        'proxy.created',
        'proxy.updated',
        'proxy.deleted',
        'agent.proxy_changed'
    ));

alter table public.admin_audit_log
    add constraint admin_audit_log_object_type_check check (object_type in (
        'preset',
        'telegram_settings',
        'proxy',
        'agent'
    ));

alter table public.admin_audit_log
    add constraint admin_audit_object_identity check (
        (object_type in ('preset', 'proxy', 'agent') and object_id is not null)
        or (object_type = 'telegram_settings' and object_id is null)
    );

alter table public.admin_audit_log
    add constraint admin_audit_action_object_consistency check (
        (
            action in ('preset.created', 'preset.updated', 'preset.visibility_changed')
            and object_type = 'preset'
            and object_id is not null
        )
        or (
            action = 'telegram.settings_updated'
            and object_type = 'telegram_settings'
            and object_id is null
        )
        or (
            action in ('proxy.created', 'proxy.updated', 'proxy.deleted')
            and object_type = 'proxy'
            and object_id is not null
        )
        or (
            action = 'agent.proxy_changed'
            and object_type = 'agent'
            and object_id is not null
        )
    );
