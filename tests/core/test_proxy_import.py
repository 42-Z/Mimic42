from __future__ import annotations

from mimic42.core.proxy_import import parse_proxy_file


def test_parses_webshare_style_lines_and_skips_duplicates() -> None:
    result = parse_proxy_file(
        "\r\n".join(
            [
                "1.2.3.4:1080:user:pass",
                "5.6.7.8:3128",
                "",
                "# comment",
                "1.2.3.4:1080:user:pass",
                "broken",
                "9.9.9.9:0:user:pass",
            ]
        )
    )

    assert [
        (entry.host, entry.port, entry.username, entry.password) for entry in result.entries
    ] == [
        ("1.2.3.4", 1080, "user", "pass"),
        ("5.6.7.8", 3128, None, None),
    ]
    assert result.skipped == 1
    assert len(result.errors) == 2
    assert "Строка 6" in result.errors[0]
    assert "Строка 7" in result.errors[1]


def test_parses_socks5_and_http_urls_with_encoded_credentials() -> None:
    result = parse_proxy_file(
        "\n".join(
            [
                "socks5://user%40name:p%40ss@proxy.example.test:1080",
                "http://proxy.example.test:3128",
            ]
        )
    )

    assert len(result.errors) == 0
    assert result.entries[0].protocol == "socks5"
    assert result.entries[0].username == "user@name"
    assert result.entries[0].password == "p@ss"
    assert result.entries[1].protocol == "http"
    assert result.entries[1].username is None


def test_default_protocol_applies_to_plain_lines() -> None:
    result = parse_proxy_file("proxy.example.test:1080", "http")

    assert result.entries[0].protocol == "http"


def test_password_without_username_is_rejected() -> None:
    result = parse_proxy_file("proxy.example.test:1080::secret")

    assert result.entries == []
    assert result.errors == ["Строка 1: Для пароля укажите логин прокси"]


def test_empty_file_reports_an_error() -> None:
    result = parse_proxy_file("\n\n# only comments\n")

    assert result.entries == []
    assert result.errors == ["Файл не содержит прокси"]
