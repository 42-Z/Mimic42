from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal
from urllib.parse import unquote, urlsplit

ProxyProtocol = Literal["socks5", "http"]

MAX_PROXY_IMPORT_LINES = 500
MAX_PROXY_IMPORT_TEXT = 200_000

_SOCKS_SCHEMES = {"socks5", "socks5h"}
_HTTP_SCHEMES = {"http"}


class ProxyImportFormatError(ValueError):
    """Строка файла не похожа на прокси."""


@dataclass(frozen=True)
class ParsedProxyEntry:
    protocol: ProxyProtocol
    host: str
    port: int
    username: str | None
    password: str | None


@dataclass(frozen=True)
class ProxyParseResult:
    entries: list[ParsedProxyEntry] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    skipped: int = 0


def normalize_proxy_host(value: str) -> str:
    host = value.strip()
    if not host:
        raise ValueError("Адрес прокси не может быть пустым")
    if "://" in host or "/" in host or any(character.isspace() for character in host):
        raise ValueError("Укажите только хост без схемы, слешей и пробелов")
    return host


def normalize_proxy_label(value: str | None) -> str | None:
    if value is None:
        return None
    label = value.strip()
    return label or None


def parse_proxy_file(
    text: str,
    default_protocol: ProxyProtocol = "socks5",
) -> ProxyParseResult:
    """Разобрать прокси из текстового файла.

    Поддерживаются строки ``host:port``, ``host:port:login:password`` и URL
    вида ``socks5://login:password@host:port``. Пустые строки и строки,
    начинающиеся с ``#``, пропускаются.
    """
    entries: list[ParsedProxyEntry] = []
    errors: list[str] = []
    skipped = 0
    seen: set[tuple[str, str, int, str | None]] = set()
    processed_lines = 0

    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip().lstrip("\ufeff")
        if not line or line.startswith("#"):
            continue
        processed_lines += 1
        if processed_lines > MAX_PROXY_IMPORT_LINES:
            errors.append(
                f"Строка {line_number}: в одном импорте не больше {MAX_PROXY_IMPORT_LINES} прокси"
            )
            break
        try:
            entry = _parse_line(line, default_protocol)
        except ValueError as exc:
            errors.append(f"Строка {line_number}: {exc}")
            continue
        key = (entry.protocol, entry.host.casefold(), entry.port, entry.username)
        if key in seen:
            skipped += 1
            continue
        seen.add(key)
        entries.append(entry)

    if not entries and not errors:
        errors.append("Файл не содержит прокси")
    return ProxyParseResult(entries=entries, errors=errors, skipped=skipped)


def _parse_line(line: str, default_protocol: ProxyProtocol) -> ParsedProxyEntry:
    if "://" in line:
        return _parse_url(line)
    if ":" in line:
        parts = line.split(":", 3)
    else:
        parts = line.split()
    if len(parts) == 2:
        host, port_text = parts
        username = password = None
    elif len(parts) == 4:
        host, port_text, username_text, password_text = parts
        username = username_text.strip() or None
        password = password_text or None
    else:
        raise ValueError("Ожидается host:port или host:port:login:password")
    port = _parse_port(port_text)
    host = normalize_proxy_host(host)
    if password is not None and username is None:
        raise ValueError("Для пароля укажите логин прокси")
    return ParsedProxyEntry(
        protocol=default_protocol,
        host=host,
        port=port,
        username=username,
        password=password,
    )


def _parse_url(line: str) -> ParsedProxyEntry:
    try:
        parsed = urlsplit(line)
        host = parsed.hostname
    except ValueError:
        raise ProxyImportFormatError("Некорректный URL прокси") from None
    scheme = parsed.scheme.casefold()
    if scheme in _SOCKS_SCHEMES:
        protocol: ProxyProtocol = "socks5"
    elif scheme in _HTTP_SCHEMES:
        protocol = "http"
    else:
        raise ValueError("Поддерживаются только SOCKS5 и HTTP")
    if host is None:
        raise ValueError("Не указан адрес прокси")
    try:
        port_value = parsed.port
    except ValueError:
        raise ProxyImportFormatError("Некорректный порт прокси") from None
    port = _parse_port(port_value)
    username = unquote(parsed.username) if parsed.username is not None else None
    if username is not None:
        username = username.strip() or None
    password = unquote(parsed.password) if parsed.password is not None else None
    if password is not None and username is None:
        raise ValueError("Для пароля укажите логин прокси")
    return ParsedProxyEntry(
        protocol=protocol,
        host=normalize_proxy_host(host),
        port=port,
        username=username,
        password=password,
    )


def _parse_port(value: str | int | None) -> int:
    if value is None:
        raise ValueError("Не указан порт прокси")
    try:
        port = int(value)
    except (TypeError, ValueError):
        raise ValueError("Порт прокси должен быть числом") from None
    if not 1 <= port <= 65_535:
        raise ValueError("Порт прокси должен быть от 1 до 65535")
    return port
