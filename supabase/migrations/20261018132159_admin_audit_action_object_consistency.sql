alter table public.admin_audit_log
    add constraint admin_audit_action_object_consistency check (
        (
            action in ('preset.created', 'preset.updated', 'preset.visibility_changed')
            and object_type = 'preset'
            and object_id is not null
        )
        or (
            action = 'telegram.settings_updated'
            and object_type = 'telegram_settings'
            and object_id is null
        )
    );
