from __future__ import annotations

import base64
import json

import pytest

from mimic42.testing.slots import DEV_PROJECT_REF, PROD_PROJECT_REF, assert_test_project


def _jwt_with_ref(ref: str) -> str:
    def encode(payload: dict[str, str]) -> str:
        raw = json.dumps(payload, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    return f"{encode({'alg': 'HS256'})}.{encode({'ref': ref})}.signature"


def test_dev_values_are_allowed() -> None:
    assert_test_project("postgresql://user:pw@db.ipqylrdmmjitemjrygej.supabase.co:5432/postgres")
    assert_test_project("https://ipqylrdmmjitemjrygej.supabase.co")
    assert_test_project(_jwt_with_ref(DEV_PROJECT_REF))
    assert_test_project(None, None)


def test_prod_values_are_rejected() -> None:
    with pytest.raises(RuntimeError, match="прод"):
        assert_test_project(f"postgresql://user:pw@db.{PROD_PROJECT_REF}.supabase.co:5432/postgres")
    with pytest.raises(RuntimeError, match="прод"):
        assert_test_project(None, f"https://{PROD_PROJECT_REF}.supabase.co")
    with pytest.raises(RuntimeError, match="прод"):
        assert_test_project(_jwt_with_ref(PROD_PROJECT_REF))


def test_values_without_a_project_ref_are_rejected() -> None:
    # Allowlist, а не denylist: чужой адрес без рефа Dev не проходит, даже
    # если в нём нет рефа прода — IP-литерал, кастомный домен, чужой ключ.
    with pytest.raises(RuntimeError, match="не опознано"):
        assert_test_project("postgresql://user:pw@10.0.0.5:5432/postgres")
    with pytest.raises(RuntimeError, match="не опознано"):
        assert_test_project("https://supabase.example.com")
    with pytest.raises(RuntimeError, match="не опознано"):
        assert_test_project(_jwt_with_ref("someoneelsesproject"))
