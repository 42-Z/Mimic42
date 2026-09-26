"""Настройка «Первый комментарий»: мгновенный комментарий под новым постом.

Хранится в JSON-колонке ``agents.settings`` под ключом ``first_comment``,
поэтому разбор обязан быть терпимым: чужая или устаревшая форма настройки
не должна ронять сборку рантайма — она просто выключает фичу.
"""

from __future__ import annotations

import logging
from collections import OrderedDict
from collections.abc import Iterable
from typing import Any, Self

from pydantic import BaseModel, Field, ValidationError, model_validator

logger = logging.getLogger("mimic42.first_comment")

# Лимиты Телеграма: 4096 символов на текстовое сообщение и 1024 на подпись
# к медиа. Вариант с картинкой уезжает подписью, поэтому режется жёстче.
MAX_COMMENT_TEXT = 4096
MAX_COMMENT_CAPTION = 1024


class FirstCommentVariant(BaseModel):
    """Один вариант комментария: текст и/или картинка."""

    text: str = Field(default="", max_length=MAX_COMMENT_TEXT)
    # Путь объекта в бакете agent-media; картинку читает бэкенд по service-ключу.
    image_path: str | None = None
    # Имя файла нужно Telethon: расширение решает, уйдёт картинка фото или файлом.
    image_name: str | None = None

    @model_validator(mode="after")
    def _caption_fits(self) -> Self:
        # Длинная подпись упала бы в Telegram на каждом посте: отсекаем при разборе.
        if self.image_path and len(self.text) > MAX_COMMENT_CAPTION:
            raise ValueError(f"подпись к картинке длиннее {MAX_COMMENT_CAPTION} символов")
        return self

    @property
    def is_usable(self) -> bool:
        return bool(self.text.strip() or self.image_path)


class FirstCommentSettings(BaseModel):
    enabled: bool = False
    variants: list[FirstCommentVariant] = Field(default_factory=list)

    @property
    def usable_variants(self) -> list[FirstCommentVariant]:
        return [variant for variant in self.variants if variant.is_usable]

    @property
    def is_active(self) -> bool:
        return self.enabled and bool(self.usable_variants)


class PostedAlbumGuard:
    """Однократность комментария на пост-альбом.

    Элементы альбома приходят отдельными апдейтами с общим ``grouped_id``,
    и каждый из них — свой dispatch-таск, поэтому отметка ставится
    синхронно, до первого ``await``. Память ограничена: рантайм живёт
    неделями, и безграничное множество ключей копилось бы вечно.
    """

    def __init__(self, capacity: int = 512) -> None:
        self._capacity = capacity
        self._keys: OrderedDict[tuple[str, str], None] = OrderedDict()

    def claim(self, key: tuple[str, str]) -> bool:
        """``True``, если ключ увиден впервые и комментарий за нами."""
        if key in self._keys:
            return False
        self._keys[key] = None
        while len(self._keys) > self._capacity:
            self._keys.popitem(last=False)
        return True


class SentFirstComments:
    """Какой вариант ушёл под какой пост — чтобы ход ИИ по посту знал о нём.

    Ход по посту начинается после отправки комментария (обработчики одного
    апдейта Telethon вызывает по очереди), а альбом ИИ-ветка ещё и копит,
    поэтому к её разбору запись уже есть. Размер ограничен, как у guard.
    """

    def __init__(self, capacity: int = 512) -> None:
        self._capacity = capacity
        self._sent: OrderedDict[tuple[str, int], FirstCommentVariant] = OrderedDict()

    def remember(self, peer: str, post_id: int, variant: FirstCommentVariant) -> None:
        self._sent[(peer, post_id)] = variant
        while len(self._sent) > self._capacity:
            self._sent.popitem(last=False)

    def lookup(self, peer: str, post_ids: Iterable[int]) -> FirstCommentVariant | None:
        """Вариант под любым из постов: у альбома комментарий висит на одном элементе."""
        for post_id in post_ids:
            variant = self._sent.get((peer, post_id))
            if variant is not None:
                return variant
        return None


def parse_first_comment(raw: Any) -> FirstCommentSettings:
    """Собрать настройку из сырого JSON, пропуская всё нечитаемое.

    Варианты разбираются поодиночке: одна битая запись не должна отключать
    остальные, а совсем неразборная настройка даёт выключенную фичу.
    """
    if not isinstance(raw, dict):
        return FirstCommentSettings()

    raw_variants = raw.get("variants")
    variants: list[FirstCommentVariant] = []
    for item in raw_variants if isinstance(raw_variants, list) else []:
        if not isinstance(item, dict):
            continue
        try:
            variant = FirstCommentVariant.model_validate(item)
        except ValidationError as exc:
            logger.warning("Вариант первого комментария пропущен: %s", exc)
            continue
        if variant.is_usable:
            variants.append(variant)

    # Строго True: строка "false" из ручной правки JSON не должна включать фичу.
    return FirstCommentSettings(enabled=raw.get("enabled") is True, variants=variants)
