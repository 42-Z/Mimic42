from __future__ import annotations

from typing import Protocol
from uuid import UUID

from pydantic import BaseModel, Field

from mimic42.core.agent_runtime import TelegramProxyConfig


class TelegramProxyUnavailableError(RuntimeError):
    """Назначенный прокси нельзя использовать: запись удалена или пароль не читается."""


class TelegramProxyAssignment(BaseModel):
    proxy_id: UUID
    config: TelegramProxyConfig


class TelegramProxyStore(Protocol):
    """Выдача и чтение прокси для онбординга и перепривязки."""

    async def allocate(self) -> TelegramProxyAssignment | None:
        """Наименее загруженный активный прокси; None — пул пуст."""
        ...

    async def load(self, proxy_id: UUID) -> TelegramProxyConfig:
        """Конфиг конкретного прокси, в том числе отключённого: агент уже им пользуется."""
        ...

    async def assignment_for_agent(self, agent_id: UUID) -> TelegramProxyAssignment | None:
        """Прокси, закреплённый за агентом в telegram_sessions."""
        ...


class TelegramProxyCheckResult(BaseModel):
    ok: bool
    latency_ms: int | None = Field(default=None, ge=0)
    error: str | None = None
