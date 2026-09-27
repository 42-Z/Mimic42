from __future__ import annotations

from typing import Any

import pytest

from mimic42.config import Settings


def _settings(**kwargs: Any) -> Settings:
    return Settings(_env_file=None, **kwargs)  # ty: ignore[unknown-argument]


def test_braintrust_settings_default_to_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BRAINTRUST_API_KEY", raising=False)
    monkeypatch.delenv("BRAINTRUST_PROJECT", raising=False)
    settings = _settings()

    assert settings.braintrust_api_key is None
    assert settings.braintrust_project == "Mimic42"


def test_braintrust_settings_read_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BRAINTRUST_API_KEY", "bt-key")
    monkeypatch.setenv("BRAINTRUST_PROJECT", "Mimic42 Dev")
    settings = _settings()

    assert settings.braintrust_api_key == "bt-key"
    assert settings.braintrust_project == "Mimic42 Dev"


def test_braintrust_settings_treat_empty_env_as_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    # .env.example отдаёт BRAINTRUST_API_KEY= (пустое значение): это должно
    # означать «не задано», а не пустую строку.
    monkeypatch.setenv("BRAINTRUST_API_KEY", "")
    monkeypatch.setenv("BRAINTRUST_PROJECT", "")
    settings = _settings()

    assert settings.braintrust_api_key is None
    assert settings.braintrust_project == "Mimic42"


def test_braintrust_settings_populate_by_name(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BRAINTRUST_API_KEY", raising=False)
    monkeypatch.delenv("BRAINTRUST_PROJECT", raising=False)
    settings = _settings(
        braintrust_api_key="bt-key",
        braintrust_project="Mimic42 Dev",
    )

    assert settings.braintrust_api_key == "bt-key"
    assert settings.braintrust_project == "Mimic42 Dev"
