from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest

from mimic42.core.agent_runtime import (
    AgentRuntimeConfig,
    FirstCommentImageUnavailable,
    MimicAgentRuntime,
    _first_comment_failure_reason,
    _first_comment_note,
    _is_broadcast_post,
    _peer_for_send,
)
from mimic42.core.first_comment import (
    MAX_COMMENT_CAPTION,
    FirstCommentSettings,
    FirstCommentVariant,
    PostedAlbumGuard,
    SentFirstComments,
    parse_first_comment,
)
from mimic42.core.media import MediaFile
from mimic42.testing.telegram import FakeTelegramAccount, FakeTelegramClient


class FakeLangChainAgent:
    """Ход агента здесь — признак провала: комментарий обязан идти мимо ИИ."""

    def __init__(self) -> None:
        self.calls = 0
        self.inputs: list[str] = []

    async def ainvoke(
        self,
        input_data: dict[str, object],
        context: object | None = None,
    ) -> dict[str, object]:
        self.calls += 1
        messages: Any = input_data["messages"]
        last = messages[-1]
        self.inputs.append(last["content"] if isinstance(last, dict) else last.content)
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


def record_events(runtime: MimicAgentRuntime) -> list[dict[str, Any]]:
    """События ленты без базы: рантайм без session_factory их не пишет."""
    events: list[dict[str, Any]] = []

    async def record(**kwargs: Any) -> None:
        events.append(kwargs)

    runtime._record_event = record  # ty: ignore[invalid-assignment]
    return events


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
    # Строка из ручной правки JSON не включает фичу: только настоящий true.
    assert parse_first_comment({"enabled": "false", "variants": [{"text": "a"}]}).enabled is False


def test_parse_drops_an_image_variant_whose_caption_telegram_would_reject() -> None:
    settings = parse_first_comment(
        {
            "enabled": True,
            "variants": [
                {"text": "x" * (MAX_COMMENT_CAPTION + 1), "image_path": "agent/pic.jpg"},
                {"text": "x" * (MAX_COMMENT_CAPTION + 1)},
            ],
        }
    )

    # Без картинки тот же текст — обычное сообщение, ему хватает 4096.
    assert [variant.image_path for variant in settings.variants] == [None]


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


def test_failures_are_reported_with_readable_reasons() -> None:
    from telethon import errors

    request = type("Request", (), {})()

    assert (
        _first_comment_failure_reason(errors.MsgIdInvalidError(request)) == "no_discussion_message"
    )
    assert (
        _first_comment_failure_reason(errors.ChatGuestSendForbiddenError(request))
        == "write_forbidden"
    )
    assert _first_comment_failure_reason(errors.AuthKeyDuplicatedError(request)) == "unauthorized"
    assert _first_comment_failure_reason(FirstCommentImageUnavailable("x")) == "image_unavailable"
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
async def test_channel_without_discussion_is_skipped_without_a_request() -> None:
    runtime, telegram, _ = build_runtime(
        FirstCommentSettings(enabled=True, variants=[FirstCommentVariant(text="Первый!")])
    )
    events = record_events(runtime)
    await runtime.start()

    await telegram.account.deliver_post(chat_id=-100500, text="Новый пост", has_link=False)

    assert [msg for msg in telegram.account.sent if "comment_to" in msg.kwargs] == []
    # Выключенные комментарии — настройка канала, а не сбой: в ленту не пишем.
    assert [event for event in events if event["event_type"].startswith("first_comment.")] == []


@pytest.mark.asyncio
async def test_sent_image_is_reused_instead_of_uploaded_again() -> None:
    store = FakeImageStore({"agent/pic.jpg": b"JPEGDATA"})
    runtime, telegram, _ = build_runtime(
        FirstCommentSettings(
            enabled=True,
            variants=[FirstCommentVariant(image_path="agent/pic.jpg", image_name="pic.jpg")],
        ),
        media_uploader=store,
    )
    await runtime.start()

    await telegram.account.deliver_post(chat_id=-100500, text="пост 1")
    await telegram.account.deliver_post(chat_id=-100501, text="пост 2")

    first, second = [msg for msg in telegram.account.sent if "comment_to" in msg.kwargs]
    assert store.opened == ["agent/pic.jpg"]
    # Второй раз уходит media первого сообщения: без скачивания и загрузки.
    assert second.kwargs["file"].message_id == telegram.account.sent.index(first) + 1


@pytest.mark.asyncio
async def test_expired_file_reference_falls_back_to_a_fresh_upload() -> None:
    from telethon import errors

    class ExpiringClient(FakeTelegramClient):
        async def send_file(self, entity: str | int, file: Any, **kwargs: Any) -> object:
            if hasattr(file, "message_id"):
                raise errors.FileReferenceExpiredError(type("Request", (), {})())
            return await super().send_file(entity, file, **kwargs)

    store = FakeImageStore({"agent/pic.jpg": b"JPEGDATA"})
    account = FakeTelegramAccount()
    account.authorized = True
    telegram = ExpiringClient(account)
    runtime = MimicAgentRuntime(
        config=make_config(
            FirstCommentSettings(
                enabled=True,
                variants=[FirstCommentVariant(image_path="agent/pic.jpg", image_name="pic.jpg")],
            )
        ),
        telegram_client=telegram,
        langchain_agent=FakeLangChainAgent(),
        media_uploader=store,
    )
    await runtime.start()

    await telegram.account.deliver_post(chat_id=-100500, text="пост 1")
    await telegram.account.deliver_post(chat_id=-100500, text="пост 2")

    comments = [msg for msg in telegram.account.sent if "comment_to" in msg.kwargs]
    assert len(comments) == 2
    assert store.opened == ["agent/pic.jpg", "agent/pic.jpg"]
    assert comments[1].kwargs["file"].getvalue() == b"JPEGDATA"


@pytest.mark.asyncio
async def test_image_only_variant_without_its_image_sends_nothing() -> None:
    runtime, telegram, _ = build_runtime(
        FirstCommentSettings(
            enabled=True,
            variants=[FirstCommentVariant(image_path="agent/gone.jpg")],
        ),
        media_uploader=FakeImageStore(),
    )
    events = record_events(runtime)
    await runtime.start()

    await telegram.account.deliver_post(chat_id=-100500, text="Новый пост")

    # Пустой текст Telegram бы отверг, а «комментарий ни о чём» хуже тишины.
    assert [msg for msg in telegram.account.sent if "comment_to" in msg.kwargs] == []
    failed = [event for event in events if event["event_type"] == "first_comment.failed"]
    assert failed[0]["payload"]["reason"] == "image_unavailable"


@pytest.mark.asyncio
async def test_dead_session_on_comment_revokes_the_runtime() -> None:
    from telethon import errors

    class DeadClient(FakeTelegramClient):
        async def send_message(self, entity: str | int, message: str, **kwargs: Any) -> object:
            raise errors.AuthKeyDuplicatedError(type("Request", (), {})())

    account = FakeTelegramAccount()
    account.authorized = True
    telegram = DeadClient(account)
    agent = FakeLangChainAgent()
    runtime = MimicAgentRuntime(
        config=make_config(
            FirstCommentSettings(enabled=True, variants=[FirstCommentVariant(text="Первый!")])
        ),
        telegram_client=telegram,
        langchain_agent=agent,
    )
    events = record_events(runtime)
    await runtime.start()

    await telegram.account.deliver_post(chat_id=-100500, text="Новый пост")

    failed = [event for event in events if event["event_type"] == "first_comment.failed"]
    assert failed[0]["payload"]["reason"] == "unauthorized"
    assert telegram.disconnect_calls == 1
    # Мёртвая сессия не чинится перезапуском: ИИ-ветка по посту уже не идёт.
    assert agent.calls == 0


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
    # ИИ узнаёт то, что ушло на самом деле, — подпись без картинки.
    note = runtime._sent_first_comments.lookup("-100500", [telegram.account.incoming[0].message_id])
    assert note is not None
    assert note.image_path is None


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


# ── Что знает ИИ ──────────────────────────────────────────────────────────────


def test_note_names_what_is_under_the_post() -> None:
    assert _first_comment_note(FirstCommentVariant(text="Первый!")) == (
        "Твой первый комментарий под этим постом: «Первый!»"
    )
    assert _first_comment_note(FirstCommentVariant(text="", image_path="a/b.jpg")).endswith(
        "картинка без подписи"
    )
    assert _first_comment_note(FirstCommentVariant(text="глянь", image_path="a/b.jpg")).endswith(
        "картинка с подписью «глянь»"
    )


def test_sent_comments_are_found_by_any_album_item_and_stay_bounded() -> None:
    sent = SentFirstComments(capacity=2)
    variant = FirstCommentVariant(text="Первый!")

    sent.remember("-100500", 11, variant)
    assert sent.lookup("-100500", [10, 11, 12]) is variant
    assert sent.lookup("-100501", [11]) is None

    sent.remember("-100500", 12, variant)
    sent.remember("-100500", 13, variant)
    assert sent.lookup("-100500", [11]) is None


@pytest.mark.asyncio
async def test_agent_turn_on_the_post_knows_about_the_first_comment() -> None:
    runtime, telegram, agent = build_runtime(
        FirstCommentSettings(enabled=True, variants=[FirstCommentVariant(text="Первый!")])
    )
    await runtime.start()

    await telegram.account.deliver_post(chat_id=-100500, text="Новый пост")

    assert agent.calls == 1
    assert "Твой первый комментарий под этим постом: «Первый!»" in agent.inputs[0]


@pytest.mark.asyncio
async def test_agent_turn_without_a_comment_carries_no_note() -> None:
    runtime, telegram, agent = build_runtime(
        FirstCommentSettings(enabled=True, variants=[FirstCommentVariant(text="Первый!")])
    )
    await runtime.start()

    await telegram.account.deliver_post(chat_id=-100500, text="Новый пост", has_link=False)
    await telegram.account.deliver(chat_id=777, text="привет")

    assert agent.calls == 2
    assert all("первый комментарий" not in text for text in agent.inputs)
