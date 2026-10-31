alter function public.lock_onboarding_proxy_pool()
    rename to lock_telegram_proxy_pool_statement;

create trigger lock_agents_proxy_pool
before delete on public.agents
for each statement execute function public.lock_telegram_proxy_pool_statement();

create trigger lock_profiles_proxy_pool
before delete on public.profiles
for each statement execute function public.lock_telegram_proxy_pool_statement();

create trigger lock_telegram_proxies_pool
before delete on public.telegram_proxies
for each statement execute function public.lock_telegram_proxy_pool_statement();
