-- Координаты медиа из прочитанной истории (tool.get_messages, issue #105)
-- достаются из result.items через containment `result @> ...`.
-- Concurrently и отдельным файлом — см. 20261001175020_media_messages_lookup_index.sql.
create index concurrently if not exists agent_events_history_media_lookup_idx
    on public.agent_events using gin (result jsonb_path_ops)
    where event_type = 'tool.get_messages' and status = 'succeeded';
