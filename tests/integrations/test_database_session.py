"""Соединения с базой быстро обнаруживают обрыв сети, а не ждут ядро 15 минут."""

from __future__ import annotations

import socket
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import event

from mimic42.integrations import database_session
from mimic42.integrations.database_session import (
    COMMAND_TIMEOUT_SECONDS,
    KEEPALIVE_IDLE_SECONDS,
    KEEPALIVE_INTERVAL_SECONDS,
    KEEPALIVE_PROBES,
    USER_TIMEOUT_MS,
    _harden_connection,
    apply_tcp_keepalive,
    create_engine,
)


def _tcp_pair() -> tuple[socket.socket, socket.socket, socket.socket]:
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    client = socket.create_connection(server.getsockname())
    accepted, _ = server.accept()
    return client, accepted, server


def test_keepalive_options_land_on_a_real_tcp_socket() -> None:
    client, accepted, server = _tcp_pair()
    try:
        apply_tcp_keepalive(client)

        assert client.getsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE) != 0
        expected = {
            "TCP_KEEPIDLE": KEEPALIVE_IDLE_SECONDS,
            "TCP_KEEPINTVL": KEEPALIVE_INTERVAL_SECONDS,
            "TCP_KEEPCNT": KEEPALIVE_PROBES,
            "TCP_USER_TIMEOUT": USER_TIMEOUT_MS,
        }
        checked = 0
        for name, value in expected.items():
            option = getattr(socket, name, None)
            if option is None:
                continue
            assert client.getsockopt(socket.IPPROTO_TCP, option) == value
            checked += 1
        assert checked > 0
    finally:
        for sock in (client, accepted, server):
            sock.close()


def test_unsupported_option_does_not_stop_the_rest() -> None:
    applied: list[int] = []

    class Sock:
        def setsockopt(self, level: int, option: int, value: int) -> None:
            if option == getattr(socket, "TCP_KEEPIDLE", -1):
                raise OSError("не поддерживается")
            applied.append(option)

    apply_tcp_keepalive(Sock())

    assert socket.SO_KEEPALIVE in applied
    assert getattr(socket, "TCP_KEEPIDLE", -1) not in applied


def test_new_pool_connection_gets_the_options() -> None:
    seen: list[tuple[int, int, int]] = []

    class Sock:
        def setsockopt(self, level: int, option: int, value: int) -> None:
            seen.append((level, option, value))

    transport = SimpleNamespace(get_extra_info=lambda name: Sock() if name == "socket" else None)
    adapted = SimpleNamespace(driver_connection=SimpleNamespace(_transport=transport))

    _harden_connection(adapted, None)

    assert (socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1) in seen


@pytest.mark.parametrize(
    "adapted",
    [
        SimpleNamespace(driver_connection=None),
        SimpleNamespace(driver_connection=SimpleNamespace()),
        SimpleNamespace(
            driver_connection=SimpleNamespace(
                _transport=SimpleNamespace(get_extra_info=lambda _name: None)
            )
        ),
    ],
    ids=["no_driver", "no_transport", "no_socket"],
)
def test_connection_without_a_reachable_socket_stays_usable(adapted: Any) -> None:
    _harden_connection(adapted, None)


def test_engine_registers_the_hook_and_bounds_commands(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}
    real_create = database_session.create_async_engine

    def spy(url: str, **kwargs: Any) -> Any:
        captured.update(kwargs)
        return real_create(url, **kwargs)

    monkeypatch.setattr(database_session, "create_async_engine", spy)

    engine = create_engine("postgresql://user:pass@127.0.0.1:1/db")

    assert event.contains(engine.sync_engine, "connect", _harden_connection)
    assert captured["pool_pre_ping"] is True
    assert captured["connect_args"]["command_timeout"] == COMMAND_TIMEOUT_SECONDS
    assert captured["connect_args"]["timeout"] == 20.0
