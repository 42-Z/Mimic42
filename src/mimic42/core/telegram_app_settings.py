from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from cryptography.fernet import InvalidToken
from pydantic import SecretStr

from mimic42.config import Settings
from mimic42.core.admin import AdminRepository, PublicTelegramSettings, StoredTelegramSettings
from mimic42.core.crypto import FernetSecretCipher


class TelegramAppUnavailableError(Exception):
    """Telegram application credentials could not be safely resolved or stored."""


@dataclass(frozen=True, slots=True)
class TelegramAppDefaults:
    api_id: int | None
    api_hash: SecretStr | None


class TelegramAppSettings:
    def __init__(
        self,
        *,
        settings: Settings,
        repository: AdminRepository | None,
        cipher: FernetSecretCipher | None,
    ) -> None:
        self._settings = settings
        self._repository = repository
        self._cipher = cipher

    async def resolve(self, api_id: int | None, api_hash: str | None) -> tuple[int, str]:
        if api_id is not None and api_hash is not None:
            return api_id, api_hash

        defaults = await self._read_defaults()
        resolved_id = api_id if api_id is not None else defaults.api_id
        resolved_hash = SecretStr(api_hash) if api_hash is not None else defaults.api_hash
        if resolved_id is None or resolved_hash is None:
            raise TelegramAppUnavailableError(
                "Telegram-приложение не настроено. Задайте TELEGRAM_API_ID и "
                "TELEGRAM_API_HASH в окружении или сохраните пару в админ-панели."
            )
        return resolved_id, resolved_hash.get_secret_value()

    async def status(self) -> PublicTelegramSettings:
        if self._repository is not None:
            try:
                stored_status = await self._repository.read_telegram_settings_status()
            except Exception:
                raise TelegramAppUnavailableError(
                    "Не удалось получить настройки Telegram-приложения"
                ) from None
            if stored_status is not None:
                return stored_status

        has_environment_settings = (
            self._settings.telegram_api_id is not None
            or self._settings.telegram_api_hash is not None
        )
        return PublicTelegramSettings(
            api_id=self._settings.telegram_api_id,
            has_api_hash=bool(self._settings.telegram_api_hash),
            source="environment" if has_environment_settings else "unconfigured",
            updated_at=None,
            updated_by=None,
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
            return await self._repository.save_telegram_settings(
                api_id=api_id,
                api_hash_ciphertext=ciphertext,
                actor_user_id=actor_user_id,
            )
        except Exception:
            raise TelegramAppUnavailableError(
                "Не удалось сохранить настройки Telegram-приложения"
            ) from None

    async def _read_defaults(self) -> TelegramAppDefaults:
        if self._repository is None:
            return self._environment_defaults()

        try:
            stored = await self._repository.read_telegram_settings()
        except Exception:
            raise TelegramAppUnavailableError(
                "Не удалось получить настройки Telegram-приложения"
            ) from None

        if stored is None:
            return self._environment_defaults()
        return TelegramAppDefaults(
            api_id=stored.api_id,
            api_hash=self._decrypt_hash(stored),
        )

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

    def _environment_defaults(self) -> TelegramAppDefaults:
        api_hash = self._settings.telegram_api_hash
        return TelegramAppDefaults(
            api_id=self._settings.telegram_api_id,
            api_hash=SecretStr(api_hash) if api_hash is not None else None,
        )
