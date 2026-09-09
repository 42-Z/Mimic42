-- Согласование схемы между окружениями и поведением приложения.
--
-- Базовый констрейнт запрещал пустой content, но приложение легитимно пишет
-- пустые сообщения: tool_call (текст живёт в payload.tool_calls) и
-- структурированные ответы (текст в payload.structured_response.text).
-- Пустой content разрешён только для них — обычные сообщения остаются
-- обязательными непустыми.
alter table public.agent_messages
    drop constraint if exists agent_messages_content_not_blank;

alter table public.agent_messages
    add constraint agent_messages_content_not_blank
    check (
        btrim(content) <> ''
        or payload ? 'tool_calls'
        or payload ? 'structured_response'
        or payload ? 'tool_call_id'
    );

-- Приводим phone_not_blank к каноничному виду из базовой миграции
-- (семантика та же: NULL разрешён, пустой номер после trim — нет).
alter table public.agent_onboarding_sessions
    drop constraint if exists agent_onboarding_sessions_phone_not_blank;

alter table public.agent_onboarding_sessions
    add constraint agent_onboarding_sessions_phone_not_blank
    check (phone_number is null or btrim(phone_number) <> '');
