drop policy "Authenticated users can read catalog presets" on public.prompt_presets;
create policy "Authenticated users can read catalog presets"
    on public.prompt_presets for select to authenticated
    using (
        owner_id = (select auth.uid())
        or (is_active and (owner_id is null or published_at is not null))
    );

drop policy "Authenticated users can update own presets" on public.prompt_presets;
create policy "Authenticated users can update own and lock published presets"
    on public.prompt_presets
    for update
    to authenticated
    using (
        owner_id = (select auth.uid())
        or (
            owner_id is not null
            and is_active
            and published_at is not null
            and owner_id <> (select auth.uid())
        )
    )
    with check (owner_id = (select auth.uid()));

drop policy "Users can favorite published presets of others" on public.preset_favorites;
create policy "Users can favorite published presets of others"
    on public.preset_favorites for insert to authenticated
    with check (
        owner_id = (select auth.uid())
        and exists (
            select 1 from public.prompt_presets pp
            where pp.id = preset_id
              and pp.is_active
              and pp.published_at is not null
              and pp.owner_id <> (select auth.uid())
        )
    );

create trigger prompt_presets_freeze_on_hide
    before update of is_active on public.prompt_presets
    for each row
    when (old.is_active and not new.is_active and old.owner_id is not null)
    execute function public.freeze_preset_favorites();

create or replace function public.set_favorite_owner() returns trigger
language plpgsql security invoker set search_path = ''
as $$
begin
    new.owner_id = auth.uid();
    perform 1
    from public.prompt_presets pp
    where pp.id = new.preset_id
      and pp.is_active
      and pp.published_at is not null
      and pp.owner_id <> new.owner_id
    for share;
    if not found then
        raise exception using
            errcode = '42501',
            message = 'Пресет недоступен для добавления в избранное';
    end if;
    return new;
end;
$$;

create or replace view public.preset_authors as
select distinct pp.owner_id as id, pr.display_name
from public.prompt_presets pp
join public.profiles pr on pr.id = pp.owner_id
where pp.published_at is not null and pp.is_active;

revoke all on public.preset_authors from public, anon;
grant select on public.preset_authors to authenticated;
