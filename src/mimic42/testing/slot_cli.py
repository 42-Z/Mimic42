"""CLI для Playwright global-setup/global-teardown: занять и освободить
слот тестовых аккаунтов, напечатать его описание в JSON.

Один и тот же питон-модуль — источник правды об аккаунтах и для pytest, и
для e2e, чтобы список пользователей не расходился по двум языкам.

Команды:
    acquire            занять свободный слот, напечатать его имя
    release <slot>     освободить слот
    describe <slot>    напечатать JSON-описание слота (персоны + пароль)
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
import sys

from mimic42.testing.slots import SLOTS, Slot, acquire_slot, release_slot


def _dsn() -> str:
    return os.environ["TEST_DATABASE_CONNECTION_STRING"]


def _find_slot(name: str) -> Slot:
    slot = next((item for item in SLOTS if item.name == name), None)
    if slot is None:
        raise SystemExit(f"Неизвестный слот: {name}")
    return slot


async def _acquire() -> None:
    holder = f"{socket.gethostname()}:{os.getpid()}:e2e"
    slot = await acquire_slot(_dsn(), holder=holder)
    print(slot.name)


async def _release(name: str) -> None:
    await release_slot(_dsn(), _find_slot(name))


def _describe(name: str) -> None:
    slot = _find_slot(name)
    payload = {
        "slot": slot.name,
        "password": os.environ.get("TEST_USER_PASSWORD", ""),
        "personas": [
            {"key": persona.key, "id": str(persona.user_id), "email": persona.email}
            for persona in slot.personas
        ],
    }
    print(json.dumps(payload, ensure_ascii=False))


def main(argv: list[str]) -> int:
    if not argv:
        raise SystemExit("Использование: slot_cli acquire | release <slot> | describe <slot>")
    command = argv[0]
    if command == "acquire":
        asyncio.run(_acquire())
    elif command == "release":
        if len(argv) < 2 or not argv[1]:
            raise SystemExit("release требует имя слота")
        asyncio.run(_release(argv[1]))
    elif command == "describe":
        if len(argv) < 2 or not argv[1]:
            raise SystemExit("describe требует имя слота")
        _describe(argv[1])
    else:
        raise SystemExit(f"Неизвестная команда: {command}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
