"""Загрузка локальных env-файлов для тестового слоя.

Приложение читает `.env` само (pydantic), а тестовый слой раньше рассчитывал на
ручной ``source .env.test``. Здесь этот порядок собран в одном месте, и правило
намеренно несимметричное:

- `.env` — база: не перетирает уже выставленные переменные окружения (так же
  ведёт себя Next: `process.env` в приоритете);
- `.env.test` — переопределения для тестов: перетирает всё, загруженное до него,
  — и значения из `.env`, и переменные окружения. Иначе тестовая заглушка не
  смогла бы уступить экспортированному в шелле значению.
"""

from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv

BASE_ENV_FILE = ".env"
TEST_ENV_FILE = ".env.test"

# src/mimic42/testing/env.py -> корень репозитория
REPO_ROOT = Path(__file__).resolve().parents[3]


def load_test_env(root: Path | None = None) -> list[Path]:
    """Загрузить `.env`, затем перекрывающий его `.env.test`.

    Возвращает список реально прочитанных файлов: в CI файлов нет и это не
    ошибка — значения приходят из секретов.
    """
    base = root if root is not None else REPO_ROOT
    loaded: list[Path] = []
    for name, override in ((BASE_ENV_FILE, False), (TEST_ENV_FILE, True)):
        path = base / name
        if path.is_file():
            load_dotenv(path, override=override)
            loaded.append(path)
    return loaded
