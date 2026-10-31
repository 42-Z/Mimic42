from __future__ import annotations

import logging
from typing import Literal, cast
from uuid import UUID

from pydantic import SecretStr
from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mimic42.core.agent_runtime import TelegramProxyConfig
from mimic42.core.onboarding import SecretCipher
from mimic42.core.telegram_proxy import (
    TelegramProxyAssignment,
    TelegramProxyUnavailableError,
)
from mimic42.integrations.database_models import (
    AgentOnboardingSessionModel,
    TelegramProxyModel,
    TelegramSessionModel,
)

logger = logging.getLogger("mimic42.telegram_proxies")


async def lock_proxy_pool(session: AsyncSession) -> None:
    await session.execute(text("select public.lock_telegram_proxy_pool()"))


async def least_loaded_proxy_id(
    session: AsyncSession, *, exclude_id: UUID | None = None
) -> UUID | None:
    agent_load = (
        select(func.count(TelegramSessionModel.id))
        .where(TelegramSessionModel.proxy_id == TelegramProxyModel.id)
        .correlate(TelegramProxyModel)
        .scalar_subquery()
    )
    onboarding_load = (
        select(func.count(AgentOnboardingSessionModel.id))
        .where(
            AgentOnboardingSessionModel.proxy_id == TelegramProxyModel.id,
            AgentOnboardingSessionModel.completed_agent_id.is_(None),
        )
        .correlate(TelegramProxyModel)
        .scalar_subquery()
    )
    statement = select(TelegramProxyModel.id).where(TelegramProxyModel.is_active.is_(True))
    if exclude_id is not None:
        statement = statement.where(TelegramProxyModel.id != exclude_id)
    return await session.scalar(
        statement.order_by(
            agent_load + onboarding_load, TelegramProxyModel.created_at, TelegramProxyModel.id
        ).limit(1)
    )


class DatabaseTelegramProxyStore:
    """Прокси из пула: автовыдача, чтение конфига и назначение агента."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        cipher: SecretCipher | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._cipher = cipher

    async def allocate(self) -> TelegramProxyAssignment | None:
        try:
            async with self._session_factory() as session:
                proxy_id = await least_loaded_proxy_id(session)
                model = await session.get(TelegramProxyModel, proxy_id) if proxy_id else None
        except SQLAlchemyError:
            raise TelegramProxyUnavailableError("Хранилище прокси временно недоступно") from None
        if model is None:
            return None
        return TelegramProxyAssignment(
            proxy_id=model.id,
            config=telegram_proxy_config(model, self._cipher),
        )

    async def load(self, proxy_id: UUID) -> TelegramProxyConfig:
        try:
            async with self._session_factory() as session:
                model = await session.get(TelegramProxyModel, proxy_id)
        except SQLAlchemyError:
            raise TelegramProxyUnavailableError("Хранилище прокси временно недоступно") from None
        if model is None:
            raise TelegramProxyUnavailableError("Прокси не найден")
        return telegram_proxy_config(model, self._cipher)

    async def assignment_for_agent(self, agent_id: UUID) -> TelegramProxyAssignment | None:
        statement = (
            select(TelegramProxyModel)
            .join(TelegramSessionModel, TelegramSessionModel.proxy_id == TelegramProxyModel.id)
            .where(TelegramSessionModel.agent_id == agent_id)
        )
        try:
            async with self._session_factory() as session:
                model = await session.scalar(statement)
        except SQLAlchemyError:
            raise TelegramProxyUnavailableError("Хранилище прокси временно недоступно") from None
        if model is None:
            return None
        return TelegramProxyAssignment(
            proxy_id=model.id,
            config=telegram_proxy_config(model, self._cipher),
        )


def telegram_proxy_config(
    model: TelegramProxyModel,
    cipher: SecretCipher | None,
) -> TelegramProxyConfig:
    """Расшифровать пароль прокси; без ключа пароль использовать нельзя."""
    password: str | None = None
    if model.password_ciphertext is not None:
        if cipher is None:
            raise TelegramProxyUnavailableError(
                "Пароль прокси зашифрован, но SECRET_KEY не настроен"
            )
        try:
            password = cipher.decrypt(model.password_ciphertext)
        except Exception:
            logger.warning("Не удалось расшифровать пароль прокси %s", model.id, exc_info=True)
            raise TelegramProxyUnavailableError("Не удалось расшифровать пароль прокси") from None
    try:
        return TelegramProxyConfig(
            protocol=cast(Literal["socks5", "http"], model.protocol),
            host=model.host,
            port=model.port,
            username=model.username,
            password=SecretStr(password) if password is not None else None,
        )
    except ValueError:
        raise TelegramProxyUnavailableError("Запись прокси повреждена") from None
