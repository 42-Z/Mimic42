drop policy if exists "Authenticated users can update own presets" on public.prompt_presets;
drop policy if exists "Authenticated users can update own and lock published presets"
    on public.prompt_presets;
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
