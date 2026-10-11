-- Issue #67: prompt_presets становится единым каталогом. Официальные строки
-- (owner_id is null) остаются read-only для клиентов; пользовательские строки
-- создаются как черновики и выкладываются публикацией published_at.

alter table public.prompt_presets
    add column owner_id uuid references public.profiles(id) on delete cascade,
    add column published_at timestamptz;

create index prompt_presets_published_idx
    on public.prompt_presets (published_at)
    where published_at is not null;

-- Платформа выдаёт authenticated все DML-привилегии по умолчанию; запись
-- раздаём заново поколоночно, чтобы клиент не мог трогать slug, is_active и
-- owner_id — их ставит триггер-ограждение.
revoke insert, update, delete on public.prompt_presets from authenticated;

grant insert (title, summary, body, settings) on public.prompt_presets to authenticated;
grant update (title, summary, body, settings, published_at) on public.prompt_presets to authenticated;
grant delete on public.prompt_presets to authenticated;

-- Старая политика «только is_active» открыла бы все пользовательские черновики
-- всем — заменяем на трёхчастную.
drop policy "Authenticated users can read active prompt presets" on public.prompt_presets;

create policy "Authenticated users can read catalog presets"
    on public.prompt_presets
    for select
    to authenticated
    using (
        owner_id = auth.uid()
        or published_at is not null
        or (owner_id is null and is_active)
    );

create policy "Authenticated users can create own draft presets"
    on public.prompt_presets
    for insert
    to authenticated
    with check (owner_id = auth.uid() and published_at is null);

create policy "Authenticated users can update own presets"
    on public.prompt_presets
    for update
    to authenticated
    using (owner_id = auth.uid())
    with check (owner_id = auth.uid());

create policy "Authenticated users can delete own presets"
    on public.prompt_presets
    for delete
    to authenticated
    using (owner_id = auth.uid());

-- Ограждение клиентских сессий: сервисная запись и миграции ходят без
-- JWT-клеймов и проходят беспрепятственно.
create or replace function public.guard_user_prompt_presets() returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
    if auth.uid() is null then
        return coalesce(new, old);
    end if;

    if tg_op = 'INSERT' then
        new.owner_id = auth.uid();
        new.published_at = null;
        new.is_active = true;
        new.slug = 'u_' || new.id::text;
        return new;
    end if;

    if old.owner_id is null then
        raise exception 'Официальные пресеты изменять нельзя';
    end if;

    if tg_op = 'UPDATE' then
        if new.owner_id <> old.owner_id then
            raise exception 'Владельца пресета менять нельзя';
        end if;
        if new.slug <> old.slug then
            raise exception 'Слаг пресета менять нельзя';
        end if;
        return new;
    end if;

    return old;
end;
$$;

create trigger prompt_presets_guard_insert
    before insert on public.prompt_presets
    for each row execute function public.guard_user_prompt_presets();

create trigger prompt_presets_guard_update
    before update on public.prompt_presets
    for each row execute function public.guard_user_prompt_presets();

create trigger prompt_presets_guard_delete
    before delete on public.prompt_presets
    for each row execute function public.guard_user_prompt_presets();
