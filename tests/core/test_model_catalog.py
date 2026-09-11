from __future__ import annotations

from mimic42.core.model_catalog import (
    DEFAULT_LLM_MODEL,
    MODEL_CATALOG,
    resolve_model_chain,
)


def test_catalog_contains_exactly_menu_models() -> None:
    assert set(MODEL_CATALOG) == {
        "z-ai/glm-5.3-flash",
        "deepseek/deepseek-v4-flash-0731",
        "inclusionai/ling-3.0-flash-vl",
        "meituan/longcat-2.0",
        "poolside/laguna-s-2.1",
    }


def test_default_model_is_in_catalog() -> None:
    assert DEFAULT_LLM_MODEL in MODEL_CATALOG


def test_free_chain_is_free_then_paid() -> None:
    assert resolve_model_chain("poolside/laguna-s-2.1") == [
        "poolside/laguna-s-2.1:free",
        "poolside/laguna-s-2.1",
    ]
    assert resolve_model_chain("inclusionai/ling-3.0-flash-vl") == [
        "inclusionai/ling-3.0-flash-vl:free",
        "inclusionai/ling-3.0-flash-vl",
    ]


def test_models_without_free_variant_resolve_to_single_slug() -> None:
    assert resolve_model_chain("z-ai/glm-5.3-flash") == ["z-ai/glm-5.3-flash"]
    assert resolve_model_chain("deepseek/deepseek-v4-flash-0731") == [
        "deepseek/deepseek-v4-flash-0731"
    ]
    assert resolve_model_chain("meituan/longcat-2.0") == ["meituan/longcat-2.0"]


def test_unknown_slug_passes_through() -> None:
    assert resolve_model_chain("google/gemini-3.1-flash-lite") == ["google/gemini-3.1-flash-lite"]
