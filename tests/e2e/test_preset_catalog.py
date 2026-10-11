"""Каталог пресетов в браузере (issue #67)."""

from __future__ import annotations

import re
from collections.abc import Callable

import httpx
import pytest
from playwright.sync_api import Locator, Page, expect

from tests.e2e.helpers import create_test_agent

pytestmark = pytest.mark.e2e

TITLE = "Ламповый олд"
SUMMARY = "говорит как с туса 2007"
PROMPT = "Ты ламповый олд интернета и помнишь, как звучали модемы."


def _card(page: Page, text: str) -> Locator:
    return page.get_by_test_id(re.compile(r"preset-card-")).filter(has_text=text)


class TestPresetCatalog:
    def test_create_publish_favorite_and_freeze(
        self,
        persona_page: Callable[..., Page],
        api: httpx.Client,
        users: dict,
    ) -> None:
        author = persona_page("full")
        reader = persona_page("flow")

        # Рантайму читателя нужен мимик: делаем тестового через тестовый API.
        reader_agent_id = create_test_agent(api, users["flow"].id, "Мимик читателя")

        # Автор создаёт пресет.
        author.goto("/presets")
        author.get_by_test_id("open-preset-editor").click()
        editor = author.get_by_role("dialog")
        editor.get_by_label("Название").fill(TITLE)
        editor.get_by_label("Короткое описание").fill(SUMMARY)
        editor.get_by_label("Промпт").fill(PROMPT)
        editor.get_by_test_id("preset-editor-save").click()
        expect(editor).to_be_hidden()

        # Выкладка: во вкладке «Мои» метка меняется на «В магазине».
        author.get_by_test_id("presets-tab-mine").click()
        mine_card = _card(author, TITLE)
        mine_card.get_by_test_id("preset-publish").click()
        expect(mine_card.get_by_text("В магазине")).to_be_visible()

        # Читатель видит пресет в магазине и сохраняет в избранное.
        reader.goto("/presets")
        reader.get_by_test_id("presets-store-search").fill(TITLE)
        foreign_card = _card(reader, TITLE)
        expect(foreign_card).to_be_visible()
        foreign_card.get_by_test_id("preset-favorite").click()

        # Избранное попадает в меню у мимика читателя.
        reader_agent_page = f"/agent/{reader_agent_id}?tab=settings"
        reader.goto(reader_agent_page)
        reader.get_by_test_id("open-presets").click()
        option = reader.get_by_role("option", name=re.compile(TITLE))
        option.click()
        expect(reader.get_by_test_id("preset-body")).to_contain_text(PROMPT)
        reader.get_by_role("button", name="Отмена").click()

        # Автор снимает с витрины — у читателя остаётся замороженная копия.
        author.goto("/presets")
        author.get_by_test_id("presets-tab-mine").click()
        author_card = _card(author, TITLE)
        author_card.get_by_test_id("preset-unpublish").click()

        reader.goto("/presets")
        reader.get_by_test_id("presets-tab-favorites").click()
        frozen_card = _card(reader, TITLE)
        expect(frozen_card.get_by_text("Копия")).to_be_visible()

        # Снова в меню мимика: снимок доступен вместо съеденного пресета.
        reader.goto(reader_agent_page)
        reader.get_by_test_id("open-presets").click()
        option = reader.get_by_role("option", name=re.compile(TITLE))
        option.click()
        expect(reader.get_by_test_id("preset-body")).to_contain_text(PROMPT)
        reader.get_by_role("button", name="Отмена").click()

        # Уборка: читатель снимает избранное, автор удаляет пресет.
        reader.goto("/presets")
        reader.get_by_test_id("presets-tab-favorites").click()
        _card(reader, TITLE).get_by_test_id("preset-unfavorite").click()

        author.goto("/presets")
        author.get_by_test_id("presets-tab-mine").click()
        cleanup_card = _card(author, TITLE)
        cleanup_card.get_by_test_id("preset-delete").click()
        cleanup_card.get_by_test_id("preset-delete").click()
        expect(_card(author, TITLE)).to_have_count(0)
