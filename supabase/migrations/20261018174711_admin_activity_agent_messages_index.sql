create index concurrently if not exists agent_messages_admin_activity_date_idx
    on public.agent_messages(created_at)
    where direction in ('incoming', 'agent_response');
