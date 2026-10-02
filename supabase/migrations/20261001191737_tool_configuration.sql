-- Issue #37: настройка инструментов Мимика живёт в agents.settings.enabled_tools
-- (allowlist), а пресеты и черновик онбординга несут частичный патч настроек
-- рядом с промптом.

alter table public.prompt_presets
    add column settings jsonb;

alter table public.prompt_presets
    add constraint prompt_presets_settings_is_object
    check (settings is null or jsonb_typeof(settings) = 'object');

-- Показательный курируемый набор: комментатор читает каналы и обсуждения,
-- комментирует, ставит реакции и проходит капчу в обсуждении, но не получает
-- доступ к администрированию, профилю и приватности аккаунта.
update public.prompt_presets
set settings = jsonb_build_object(
    'enabled_tools',
    jsonb_build_array(
        'get_dialogs',
        'get_messages',
        'search_messages',
        'get_discussion_messages',
        'join_channel_discussion',
        'view_image',
        'send_text_message',
        'send_chat_action',
        'send_reaction',
        'get_message_reactions',
        'mark_chat_as_read',
        'get_chat_info',
        'check_admin_permissions',
        'get_message_buttons',
        'click_inline_button',
        'start_bot'
    )
)
where slug = 'rage_comments';

alter table public.agent_onboarding_sessions
    add column settings jsonb not null default '{}'::jsonb;

alter table public.agent_onboarding_sessions
    add constraint agent_onboarding_sessions_settings_is_object
    check (jsonb_typeof(settings) = 'object');

-- Визард пишет настройки будущего агента рядом с именем и характером.
-- Колоночные привилегии накапливаются: прежние гранты не отзываются.
grant insert (settings) on table public.agent_onboarding_sessions to authenticated;
grant update (settings) on table public.agent_onboarding_sessions to authenticated;
