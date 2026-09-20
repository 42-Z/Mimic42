"""Запуск тестовых серверов процесс-группами.

`terminate()` шлёт SIGTERM только процессу-обёртке (`uv run`, `bun run`), а
её дети (uvicorn, next dev) переживают это и остаются висеть на портах —
следующий прогон молча тестирует чужой/устаревший сервер. Поэтому серверы
стартуют в отдельной сессии и убиваются всей группой.
"""

from __future__ import annotations

import os
import signal
import socket
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path

SHUTDOWN_TIMEOUT_SECONDS = 30


def spawn(
    command: Sequence[str],
    *,
    cwd: Path,
    env: Mapping[str, str] | None = None,
) -> subprocess.Popen[bytes]:
    return subprocess.Popen(
        command,
        cwd=cwd,
        env=dict(env) if env is not None else None,
        start_new_session=True,
    )


def terminate(proc: subprocess.Popen[bytes]) -> None:
    if proc.poll() is not None:
        return
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        proc.wait(timeout=SHUTDOWN_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        proc.wait(timeout=10)


def assert_port_free(port: int) -> None:
    """Порт обязан быть свободен: иначе тесты молча пойдут в чужой сервер."""
    with socket.socket() as sock:
        # Как у uvicorn и next: остатки прошлого прогона в TIME_WAIT порт не
        # занимают. Живой слушатель bind по-прежнему отвергает.
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("127.0.0.1", port))
        except OSError as exc:
            raise RuntimeError(
                f"порт {port} занят посторонним процессом: останови его "
                "или задай другой E2E_API_PORT/E2E_APP_PORT"
            ) from exc
