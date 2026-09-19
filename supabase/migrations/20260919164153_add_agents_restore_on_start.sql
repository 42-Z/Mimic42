-- Признак «восстанавливать агента при старте бэкенда» (issue #87).
-- Тестовые мимики (инфраструктура real-Telegram тестов) помечаются false:
-- обычный запуск их не поднимает, тесты стартуют их явно.
alter table public.agents
    add column restore_on_start boolean not null default true;
