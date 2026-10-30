from __future__ import annotations

from uuid import UUID

from cryptography.fernet import InvalidToken
from pydantic import SecretStr

from mimic42.core.admin import (
    PublicTelegramSettings,
    StoredTelegramSettings,
    TelegramSettingsStore,
)
from mimic42.core.crypto import FernetSecretCipher


class TelegramAppUnavailableError(Exception):
    """Telegram application credentials could not be safely resolved or stored."""


class TelegramAppSettings:
    """Пара Telegram-приложения — только из строки platform_telegram_settings.

    Панель администра — единственный источник пары: приложение не читает переменные
    окружения и не принимает пару из запроса. Пока пара не сохранена, новые
    подключения невозможны.
    """

    def __init__(
        self,
        *,
        repository: TelegramSettingsStore | None,
        cipher: FernetSecretCipher | None,
    ) -> None:
        self._repository = repository
        self._cipher = cipher

    async def resolve(self) -> tuple[int, str]:
        stored = await self._read_stored()
        if stored is None:
            raise TelegramAppUnavailableError(
                "Telegram-приложение не настроено. Сохраните пару API ID и API HASH в админ-панели."
            )
        return stored.api_id, self._decrypt_hash(stored).get_secret_value()

    async def status(self) -> PublicTelegramSettings:
        stored = await self._read_stored()
        if stored is None:
            return PublicTelegramSettings(
                api_id=None,
                api_hash=None,
                has_api_hash=False,
                source="unconfigured",
                updated_at=None,
                updated_by=None,
            )
        return PublicTelegramSettings(
            api_id=stored.api_id,
            api_hash=self._try_decrypt_hash(stored),
            has_api_hash=True,
            source="database",
            updated_at=stored.updated_at,
            updated_by=stored.updated_by,
        )

    async def save(
        self,
        *,
        api_id: int,
        api_hash: SecretStr,
        actor_user_id: UUID,
    ) -> PublicTelegramSettings:
        if self._repository is None or self._cipher is None:
            raise TelegramAppUnavailableError(
                "Сохранение Telegram-приложения недоступно без хранилища и SECRET_KEY"
            )

        try:
            ciphertext = self._cipher.encrypt(api_hash.get_secret_value())
            result = await self._repository.save_telegram_settings(
                api_id=api_id,
                api_hash_ciphertext=ciphertext,
                actor_user_id=actor_user_id,
            )
        except Exception:
            raise TelegramAppUnavailableError(
                "Не удалось сохранить настройки Telegram-приложения"
            ) from None
        # Ответ показывает только что сохранённое значение: админ его и ввёл.
        return result.model_copy(update={"api_hash": api_hash})

    async def _read_stored(self) -> StoredTelegramSettings | None:
        if self._repository is None:
            return None
        try:
            return await self._repository.read_telegram_settings()
        except Exception:
            raise TelegramAppUnavailableError(
                "Не удалось получить настройки Telegram-приложения"
            ) from None

    def _decrypt_hash(self, stored: StoredTelegramSettings) -> SecretStr:
        if self._cipher is None:
            raise TelegramAppUnavailableError(
                "Расшифровка Telegram-приложения недоступна без SECRET_KEY"
            )
        try:
            api_hash = self._cipher.decrypt(stored.api_hash_ciphertext.get_secret_value())
        except (InvalidToken, UnicodeDecodeError, ValueError):
            raise TelegramAppUnavailableError(
                "Не удалось расшифровать настройки Telegram-приложения"
            ) from None
        return SecretStr(api_hash)

    def _try_decrypt_hash(self, stored: StoredTelegramSettings) -> SecretStr | None:
        # Статус — только показ: без SECRET_KEY или с битым шифром форма остаётся
        # доступной, значение пустое, но признак «HASH задан» сохраняется.
        if self._cipher is None:
            return None
        try:
            return self._decrypt_hash(stored)
        except TelegramAppUnavailableError:
            return None
