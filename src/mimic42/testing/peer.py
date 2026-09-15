"""Роль собеседника: то, чем тест разговаривает с Мимиком.

Тесты пишутся против этого интерфейса, а не против подделки напрямую.
Когда появится живая телега, рядом встанет реализация поверх второго
настоящего аккаунта, и тесты менять не придётся.
"""

from __future__ import annotations

import asyncio
from typing import Protocol

from mimic42.testing.telegram import FakeTelegramAccount


class ConversationPeer(Protocol):
    async def send(self, text: str) -> None: ...

    async def wait_for_reply(self, timeout: float = 30.0) -> str: ...

    async def history(self) -> list[str]: ...

    async def was_read(self) -> bool: ...


class FakePeer:
    def __init__(self, account: FakeTelegramAccount, chat_id: int) -> None:
        self._account = account
        self._chat_id = chat_id
        self._seen_replies = 0

    async def send(self, text: str) -> None:
        await self._account.deliver(chat_id=self._chat_id, text=text)

    async def wait_for_reply(self, timeout: float = 30.0) -> str:
        # Дефолт с запасом: рантайм отвечает не мгновенно — перед отправкой
        # он выдерживает человекоподобную паузу печати (до 15 секунд).
        deadline = asyncio.get_running_loop().time() + timeout
        while asyncio.get_running_loop().time() < deadline:
            replies = self._replies()
            if len(replies) > self._seen_replies:
                self._seen_replies += 1
                return replies[self._seen_replies - 1]
            await asyncio.sleep(0.05)
        raise TimeoutError(f"Ответ не пришёл за {timeout} секунд")

    async def history(self) -> list[str]:
        events = [
            (message.order, message.text)
            for message in self._account.incoming
            if message.chat_id == self._chat_id
        ]
        events.extend(
            (message.order, message.text)
            for message in self._account.sent
            if message.chat_id == str(self._chat_id)
        )
        return [text for _, text in sorted(events)]

    async def was_read(self) -> bool:
        return str(self._chat_id) in self._account.read_marks

    def _replies(self) -> list[str]:
        return [
            message.text for message in self._account.sent if message.chat_id == str(self._chat_id)
        ]
