from __future__ import annotations

from mimic42.core.media import safe_filename


def test_safe_filename_keeps_plain_names() -> None:
    assert safe_filename("photo.jpeg") == "photo.jpeg"
    assert safe_filename("report_final-2.pdf") == "report_final-2.pdf"


def test_safe_filename_replaces_url_delimiters() -> None:
    # `#`/`?` в пути обрезают URL у supabase-py, пробелы и юникод ломают запрос.
    assert safe_filename("photo #1?.jpeg") == "photo_1_.jpeg"
    assert safe_filename("протокол 2026.pdf") == "2026.pdf"
    assert safe_filename("a b/c\\d.txt") == "a_b_c_d.txt"


def test_safe_filename_strips_dot_segments() -> None:
    assert safe_filename("..") == "file"
    assert safe_filename("...jpeg") == "jpeg"
    assert safe_filename("") == "file"


def test_safe_filename_keeps_extension_when_truncating() -> None:
    long_name = "x" * 300 + ".jpeg"
    result = safe_filename(long_name)
    assert len(result) <= 120
    assert result.endswith(".jpeg")
