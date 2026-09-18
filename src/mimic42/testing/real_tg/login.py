"""Одноразовый вход для session string проверяющего.

    uv run python -m mimic42.testing.real_tg.login

Креды берутся из `.env`/`.env.test` (TG_CHECKER_API_ID/HASH), интерактивно
спрашиваются телефон, код из SMS и 2FA-пароль; session string сохраняется
в `TG_CHECKER_SESSION` строку `.env.test` и не печатается в логи. Использует
`with client` → start(): интерактивный поток по документации Telethon.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import cast

from telethon import TelegramClient
from telethon.sessions import StringSession

from mimic42.testing.env import load_test_env

REPO_ROOT = Path(__file__).resolve().parents[4]
ENV_TEST = REPO_ROOT / ".env.test"


def _save_session(session_string: str) -> None:
    lines: list[str] = []
    if ENV_TEST.exists():
        lines = [
            line
            for line in ENV_TEST.read_text().splitlines()
            if not line.startswith("TG_CHECKER_SESSION=")
        ]
    lines.append(f"TG_CHECKER_SESSION={session_string}")
    ENV_TEST.write_text("\n".join(lines) + "\n")


def main() -> None:
    load_test_env()
    api_id = os.environ.get("TG_CHECKER_API_ID")
    api_hash = os.environ.get("TG_CHECKER_API_HASH")
    if not api_id or not api_hash:
        sys.exit("TG_CHECKER_API_ID / TG_CHECKER_API_HASH не заданы (см. .env.example)")
    client = TelegramClient(StringSession(), int(api_id), api_hash)
    with client:
        session = cast(StringSession, client.session)
        _save_session(session.save())
    print(f"TG_CHECKER_SESSION сохранён в {ENV_TEST}")


if __name__ == "__main__":
    main()
