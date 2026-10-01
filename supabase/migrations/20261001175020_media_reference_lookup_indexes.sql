-- Media resolution must not scan an agent's whole transcript after a restart.
create index agent_messages_media_lookup_idx
    on public.agent_messages using gin (payload jsonb_path_ops);
create index agent_events_view_image_media_lookup_idx
    on public.agent_events (agent_id, ((payload->'args'->>'media_id')), created_at desc, id desc)
    where event_type = 'tool.view_image' and status = 'succeeded';
create index agent_events_history_media_lookup_idx
    on public.agent_events using gin (result jsonb_path_ops)
    where event_type = 'tool.get_messages' and status = 'succeeded';
