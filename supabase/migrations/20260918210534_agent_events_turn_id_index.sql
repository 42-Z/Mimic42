-- Лента ходов (DatabaseAgentStore.get_conversation) выбирает события хода
-- выражением `agent_id = ... and payload->>'turn_id' in (...)`. Без индекса
-- под это выражение PostgreSQL перебирает все события агента, а эндпоинт
-- дергается realtime-инвалидацией почти раз в секунду по всем загруженным
-- страницам — на десятках тысяч событий это линейный рост на каждый тик.
--
-- Выражение обязано совпадать с запросом SQLAlchemy
-- (`payload["turn_id"].as_string()`), который компилируется в
-- `CAST((payload ->> 'turn_id') AS VARCHAR)`. text->varchar — бинарно
-- совместимое приведение, планировщик его снимает, поэтому обычное
-- `((payload->>'turn_id'))` индексирует то же выражение.
create index if not exists agent_events_agent_id_turn_id_idx
    on public.agent_events (agent_id, ((payload->>'turn_id')));
