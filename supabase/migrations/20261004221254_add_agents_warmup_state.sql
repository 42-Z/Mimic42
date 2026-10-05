-- Ограничение аккаунта Telegram и режим восстановления (прогрев аккаунтов, issue #111).
-- Когда Telegram запретил агенту писать первым незнакомым (PeerFloodError), сервер
-- ставит warmup_restricted_at; warmup_recovery — пользователь выбрал восстановление.
-- Колонками, а не в agents.settings: форма настроек перезаписывает settings целиком
-- и затёрла бы состояние, которое ведёт только сервер.
alter table public.agents
    add column warmup_restricted_at timestamptz,
    add column warmup_recovery boolean not null default false;

-- Восстанавливать можно только ограниченный аккаунт.
alter table public.agents
    add constraint agents_warmup_recovery_requires_restriction
    check (not warmup_recovery or warmup_restricted_at is not null);
