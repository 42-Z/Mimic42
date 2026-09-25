-- Issue #95: поддельная онбординг-сессия переприсваивала чужого агента.
--
-- agent_onboarding_sessions.id — это id будущего агента, а политика «для всего»
-- позволяла аутентифицированному клиенту вставить строку с любыми id,
-- completed_agent_id и authorization_status. Сценарий: строка с id чужого
-- агента и authorization_status = 'authorized', затем
-- POST /api/v1/onboarding/{id}/agent — create_from_onboarding находит агента по
-- id онбординг-сессии и переписывает ему владельца вместе с Telegram-сессией.
--
-- Клиент пишет в таблицу через PostgREST (anon-ключ + JWT пользователя),
-- бэкенд — своей ролью, для него RLS не действует. Клиентский путь закрывается
-- двумя слоями:
--   1. привилегии по колонкам — клиент физически не задаёт id будущего агента,
--      связь с уже созданным агентом и секреты Telegram;
--   2. политики по командам — только свои строки и только черновик онбординга.
--
-- Проверку «id занят агентом» в политику не выносили: подзапрос к agents внутри
-- with check выполняется от имени клиента и видит только его собственных
-- агентов, чужой id он бы не заметил. Последний рубеж — сам
-- create_from_onboarding: он отказывается переприсваивать агента чужого
-- владельца (см. AgentOwnershipError).
--
-- auth.uid() обёрнут в (select ...): так требует Supabase-адвайзер
-- auth_rls_initplan — без обёртки функция пересчитывается на каждой строке.

-- ── agent_onboarding_sessions ────────────────────────────────────────────────

drop policy "Users can manage their onboarding sessions"
    on public.agent_onboarding_sessions;

-- Визард пишет только имя, характер и метки времени. Обновлять можно и
-- authorization_status — кнопка «Назад» с шага кода сбрасывает его в
-- 'not_started', больше клиенту статус не нужен.
revoke insert, update, delete on table public.agent_onboarding_sessions
    from anon, authenticated;
grant insert (owner_id, agent_name, soul_prompt, updated_at)
    on table public.agent_onboarding_sessions to authenticated;
grant update (owner_id, agent_name, soul_prompt, updated_at, authorization_status)
    on table public.agent_onboarding_sessions to authenticated;
grant delete on table public.agent_onboarding_sessions to authenticated;

create policy "Users can read their onboarding sessions"
on public.agent_onboarding_sessions
for select
to authenticated
using (owner_id = (select auth.uid()));

create policy "Users can create their onboarding drafts"
on public.agent_onboarding_sessions
for insert
to authenticated
with check (
    owner_id = (select auth.uid())
    -- Новая строка — всегда черновик без агента и без авторизации: её выдаёт
    -- только бэкенд после входа в Telegram.
    and completed_agent_id is null
    and authorization_status = 'not_started'
);

create policy "Users can edit their onboarding drafts"
on public.agent_onboarding_sessions
for update
to authenticated
using (owner_id = (select auth.uid()))
with check (
    owner_id = (select auth.uid())
    -- Завершённая строка обслуживает перепривязку Telegram — клиент её не
    -- трогает, правит только бэкенд.
    and completed_agent_id is null
    -- Клиенту нельзя самому выдать себе authorized: авторизацию подтверждает
    -- бэкенд, только что вернувшийся из Telegram.
    and authorization_status <> 'authorized'
);

create policy "Users can discard their onboarding drafts"
on public.agent_onboarding_sessions
for delete
to authenticated
using (owner_id = (select auth.uid()) and completed_agent_id is null);

-- ── agents ───────────────────────────────────────────────────────────────────

-- Агента создаёт только бэкенд (финализация онбординга), поэтому клиенту не
-- нужно ни вставлять строки, ни трогать состояние/идентичность: строка agents с
-- выбранным клиентом id — это захват id будущего агента и подмена статуса при
-- восстановлении на старте. Правки профиля (имя, характер, настройки) остаются.
drop policy "Users can create their agents" on public.agents;
revoke insert, update on table public.agents from anon, authenticated;
grant update (name, soul_prompt, settings, updated_at)
    on table public.agents to authenticated;
