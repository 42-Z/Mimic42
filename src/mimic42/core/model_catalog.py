"""Catalog of the model switcher menu (issue #46)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelSpec:
    """One entry of the model switcher menu."""

    slug: str
    name: str
    free_slug: str | None = None
    """OpenRouter ``:free`` variant, if the model has one."""


MODEL_CATALOG: dict[str, ModelSpec] = {
    spec.slug: spec
    for spec in (
        ModelSpec(slug="z-ai/glm-5.3-flash", name="GLM 5.3 Flash"),
        ModelSpec(slug="deepseek/deepseek-v4-flash-0731", name="DeepSeek V4 Flash 0731"),
        ModelSpec(
            slug="inclusionai/ling-3.0-flash-vl",
            name="Ling 3.0 Flash VL",
            free_slug="inclusionai/ling-3.0-flash-vl:free",
        ),
        ModelSpec(slug="meituan/longcat-2.0", name="Longcat 2.0"),
        ModelSpec(
            slug="poolside/laguna-s-2.1",
            name="Laguna S 2.1",
            free_slug="poolside/laguna-s-2.1:free",
        ),
    )
}

DEFAULT_LLM_MODEL = "z-ai/glm-5.3-flash"


def resolve_model_chain(slug: str) -> list[str]:
    """Return OpenRouter model IDs in priority order for ``slug``.

    Catalog models with a free variant resolve to ``[free, paid]`` so
    OpenRouter serves the free variant first and automatically falls back to
    the paid one when the free rate limit is exhausted (the ``models``
    request parameter retries the next entry on 429 and other errors).
    Unknown slugs pass through unchanged so legacy agent settings keep
    working.
    """
    spec = MODEL_CATALOG.get(slug)
    if spec is None or spec.free_slug is None:
        return [slug]
    return [spec.free_slug, spec.slug]
