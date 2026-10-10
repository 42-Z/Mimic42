from __future__ import annotations

import logging
import socket
from typing import Any

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

logger = logging.getLogger("mimic42.database")

# После смены сети (другой Wi-Fi, переподключение хотспота) соединения в пуле
# остаются ESTABLISHED на адрес, которого уже нет: ядро ждёт tcp_retries2, около
# 15 минут. Всё это время висят запросы, rollback и закрытие соединения, а вместе
# с ними остановка агента. Короткие keepalive и TCP_USER_TIMEOUT рвут такой сокет
# за секунды, и пул получает обычный разрыв, который сам и обрабатывает.
KEEPALIVE_IDLE_SECONDS = 15
KEEPALIVE_INTERVAL_SECONDS = 5
KEEPALIVE_PROBES = 3
USER_TIMEOUT_MS = 30_000
# Потолок одной команды на случай, когда сокет жив, а сервер не отвечает.
COMMAND_TIMEOUT_SECONDS = 60.0


def normalize_async_database_url(database_url: str) -> str:
    if database_url.startswith("postgresql://"):
        return database_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if database_url.startswith("postgres://"):
        return database_url.replace("postgres://", "postgresql+asyncpg://", 1)
    return database_url


def apply_tcp_keepalive(sock: Any) -> None:
    """Включить на сокете быстрое обнаружение мёртвого соединения.

    Опции Linux-специфичны: на платформе без какой-то из них она пропускается,
    остальные всё равно применяются.
    """
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
    for name, value in (
        ("TCP_KEEPIDLE", KEEPALIVE_IDLE_SECONDS),
        ("TCP_KEEPINTVL", KEEPALIVE_INTERVAL_SECONDS),
        ("TCP_KEEPCNT", KEEPALIVE_PROBES),
        ("TCP_USER_TIMEOUT", USER_TIMEOUT_MS),
    ):
        option = getattr(socket, name, None)
        if option is None:
            continue
        try:
            sock.setsockopt(socket.IPPROTO_TCP, option, value)
        except OSError:
            logger.debug("Сокет не поддерживает %s", name, exc_info=True)


def _harden_connection(dbapi_connection: Any, _connection_record: Any) -> None:
    """Событие пула: только что созданное соединение получает опции keepalive.

    У asyncpg нет публичного доступа к сокету, поэтому берём транспорт соединения;
    если его форма изменится, соединение останется рабочим, но без ускоренного
    обнаружения обрыва.
    """
    driver_connection = getattr(dbapi_connection, "driver_connection", None)
    transport = getattr(driver_connection, "_transport", None)
    sock = transport.get_extra_info("socket") if transport is not None else None
    if sock is None:
        logger.debug("Сокет соединения с базой недоступен, keepalive не включён")
        return
    try:
        apply_tcp_keepalive(sock)
    except OSError:
        logger.warning("Не удалось включить keepalive на соединении с базой", exc_info=True)


def create_engine(database_url: str) -> AsyncEngine:
    engine = create_async_engine(
        normalize_async_database_url(database_url),
        pool_pre_ping=True,
        # Без явного таймаута asyncpg не ограничивает время установки
        # соединения — при временной недоступности пулера Supabase запуск
        # приложения (и любой первый запрос) мог зависнуть без ограничения.
        connect_args={"timeout": 20.0, "command_timeout": COMMAND_TIMEOUT_SECONDS},
    )
    event.listen(engine.sync_engine, "connect", _harden_connection)
    return engine


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)
