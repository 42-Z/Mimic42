from __future__ import annotations

from typing import Any

from mimic42.integrations.activity_middleware import _sanitize_result


def test_data_urls_are_replaced_with_marker() -> None:
    result: dict[str, Any] = {
        "items": [
            {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + "A" * 500}},
            {"type": "media_ref", "storage_path": "ag/1/x.jpeg"},
        ]
    }

    cleaned = _sanitize_result(result)

    assert cleaned is not None
    item = cleaned["items"][0]
    assert "_omitted" in item["image_url"]["url"]
    assert cleaned["items"][1] == {"type": "media_ref", "storage_path": "ag/1/x.jpeg"}


def test_short_strings_and_non_base64_are_kept() -> None:
    result: dict[str, Any] = {"text": "привет", "small": "data:x"}

    assert _sanitize_result(result) == result


def test_none_result_stays_none() -> None:
    assert _sanitize_result(None) is None
