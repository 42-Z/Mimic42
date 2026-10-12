-- Снятие с витрины и удаление пресета не отбирают уже сохранённое: в
-- избранном остаётся замороженная копия на момент снятия, её можно только
-- применять. Повторная выкладка оживляет только новые записи.

create or replace function public.freeze_preset_favorites() returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
    if tg_op = 'UPDATE' then
        update public.preset_favorites fav
        set preset_id = null,
            frozen_title = pp.title,
            frozen_summary = pp.summary,
            frozen_body = pp.body,
            frozen_settings = pp.settings,
            frozen_at = now()
        from public.prompt_presets pp
        where fav.preset_id = pp.id
          and pp.id = old.id;
        return new;
    end if;

    -- DELETE: снимок перед удалением строки, ссылки отвязываются до каскада.
    update public.preset_favorites fav
    set preset_id = null,
        frozen_title = old.title,
        frozen_summary = old.summary,
        frozen_body = old.body,
        frozen_settings = old.settings,
        frozen_at = now()
    where fav.preset_id = old.id;

    return old;
end;
$$;

create trigger prompt_presets_freeze_on_unpublish
    before update of published_at on public.prompt_presets
    for each row
    when (old.published_at is not null and new.published_at is null)
    execute function public.freeze_preset_favorites();

create trigger prompt_presets_freeze_on_delete
    before delete on public.prompt_presets
    for each row
    execute function public.freeze_preset_favorites();

-- Имена авторов витрины. Вид исполняется с правами владельца (не
-- security_invoker), поэтому RLS профилей не применяется; наружу идут только
-- display_name авторов выложенных пресетов — без email.
create view public.preset_authors as
select distinct pp.owner_id as id, pr.display_name
from public.prompt_presets pp
join public.profiles pr on pr.id = pp.owner_id
where pp.published_at is not null;

grant select on public.preset_authors to authenticated;
