from __future__ import annotations

import io
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from telethon import errors, functions, types

from mimic42.core.agent_runtime import (
    AgentRuntimeState,
    AgentTrigger,
    AttackModeActiveError,
    CommentMediaUnavailable,
    MimicAgentRuntime,
    OpenerResult,
    TelegramEventLike,
)
from mimic42.core.first_comment import FirstCommentSettings, FirstCommentVariant
from mimic42.core.media import MediaFile
from mimic42.testing.telegram import FakeIncomingEvent, FakeTelegramClient, IncomingMessage
from tests.core.test_agent_runtime import (
    FakeLangChainAgent,
    FakeRuntimeMemoryService,
    make_config,
)


@pytest.fixture
def fast_typing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Задержка «печатает» без реальных секунд: часы идут вперёд вместе со сном."""
    now = [0.0]

    monkeypatch.setattr(
        "mimic42.core.agent_runtime.asyncio.get_event_loop",
        lambda: SimpleNamespace(time=lambda: now[0]),
    )

    async def sleep(delta: float) -> None:
        now[0] += delta

    monkeypatch.setattr("mimic42.core.agent_runtime.asyncio.sleep", sleep)
    # Без случайных прерываний в тесте: их отдельно проверяет test_agent_runtime.
    monkeypatch.setattr("mimic42.core.agent_runtime.random.random", lambda: 1.0)


class FakeMediaUploader:
    def __init__(self, files: dict[str, bytes]) -> None:
        self.files = files

    async def upload(
        self,
        *,
        agent_id: UUID,
        filename: str,
        data: bytes,
        mime_type: str,
        kind: str = "doc",
    ) -> MediaFile | None:
        raise AssertionError("атака не пишет медиа в хранилище")

    async def open(self, path: str) -> bytes | None:
        return self.files.get(path)

    async def remove_prefix(self, agent_id: UUID) -> None:
        return None


def _uploaded_photo(index: int) -> types.MessageMediaPhoto:
    return types.MessageMediaPhoto(
        photo=types.Photo(
            id=index,
            access_hash=index,
            file_reference=b"reference",
            date=None,
            sizes=[],
            dc_id=2,
        )
    )


class CommentTelegramClient(FakeTelegramClient):
    """Подделка клиента, которая отвечает на загрузку фото описанием на сервере."""

    def __init__(self) -> None:
        super().__init__()
        # Сколько ближайших отправок медиа упадёт с протухшей ссылкой на файл.
        self.expire_media_sends = 0

    async def __call__(self, request: Any) -> Any:
        if isinstance(request, functions.messages.UploadMediaRequest):
            self.requests.append(request)
            return _uploaded_photo(len(self.uploads))
        if self.expire_media_sends > 0 and isinstance(
            request,
            (functions.messages.SendMediaRequest, functions.messages.SendMultiMediaRequest),
        ):
            self.expire_media_sends -= 1
            self.requests.append(request)
            raise errors.FileReferenceExpiredError(request=request)
        return await super().__call__(request)


class _UntouchableSessions:
    """Сессия, к которой обращаться нельзя: таймеры обязаны остаться pending."""

    def __call__(self) -> Any:
        raise AssertionError("во время атаки планировщик не трогает таймеры")


def make_runtime(
    *,
    uploader: FakeMediaUploader | None = None,
    first_comment: bool = False,
) -> tuple[MimicAgentRuntime, CommentTelegramClient, FakeLangChainAgent, FakeRuntimeMemoryService]:
    telegram = CommentTelegramClient()
    agent = FakeLangChainAgent(response="ответ")
    memory = FakeRuntimeMemoryService()
    config = make_config()
    if first_comment:
        config = config.model_copy(
            update={
                "first_comment": FirstCommentSettings(
                    enabled=True, variants=[FirstCommentVariant(text="первый")]
                )
            }
        )
    runtime = MimicAgentRuntime(
        config=config,
        telegram_client=telegram,
        langchain_agent=agent,
        memory_service=memory,
        media_uploader=uploader,
    )
    return runtime, telegram, agent, memory


def _incoming_event(client: FakeTelegramClient) -> TelegramEventLike:
    return cast(
        TelegramEventLike,
        FakeIncomingEvent(
            IncomingMessage(chat_id=555, message_id=1, text="привет", sender_id=555),
            client=client,
        ),
    )


def _post_event(client: FakeTelegramClient) -> TelegramEventLike:
    return cast(
        TelegramEventLike,
        FakeIncomingEvent(
            IncomingMessage(
                chat_id=-100_555,
                message_id=2,
                text="пост",
                sender_id=-100_555,
                is_channel=True,
                has_link=True,
            ),
            client=client,
        ),
    )


async def test_enter_and_exit_attack_switch_the_normal_traffic_predicate() -> None:
    runtime, _, _, _ = make_runtime()
    assert runtime.accepts_normal_traffic is False

    await runtime.start()
    attack_id = uuid4()

    assert runtime.attack_id is None
    assert runtime.accepts_normal_traffic is True
    assert runtime.status.attack_id is None

    runtime.enter_attack(attack_id)

    assert runtime.attack_id == attack_id
    assert runtime.accepts_normal_traffic is False
    assert runtime.status.state is AgentRuntimeState.RUNNING
    assert runtime.status.attack_id == attack_id

    runtime.exit_attack()

    assert runtime.attack_id is None
    assert runtime.accepts_normal_traffic is True
    assert runtime.status.attack_id is None
    await runtime.stop()


async def test_text_comment_is_a_raw_request_with_random_id_and_reply(
    fast_typing: None,
) -> None:
    runtime, telegram, _, _ = make_runtime()
    random_id = 849_541_892_288_586_017

    await runtime.send_humanized_comment(
        telegram,
        entity="group",
        text="Участвую!",
        media=(),
        reply_to=77,
        random_id=random_id,
    )

    sends = [
        request
        for request in telegram.requests
        if isinstance(request, functions.messages.SendMessageRequest)
    ]
    assert len(sends) == 1
    request = sends[0]
    assert request.peer == "group"
    assert request.message == "Участвую!"
    assert request.random_id == random_id
    assert request.no_webpage is True
    assert request.entities is None
    assert not hasattr(request, "parse_mode")
    assert isinstance(request.reply_to, types.InputReplyToMessage)
    assert request.reply_to.reply_to_msg_id == 77
    assert telegram.account.sent == []


async def test_single_image_is_uploaded_and_sent_as_a_photo(fast_typing: None) -> None:
    runtime, telegram, _, _ = make_runtime(
        uploader=FakeMediaUploader({"attacks/owner/a.jpg": b"jpeg-bytes"})
    )
    random_id = 12345

    await runtime.send_humanized_comment(
        telegram,
        entity="group",
        text="Подпись",
        media=("attacks/owner/a.jpg",),
        reply_to=77,
        random_id=random_id,
    )

    assert len(telegram.uploads) == 1
    stream = telegram.uploads[0]
    assert isinstance(stream, io.BytesIO)
    assert stream.name == "a.jpg"
    assert stream.getvalue() == b"jpeg-bytes"

    uploads = [
        request
        for request in telegram.requests
        if isinstance(request, functions.messages.UploadMediaRequest)
    ]
    assert len(uploads) == 1
    assert isinstance(uploads[0].media, types.InputMediaUploadedPhoto)
    assert cast(types.InputFile, uploads[0].media.file).name == "a.jpg"

    sends = [
        request
        for request in telegram.requests
        if isinstance(request, functions.messages.SendMediaRequest)
    ]
    assert len(sends) == 1
    request = sends[0]
    assert isinstance(request.media, types.InputMediaPhoto)
    assert request.message == "Подпись"
    assert request.random_id == random_id
    assert isinstance(request.reply_to, types.InputReplyToMessage)
    assert request.reply_to.reply_to_msg_id == 77


async def test_album_is_sent_through_send_file(fast_typing: None) -> None:
    runtime, telegram, _, _ = make_runtime(
        uploader=FakeMediaUploader(
            {
                "attacks/owner/a.jpg": b"a",
                "attacks/owner/b.jpg": b"b",
                "attacks/owner/c.jpg": b"c",
            }
        )
    )
    media = ("attacks/owner/a.jpg", "attacks/owner/b.jpg", "attacks/owner/c.jpg")

    await runtime.send_humanized_comment(
        telegram,
        entity="group",
        text="Подпись",
        media=media,
        reply_to=77,
        random_id=9000,
    )

    sent = telegram.account.sent[-1]
    assert sent.text == "Подпись"
    files = cast(list[io.BytesIO], sent.kwargs["file"])
    assert [stream.name for stream in files] == ["a.jpg", "b.jpg", "c.jpg"]
    assert [stream.getvalue() for stream in files] == [b"a", b"b", b"c"]
    assert sent.kwargs["reply_to"] == 77
    assert sent.kwargs["parse_mode"] is None
    assert not [
        request
        for request in telegram.requests
        if isinstance(
            request, (functions.messages.SendMediaRequest, functions.messages.SendMultiMediaRequest)
        )
    ]


async def test_the_same_image_is_uploaded_once_and_then_comes_from_the_cache(
    fast_typing: None,
) -> None:
    runtime, telegram, _, _ = make_runtime(
        uploader=FakeMediaUploader({"attacks/owner/a.jpg": b"jpeg-bytes"})
    )

    for random_id in (1, 2):
        await runtime.send_humanized_comment(
            telegram,
            entity="group",
            text="Подпись",
            media=("attacks/owner/a.jpg",),
            reply_to=77,
            random_id=random_id,
        )

    assert len(telegram.uploads) == 1
    uploads = [
        request
        for request in telegram.requests
        if isinstance(request, functions.messages.UploadMediaRequest)
    ]
    assert len(uploads) == 1

    sends = [
        request
        for request in telegram.requests
        if isinstance(request, functions.messages.SendMediaRequest)
    ]
    assert [request.random_id for request in sends] == [1, 2]
    assert isinstance(sends[0].media, types.InputMediaPhoto)
    assert isinstance(sends[1].media, types.InputMediaPhoto)
    first_photo = cast(types.InputPhoto, sends[0].media.id)
    second_photo = cast(types.InputPhoto, sends[1].media.id)
    assert first_photo.id == second_photo.id


async def test_an_expired_file_reference_is_evicted_and_the_send_retried(
    fast_typing: None,
) -> None:
    runtime, telegram, _, _ = make_runtime(
        uploader=FakeMediaUploader({"attacks/owner/a.jpg": b"jpeg-bytes"})
    )

    await runtime.send_humanized_comment(
        telegram,
        entity="group",
        text="Подпись",
        media=("attacks/owner/a.jpg",),
        reply_to=77,
        random_id=1,
    )
    assert len(telegram.uploads) == 1

    telegram.expire_media_sends = 1
    await runtime.send_humanized_comment(
        telegram,
        entity="group",
        text="Подпись",
        media=("attacks/owner/a.jpg",),
        reply_to=77,
        random_id=2,
    )

    assert [cast(io.BytesIO, stream).name for stream in telegram.uploads] == ["a.jpg", "a.jpg"]
    uploads = [
        request
        for request in telegram.requests
        if isinstance(request, functions.messages.UploadMediaRequest)
    ]
    assert len(uploads) == 2

    sends = [
        request
        for request in telegram.requests
        if isinstance(request, functions.messages.SendMediaRequest)
    ]
    assert [request.random_id for request in sends] == [1, 2, 2]
    assert isinstance(sends[-1].media, types.InputMediaPhoto)
    assert cast(types.InputPhoto, sends[-1].media.id).id == 2


async def test_comment_holds_typing_and_cancels_it(fast_typing: None) -> None:
    runtime, telegram, _, _ = make_runtime()

    await runtime.send_humanized_comment(
        telegram,
        entity="group",
        text="Участвую!",
        media=(),
        reply_to=None,
        random_id=1,
    )

    typing = [
        request
        for request in telegram.requests
        if isinstance(request, functions.messages.SetTypingRequest)
        and isinstance(request.action, types.SendMessageTypingAction)
    ]
    cancel = [
        request
        for request in telegram.requests
        if isinstance(request, functions.messages.SetTypingRequest)
        and isinstance(request.action, types.SendMessageCancelAction)
    ]
    assert typing
    assert cancel
    last_typing = [
        request
        for request in telegram.requests
        if isinstance(request, functions.messages.SetTypingRequest)
    ][-1]
    assert isinstance(last_typing.action, types.SendMessageCancelAction)


async def test_missing_image_raises_instead_of_sending_a_document(fast_typing: None) -> None:
    runtime, telegram, _, _ = make_runtime(uploader=FakeMediaUploader({}))

    with pytest.raises(CommentMediaUnavailable):
        await runtime.send_humanized_comment(
            telegram,
            entity="group",
            text="Подпись",
            media=("attacks/owner/missing.jpg",),
            reply_to=77,
            random_id=1,
        )

    assert not [
        request
        for request in telegram.requests
        if isinstance(
            request, (functions.messages.SendMediaRequest, functions.messages.SendMessageRequest)
        )
    ]
    assert telegram.account.sent == []
    assert telegram.uploads == []


async def test_comment_without_a_media_uploader_cannot_send_an_image(fast_typing: None) -> None:
    runtime, telegram, _, _ = make_runtime()

    with pytest.raises(CommentMediaUnavailable):
        await runtime.send_humanized_comment(
            telegram,
            entity="group",
            text="Подпись",
            media=("attacks/owner/a.jpg",),
            reply_to=77,
            random_id=1,
        )

    assert telegram.account.sent == []


GATE_ENTRIES = (
    "handle_incoming_message",
    "dispatch_incoming",
    "flush_deferred",
    "process_batch",
    "trigger_while_running",
    "handle_channel_post",
    "send_turn_reply_locked",
    "trigger_message",
    "trigger_running_message",
    "send_warmup_opener",
    "check_and_trigger_timers",
)


@pytest.mark.parametrize("entry", GATE_ENTRIES)
async def test_attack_mode_closes_every_normal_entry_point(
    entry: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime, telegram, agent, _ = make_runtime(first_comment=True)
    await runtime.start()
    runtime.enter_attack(uuid4())
    assert runtime.accepts_normal_traffic is False

    first_comments: list[object] = []

    async def send_first_comment(
        peer: str, message_id: int, variant: FirstCommentVariant
    ) -> tuple[object, FirstCommentVariant]:
        first_comments.append(variant)
        return object(), variant

    monkeypatch.setattr(runtime, "_send_first_comment", send_first_comment)
    event = _incoming_event(telegram)

    try:
        if entry == "handle_incoming_message":
            await runtime._handle_incoming_message(event)
        elif entry == "dispatch_incoming":
            await runtime._dispatch_incoming([event])
        elif entry == "flush_deferred":
            await runtime._flush_deferred("555", [[event]], [0.0])
        elif entry == "process_batch":
            await runtime._process_batch("555", [[event]])
        elif entry == "trigger_while_running":
            await runtime._trigger_while_running(AgentTrigger(peer="555", text="ping"))
        elif entry == "handle_channel_post":
            await runtime._handle_channel_post(_post_event(telegram))
        elif entry == "send_turn_reply_locked":
            assert await runtime._send_turn_reply_locked("555", "555", "ответ", None) is None
        elif entry == "trigger_message":
            with pytest.raises(AttackModeActiveError):
                await runtime.trigger_message(AgentTrigger(peer="555", text="ping"))
        elif entry == "trigger_running_message":
            with pytest.raises(AttackModeActiveError):
                await runtime._trigger_running_message(AgentTrigger(peer="555", text="ping"))
        elif entry == "send_warmup_opener":
            opener = await runtime.send_warmup_opener(
                username="partner",
                user_id=777,
                partner_agent_id=uuid4(),
                partner_name="Партнёр",
                text="привет",
                dialog_length=1,
            )
            assert opener is OpenerResult.FAILED
        else:
            runtime._session_factory = cast(Any, _UntouchableSessions())
            await runtime._check_and_trigger_timers()
    finally:
        await runtime.stop()

    assert agent.inputs == []
    assert first_comments == []
    assert telegram.account.sent == []


async def test_channel_post_reaches_the_first_comment_without_an_attack(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, telegram, _, _ = make_runtime(first_comment=True)
    await runtime.start()
    calls: list[FirstCommentVariant] = []

    async def send_first_comment(
        peer: str, message_id: int, variant: FirstCommentVariant
    ) -> tuple[object, FirstCommentVariant]:
        calls.append(variant)
        return object(), variant

    monkeypatch.setattr(runtime, "_send_first_comment", send_first_comment)

    await runtime._handle_channel_post(_post_event(telegram))
    await runtime.stop()

    assert len(calls) == 1


async def test_remember_note_writes_history_once_and_sends_nothing() -> None:
    runtime, telegram, _, memory = make_runtime()

    await runtime.remember_note(peer="-100_555", text="Участие в атаке завершено.")

    assert telegram.account.sent == []
    assert len(memory.saved_messages) == 1
    agent_id, peer, inputs, outputs, structured = memory.saved_messages[0]
    assert agent_id == runtime.config.agent_id
    assert peer == "-100_555"
    assert inputs == []
    assert outputs[0]["content"] == "Участие в атаке завершено."
    assert structured == {"send_any_message": True, "text": "Участие в атаке завершено."}


async def test_remember_note_propagates_memory_failures_for_retry() -> None:
    class BrokenMemory(FakeRuntimeMemoryService):
        async def save_messages(self, **kwargs: Any) -> None:
            raise RuntimeError("Mem0 недоступен")

    runtime, _, _, _ = make_runtime()
    runtime._memory_service = BrokenMemory()

    with pytest.raises(RuntimeError):
        await runtime.remember_note(peer="555", text="заметка")
