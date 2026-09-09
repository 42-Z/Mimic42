-- Пользователь может проходить онбординг многократно: одна сессия = один агент
alter table public.agent_onboarding_sessions
    drop constraint if exists agent_onboarding_sessions_owner_id_key;

-- Статусы агентов должны приезжать в дашборд по realtime.
-- Guard нужен: если agents уже включён в публикацию (например, через дашборд
-- в окружении, склонированном с прода), безусловный alter прерывает миграцию.
do $$
begin
    if not exists (
        select 1 from pg_publication_tables
        where pubname = 'supabase_realtime'
          and schemaname = 'public'
          and tablename = 'agents'
    ) then
        alter publication supabase_realtime add table public.agents;
    end if;
end
$$;
