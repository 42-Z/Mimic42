from __future__ import annotations

import os
from pathlib import Path

import pytest

from mimic42.testing.env import load_test_env


def test_test_file_overrides_base(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / ".env").write_text("MIMIC42_PROBE=base\nMIMIC42_ONLY_BASE=base\n")
    (tmp_path / ".env.test").write_text("MIMIC42_PROBE=test\n")
    monkeypatch.delenv("MIMIC42_PROBE", raising=False)
    monkeypatch.delenv("MIMIC42_ONLY_BASE", raising=False)

    loaded = load_test_env(tmp_path)

    assert loaded == [tmp_path / ".env", tmp_path / ".env.test"]
    assert os.environ["MIMIC42_PROBE"] == "test"
    assert os.environ["MIMIC42_ONLY_BASE"] == "base"


def test_missing_files_are_not_an_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MIMIC42_PROBE", raising=False)
    assert load_test_env(tmp_path) == []
    assert "MIMIC42_PROBE" not in os.environ


def test_real_environment_wins_over_base_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / ".env").write_text("MIMIC42_PROBE=base\n")
    monkeypatch.setenv("MIMIC42_PROBE", "shell")

    load_test_env(tmp_path)

    assert os.environ["MIMIC42_PROBE"] == "shell"
