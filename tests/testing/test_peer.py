from __future__ import annotations

from typing import Any, cast

from telethon import functions

from mimic42.testing.peer import FakePeer
from mimic42.testing.telegram import FakeTelegramAccount, FakeTelegramClient


async def test_peer_sends_and_waits_for_reply() -> None:
    account = FakeTelegramAccount()
    account.authorized = True
    peer = FakePeer(account, chat_id=42)

    await peer.send("привет")
    # Ответ появляется, когда агент кладёт сообщение в отправленные.
    await FakeTelegramClient(account).send_message("42", "привет, чем помочь")

    assert await peer.wait_for_reply(timeout=1.0) == "привет, чем помочь"
    assert await peer.history() == ["привет", "привет, чем помочь"]


async def test_read_mark_matches_the_peer_exactly() -> None:
    account = FakeTelegramAccount()
    account.authorized = True
    client = FakeTelegramClient(account)

    await client(functions.messages.ReadHistoryRequest(peer=cast(Any, 4242), max_id=1))

    assert await FakePeer(account, chat_id=42).was_read() is False
    assert await FakePeer(account, chat_id=4242).was_read() is True


async def test_read_mark_reads_the_id_out_of_a_peer_object() -> None:
    account = FakeTelegramAccount()
    account.authorized = True
    client = FakeTelegramClient(account)

    peer_object = type("Peer", (), {"user_id": 7})()
    await client(functions.messages.ReadHistoryRequest(peer=cast(Any, peer_object), max_id=1))

    assert await FakePeer(account, chat_id=7).was_read() is True
    assert await FakePeer(account, chat_id=70).was_read() is False


async def test_history_keeps_the_chronological_order() -> None:
    account = FakeTelegramAccount()
    account.authorized = True
    client = FakeTelegramClient(account)
    peer = FakePeer(account, chat_id=42)

    await peer.send("раз")
    await client.send_message("42", "два")
    await peer.send("три")
    await client.send_message("42", "четыре")

    assert await peer.history() == ["раз", "два", "три", "четыре"]
