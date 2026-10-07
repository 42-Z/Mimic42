"""Правило доступа к чатам: отключённые, комментарии, терпимый разбор."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from mimic42.core.chat_access import (
    ChatAccess,
    ChatDisabledError,
    link_hint,
    parse_disabled_chats,
)

CHANNEL = -1001111111111
GROUP = -1002222222222
OTHER_GROUP = -1003333333333


def _access(
    disabled: set[int], links: dict[int, int | None] | None = None
) -> tuple[ChatAccess, list[int]]:
    calls: list[int] = []

    async def discussion_of(chat_id: int) -> int | None:
        calls.append(chat_id)
        return (links or {}).get(chat_id)

    return ChatAccess(frozenset(disabled), discussion_of), calls


def test_missing_key_disables_nothing() -> None:
    assert parse_disabled_chats(None) == frozenset()


def test_list_of_ids_becomes_the_disabled_set() -> None:
    assert parse_disabled_chats([CHANNEL, 42, -7]) == frozenset({CHANNEL, 42, -7})


def test_garbage_items_are_dropped() -> None:
    # bool — подкласс int: «true» из ручной правки JSON не должен стать ID 1.
    assert parse_disabled_chats([CHANNEL, True, "42", 1.5, None]) == frozenset({CHANNEL})


def test_unexpected_type_disables_nothing() -> None:
    assert parse_disabled_chats({"id": CHANNEL}) == frozenset()
    assert parse_disabled_chats("42") == frozenset()


def test_link_hint_trusts_only_real_booleans() -> None:
    assert link_hint(SimpleNamespace(has_link=True)) is True
    assert link_hint(SimpleNamespace(has_link=False)) is False
    assert link_hint(SimpleNamespace(has_link=None)) is None
    assert link_hint(SimpleNamespace()) is None
    assert link_hint(SimpleNamespace(has_link=object())) is None


def test_disabled_error_tells_the_model_why() -> None:
    error = ChatDisabledError(42)
    assert error.chat_id == 42
    assert "отключён в настройках агента" in str(error)
    assert ChatDisabledError().chat_id is None


@pytest.mark.asyncio
async def test_chats_are_available_by_default() -> None:
    access, calls = _access({42})
    assert await access.allows(7) is True
    assert await access.allows(CHANNEL) is True
    assert calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("chat_id", [42, -777, CHANNEL])
async def test_disabled_private_basic_and_channel_chats_are_refused(chat_id: int) -> None:
    access, _ = _access({chat_id})
    assert await access.allows(chat_id) is False


@pytest.mark.asyncio
async def test_no_lookup_for_chats_that_cannot_be_discussion_groups() -> None:
    access, calls = _access({42, -777})
    await access.allows(42)
    await access.allows(-777)
    assert calls == []


@pytest.mark.asyncio
async def test_discussion_group_of_an_enabled_channel_is_available() -> None:
    access, calls = _access({GROUP}, {GROUP: CHANNEL})
    assert await access.allows(GROUP) is True
    assert calls == [GROUP]


@pytest.mark.asyncio
async def test_discussion_group_of_a_disabled_channel_is_refused() -> None:
    access, _ = _access({GROUP, CHANNEL}, {GROUP: CHANNEL})
    assert await access.allows(GROUP) is False


@pytest.mark.asyncio
async def test_disabled_supergroup_without_a_channel_is_refused() -> None:
    access, _ = _access({OTHER_GROUP}, {OTHER_GROUP: None})
    assert await access.allows(OTHER_GROUP) is False


@pytest.mark.asyncio
async def test_entity_without_a_link_skips_the_lookup() -> None:
    access, calls = _access({GROUP}, {GROUP: CHANNEL})
    assert await access.allows(GROUP, has_link=False) is False
    assert calls == []
    assert await access.allows(GROUP, has_link=True) is True


@pytest.mark.asyncio
async def test_lookup_failure_closes_the_chat() -> None:
    attempts = 0

    async def failing(chat_id: int) -> int | None:
        nonlocal attempts
        attempts += 1
        raise RuntimeError("FLOOD_WAIT")

    access = ChatAccess(frozenset({GROUP}), failing)

    assert await access.allows(GROUP) is False
    # Неудача не запоминается: следующая проверка пробует снова.
    assert await access.allows(GROUP) is False
    assert attempts == 2
