"""Одноразовый вход для session string проверяющего.

    TG_CHECKER_API_ID=... TG_CHECKER_API_HASH=... uv run python -m mimic42.testing.real_tg.login

Интерактивно спросит телефон, код (из SMS) и 2FA-пароль, затем напечатает
session string — вставь её в TG_CHECKER_SESSION (.env.test). Использует
`with client` → start(): интерактивный поток по документации Telethon.
"""

from __future__ import annotations

import os
import sys
from typing import cast

from telethon import TelegramClient
from telethon.sessions import StringSession


def main() -> None:
    api_id = os.environ.get("TG_CHECKER_API_ID")
    api_hash = os.environ.get("TG_CHECKER_API_HASH")
    if not api_id or not api_hash:
        sys.exit("TG_CHECKER_API_ID / TG_CHECKER_API_HASH не заданы (см. .env.example)")
    client = TelegramClient(StringSession(), int(api_id), api_hash)
    with client:
        session = cast(StringSession, client.session)
        print("\nTG_CHECKER_SESSION=")
        print(session.save())


if __name__ == "__main__":
    main()
