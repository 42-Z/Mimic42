"""Обвязка проверки поведения на живой модели.

Берётся самая слабая модель каталога: интересен худший сценарий, а не лучший.
Переопределяется переменной MIMIC_WEAK_MODEL.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_WEAK_MODEL = "inclusionai/ling-3.0-flash-vl"


@pytest.fixture(scope="session")
def weak_model() -> Iterator[str]:
    """Боевой .env подмешивается только на время этого слоя.

    На уровне модуля его нельзя грузить: conftest импортируется при сборке любого
    прогона pytest, и остальные тесты получили бы боевые переменные."""
    values = {k: v for k, v in dotenv_values(ROOT / ".env").items() if v is not None}
    saved = {name: os.environ.get(name) for name in values}
    os.environ.update(values)
    try:
        if not os.environ.get("OPENROUTER_API_KEY"):
            pytest.skip("OPENROUTER_API_KEY не задан")
        yield os.environ.get("MIMIC_WEAK_MODEL", DEFAULT_WEAK_MODEL)
    finally:
        for name, old in saved.items():
            if old is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = old
