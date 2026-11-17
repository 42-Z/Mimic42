-- Telegram counts each item of an album as a separate message. The original
-- attack counters counted one comment as one message, so existing campaigns are
-- converted before the new claim/settle logic starts using message units.
--
-- A comment in the old code always took min(10, media pool) images, or one text
-- message when the pool was empty. Historical sent comments are converted by
-- that rule; a cleared/in-flight reservation keeps its full pool weight.

alter table public.attack_agents
    add column pending_count integer not null default 0;

with per_attack as (
    select id, greatest(1, least(10, jsonb_array_length(media_paths))) as per_comment
    from public.attacks
)
update public.attack_agents aa
set
    sent_count = aa.sent_count * pa.per_comment,
    pending_count = case
        when aa.pending_random_id is null then 0
        when coalesce(jsonb_array_length(aa.pending_media), 0) > 0
            then jsonb_array_length(aa.pending_media)
        when pa.per_comment > 1 then pa.per_comment
        else 1
    end
from per_attack pa
where aa.attack_id = pa.id;

with pending as (
    select attack_id, sum(pending_count) as pending_count
    from public.attack_agents
    where pending_random_id is not null
    group by attack_id
),
per_attack as (
    select id, greatest(1, least(10, jsonb_array_length(media_paths))) as per_comment
    from public.attacks
)
update public.attacks a
set
    sent_count = a.sent_count * pa.per_comment,
    claimed_count = a.sent_count * pa.per_comment + coalesce(p.pending_count, 0)
from per_attack pa
left join pending p on p.attack_id = pa.id
where a.id = pa.id;

alter table public.attack_agents
    add constraint attack_agents_pending_count_nonnegative check (pending_count >= 0),
    add constraint attack_agents_pending_count_shape
        check ((pending_random_id is null) = (pending_count = 0));
