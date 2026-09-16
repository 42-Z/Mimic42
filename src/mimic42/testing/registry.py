"""Один поддельный телеграм-аккаунт на агента: сервер и тест смотрят
в одно и то же состояние."""

from __future__ import annotations

from uuid import UUID

from mimic42.testing.telegram import FakeTelegramAccount

_ACCOUNTS: dict[UUID, FakeTelegramAccount] = {}
_ONBOARDING_ACCOUNT = FakeTelegramAccount()


def account_for(agent_id: UUID) -> FakeTelegramAccount:
    account = _ACCOUNTS.get(agent_id)
    if account is None:
        account = FakeTelegramAccount()
        account.authorized = True
        _ACCOUNTS[agent_id] = account
    return account


def onboarding_account() -> FakeTelegramAccount:
    """Аккаунт, через который проходит вход в телегу во время онбординга."""
    return _ONBOARDING_ACCOUNT


def reset() -> None:
    """Очистить состояние на следующий тест.

    ``_ONBOARDING_ACCOUNT`` сбрасывается на месте (поля, а не сам объект):
    ``FakeTelegramAuthClientFactory`` в уже собранном приложении держит
    прямую ссылку на этот экземпляр, и подмена объекта её бы не затронула.
    """
    _ACCOUNTS.clear()
    reset_onboarding_account()


def reset_onboarding_account() -> None:
    """Снять сценарий входа (код и 2FA-пароль) с общего аккаунта онбординга.

    Сценарий живёт на весь процесс: без сброса пароль, заготовленный одним
    тестом, требует ввода от следующего — включая повторные прогоны упавших
    тестов."""
    fresh = FakeTelegramAccount()
    _ONBOARDING_ACCOUNT.__dict__.update(fresh.__dict__)
