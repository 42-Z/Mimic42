from __future__ import annotations

import pytest

from mimic42.config import Settings


def test_braintrust_settings_default_to_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BRAINTRUST_API_KEY", raising=False)
    monkeypatch.delenv("BRAINTRUST_PROJECT", raising=False)
    settings = Settings(_env_file=None)  # ty: ignore[unknown-argument]

    assert settings.braintrust_api_key is None
    assert settings.braintrust_project == "Mimic42"


def test_braintrust_settings_read_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BRAINTRUST_API_KEY", "bt-key")
    monkeypatch.setenv("BRAINTRUST_PROJECT", "Mimic42 Dev")
    settings = Settings(_env_file=None)  # ty: ignore[unknown-argument]

    assert settings.braintrust_api_key == "bt-key"
    assert settings.braintrust_project == "Mimic42 Dev"


def test_braintrust_settings_treat_empty_env_as_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    # .env.example отдаёт BRAINTRUST_API_KEY= (пустое значение): это должно
    # означать «не задано», а не пустую строку.
    monkeypatch.setenv("BRAINTRUST_API_KEY", "")
    monkeypatch.setenv("BRAINTRUST_PROJECT", "")
    settings = Settings(_env_file=None)  # ty: ignore[unknown-argument]

    assert settings.braintrust_api_key is None
    assert settings.braintrust_project == "Mimic42"


def test_braintrust_settings_populate_by_name(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BRAINTRUST_API_KEY", raising=False)
    monkeypatch.delenv("BRAINTRUST_PROJECT", raising=False)
    settings = Settings(
        braintrust_api_key="bt-key",
        braintrust_project="Mimic42 Dev",
        _env_file=None,  # ty: ignore[unknown-argument]
    )

    assert settings.braintrust_api_key == "bt-key"
    assert settings.braintrust_project == "Mimic42 Dev"
