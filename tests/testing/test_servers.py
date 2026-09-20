"""Проверка порта перед стартом тестовых серверов."""

from __future__ import annotations

import socket

import pytest

from tests.servers import assert_port_free


def _listener() -> tuple[socket.socket, int]:
    """Слушатель как у uvicorn и next: с SO_REUSEADDR.

    Флаг наследуют и его соединения в TIME_WAIT; без флага с обеих сторон
    Linux не даёт занять порт повторно, и тест не отражал бы реальные серверы.
    """
    server = socket.socket()
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("127.0.0.1", 0))
    server.listen()
    return server, server.getsockname()[1]


def test_live_listener_is_reported_as_busy() -> None:
    server, port = _listener()
    try:
        with pytest.raises(RuntimeError, match=str(port)):
            assert_port_free(port)
    finally:
        server.close()


def test_time_wait_leftovers_do_not_count_as_busy() -> None:
    """После остановки сервера соединения ещё минуту висят в TIME_WAIT.

    Порт при этом свободен: сервер поднимется. Ложный отказ ломал бы каждый
    e2e-прогон, запущенный сразу вслед за предыдущим.
    """
    server, port = _listener()
    client = socket.create_connection(("127.0.0.1", port))
    accepted, _ = server.accept()
    # Первой закрывает серверная сторона: TIME_WAIT остаётся именно на ней.
    accepted.close()
    client.close()
    server.close()

    assert_port_free(port)
