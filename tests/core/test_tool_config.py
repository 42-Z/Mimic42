"""Разбор settings.enabled_tools: allowlist, который не роняет агента."""

from __future__ import annotations

from mimic42.core.tool_config import parse_enabled_tools


def test_missing_key_enables_all_tools() -> None:
    assert parse_enabled_tools(None) is None


def test_empty_list_is_an_empty_allowlist() -> None:
    assert parse_enabled_tools([]) == frozenset()


def test_list_of_names_becomes_allowlist() -> None:
    assert parse_enabled_tools(["send_text_message", " view_image "]) == frozenset(
        {"send_text_message", "view_image"}
    )


def test_non_string_items_are_dropped() -> None:
    assert parse_enabled_tools(["send_text_message", 42, None, ""]) == frozenset(
        {"send_text_message"}
    )


def test_list_without_valid_names_enables_all_tools() -> None:
    # Мусорный список не должен случайно выключить все инструменты.
    assert parse_enabled_tools([42, None, "  "]) is None


def test_unexpected_type_enables_all_tools() -> None:
    assert parse_enabled_tools({"send_text_message": True}) is None
