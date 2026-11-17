update public.prompt_presets
set settings = jsonb_set(
    coalesce(settings, '{}'::jsonb),
    '{enabled_tools}',
    '[
        "get_dialogs", "get_chat_info", "get_profile", "get_messages",
        "search_messages", "get_discussion_messages",
        "send_text_message", "edit_text_message", "delete_messages", "forward_messages",
        "send_reaction", "get_message_reactions", "mark_chat_as_read", "send_chat_action",
        "join_channel", "join_channel_discussion", "check_admin_permissions",
        "get_message_buttons", "click_inline_button", "click_reply_keyboard_button",
        "start_bot", "view_image", "send_file", "transcribe_voice_note", "read_document_file",
        "get_sticker_sets", "get_stickers_in_set", "search_sticker_sets",
        "query_inline_bot", "send_inline_bot_result", "set_wakeup_timer"
    ]'::jsonb
)
where owner_id is null;
