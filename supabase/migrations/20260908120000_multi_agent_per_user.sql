-- Пользователь может проходить онбординг многократно: одна сессия = один агент
alter table public.agent_onboarding_sessions
    drop constraint if exists agent_onboarding_sessions_owner_id_key;

-- Статусы агентов должны приезжать в дашборд по realtime
alter publication supabase_realtime add table public.agents;
