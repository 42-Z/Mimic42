-- Приватный бакет для медиа из ленты активности: файлы пишет/читает только
-- бэкенд (service_role), дашборд ходит через /api/v1/agents/{id}/media/*.
-- file_size_limit = 20 МБ — совпадает с MAX_MEDIA_BYTES в supabase_media.py.
insert into storage.buckets (id, name, public, file_size_limit)
values ('agent-media', 'agent-media', false, 20971520)
on conflict (id) do update
    set file_size_limit = excluded.file_size_limit,
        public = false;
