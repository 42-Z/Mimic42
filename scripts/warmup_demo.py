"""Живая проверка прогрева: два агента, один терминал, без базы и дашборда.

    uv run python scripts/warmup_demo.py

Скрипт сам спросит всё нужное: ключи Telegram-приложения, вход в два аккаунта
(телефон → код → пароль 2FA, если есть) и, по желанию, ключ OpenRouter. Затем
поднимает двух агентов, один пишет другому зачин из базы прогрева, и они
переписываются до конца диалога. Все сообщения печатаются в терминал.

Сессии и ключи сохраняются в sessions/warmup_demo.json (папка в .gitignore),
чтобы в следующий раз не вводить код заново. Ничего не отправляется в репозиторий.

Без ключа OpenRouter агенты отвечают заготовленными фразами: проверяется
механика прогрева, но не живость ответов.
"""

from __future__ import annotations

import asyncio
import getpass
import json
import logging
import os
import random
import sys
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

from telethon import TelegramClient, events, functions
from telethon.errors import SessionPasswordNeededError
from telethon.sessions import StringSession

from mimic42.core.agent_runtime import (
    AgentRuntimeConfig,
    LangChainAgentLike,
    MimicAgentRuntime,
    TelegramClientLike,
)
from mimic42.core.memory import RuntimeMemoryService
from mimic42.core.send_window import SendWindowTracker
from mimic42.core.warmup import WarmupSettings
from mimic42.core.warmup_service import WarmupService
from mimic42.integrations.langchain_agent import build_langchain_agent
from mimic42.integrations.telegram_tools import (
    CustomMarkdown,
    TelethonRequestClient,
    build_telegram_langchain_tools,
)

STORE = Path(__file__).resolve().parent.parent / "sessions" / "warmup_demo.json"
BASE_PROMPT = (
    "Ты {{name}}, живой человек в Telegram, не ассистент и не бот. Отвечай коротко, как в "
    "переписке со знакомым: одна-две строки, без списков, без вопросов в каждом сообщении. "
    "Никогда не говори, что ты ИИ."
)
CANNED_REPLIES = (
    "да нормально, ты как?",
    "ха, понимаю тебя",
    "ну такое, честно говоря",
    "о, интересно, расскажи",
    "согласен, бывает",
    "ладно, потом дособеседуем",
)
IDLE_STOP_SECONDS = 240
# В демо ответы приходят через 5–40 секунд, чтобы не ждать десятки минут.
DEMO_REPLY_DELAY = (5.0, 40.0)


def ask(prompt: str, *, secret: bool = False, default: str | None = None) -> str:
    suffix = f" [{default}]" if default else ""
    while True:
        raw = (getpass.getpass if secret else input)(f"{prompt}{suffix}: ").strip()
        if raw:
            return raw
        if default is not None:
            return default


def load_store() -> dict[str, Any]:
    try:
        return json.loads(STORE.read_text())
    except (OSError, ValueError):
        return {}


def save_store(data: dict[str, Any]) -> None:
    STORE.parent.mkdir(parents=True, exist_ok=True)
    STORE.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    STORE.chmod(0o600)


def new_client(session: str, api_id: int, api_hash: str) -> TelegramClient:
    # Как в build_telegram_client: SlowModeWait не должен усыплять отправку внутри клиента.
    client = TelegramClient(StringSession(session), api_id, api_hash, flood_sleep_threshold=0)
    client.parse_mode = cast(Any, CustomMarkdown())
    return client


async def login(slot: int, api_id: int, api_hash: str, saved: str | None) -> str:
    """Войти в аккаунт и вернуть строку сессии."""
    client = new_client(saved or "", api_id, api_hash)
    await client.connect()
    try:
        if await client.is_user_authorized():
            return cast(str, client.session.save())
        print(f"\n── Аккаунт {slot}: вход ──")
        phone = ask("Номер телефона (с +, например +79991234567)")
        await client.send_code_request(phone)
        code = ask("Код из Telegram")
        try:
            await client.sign_in(phone, code)
        except SessionPasswordNeededError:
            await client.sign_in(password=ask("Пароль 2FA", secret=True))
        return cast(str, client.session.save())
    finally:
        await client.disconnect()


class DemoShortTerm:
    """Короткая память в оперативке: диалог связный, но живёт до конца скрипта."""

    def __init__(self) -> None:
        self._rows: dict[tuple[UUID, str], list[dict[str, Any]]] = {}

    async def load_recent_messages(
        self, *, agent_id: UUID, peer: str, since: datetime
    ) -> list[dict[str, Any]]:
        return list(self._rows.get((agent_id, peer), []))

    async def save_messages(
        self,
        *,
        agent_id: UUID,
        peer: str,
        messages: list[dict[str, Any]],
        structured_response: dict[str, Any] | None = None,
        raw_user_text: str = "",
        **_: Any,
    ) -> None:
        rows = self._rows.setdefault((agent_id, peer), [])
        if raw_user_text:
            rows.append({"type": "human", "role": "user", "content": raw_user_text})
        for message in messages:
            role = str(message.get("role", message.get("type", "")))
            if role in ("ai", "assistant"):
                content = message.get("content") or (structured_response or {}).get("text", "")
                if content:
                    rows.append({"type": "ai", "role": "assistant", "content": content})


class CannedAgent:
    """Запасной «мозг» без LLM: отвечает по кругу заготовками."""

    def __init__(self) -> None:
        self._rng = random.Random()

    async def ainvoke(
        self, input_data: dict[str, object], context: object | None = None
    ) -> dict[str, object]:
        text = self._rng.choice(CANNED_REPLIES)
        return {
            "messages": [{"role": "assistant", "content": text}],
            "structured_response": {"text": text, "send_any_message": True, "reply_to": None},
        }


class DemoHistory:
    def __init__(self) -> None:
        self.openers: list[str] = []

    async def attempts_since(self, agent_id: UUID, since: datetime) -> int:
        return 0

    async def used_openers(self, agent_id: UUID) -> list[str]:
        return list(self.openers)

    async def recent_partners(self, agent_id: UUID) -> list[UUID]:
        return []


def build_runtime(
    *,
    name: str,
    client: TelegramClient,
    api_id: int,
    api_hash: str,
    use_llm: bool,
    short_term: DemoShortTerm,
) -> MimicAgentRuntime:
    config = AgentRuntimeConfig(
        agent_id=uuid4(),
        owner_id=uuid4(),
        telegram_api_id=api_id,
        telegram_api_hash=api_hash,
        system_prompt=BASE_PROMPT,
        name=name,
        warmup=WarmupSettings(enabled=True),
    )
    send_window = SendWindowTracker(cast(TelegramClientLike, client))
    brain: LangChainAgentLike
    if use_llm:
        tools = build_telegram_langchain_tools(
            cast(TelethonRequestClient, client), agent_id=config.agent_id, send_window=send_window
        )
        brain = build_langchain_agent(config, tools=tools)
    else:
        brain = cast(LangChainAgentLike, CannedAgent())
    return MimicAgentRuntime(
        config=config,
        telegram_client=cast(TelegramClientLike, client),
        langchain_agent=brain,
        memory_service=RuntimeMemoryService(short_term=short_term),
        send_window=send_window,
    )


def watch(client: TelegramClient, label: str, other: Callable[[], str]) -> None:
    """Печатать каждое сообщение этого аккаунта в терминал."""

    async def on_message(event: Any) -> None:
        if not event.is_private:
            return
        stamp = datetime.now().strftime("%H:%M:%S")
        if event.out:
            print(f"[{stamp}] {label} → {other()}: {event.raw_text}", flush=True)

    client.add_event_handler(on_message, events.NewMessage(outgoing=True))


async def add_each_other_as_contacts(
    clients: list[TelegramClient], runtimes: list[MimicAgentRuntime]
) -> None:
    """Взаимно добавить аккаунты в контакты.

    Telegram режет новые аккаунты, которые пишут незнакомым (PeerFloodError), а
    знакомым из контактов — нет. Живые люди тоже сначала сохраняют друг друга.
    """
    for me, other in ((0, 1), (1, 0)):
        try:
            other_user = await clients[other].get_me()
            await clients[me](
                functions.contacts.AddContactRequest(
                    id=f"@{runtimes[other].telegram_username}",
                    first_name=runtimes[other].config.name,
                    last_name="",
                    phone=str(getattr(other_user, "phone", "") or ""),
                )
            )
            print(
                f"{runtimes[me].config.name}: {runtimes[other].config.name} добавлен(а) в контакты"
            )
        except Exception as exc:
            print(f"Не удалось добавить в контакты ({type(exc).__name__}): {exc}")


async def main() -> None:
    logging.basicConfig(level=logging.WARNING)
    logging.getLogger("mimic42.warmup").setLevel(logging.INFO)
    store = load_store()

    print("Живая проверка прогрева: два аккаунта пишут друг другу.\n")
    print("Нужны api_id и api_hash Telegram-приложения (my.telegram.org → API development tools).")
    api_id = int(store.get("api_id") or ask("api_id"))
    api_hash = store.get("api_hash") or ask("api_hash")
    store.update(api_id=api_id, api_hash=api_hash)
    save_store(store)

    openrouter = os.environ.get("OPENROUTER_API_KEY") or store.get("openrouter_key")
    if not openrouter:
        raw = input(
            "\nКлюч OpenRouter для живых ответов (Enter — без LLM, ответы-заготовки): "
        ).strip()
        openrouter = raw or None
    if openrouter:
        os.environ["OPENROUTER_API_KEY"] = openrouter
        store["openrouter_key"] = openrouter
        save_store(store)

    sessions: list[str] = store.get("sessions", [None, None])
    for slot in (1, 2):
        sessions[slot - 1] = await login(slot, api_id, api_hash, sessions[slot - 1])
        store["sessions"] = sessions
        save_store(store)

    clients = [new_client(s, api_id, api_hash) for s in sessions]
    short_term = DemoShortTerm()
    runtimes = [
        build_runtime(
            name=name,
            client=client,
            api_id=api_id,
            api_hash=api_hash,
            use_llm=bool(openrouter),
            short_term=short_term,
        )
        for name, client in zip(("Аня", "Макс"), clients, strict=True)
    ]
    for runtime in runtimes:
        await runtime.start()

    for index, runtime in enumerate(runtimes, start=1):
        if not runtime.telegram_username:
            print(
                f"\nУ аккаунта {index} нет @username. Задай его в Telegram "
                "(Настройки → Имя пользователя) и запусти скрипт заново."
            )
            await asyncio.gather(*(r.close() for r in runtimes))
            sys.exit(1)

    names = [f"{r.config.name} (@{r.telegram_username})" for r in runtimes]
    print(f"\nАгенты запущены: {names[0]} и {names[1]}")
    watch(clients[0], runtimes[0].config.name, lambda: runtimes[1].config.name)
    watch(clients[1], runtimes[1].config.name, lambda: runtimes[0].config.name)

    await add_each_other_as_contacts(clients, runtimes)

    history = DemoHistory()
    service = WarmupService(
        lambda: runtimes, history, delay=lambda: random.uniform(*DEMO_REPLY_DELAY)
    )
    for runtime in runtimes:
        runtime.set_warmup_gate(service)

    starter, _ = random.sample(runtimes, 2)
    print(f"Диалог начинает {starter.config.name}. Остановить — Ctrl+C.\n")
    sent = await service.start_dialog(starter, runtimes)
    if not sent:
        print(
            "Зачин не отправился, смотри ошибку выше.\n"
            "Если там PeerFloodError — Telegram ограничил аккаунт-отправитель за рассылку "
            "незнакомым. Открой @SpamBot с него и нажми /start: бот скажет, есть ли "
            "ограничение и до какого числа. Пока оно действует, этот аккаунт писать "
            "первым не сможет; можно запустить скрипт ещё раз позже или начать диалог "
            "с другого аккаунта."
        )
    else:
        # Ждём, пока диалог не затихнет: сам он заканчивается по длине, а не по таймеру.
        last_count = -1
        idle = 0
        while idle < IDLE_STOP_SECONDS:
            await asyncio.sleep(5)
            total = sum(len(v) for v in short_term._rows.values())
            idle = idle + 5 if total == last_count else 0
            last_count = total
        print("\nДиалог закончился (тишина больше 4 минут).")

    await asyncio.gather(*(r.close() for r in runtimes), return_exceptions=True)
    print(f"Готово. Сессии сохранены в {STORE}, при повторном запуске вводить код не придётся.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nОстановлено.")
