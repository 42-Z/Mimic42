-- Восстановление архивной копии, открытой через view_image (issue #105):
-- событие ищется по media_id из payload.args, поэтому выражение индекса
-- обязано совпадать с запросом `payload["args"]["media_id"].as_string()`.
-- Concurrently и отдельным файлом — см. 20261001175020_media_messages_lookup_index.sql.
create index concurrently if not exists agent_events_view_image_media_lookup_idx
    on public.agent_events (agent_id, ((payload->'args'->>'media_id')), created_at desc, id desc)
    where event_type = 'tool.view_image' and status = 'succeeded';
