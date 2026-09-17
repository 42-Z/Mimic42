-- Приватность media-бакета не должна зависеть от того, что «пока никто не
-- добавил широкую policy» на storage.objects: было достаточно одной чужой
-- permissive-политики (`bucket_id = 'agent-media'` или вообще без условия),
-- чтобы anon/authenticated выкачали файлы агентов напрямую, минуя API.
-- Restrictive-политика перемножается со всеми permissive: доступ к объектам
-- бакета запрещён всем клиентским ролям при любом наборе политик.
-- service_role (бэкенд) RLS обходит и продолжает работать как раньше.
create policy "agent_media_clients_denied"
    on storage.objects
    as restrictive
    for all
    to anon, authenticated
    using (bucket_id <> 'agent-media')
    with check (bucket_id <> 'agent-media');
