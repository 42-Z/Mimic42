-- Название прокси необязательно: в интерфейсе можно показывать адрес.
alter table public.telegram_proxies
    alter column label drop not null;

alter table public.telegram_proxies
    drop constraint if exists telegram_proxies_label_check;

alter table public.telegram_proxies
    add constraint telegram_proxies_label_check
    check (label is null or btrim(label) <> '');
