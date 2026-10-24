create index concurrently if not exists agent_events_admin_activity_date_idx
    on public.agent_events(created_at)
    where event_type like 'tool.%' or status = 'failed';
