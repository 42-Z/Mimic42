"""Настройка «Первый комментарий»: мгновенный комментарий под новым постом.

Хранится в JSON-колонке ``agents.settings`` под ключом ``first_comment``,
поэтому разбор обязан быть терпимым: чужая или устаревшая форма настройки
не должна ронять сборку рантайма — она просто выключает фичу.
"""

from __future__ import annotations

from collections import OrderedDict
from typing import Any

from pydantic import BaseModel, Field

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


def parse_first_comment(raw: Any) -> FirstCommentSettings:
    """Собрать настройку из сырого JSON, пропуская всё нечитаемое.

    Варианты разбираются поодиночке: одна битая запись не должна отключать
    остальные, а совсем неразборная настройка даёт выключенную фичу.
    """
    if not isinstance(raw, dict):
        return FirstCommentSettings()

    variants: list[FirstCommentVariant] = []
    for item in raw.get("variants") or []:
        if not isinstance(item, dict):
            continue
        try:
            variant = FirstCommentVariant.model_validate(item)
        except Exception:
            continue
        if variant.is_usable:
            variants.append(variant)

    return FirstCommentSettings(enabled=bool(raw.get("enabled")), variants=variants)
