"""Обвязка проверки поведения на живой модели.

Берётся самая слабая модель каталога: интересен худший сценарий, а не лучший.
Переопределяется переменной MIMIC_WEAK_MODEL.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
# Как и в real_tg: боевой .env грузится поверх тестовых переопределений.
load_dotenv(ROOT / ".env", override=True)

WEAK_MODEL = os.environ.get("MIMIC_WEAK_MODEL", "inclusionai/ling-3.0-flash-vl")


@pytest.fixture(scope="session")
def weak_model() -> str:
    if not os.environ.get("OPENROUTER_API_KEY"):
        pytest.skip("OPENROUTER_API_KEY не задан")
    return WEAK_MODEL
