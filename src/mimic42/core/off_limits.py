"""Служебные боты Telegram, с которыми агент не работает: ими занимается владелец."""

from __future__ import annotations

from typing import Any

from telethon import types, utils


class OffLimitsBotError(RuntimeError):
    """Диалог со служебным ботом Telegram ведёт система и владелец, а не агент."""

    def __init__(self, username: str) -> None:
        super().__init__(
            f"Бот @{username} не для агента: состояние аккаунта система проверяет сама, "
            "а апелляцию подаёт владелец. Ничего ему не отправляй, кнопок не нажимай и "
            "таймеров на него не ставь."
        )


# Через этого бота Telegram снимает ограничения аккаунта: его кнопки — заявления
# от имени владельца («я не рассылал спам»), и решать такое должен человек.
OFF_LIMITS_BOTS = frozenset({"spambot"})


def off_limits_bot(peer: Any) -> str | None:
    """Юзернейм служебного бота, если строка peer указывает на него.

    Строку разбирает тот же ``utils.parse_username``, что и Telethon при разрешении
    чата: собственный разбор пропустил бы форму, которую Telethon всё равно распознает.
    Метка перед «#» отбрасывается, как при разрешении peer.
    """
    if not isinstance(peer, str):
        return None
    username, is_invite = utils.parse_username(peer.split("#", 1)[-1].strip())
    if is_invite or username is None:
        return None
    return username if username in OFF_LIMITS_BOTS else None


def is_off_limits_entity(entity: Any, off_limits_user_id: Any) -> bool:
    """Это пользователь с известным id служебного бота (имя, число, ссылка — всё сойдётся)."""
    if not isinstance(off_limits_user_id, int):
        return False
    if isinstance(entity, types.User):
        return entity.id == off_limits_user_id
    if isinstance(entity, types.InputPeerUser):
        return entity.user_id == off_limits_user_id
    return False
