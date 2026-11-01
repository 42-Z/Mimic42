from __future__ import annotations

import re
from typing import Any, Protocol

from pydantic import BaseModel, SecretStr, field_validator
from telethon import errors, functions

# Документация account.checkUsername: A-z, 0-9 и underscore, длина 5..32.
USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_]{5,32}$")

SESSION_INVALID_MESSAGE = (
    "Сессия Telegram недействительна. Требуется повторная привязка Telegram-аккаунта."
)


class TelegramAccountClient(Protocol):
    """Часть клиента Telethon, нужная управлению публичными данными аккаунта."""

    async def __call__(self, request: Any) -> Any: ...

    async def edit_2fa(
        self,
        current_password: str | None = None,
        new_password: str | None = None,
        *,
        hint: str = "",
    ) -> bool: ...


class TelegramAccountError(RuntimeError):
    """Отказ Telegram или политики, который API переводит в понятный ответ."""


class TelegramSessionInvalidError(TelegramAccountError):
    def __init__(self) -> None:
        super().__init__(SESSION_INVALID_MESSAGE)


class TelegramUsernameInvalidError(TelegramAccountError):
    def __init__(self) -> None:
        super().__init__(
            "Telegram не принимает такое имя. Нужны 5-32 символа: латинские буквы, "
            "цифры и подчёркивание."
        )


class TelegramUsernameOccupiedError(TelegramAccountError):
    def __init__(self) -> None:
        super().__init__("Это имя уже занято в Telegram. Выберите другое.")


class TelegramCurrentPasswordRequiredError(TelegramAccountError):
    def __init__(self) -> None:
        super().__init__("Для смены облачного пароля введите текущий пароль.")


class TelegramCurrentPasswordInvalidError(TelegramAccountError):
    def __init__(self) -> None:
        super().__init__("Неверный текущий облачный пароль. Пароль не изменён.")


class TelegramPasswordEmptyError(TelegramAccountError):
    def __init__(self) -> None:
        super().__init__("Новый пароль не может быть пустым.")


class TelegramPasswordHintCollisionError(TelegramAccountError):
    def __init__(self) -> None:
        super().__init__(
            "Новый пароль совпадает с подсказкой, которую Telegram показывает при входе. "
            "Выберите другой пароль."
        )


class TelegramPasswordTooFreshError(TelegramAccountError):
    def __init__(self) -> None:
        super().__init__("Telegram пока не разрешает менять пароль. Попробуйте позже.")


class TelegramAccountFloodWaitError(TelegramAccountError):
    def __init__(self, seconds: int) -> None:
        self.seconds = seconds
        super().__init__(f"Telegram просит подождать {seconds} сек.")


class TelegramAccountUnavailableError(TelegramAccountError):
    def __init__(self) -> None:
        super().__init__("Telegram не ответил на запрос. Попробуйте ещё раз.")


def normalize_username(value: str) -> str:
    username = value.strip()
    if username.startswith("@"):
        username = username[1:]
    if USERNAME_PATTERN.fullmatch(username) is None:
        raise ValueError(
            "Имя должно быть длиной 5-32 символа и состоять из латинских букв, цифр "
            "и подчёркиваний."
        )
    return username


class TelegramUsernameUpdate(BaseModel):
    username: str

    @field_validator("username")
    @classmethod
    def _normalize(cls, value: str) -> str:
        return normalize_username(value)


class TelegramPasswordUpdate(BaseModel):
    current_password: SecretStr | None = None
    new_password: SecretStr

    @field_validator("new_password")
    @classmethod
    def _not_empty(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value().strip():
            raise ValueError("Новый пароль не может быть пустым.")
        return value


class TelegramPasswordState(BaseModel):
    has_password: bool


class TelegramUsernameChanged(BaseModel):
    username: str


class TelegramPasswordChanged(BaseModel):
    changed: bool = True


def _flood_wait(exc: errors.FloodError) -> TelegramAccountError:
    seconds = getattr(exc, "seconds", None)
    if isinstance(seconds, int) and seconds > 0:
        return TelegramAccountFloodWaitError(seconds)
    return TelegramAccountUnavailableError()


async def _get_password(client: TelegramAccountClient) -> Any:
    try:
        return await client(functions.account.GetPasswordRequest())
    except errors.FloodError as exc:
        raise _flood_wait(exc) from exc
    except (errors.AuthKeyDuplicatedError, errors.UnauthorizedError) as exc:
        raise TelegramSessionInvalidError() from exc
    except errors.RPCError as exc:
        raise TelegramAccountUnavailableError() from exc
    except OSError as exc:
        raise TelegramAccountUnavailableError() from exc


async def read_password_state(client: TelegramAccountClient) -> TelegramPasswordState:
    password = await _get_password(client)
    return TelegramPasswordState(has_password=bool(getattr(password, "has_password", False)))


async def apply_username(client: TelegramAccountClient, username: str) -> str:
    normalized = normalize_username(username)
    try:
        user = await client(functions.account.UpdateUsernameRequest(username=normalized))
    except errors.UsernameNotModifiedError:
        return normalized
    except errors.UsernameInvalidError as exc:
        raise TelegramUsernameInvalidError() from exc
    except (errors.UsernameOccupiedError, errors.UsernamePurchaseAvailableError) as exc:
        raise TelegramUsernameOccupiedError() from exc
    except errors.FloodError as exc:
        raise _flood_wait(exc) from exc
    except (errors.AuthKeyDuplicatedError, errors.UnauthorizedError) as exc:
        raise TelegramSessionInvalidError() from exc
    except errors.RPCError as exc:
        raise TelegramAccountUnavailableError() from exc
    except OSError as exc:
        raise TelegramAccountUnavailableError() from exc
    confirmed = getattr(user, "username", None)
    return confirmed if isinstance(confirmed, str) and confirmed else normalized


async def apply_password(client: TelegramAccountClient, change: TelegramPasswordUpdate) -> None:
    new_password = change.new_password.get_secret_value()
    if not new_password.strip():
        raise TelegramPasswordEmptyError()
    current_password = (
        change.current_password.get_secret_value() if change.current_password is not None else None
    )
    password = await _get_password(client)
    has_password = bool(getattr(password, "has_password", False))
    if has_password and not current_password:
        raise TelegramCurrentPasswordRequiredError()
    hint = getattr(password, "hint", None)
    hint_text = hint if isinstance(hint, str) else ""
    if hint_text and hint_text == new_password:
        raise TelegramPasswordHintCollisionError()
    try:
        changed = await client.edit_2fa(
            current_password=current_password if has_password else None,
            new_password=new_password,
            hint=hint_text,
        )
    except errors.PasswordHashInvalidError as exc:
        raise TelegramCurrentPasswordInvalidError() from exc
    except errors.PasswordTooFreshError as exc:
        raise TelegramPasswordTooFreshError() from exc
    except errors.FloodError as exc:
        raise _flood_wait(exc) from exc
    except (errors.AuthKeyDuplicatedError, errors.UnauthorizedError) as exc:
        raise TelegramSessionInvalidError() from exc
    except errors.RPCError as exc:
        raise TelegramAccountUnavailableError() from exc
    except OSError as exc:
        raise TelegramAccountUnavailableError() from exc
    if not changed:
        raise TelegramAccountUnavailableError()
