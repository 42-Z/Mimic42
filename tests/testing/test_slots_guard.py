from __future__ import annotations

import pytest

from mimic42.testing.slots import PROD_PROJECT_REF, assert_not_prod


def test_assert_not_prod_allows_dev_values() -> None:
    assert_not_prod("postgresql://user:pw@db.ipqylrdmmjitemjrygej.supabase.co:5432/postgres")
    assert_not_prod("https://ipqylrdmmjitemjrygej.supabase.co")
    assert_not_prod(None, None)


def test_assert_not_prod_rejects_prod_dsn() -> None:
    with pytest.raises(RuntimeError, match="прод"):
        assert_not_prod(f"postgresql://user:pw@db.{PROD_PROJECT_REF}.supabase.co:5432/postgres")


def test_assert_not_prod_rejects_prod_supabase_url() -> None:
    with pytest.raises(RuntimeError, match="прод"):
        assert_not_prod(None, f"https://{PROD_PROJECT_REF}.supabase.co")
