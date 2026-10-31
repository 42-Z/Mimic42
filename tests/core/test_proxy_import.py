from __future__ import annotations

import pytest

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


@pytest.mark.parametrize(
    "line",
    [
        pytest.param("socks5://user:review_secret#rest@proxy.example.test:1080", id="fragment"),
        pytest.param("http://user:review_secret?rest@proxy.example.test:3128", id="query"),
        pytest.param("socks5://user:review_secret/rest@proxy.example.test:1080", id="path"),
        pytest.param(
            "socks5://user:review_secret\uff03rest@proxy.example.test:1080", id="nfkc-password"
        ),
        pytest.param("socks5://user:review_secret@proxy\uff1a.example.test:1080", id="nfkc-host"),
        pytest.param("socks5://user:review_secret@[review_secret]:1080", id="bracketed-host"),
        pytest.param(
            "socks5://user:review_secret@[proxy.example.test:1080", id="unmatched-bracket"
        ),
    ],
)
def test_url_errors_never_echo_credentials_and_keep_line_numbers(line: str) -> None:
    result = parse_proxy_file(
        f"\n# comment\n{line}\nproxy.example.test:1080\nproxy.example.test:1080"
    )

    assert len(result.errors) == 1
    assert result.errors[0].startswith("Строка 3: ")
    assert "review_secret" not in result.errors[0]
    assert "rest" not in result.errors[0]
    assert len(result.entries) == 1
    assert result.entries[0].host == "proxy.example.test"
    assert result.skipped == 1


@pytest.mark.parametrize(
    ("line", "message"),
    [
        (
            "https://user:review_secret@proxy.example.test:1080",
            "Поддерживаются только SOCKS5 и HTTP",
        ),
        ("socks5:///", "Не указан адрес прокси"),
        ("socks5://proxy.example.test", "Не указан порт прокси"),
        ("socks5://proxy.example.test:0", "Порт прокси должен быть от 1 до 65535"),
        ("socks5://:review_secret@proxy.example.test:1080", "Для пароля укажите логин прокси"),
        ("proxy.example.test:review_secret:user:rest", "Порт прокси должен быть числом"),
    ],
)
def test_import_keeps_safe_validation_messages(line: str, message: str) -> None:
    result = parse_proxy_file(line)

    assert result.entries == []
    assert result.errors == [f"Строка 1: {message}"]


def test_parses_socks5h_ipv6_and_encoded_password_delimiters() -> None:
    result = parse_proxy_file("socks5h://user:review_secret%23rest%3F%2F@[::1]:1080")

    assert result.errors == []
    assert result.entries[0].protocol == "socks5"
    assert result.entries[0].host == "::1"
    assert result.entries[0].port == 1080
    assert result.entries[0].password == "review_secret#rest?/"


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
