-- Идемпотентная защита: на проекте, где agents уже включён в публикацию
-- через дашборд, обычный `alter publication ... add table` прерывает всю
-- миграцию с "already member of publication". Добавляем только при отсутствии.
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
