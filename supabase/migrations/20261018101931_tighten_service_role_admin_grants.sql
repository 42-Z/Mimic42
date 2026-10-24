revoke all on public.admin_users, public.platform_telegram_settings,
    public.admin_audit_log from service_role;

grant select, insert, update, delete on public.admin_users to service_role;

grant select, insert, update on public.platform_telegram_settings to service_role;

grant select, insert on public.admin_audit_log to service_role;
