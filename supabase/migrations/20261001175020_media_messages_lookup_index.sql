-- Поиск медиа после рестарта (issue #105) идёт по payload сообщений
-- выражением `payload @> '{"media": [{"media_id": ...}]}'`.
--
-- Индекс строится concurrently: в проде работают живые агенты, и обычная
-- сборка заблокировала бы запись на всё время построения. Один оператор на
-- файл — CLI выносит одиночный `create index concurrently` из транзакции, а
-- файл с несколькими операторами уходит в pipeline и падает (SQLSTATE 25001).
create index concurrently if not exists agent_messages_media_lookup_idx
    on public.agent_messages using gin (payload jsonb_path_ops);
