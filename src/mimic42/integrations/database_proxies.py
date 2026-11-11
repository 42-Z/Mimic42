from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Literal, cast
from uuid import UUID

from pydantic import SecretStr
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mimic42.core.agent_runtime import TelegramProxyConfig
from mimic42.core.onboarding import SecretCipher
from mimic42.core.telegram_proxy import (
    TelegramProxyAssignment,
    TelegramProxyCheckResult,
    TelegramProxyUnavailableError,
)
from mimic42.integrations.database_models import (
    AgentOnboardingSessionModel,
    TelegramProxyModel,
    TelegramSessionModel,
)

logger = logging.getLogger("mimic42.telegram_proxies")

# Сколько кандидатов проверять за одну выдачу: мёртвые снимаются с пула,
# поэтому в следующий раз проверка начнётся со следующего по загрузке.
ALLOCATION_CHECK_LIMIT = 5


async def lock_proxy_pool(session: AsyncSession) -> None:
    await session.execute(text("select public.lock_telegram_proxy_pool()"))


async def least_loaded_proxy_ids(
    session: AsyncSession, *, limit: int, exclude_id: UUID | None = None
) -> list[UUID]:
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
    return list(
        await session.scalars(
            statement.order_by(
                agent_load + onboarding_load,
                TelegramProxyModel.created_at,
                TelegramProxyModel.id,
            ).limit(limit)
        )
    )


async def least_loaded_proxy_id(
    session: AsyncSession, *, exclude_id: UUID | None = None
) -> UUID | None:
    ids = await least_loaded_proxy_ids(session, limit=1, exclude_id=exclude_id)
    return ids[0] if ids else None


class DatabaseTelegramProxyStore:
    """Прокси из пула: проверенная выдача, чтение конфига и назначение агента."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        cipher: SecretCipher | None = None,
        checker: Callable[[TelegramProxyConfig], Awaitable[TelegramProxyCheckResult]],
    ) -> None:
        self._session_factory = session_factory
        self._cipher = cipher
        self._checker = checker

    async def allocate(self) -> TelegramProxyAssignment | None:
        """Выдать прокси, проверив его через Telegram до назначения.

        Непригодные записи снимаются с выдачи, поэтому следующий вызов
        начнёт с других кандидатов.
        """
        try:
            async with self._session_factory() as session:
                proxy_ids = await least_loaded_proxy_ids(session, limit=ALLOCATION_CHECK_LIMIT)
                models = {
                    model.id: model
                    for model in await session.scalars(
                        select(TelegramProxyModel).where(TelegramProxyModel.id.in_(proxy_ids))
                    )
                }
        except SQLAlchemyError:
            raise TelegramProxyUnavailableError("Хранилище прокси временно недоступно") from None
        for proxy_id in proxy_ids:
            model = models.get(proxy_id)
            if model is None:
                continue
            try:
                config = telegram_proxy_config(model, self._cipher)
            except TelegramProxyUnavailableError as exc:
                logger.warning("Прокси %s непригоден (%s); снимаю с выдачи", model.id, exc)
                await self.deactivate(model.id)
                continue
            check = await self._checker(config)
            if check.ok:
                return TelegramProxyAssignment(proxy_id=model.id, config=config)
            logger.warning(
                "Прокси %s:%s не прошёл проверку (%s); снимаю с выдачи",
                model.host,
                model.port,
                check.error,
            )
            await self.deactivate(model.id)
        if proxy_ids:
            # Пул был непустым, но всё, что в нём есть, не проходит проверку.
            # Молча уходить напрямую нельзя: политика приложения — без прокси
            # в Telegram не ходить (пустой пул — отдельный случай разработки).
            raise TelegramProxyUnavailableError("Ни один прокси из пула не пропускает Telegram")
        return None

    async def load(self, proxy_id: UUID) -> TelegramProxyConfig:
        try:
            async with self._session_factory() as session:
                model = await session.get(TelegramProxyModel, proxy_id)
        except SQLAlchemyError:
            raise TelegramProxyUnavailableError("Хранилище прокси временно недоступно") from None
        if model is None:
            raise TelegramProxyUnavailableError("Прокси не найден")
        return telegram_proxy_config(model, self._cipher)

    async def deactivate(self, proxy_id: UUID) -> None:
        """Снять прокси с автовыдачи, не удаляя запись у привязанных агентов."""
        try:
            async with self._session_factory() as session, session.begin():
                await session.execute(
                    update(TelegramProxyModel)
                    .where(TelegramProxyModel.id == proxy_id)
                    .values(is_active=False)
                )
        except SQLAlchemyError:
            raise TelegramProxyUnavailableError("Хранилище прокси временно недоступно") from None

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
