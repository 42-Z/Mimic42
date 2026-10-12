-- Избранное пресетов. Пока пресет на витрине, избранное смотрит на живую
-- строку (снимки пустые). Снятие с витрины и удаление пресета замораживают
-- избранное триггером из следующей миграции; замороженная копия остаётся
-- только для применения.

create table public.preset_favorites (
    id uuid primary key default gen_random_uuid(),
    owner_id uuid not null references public.profiles(id) on delete cascade,
    preset_id uuid references public.prompt_presets(id) on delete cascade,
    frozen_title text,
    frozen_summary text,
    frozen_body text,
    frozen_settings jsonb
        check (frozen_settings is null or jsonb_typeof(frozen_settings) = 'object'),
    frozen_at timestamptz,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (owner_id, preset_id),
    constraint preset_favorites_source_xor_snapshot
        check (
            -- Живое избранное: ссылка есть, снимка нет. Замороженное ровно наоборот.
            (preset_id is not null and frozen_at is null)
            or (preset_id is null and frozen_at is not null and frozen_body is not null)
        )
);

create trigger preset_favorites_set_updated_at
    before update on public.preset_favorites
    for each row execute function public.set_updated_at();

alter table public.preset_favorites enable row level security;

-- Платформа выдаёт authenticated все DML-привилегии по умолчанию: сужаем до
-- нужного. owner_id клиент передаёт из своей сессии, RLS with check проверяет
-- его, а триггер перепроверяет.
revoke insert, update, delete on public.preset_favorites from authenticated;

grant select, delete on public.preset_favorites to authenticated;
-- owner_id клиент даёт из сессии (как в онбординге), правду проверяет RLS
-- with check; триггер перепроверяет и переписывает.
grant insert (owner_id, preset_id) on public.preset_favorites to authenticated;

create or replace function public.set_favorite_owner() returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
    new.owner_id = auth.uid();
    return new;
end;
$$;

create trigger preset_favorites_set_owner
    before insert on public.preset_favorites
    for each row execute function public.set_favorite_owner();

create policy "Users can read own favorites"
    on public.preset_favorites
    for select
    to authenticated
    using (owner_id = auth.uid());

-- В избранное кладут только чужой выложенный пресет: официальные (owner_id
-- null) и свои отсекаются одним условием.
create policy "Users can favorite published presets of others"
    on public.preset_favorites
    for insert
    to authenticated
    with check (
        owner_id = auth.uid()
        and exists (
            select 1 from public.prompt_presets pp
            where pp.id = preset_id
              and pp.published_at is not null
              and pp.owner_id <> auth.uid()
        )
    );

create policy "Users can remove own favorites"
    on public.preset_favorites
    for delete
    to authenticated
    using (owner_id = auth.uid());
