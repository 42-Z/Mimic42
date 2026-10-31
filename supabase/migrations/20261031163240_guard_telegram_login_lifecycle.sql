alter table public.agent_onboarding_sessions
    add column auth_generation uuid not null default gen_random_uuid(),
    add column applied_auth_generation uuid,
    add column username text;

create function public.lock_telegram_proxy_pool()
returns void
language sql
set search_path = ''
as $$
    select pg_catalog.pg_advisory_xact_lock(42138, 1);
$$;

revoke all on function public.lock_telegram_proxy_pool() from public, anon;
grant execute on function public.lock_telegram_proxy_pool() to authenticated, service_role;

create function public.lock_onboarding_proxy_pool()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
    perform public.lock_telegram_proxy_pool();
    return null;
end;
$$;

revoke all on function public.lock_onboarding_proxy_pool() from public, anon, authenticated;

create trigger lock_onboarding_proxy_pool
before insert or update or delete on public.agent_onboarding_sessions
for each statement execute function public.lock_onboarding_proxy_pool();

create function public.advance_onboarding_auth_generation()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
    new.auth_generation = gen_random_uuid();
    new.applied_auth_generation = null;
    if new.authorization_status = 'not_started' then
        new.phone_code_hash_ciphertext = null;
        new.session_ciphertext = null;
        new.username = null;
    end if;
    return new;
end;
$$;

revoke all on function public.advance_onboarding_auth_generation() from public, anon, authenticated;

create trigger advance_onboarding_auth_generation
before update of auth_generation, authorization_status, api_id, api_hash_ciphertext,
    phone_number, phone_code_hash_ciphertext, session_ciphertext
on public.agent_onboarding_sessions
for each row execute function public.advance_onboarding_auth_generation();

update public.agent_onboarding_sessions
set proxy_id = null
where completed_agent_id is not null;

revoke insert (auth_generation, applied_auth_generation, username),
    update (auth_generation, applied_auth_generation, username)
on public.agent_onboarding_sessions from anon, authenticated;
