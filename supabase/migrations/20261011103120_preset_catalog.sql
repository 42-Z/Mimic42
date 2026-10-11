-- Issue #67: каталог пресетов. Пользователи создают свои пресеты, публикуют их
-- для всех и сохраняют чужие в избранное. Наши (курируемые) пресеты остаются
-- строками без владельца: их по-прежнему пишет только service_role.

-- ── prompt_presets: владелец и публикация ────────────────────────────────────

alter table public.prompt_presets
    add column owner_id uuid references public.profiles(id) on delete cascade,
    add column is_published boolean not null default true;

-- Существующие строки — наши и опубликованы. Новые строки личные, пока автор
-- сам их не опубликует.
alter table public.prompt_presets
    alter column is_published set default false;

-- Slug нужен только нашим пресетам: миграции правят их текст по slug.
alter table public.prompt_presets
    alter column slug drop not null;

alter table public.prompt_presets
    add constraint prompt_presets_slug_only_for_curated
    check ((owner_id is null) = (slug is not null)),
    add constraint prompt_presets_curated_is_published
    check (owner_id is not null or is_published),
    add constraint prompt_presets_title_length check (char_length(title) <= 80),
    add constraint prompt_presets_summary_length check (char_length(summary) <= 200),
    -- Тот же предел, что у soul_prompt в форме агента.
    add constraint prompt_presets_body_length check (char_length(body) <= 50000),
    add constraint prompt_presets_settings_size
    check (settings is null or octet_length(settings::text) <= 16384);

-- По владельцу идут политики и каскадное удаление вместе с профилем.
create index prompt_presets_owner_id_idx
    on public.prompt_presets (owner_id)
    where owner_id is not null;

-- Лимит собственных пресетов считается триггером, а не политикой: подзапрос к
-- prompt_presets внутри её же политики вставки даёт 42P17 (бесконечная
-- рекурсия), потому что политика чтения содержит подзапрос auth.uid().
create function public.enforce_prompt_preset_limit()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
    if new.owner_id is not null
        and (
            select count(*)
            from public.prompt_presets as own_presets
            where own_presets.owner_id = new.owner_id
        ) >= 50
    then
        raise exception 'Достигнут лимит собственных пресетов (50)'
            using errcode = 'check_violation';
    end if;
    return new;
end;
$$;

create trigger prompt_presets_enforce_limit
    before insert on public.prompt_presets
    for each row execute function public.enforce_prompt_preset_limit();

-- ── prompt_presets: права и политики ─────────────────────────────────────────

-- Платформа выдавала anon и authenticated всё подряд (даже TRUNCATE), а
-- прежняя миграция этого не отзывала. Отзываем и возвращаем только нужное.
revoke all on table public.prompt_presets from anon, authenticated;
grant select on table public.prompt_presets to authenticated;
-- Колоночные гранты: slug, sort_order и is_active клиент не задаёт вовсе.
grant insert (owner_id, title, summary, body, settings, is_published)
    on table public.prompt_presets to authenticated;
grant update (title, summary, body, settings, is_published)
    on table public.prompt_presets to authenticated;
grant delete on table public.prompt_presets to authenticated;

drop policy "Authenticated users can read active prompt presets"
    on public.prompt_presets;

create policy "Users can read published and own prompt presets"
    on public.prompt_presets
    for select
    to authenticated
    using (is_active and (is_published or owner_id = (select auth.uid())));

create policy "Users can create their own prompt presets"
    on public.prompt_presets
    for insert
    to authenticated
    with check (owner_id = (select auth.uid()));

create policy "Users can edit their own prompt presets"
    on public.prompt_presets
    for update
    to authenticated
    using (owner_id = (select auth.uid()))
    with check (owner_id = (select auth.uid()));

create policy "Users can delete their own prompt presets"
    on public.prompt_presets
    for delete
    to authenticated
    using (owner_id = (select auth.uid()));

-- ── prompt_preset_favorites ──────────────────────────────────────────────────

create table public.prompt_preset_favorites (
    user_id uuid not null references public.profiles(id) on delete cascade,
    preset_id uuid not null references public.prompt_presets(id) on delete cascade,
    created_at timestamptz not null default now(),
    primary key (user_id, preset_id)
);

-- Первичный ключ покрывает user_id; по preset_id идёт каскад при удалении пресета.
create index prompt_preset_favorites_preset_id_idx
    on public.prompt_preset_favorites (preset_id);

alter table public.prompt_preset_favorites enable row level security;

revoke all on table public.prompt_preset_favorites from anon, authenticated;
grant select, delete on table public.prompt_preset_favorites to authenticated;
grant insert (user_id, preset_id) on table public.prompt_preset_favorites to authenticated;

create policy "Users can read their favorite presets"
    on public.prompt_preset_favorites
    for select
    to authenticated
    using (user_id = (select auth.uid()));

-- Подзапрос идёт под RLS пользователя: чужой личный пресет в избранное не
-- положить, даже зная его id.
create policy "Users can favorite visible presets"
    on public.prompt_preset_favorites
    for insert
    to authenticated
    with check (
        user_id = (select auth.uid())
        and exists (
            select 1
            from public.prompt_presets
            where prompt_presets.id = prompt_preset_favorites.preset_id
        )
    );

create policy "Users can remove their favorite presets"
    on public.prompt_preset_favorites
    for delete
    to authenticated
    using (user_id = (select auth.uid()));
