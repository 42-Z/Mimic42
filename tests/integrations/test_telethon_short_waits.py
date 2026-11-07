from __future__ import annotations

import asyncio
import json
from collections import deque
from collections.abc import Iterator
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from langchain_core.messages import ToolMessage
from telethon import errors, functions, types

from mimic42.core.activity import ActivityRecorder
from mimic42.integrations.activity_middleware import ActivityMiddleware
from mimic42.integrations.telegram_tools import TelegramToolbox
from mimic42.integrations.telethon_client import MimicTelegramClient, build_telegram_client
from tests.integrations.test_telethon_client import _config, _valid_session_string


class ScriptedSender:
    def __init__(self, *outcomes: Any) -> None:
        self.outcomes = deque(outcomes)
        self.requests: list[Any] = []

    def send(self, request: Any, ordered: bool = False) -> Any:
        if isinstance(request, list):
            return [self.send(item, ordered=ordered) for item in request]
        self.requests.append(request)
        outcome = self.outcomes.popleft()
        future = asyncio.get_running_loop().create_future()
        if isinstance(outcome, Exception):
            future.set_exception(outcome)
        else:
            future.set_result(outcome)
        return future


class Clock:
    def __init__(self) -> None:
        self.now = 1_800_000_000.0
        self.sleeps: list[float] = []

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> Iterator[Clock]:
    clock = Clock()
    monkeypatch.setattr("telethon.client.users.time.time", lambda: clock.now)
    monkeypatch.setattr("asyncio.sleep", clock.sleep)
    yield clock


def client_for(sender: ScriptedSender) -> MimicTelegramClient:
    client = build_telegram_client(_config(_valid_session_string()))
    assert isinstance(client, MimicTelegramClient)
    client._sender = cast(Any, sender)
    return client


WAIT_ERRORS = (
    errors.FloodWaitError,
    errors.FloodPremiumWaitError,
    errors.SlowModeWaitError,
    errors.FloodTestPhoneWaitError,
)


@pytest.mark.parametrize("error_class", WAIT_ERRORS)
@pytest.mark.parametrize("seconds", [0, 1, 3, 4])
async def test_short_wait_returns_result_after_four_seconds(
    clock: Clock, error_class: Any, seconds: int
) -> None:
    request = functions.help.GetConfigRequest()
    result = types.UserEmpty(id=7)
    sender = ScriptedSender(error_class(request=request, capture=seconds), result)

    assert await client_for(sender)(request) is result
    assert clock.sleeps == [4]
    assert sender.requests == [request, request]


@pytest.mark.parametrize("error_class", WAIT_ERRORS)
@pytest.mark.parametrize("seconds", [5, 30])
async def test_long_wait_is_not_hidden(clock: Clock, error_class: Any, seconds: int) -> None:
    request = functions.help.GetConfigRequest()
    error = error_class(request=request, capture=seconds)
    sender = ScriptedSender(error)

    with pytest.raises(error_class) as caught:
        await client_for(sender)(request)

    assert caught.value is error
    assert sender.requests == [request]
    assert clock.sleeps == []


async def test_repeated_wait_is_not_retried_forever(clock: Clock) -> None:
    request = functions.help.GetConfigRequest()
    first = errors.FloodWaitError(request=request, capture=4)
    second = errors.FloodWaitError(request=request, capture=4)
    sender = ScriptedSender(first, second)

    with pytest.raises(errors.FloodWaitError) as caught:
        await client_for(sender)(request)

    assert caught.value is second
    assert sender.requests == [request, request]
    assert clock.sleeps == [4]


@pytest.mark.parametrize("as_batch", [False, True])
async def test_nested_username_resolution_does_not_restart_exhausted_retry(
    clock: Clock, as_batch: bool
) -> None:
    request = functions.channels.JoinChannelRequest(channel=cast(Any, "@uncached_channel"))
    first = errors.FloodWaitError(request=None, capture=4)
    second = errors.FloodWaitError(request=None, capture=4)
    sender = ScriptedSender(first, second)

    with pytest.raises(errors.FloodWaitError) as caught:
        await client_for(sender)([request] if as_batch else request)

    assert caught.value is second
    assert len(sender.requests) == 2
    assert all(
        isinstance(item, functions.contacts.ResolveUsernameRequest) for item in sender.requests
    )
    assert clock.sleeps == [4]


async def test_cached_short_wait_is_respected_before_sending(clock: Clock) -> None:
    request = functions.help.GetConfigRequest()
    result = types.UserEmpty(id=7)
    sender = ScriptedSender(errors.FloodWaitError(request=request, capture=5), result)
    client = client_for(sender)
    with pytest.raises(errors.FloodWaitError):
        await client(request)
    clock.now += 1

    assert await client(request) is result
    assert clock.sleeps == [4]
    assert sender.requests == [request, request]


async def test_short_wait_on_download_sender_is_handled(clock: Clock) -> None:
    request = functions.help.GetConfigRequest()
    result = types.UserEmpty(id=7)
    sender = ScriptedSender(errors.FloodWaitError(request=request, capture=4), result)

    assert await client_for(sender)._call(sender, request) is result
    assert clock.sleeps == [4]


@pytest.mark.parametrize("mixed_error", [False, True])
async def test_batch_retries_only_short_waits_in_their_original_positions(
    clock: Clock, mixed_error: bool
) -> None:
    requests = [functions.help.GetConfigRequest() for _ in range(4)]
    results = [types.UserEmpty(id=index) for index in range(4)]
    long_wait = errors.SlowModeWaitError(request=requests[3], capture=20)
    sender = ScriptedSender(
        results[0],
        errors.FloodWaitError(request=requests[1], capture=4),
        errors.SlowModeWaitError(request=requests[2], capture=2),
        long_wait if mixed_error else results[3],
        results[1],
        results[2],
    )
    client = client_for(sender)
    if mixed_error:
        with pytest.raises(errors.MultiError) as caught:
            await client(requests, ordered=True)
        batch = cast(Any, caught.value)
        assert batch.results == [*results[:3], None]
        assert batch.exceptions == [None, None, None, long_wait]
        assert batch.requests == requests
    else:
        assert await client(requests, ordered=True) == results

    assert sender.requests == [*requests, requests[1], requests[2]]
    assert clock.sleeps == [4]


async def test_singleton_batch_keeps_list_result(clock: Clock) -> None:
    request = functions.help.GetConfigRequest()
    result = types.UserEmpty(id=7)
    sender = ScriptedSender(errors.FloodWaitError(request=request, capture=4), result)

    assert await client_for(sender)([request]) == [result]
    assert clock.sleeps == [4]


async def test_cancellation_during_wait_does_not_retry(
    clock: Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def cancelled(seconds: float) -> None:
        raise asyncio.CancelledError

    monkeypatch.setattr("asyncio.sleep", cancelled)
    request = functions.help.GetConfigRequest()
    sender = ScriptedSender(errors.FloodWaitError(request=request, capture=4))
    with pytest.raises(asyncio.CancelledError):
        await client_for(sender)(request)
    assert sender.requests == [request]


async def test_batch_retry_failure_keeps_successes_and_other_errors(clock: Clock) -> None:
    requests = [functions.help.GetConfigRequest() for _ in range(3)]
    result = types.UserEmpty(id=7)
    refusal = errors.ChatAdminRequiredError(request=requests[2])
    second_wait = errors.SlowModeWaitError(request=requests[1], capture=9)
    sender = ScriptedSender(
        result,
        errors.FloodWaitError(request=requests[1], capture=4),
        refusal,
        second_wait,
    )
    with pytest.raises(errors.MultiError) as caught:
        await client_for(sender)(requests)

    batch = cast(Any, caught.value)
    assert batch.results == [result, None, None]
    assert batch.exceptions == [None, second_wait, refusal]
    assert sender.requests == [*requests, requests[1]]
    assert clock.sleeps == [4]


async def test_batch_without_short_waits_is_not_retried(clock: Clock) -> None:
    requests = [functions.help.GetConfigRequest() for _ in range(2)]
    result = types.UserEmpty(id=7)
    wait = errors.FloodWaitError(request=requests[1], capture=5)
    sender = ScriptedSender(result, wait)
    with pytest.raises(errors.MultiError) as caught:
        await client_for(sender)(requests)
    assert cast(Any, caught.value).results == [result, None]
    assert sender.requests == requests
    assert clock.sleeps == []


@pytest.mark.parametrize(
    "error_class",
    [errors.PeerFloodError, errors.UserBannedInChannelError, errors.UserRestrictedError],
)
async def test_retry_still_reports_account_restrictions(clock: Clock, error_class: Any) -> None:
    request = functions.help.GetConfigRequest()
    sender = ScriptedSender(
        errors.FloodWaitError(request=request, capture=4), error_class(request=request)
    )
    client = client_for(sender)
    handler = AsyncMock()
    client.peer_flood_handler = handler
    client.spam_limit_suspect_handler = handler
    with pytest.raises(error_class):
        await client(request)
    handler.assert_awaited_once_with()


async def test_tool_and_activity_receive_only_final_success(
    clock: Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    channel = types.Channel(
        id=1,
        title="News",
        photo=types.ChatPhotoEmpty(),
        date=datetime.now(UTC),
        access_hash=1,
        broadcast=True,
    )
    discussion = types.Channel(
        id=2,
        title="Discussion",
        photo=types.ChatPhotoEmpty(),
        date=datetime.now(UTC),
        access_hash=2,
        megagroup=True,
    )
    sender = ScriptedSender(
        SimpleNamespace(full_chat=SimpleNamespace(linked_chat_id=2), chats=[discussion]),
        errors.FloodWaitError(request=None, capture=4),
        types.UpdatesTooLong(),
    )
    toolbox = TelegramToolbox(cast(Any, client_for(sender)))
    monkeypatch.setattr(toolbox, "_resolve_chat", AsyncMock(return_value=channel))
    monkeypatch.setattr(toolbox, "_newcomer_overview", AsyncMock(return_value=[]))
    recorder = ActivityRecorder(cast(Any, None))
    record = AsyncMock()
    monkeypatch.setattr(recorder, "record", record)
    middleware = ActivityMiddleware(agent_id=uuid4(), recorder=recorder)
    request = cast(
        Any,
        SimpleNamespace(
            tool_call={"name": "join_channel_discussion", "args": {"peer": "@news"}},
            runtime=SimpleNamespace(context=None),
        ),
    )
    waiting = asyncio.Event()
    resume = asyncio.Event()

    async def pause(seconds: float) -> None:
        waiting.set()
        await resume.wait()
        await clock.sleep(seconds)

    async def invoke(request: Any) -> ToolMessage:
        result = await toolbox.join_channel_discussion(request.tool_call["args"]["peer"])
        return ToolMessage(content=json.dumps(result), tool_call_id="call-1")

    monkeypatch.setattr("asyncio.sleep", pause)
    task = asyncio.create_task(middleware.awrap_tool_call(request, invoke))
    try:
        await asyncio.wait_for(waiting.wait(), timeout=2)
        assert not task.done()
        record.assert_not_awaited()
        resume.set()
        response = await asyncio.wait_for(task, timeout=2)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    result = json.loads(response.content)
    assert result["success"] is True
    assert result["linked_chat_id"] == -1000000000002
    assert "retry_after_seconds" not in result
    assert len(sender.requests) == 3
    assert isinstance(sender.requests[0], functions.channels.GetFullChannelRequest)
    assert isinstance(sender.requests[1], functions.channels.JoinChannelRequest)
    assert sender.requests[2] is sender.requests[1]
    assert record.await_count == 1
    assert record.await_args is not None
    assert record.await_args.kwargs["status"] == "succeeded"
    assert record.await_args.kwargs["error"] is None
    assert clock.sleeps == [4]
