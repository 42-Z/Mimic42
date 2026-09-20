from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest

from mimic42.core.agent_runtime import (
    AgentRuntimeConfig,
    MimicAgentRuntime,
    _first_comment_failure_reason,
    _is_broadcast_post,
    _peer_for_send,
)
from mimic42.core.first_comment import (
    FirstCommentSettings,
    FirstCommentVariant,
    PostedAlbumGuard,
    parse_first_comment,
)
from mimic42.core.media import MediaFile
from mimic42.testing.telegram import FakeTelegramAccount, FakeTelegramClient


class FakeLangChainAgent:
    """Ход агента здесь — признак провала: комментарий обязан идти мимо ИИ."""

    def __init__(self) -> None:
        self.calls = 0

    async def ainvoke(
        self,
        input_data: dict[str, object],
        context: object | None = None,
    ) -> dict[str, object]:
        self.calls += 1
        return {
            "messages": [{"role": "assistant", "content": ""}],
            "structured_response": {"text": "", "send_any_message": False, "reply_to": None},
        }


class FakeImageStore:
    def __init__(self, files: dict[str, bytes] | None = None) -> None:
        self.files = files or {}
        self.opened: list[str] = []

    async def upload(
        self,
        *,
        agent_id: UUID,
        filename: str,
        data: bytes,
        mime_type: str,
        kind: str = "doc",
    ) -> MediaFile | None:
        return None

    async def open(self, path: str) -> bytes | None:
        self.opened.append(path)
        return self.files.get(path)

    async def remove_prefix(self, agent_id: UUID) -> None:
        return None


def make_config(
    first_comment: FirstCommentSettings | None = None,
) -> AgentRuntimeConfig:
    return AgentRuntimeConfig(
        agent_id=uuid4(),
        owner_id=uuid4(),
        telegram_session_string="sessions/test-agent",
        telegram_api_id=12345,
        telegram_api_hash="hash",
        system_prompt="Base system prompt",
        first_comment=first_comment or FirstCommentSettings(),
    )


def build_runtime(
    settings: FirstCommentSettings,
    *,
    media_uploader: FakeImageStore | None = None,
) -> tuple[MimicAgentRuntime, FakeTelegramClient, FakeLangChainAgent]:
    account = FakeTelegramAccount()
    account.authorized = True
    telegram = FakeTelegramClient(account)
    agent = FakeLangChainAgent()
    runtime = MimicAgentRuntime(
        config=make_config(settings),
        telegram_client=telegram,
        langchain_agent=agent,
        media_uploader=media_uploader,
    )
    return runtime, telegram, agent


# ── Разбор настройки ──────────────────────────────────────────────────────────


def test_parse_ignores_settings_of_a_foreign_shape() -> None:
    assert parse_first_comment(None) == FirstCommentSettings()
    assert parse_first_comment("on") == FirstCommentSettings()
    assert parse_first_comment({"enabled": True, "variants": "nope"}).variants == []


def test_parse_drops_only_the_unusable_variants() -> None:
    settings = parse_first_comment(
        {
            "enabled": True,
            "variants": [
                {"text": "первый"},
                {"text": "   "},
                "мусор",
                {"text": "", "image_path": "agent/pic.jpg"},
            ],
        }
    )

    assert settings.enabled is True
    assert [variant.text for variant in settings.variants] == ["первый", ""]
    assert settings.variants[1].image_path == "agent/pic.jpg"


def test_settings_without_usable_variants_are_inactive() -> None:
    assert FirstCommentSettings(enabled=True, variants=[]).is_active is False
    assert (
        FirstCommentSettings(enabled=False, variants=[FirstCommentVariant(text="тут")]).is_active
        is False
    )
    assert (
        FirstCommentSettings(enabled=True, variants=[FirstCommentVariant(text="тут")]).is_active
        is True
    )


def test_album_guard_claims_a_key_once_and_stays_bounded() -> None:
    guard = PostedAlbumGuard(capacity=2)

    assert guard.claim(("chat", "album")) is True
    assert guard.claim(("chat", "album")) is False

    guard.claim(("chat", "second"))
    guard.claim(("chat", "third"))
    # Самый старый ключ вытеснен — иначе множество росло бы неделями.
    assert guard.claim(("chat", "album")) is True


# ── Отбор событий ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("is_channel", "is_group", "expected"),
    [(True, False, True), (True, True, False), (False, False, False)],
)
def test_broadcast_post_is_told_apart_from_supergroup_and_private(
    is_channel: bool, is_group: bool, expected: bool
) -> None:
    event = type("Event", (), {"is_channel": is_channel, "is_group": is_group})()

    assert _is_broadcast_post(event) is expected


def test_missing_discussion_group_is_reported_as_its_own_reason() -> None:
    from telethon import errors

    request = type("Request", (), {})()

    assert _first_comment_failure_reason(errors.MsgIdInvalidError(request)) == "no_discussion_group"
    assert _first_comment_failure_reason(ValueError("boom")) == "exception"


def test_numeric_peer_goes_to_telethon_as_a_number() -> None:
    """Сессия Telethon ищет сущность по строке среди телефонов, юзернеймов и
    инвайтов — ID канала строкой там не нашёлся бы."""
    assert _peer_for_send("-1001234567890") == -1001234567890
    assert _peer_for_send("777000") == 777000
    assert _peer_for_send("durov") == "durov"


# ── Отправка ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_channel_post_gets_an_instant_comment() -> None:
    runtime, telegram, _ = build_runtime(
        FirstCommentSettings(enabled=True, variants=[FirstCommentVariant(text="Первый!")])
    )
    await runtime.start()

    await telegram.account.deliver_post(chat_id=-100500, text="Новый пост")

    comments = [msg for msg in telegram.account.sent if "comment_to" in msg.kwargs]
    assert len(comments) == 1
    assert comments[0].chat_id == "-100500"
    assert comments[0].text == "Первый!"
    assert comments[0].kwargs["comment_to"] == telegram.account.incoming[0].message_id
    # Первое, что уходит от аккаунта: ни печатания, ни хода агента перед ним.
    assert telegram.account.sent[0] is comments[0]


@pytest.mark.asyncio
async def test_disabled_setting_leaves_channel_posts_alone() -> None:
    runtime, telegram, _ = build_runtime(
        FirstCommentSettings(enabled=False, variants=[FirstCommentVariant(text="Первый!")])
    )
    await runtime.start()

    await telegram.account.deliver_post(chat_id=-100500, text="Новый пост")

    assert [msg for msg in telegram.account.sent if "comment_to" in msg.kwargs] == []


@pytest.mark.asyncio
async def test_private_message_never_gets_a_first_comment() -> None:
    runtime, telegram, _ = build_runtime(
        FirstCommentSettings(enabled=True, variants=[FirstCommentVariant(text="Первый!")])
    )
    await runtime.start()

    await telegram.account.deliver(chat_id=777, text="привет")

    assert [msg for msg in telegram.account.sent if "comment_to" in msg.kwargs] == []


@pytest.mark.asyncio
async def test_album_post_is_commented_once() -> None:
    runtime, telegram, _ = build_runtime(
        FirstCommentSettings(enabled=True, variants=[FirstCommentVariant(text="Первый!")])
    )
    await runtime.start()

    await telegram.account.deliver_post(chat_id=-100500, text="фото 1", grouped_id=42)
    await telegram.account.deliver_post(chat_id=-100500, text="фото 2", grouped_id=42)

    assert len([msg for msg in telegram.account.sent if "comment_to" in msg.kwargs]) == 1


@pytest.mark.asyncio
async def test_each_post_draws_a_variant_at_random(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, telegram, _ = build_runtime(
        FirstCommentSettings(
            enabled=True,
            variants=[FirstCommentVariant(text="раз"), FirstCommentVariant(text="два")],
        )
    )
    await runtime.start()

    drawn: list[str] = []
    picks = iter(["два", "раз"])

    def fake_choice(options: list[FirstCommentVariant]) -> FirstCommentVariant:
        assert [variant.text for variant in options] == ["раз", "два"]
        wanted = next(picks)
        chosen = next(variant for variant in options if variant.text == wanted)
        drawn.append(chosen.text)
        return chosen

    monkeypatch.setattr("mimic42.core.agent_runtime.random.choice", fake_choice)

    await telegram.account.deliver_post(chat_id=-100500, text="пост 1")
    await telegram.account.deliver_post(chat_id=-100500, text="пост 2")

    comments = [msg.text for msg in telegram.account.sent if "comment_to" in msg.kwargs]
    assert comments == ["два", "раз"]
    assert drawn == ["два", "раз"]


@pytest.mark.asyncio
async def test_variant_with_an_image_goes_out_as_a_photo_with_a_caption() -> None:
    store = FakeImageStore({"agent/pic.jpg": b"JPEGDATA"})
    runtime, telegram, _ = build_runtime(
        FirstCommentSettings(
            enabled=True,
            variants=[
                FirstCommentVariant(
                    text="Подпись", image_path="agent/pic.jpg", image_name="pic.jpg"
                )
            ],
        ),
        media_uploader=store,
    )
    await runtime.start()

    await telegram.account.deliver_post(chat_id=-100500, text="Новый пост")

    sent = [msg for msg in telegram.account.sent if "comment_to" in msg.kwargs][0]
    stream: Any = sent.kwargs["file"]
    assert store.opened == ["agent/pic.jpg"]
    assert stream.getvalue() == b"JPEGDATA"
    # Telethon решает «фото или документ» по расширению имени потока.
    assert stream.name == "pic.jpg"
    assert sent.text == "Подпись"


@pytest.mark.asyncio
async def test_unreadable_image_still_sends_the_text() -> None:
    store = FakeImageStore()
    runtime, telegram, _ = build_runtime(
        FirstCommentSettings(
            enabled=True,
            variants=[FirstCommentVariant(text="Подпись", image_path="agent/gone.jpg")],
        ),
        media_uploader=store,
    )
    await runtime.start()

    await telegram.account.deliver_post(chat_id=-100500, text="Новый пост")

    sent = [msg for msg in telegram.account.sent if "comment_to" in msg.kwargs][0]
    assert sent.text == "Подпись"
    assert "file" not in sent.kwargs


@pytest.mark.asyncio
async def test_a_failed_comment_does_not_break_the_incoming_pipeline() -> None:
    class RefusingClient(FakeTelegramClient):
        async def send_message(self, entity: str | int, message: str, **kwargs: Any) -> object:
            if "comment_to" in kwargs:
                raise RuntimeError("no discussion group")
            return await super().send_message(entity, message, **kwargs)

    account = FakeTelegramAccount()
    account.authorized = True
    telegram = RefusingClient(account)
    runtime = MimicAgentRuntime(
        config=make_config(
            FirstCommentSettings(enabled=True, variants=[FirstCommentVariant(text="Первый!")])
        ),
        telegram_client=telegram,
        langchain_agent=FakeLangChainAgent(),
    )
    await runtime.start()

    await telegram.account.deliver_post(chat_id=-100500, text="Новый пост")

    assert telegram.account.sent == []
