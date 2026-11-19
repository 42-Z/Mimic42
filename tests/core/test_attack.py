from __future__ import annotations

import asyncio
import random
from datetime import UTC, datetime
from typing import cast
from uuid import uuid4

import pytest
from telethon import errors

from mimic42.core.attack import (
    MAX_TEXT,
    MAX_TEXT_WITH_MEDIA,
    AttackAgentStatus,
    AttackConfig,
    AttackEndReason,
    AttackStatus,
    AttackView,
    CommentContent,
    ExitReason,
    MessagesLimit,
    MinutesLimit,
    ParticipationView,
    SendFailure,
    SendOutcome,
    base_pause,
    can_transition,
    classify_outcome,
    classify_send_error,
    compose_comment,
    initial_offset,
    next_send_at,
    note_text,
    parse_target_link,
    typing_delay,
    validate_config,
)

NOW = datetime(2026, 11, 16, 12, 0, tzinfo=UTC)


def make_config(
    *,
    title: str | None = None,
    target: str = "https://t.me/example/412",
    texts: tuple[str, ...] = ("Участвую!",),
    media_paths: tuple[str, ...] = (),
    limit: MessagesLimit | MinutesLimit | None = None,
) -> AttackConfig:
    return AttackConfig(
        title=title,
        target=parse_target_link(target),
        texts=texts,
        media_paths=media_paths,
        limit=limit if limit is not None else MessagesLimit(10),
    )


def make_participation(
    *, sent_count: int = 0, exit_reason: ExitReason | None = None
) -> ParticipationView:
    return ParticipationView(
        id=uuid4(),
        attack_id=uuid4(),
        agent_id=uuid4(),
        status=AttackAgentStatus.EXITED if exit_reason else AttackAgentStatus.ACTIVE,
        sent_count=sent_count,
        next_at=None,
        last_error=None,
        exit_reason=exit_reason,
        note_written_at=None,
    )


def make_attack(
    *, title: str | None = "Розыгрыш", end_reason: AttackEndReason | None = None
) -> AttackView:
    return AttackView(
        id=uuid4(),
        owner_id=uuid4(),
        config=make_config(title=title),
        status=AttackStatus.FINISHED if end_reason else AttackStatus.RUNNING,
        sent_count=0,
        claimed_count=0,
        version=1,
        started_at=NOW,
        finished_at=None,
        end_reason=end_reason,
        participations=(),
    )


@pytest.mark.parametrize(
    "link",
    [
        "https://t.me/example/412",
        "t.me/example/412",
        "https://www.t.me/example/412/",
        "https://t.me/example/412?single",
        "https://t.me/example/412?comment=99",
        "  https://t.me/example/412  ",
    ],
)
def test_public_post_forms_point_to_the_same_channel_and_post(link: str) -> None:
    ref = parse_target_link(link)

    assert (ref.channel, ref.post_id) == ("example", 412)
    assert ref.link == "https://t.me/example/412"


def test_private_post_link_builds_internal_channel_id() -> None:
    ref = parse_target_link("https://t.me/c/123456789/412?comment=7")

    assert ref.channel == "-100123456789"
    assert ref.post_id == 412
    assert ref.link == "https://t.me/c/123456789/412"


def test_tg_resolve_link_is_accepted() -> None:
    ref = parse_target_link("tg://resolve?domain=example&post=412")

    assert (ref.channel, ref.post_id) == ("example", 412)
    assert ref.link == "https://t.me/example/412"


def test_tg_resolve_link_ignores_the_at_sign() -> None:
    ref = parse_target_link("tg://resolve?domain=@example&post=412")

    assert ref.channel == "example"


@pytest.mark.parametrize(
    "link",
    [
        "",
        "https://t.me/example",
        "https://t.me/example/0",
        "https://t.me/example/-5",
        "https://t.me/example/abc",
        "https://t.me/+AbCdEfGh",
        "https://t.me/joinchat/AbCdEfGh",
        "https://example.com/example/412",
        "https://t.me/example/412/999",
        "https://t.me/c/abc/412",
        "https://t.me/c/123456789",
        "tg://resolve?domain=example",
        "not a link",
    ],
)
def test_links_that_are_not_channel_posts_are_rejected(link: str) -> None:
    with pytest.raises(ValueError):
        parse_target_link(link)


def test_config_accepts_a_comment_with_media_at_the_caption_limit() -> None:
    validate_config(
        make_config(
            texts=("а" * MAX_TEXT_WITH_MEDIA,),
            media_paths=("attacks/owner/a.jpg",),
        )
    )


def test_config_rejects_a_comment_with_media_over_the_caption_limit() -> None:
    with pytest.raises(ValueError):
        validate_config(
            make_config(
                texts=("а" * (MAX_TEXT_WITH_MEDIA + 1),),
                media_paths=("attacks/owner/a.jpg",),
            )
        )


def test_config_accepts_a_text_comment_at_the_message_limit() -> None:
    validate_config(make_config(texts=("а" * MAX_TEXT,)))


def test_config_rejects_a_text_comment_over_the_message_limit() -> None:
    with pytest.raises(ValueError):
        validate_config(make_config(texts=("а" * (MAX_TEXT + 1),)))


def test_text_limit_counts_emoji_the_way_the_browser_does() -> None:
    emoji = "🙂"
    validate_config(make_config(texts=(emoji * 512,), media_paths=("a.jpg",)))

    with pytest.raises(ValueError):
        validate_config(make_config(texts=(emoji * 513,), media_paths=("a.jpg",)))


def test_config_rejects_an_empty_text_pool() -> None:
    with pytest.raises(ValueError):
        validate_config(make_config(texts=()))


def test_config_rejects_a_blank_text() -> None:
    with pytest.raises(ValueError):
        validate_config(make_config(texts=("Участвую!", "   ")))


def test_config_rejects_a_blank_media_path() -> None:
    with pytest.raises(ValueError):
        validate_config(make_config(media_paths=("attacks/owner/a.jpg", " ")))


@pytest.mark.parametrize(
    "limit",
    [MessagesLimit(0), MessagesLimit(-3), MinutesLimit(0), MinutesLimit(-1)],
)
def test_config_rejects_a_non_positive_limit(limit: MessagesLimit | MinutesLimit) -> None:
    with pytest.raises(ValueError):
        validate_config(make_config(limit=limit))


def test_config_rejects_a_limit_that_is_neither_messages_nor_minutes() -> None:
    config = make_config()
    broken = AttackConfig(
        title=config.title,
        target=config.target,
        texts=config.texts,
        media_paths=config.media_paths,
        limit=cast("MessagesLimit | MinutesLimit", "everyone"),
    )

    with pytest.raises(ValueError):
        validate_config(broken)


def test_config_accepts_a_long_but_bounded_title() -> None:
    validate_config(make_config(title="а" * 200))


def test_config_rejects_an_overlong_title() -> None:
    with pytest.raises(ValueError):
        validate_config(make_config(title="а" * 201))


def test_config_reports_limit_shape_for_the_database_row() -> None:
    assert make_config(limit=MessagesLimit(40)).limit_type == "messages"
    assert make_config(limit=MessagesLimit(40)).limit_value == 40
    assert make_config(limit=MinutesLimit(7)).limit_type == "minutes"
    assert make_config(limit=MinutesLimit(7)).limit_value == 7


def test_comment_text_comes_from_the_shared_pool() -> None:
    rng = random.Random(1)
    texts = ("Участвую!", "Бросаю в зачёт")

    chosen = {compose_comment(texts, (), rng).text for _ in range(50)}

    assert chosen == set(texts)


def test_the_same_text_may_repeat_in_consecutive_comments() -> None:
    rng = random.Random(2)

    comments = [compose_comment(("единственный",), (), rng) for _ in range(5)]

    assert [comment.text for comment in comments] == ["единственный"] * 5


def test_small_media_pool_enters_every_comment_once() -> None:
    rng = random.Random(3)
    paths = tuple(f"attacks/owner/{i}.jpg" for i in range(7))

    media = compose_comment(("текст",), paths, rng).media

    assert len(media) == 7
    assert set(media) == set(paths)


def test_large_media_pool_gives_ten_distinct_images() -> None:
    rng = random.Random(4)
    paths = tuple(f"attacks/owner/{i}.jpg" for i in range(25))

    media = compose_comment(("текст",), paths, rng).media

    assert len(media) == 10
    assert len(set(media)) == 10
    assert set(media) <= set(paths)


def test_media_order_changes_between_comments() -> None:
    rng = random.Random(5)
    paths = tuple(f"attacks/owner/{i}.jpg" for i in range(10))

    orders = {compose_comment(("текст",), paths, rng).media for _ in range(30)}

    assert len(orders) > 1


def test_slow_mode_takes_one_image_per_comment() -> None:
    rng = random.Random(6)
    paths = tuple(f"attacks/owner/{i}.jpg" for i in range(25))

    media = compose_comment(("текст",), paths, rng, max_media=1).media

    assert len(media) == 1
    assert media[0] in paths


def test_comment_without_media_has_an_empty_tuple() -> None:
    assert compose_comment(("текст",), (), random.Random(6)).media == ()


def test_a_comment_can_hold_at_most_ten_images() -> None:
    with pytest.raises(ValueError):
        CommentContent(text="текст", media=tuple(f"{i}.jpg" for i in range(11)))


@pytest.mark.parametrize(
    ("slow_mode", "expected"),
    [(30, 30), (5, 5), (1, 1), (0, 10), (None, 10), (-1, 10)],
)
def test_base_pause_uses_slow_mode_or_ten_seconds(slow_mode: int | None, expected: int) -> None:
    assert base_pause(slow_mode) == expected


def test_next_send_waits_inside_the_jitter_band() -> None:
    rng = random.Random(7)

    for _ in range(100):
        delay = (next_send_at(NOW, None, rng) - NOW).total_seconds()
        assert 10.0 <= delay <= 14.5


def test_next_send_never_goes_below_a_slow_mode_base() -> None:
    rng = random.Random(8)

    for _ in range(100):
        delay = (next_send_at(NOW, 60, rng) - NOW).total_seconds()
        assert 60.0 <= delay <= 87.0


def test_flood_wait_stretches_the_pause_to_telegrams_demand() -> None:
    rng = random.Random(9)

    at = next_send_at(NOW, 30, rng, SendFailure.FLOOD_WAIT, retry_after=120)

    assert (at - NOW).total_seconds() >= 120.0


def test_flood_wait_does_not_shorten_a_longer_slow_mode() -> None:
    rng = random.Random(10)

    at = next_send_at(NOW, 300, rng, SendFailure.FLOOD_WAIT, retry_after=5)

    assert (at - NOW).total_seconds() >= 300.0


def test_slow_mode_wait_uses_the_wait_from_telegram() -> None:
    rng = random.Random(11)

    at = next_send_at(NOW, 10, rng, SendFailure.SLOW_MODE, retry_after=45)

    assert (at - NOW).total_seconds() >= 45.0


@pytest.mark.parametrize(
    ("text", "low", "high"),
    [("", 1.0, 2.0), ("а" * 100, 7.2, 8.2), ("а" * 1000, 15.2, 16.2)],
)
def test_typing_delay_follows_text_length_within_bounds(text: str, low: float, high: float) -> None:
    rng = random.Random(12)

    for _ in range(50):
        delay = typing_delay(text, rng)
        assert low <= delay <= high


def test_initial_offset_stays_inside_the_first_pause() -> None:
    rng = random.Random(13)

    offsets = [initial_offset(None, rng) for _ in range(50)]

    assert all(0.0 <= offset <= 10.0 for offset in offsets)
    assert any(offset > 0.0 for offset in offsets)


def test_initial_offset_follows_a_short_slow_mode() -> None:
    rng = random.Random(14)

    offsets = [initial_offset(3, rng) for _ in range(50)]

    assert all(0.0 <= offset <= 3.0 for offset in offsets)


@pytest.mark.parametrize(
    ("exc", "failure"),
    [
        pytest.param(errors.FloodWaitError(request=None), SendFailure.FLOOD_WAIT, id="flood"),
        pytest.param(
            errors.FloodPremiumWaitError(request=None),
            SendFailure.FLOOD_WAIT,
            id="premium-flood",
        ),
        pytest.param(errors.SlowModeWaitError(request=None), SendFailure.SLOW_MODE, id="slow-mode"),
        pytest.param(errors.PeerFloodError(request=None), SendFailure.PEER_FLOOD, id="peer-flood"),
        pytest.param(
            errors.UserBannedInChannelError(request=None),
            SendFailure.BANNED_IN_CHANNEL,
            id="banned",
        ),
        pytest.param(
            errors.UserRestrictedError(request=None),
            SendFailure.BANNED_IN_CHANNEL,
            id="restricted",
        ),
        pytest.param(
            errors.ChatWriteForbiddenError(request=None),
            SendFailure.BANNED_IN_CHANNEL,
            id="write-forbidden",
        ),
        pytest.param(
            errors.ChatRestrictedError(request=None),
            SendFailure.BANNED_IN_CHANNEL,
            id="chat-restricted",
        ),
        pytest.param(
            errors.ChatAdminRequiredError(request=None),
            SendFailure.JOIN_BLOCKED,
            id="admin-required",
        ),
        pytest.param(
            errors.UserNotParticipantError(request=None),
            SendFailure.JOIN_BLOCKED,
            id="not-participant",
        ),
        pytest.param(
            errors.ChannelPrivateError(request=None),
            SendFailure.JOIN_BLOCKED,
            id="channel-private",
        ),
        pytest.param(
            errors.MsgIdInvalidError(request=None),
            SendFailure.TARGET_UNAVAILABLE,
            id="msg-id-invalid",
        ),
        pytest.param(
            errors.AuthKeyUnregisteredError(request=None),
            SendFailure.SESSION_REVOKED,
            id="auth-key-unregistered",
        ),
        pytest.param(
            errors.SessionRevokedError(request=None),
            SendFailure.SESSION_REVOKED,
            id="session-revoked",
        ),
        pytest.param(
            errors.UserDeactivatedError(request=None),
            SendFailure.SESSION_REVOKED,
            id="user-deactivated",
        ),
        pytest.param(
            errors.FileReferenceExpiredError(request=None),
            SendFailure.MEDIA_STALE,
            id="file-reference-expired",
        ),
        pytest.param(
            errors.FileReferenceInvalidError(request=None),
            SendFailure.MEDIA_STALE,
            id="file-reference-invalid",
        ),
        pytest.param(
            errors.FileReferenceEmptyError(request=None),
            SendFailure.MEDIA_STALE,
            id="file-reference-empty",
        ),
        pytest.param(
            errors.RandomIdDuplicateError(request=None),
            SendFailure.DUPLICATE,
            id="random-id-duplicate",
        ),
        pytest.param(OSError("connection reset"), SendFailure.TRANSIENT, id="os-error"),
        pytest.param(TimeoutError(), SendFailure.TRANSIENT, id="timeout"),
        pytest.param(
            errors.TimeoutError(request=None), SendFailure.TRANSIENT, id="telegram-timeout"
        ),
        pytest.param(
            errors.RPCError(request=None, message="UNKNOWN"),
            SendFailure.SEND_FAILED,
            id="unknown-rpc-error",
        ),
        pytest.param(ValueError("bug in our code"), SendFailure.TRANSIENT, id="unexpected"),
    ],
)
def test_send_errors_are_classified_by_their_consequence(
    exc: BaseException, failure: SendFailure
) -> None:
    assert classify_send_error(exc) == failure


def test_unknown_outcomes_hold_the_reservation() -> None:
    assert classify_outcome(OSError("connection reset")) == SendOutcome.unknown(
        SendFailure.TRANSIENT
    )
    assert classify_outcome(errors.RandomIdDuplicateError(request=None)) == SendOutcome.unknown(
        SendFailure.DUPLICATE
    )


def test_known_refusals_release_the_reservation() -> None:
    assert classify_outcome(errors.PeerFloodError(request=None)) == SendOutcome.not_sent(
        SendFailure.PEER_FLOOD
    )
    assert classify_outcome(errors.FloodWaitError(request=None)) == SendOutcome.not_sent(
        SendFailure.FLOOD_WAIT
    )


def test_cancellation_is_reported_as_interrupted() -> None:
    assert classify_outcome(asyncio.CancelledError()).kind == "interrupted"


def test_send_outcome_factories_describe_the_result() -> None:
    assert SendOutcome.sent(77) == SendOutcome(kind="sent", message_id=77, failure=None)
    assert SendOutcome.not_sent(SendFailure.BANNED_IN_CHANNEL) == SendOutcome(
        kind="not_sent", failure=SendFailure.BANNED_IN_CHANNEL
    )
    assert SendOutcome.unknown(SendFailure.TRANSIENT) == SendOutcome(
        kind="unknown", failure=SendFailure.TRANSIENT
    )
    assert SendOutcome.interrupted() == SendOutcome(kind="interrupted")


@pytest.mark.parametrize(
    ("status", "to"),
    [
        (AttackStatus.DRAFT, AttackStatus.RUNNING),
        (AttackStatus.DRAFT, AttackStatus.CANCELLED),
        (AttackStatus.RUNNING, AttackStatus.FINISHED),
        (AttackStatus.RUNNING, AttackStatus.CANCELLED),
    ],
)
def test_allowed_attack_transitions(status: AttackStatus, to: AttackStatus) -> None:
    assert can_transition(status, to)


@pytest.mark.parametrize(
    ("status", "to"),
    [
        (AttackStatus.DRAFT, AttackStatus.FINISHED),
        (AttackStatus.RUNNING, AttackStatus.DRAFT),
        (AttackStatus.FINISHED, AttackStatus.RUNNING),
        (AttackStatus.FINISHED, AttackStatus.CANCELLED),
        (AttackStatus.CANCELLED, AttackStatus.RUNNING),
        (AttackStatus.CANCELLED, AttackStatus.FINISHED),
    ],
)
def test_forbidden_attack_transitions(status: AttackStatus, to: AttackStatus) -> None:
    assert not can_transition(status, to)


def test_repeating_the_same_status_is_idempotent() -> None:
    assert can_transition(AttackStatus.RUNNING, AttackStatus.RUNNING)
    assert can_transition(AttackStatus.CANCELLED, AttackStatus.CANCELLED)


def test_note_names_the_post_the_count_and_the_exit_reason() -> None:
    note = note_text(make_attack(), make_participation(sent_count=3, exit_reason=ExitReason.PAUSED))

    assert "https://t.me/example/412" in note
    assert "3" in note
    assert "сообщений" in note
    assert "пауза" in note


def test_note_is_deterministic() -> None:
    attack = make_attack()
    participation = make_participation(sent_count=2, exit_reason=ExitReason.PEER_FLOOD)

    assert note_text(attack, participation) == note_text(attack, participation)


def test_note_falls_back_to_the_attack_end_reason() -> None:
    note = note_text(
        make_attack(end_reason=AttackEndReason.LIMIT_REACHED),
        make_participation(sent_count=40),
    )

    assert "лимит достигнут" in note


def test_note_without_a_title_still_names_the_target() -> None:
    note = note_text(
        make_attack(title=None), make_participation(exit_reason=ExitReason.ATTACK_FINISHED)
    )

    assert "https://t.me/example/412" in note
    assert "«" not in note
    assert "атака завершена" in note
