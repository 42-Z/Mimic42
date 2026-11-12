-- Временная недоступность прокси не выключает его навсегда: запись остаётся
-- активной, а выдача пропускает её до указанного момента и пробует снова.
alter table public.telegram_proxies
    add column if not exists unavailable_until timestamptz;
