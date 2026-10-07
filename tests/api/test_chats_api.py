"""GET /agents/{id}/chats: диалоги аккаунта для настройки доступных чатов."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from mimic42.api.app import create_app
from mimic42.core.agent_runtime import AgentRuntimeConfig, ChatListUnavailableError
from mimic42.core.chat_directory import ChatItem
from tests.api.auth_helpers import AUTH_HEADERS, FakeAuthVerifier
from tests.api.fakes import FakeAgentManager

CHATS = [
    ChatItem(id=-1001000000001, title="Новости", username="news", kind="channel"),
    ChatItem(
        id=-1001000000002,
        title="Комментарии",
        kind="group",
        discussion_of=-1001000000001,
    ),
    ChatItem(id=42, title="Анна", kind="private"),
]


class ChatsAgentManager(FakeAgentManager):
    def __init__(self) -> None:
        super().__init__()
        self.chats: list[ChatItem] = []
        self.unavailable = False
        self.broken = False

    async def list_chats(self, agent_id: UUID) -> list[ChatItem]:
        if self.unavailable:
            raise ChatListUnavailableError("Агент не запущен: запустите его, чтобы увидеть чаты.")
        if self.broken:
            raise RuntimeError("telegram is down")
        return self.chats


async def _agent(manager: FakeAgentManager, owner_id: UUID) -> UUID:
    agent_id = uuid4()
    await manager.create_agent(
        AgentRuntimeConfig(
            agent_id=agent_id,
            owner_id=owner_id,
            telegram_api_id=1,
            telegram_api_hash="hash",
            telegram_session_string="session",
            system_prompt="system",
        )
    )
    return agent_id


def _client(manager: FakeAgentManager, user_id: UUID) -> AsyncClient:
    app = create_app(manager=manager, auth_verifier=FakeAuthVerifier(user_id))
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver")


@pytest.mark.asyncio
async def test_owner_gets_the_dialogs() -> None:
    owner_id = uuid4()
    manager = ChatsAgentManager()
    agent_id = await _agent(manager, owner_id)
    manager.chats = CHATS

    async with _client(manager, owner_id) as client:
        response = await client.get(f"/api/v1/agents/{agent_id}/chats", headers=AUTH_HEADERS)

    assert response.status_code == 200
    assert response.json() == [
        {
            "id": -1001000000001,
            "title": "Новости",
            "username": "news",
            "kind": "channel",
            "discussion_of": None,
        },
        {
            "id": -1001000000002,
            "title": "Комментарии",
            "username": None,
            "kind": "group",
            "discussion_of": -1001000000001,
        },
        {"id": 42, "title": "Анна", "username": None, "kind": "private", "discussion_of": None},
    ]


@pytest.mark.asyncio
async def test_stopped_agent_is_a_conflict_with_a_readable_reason() -> None:
    owner_id = uuid4()
    manager = ChatsAgentManager()
    agent_id = await _agent(manager, owner_id)
    manager.unavailable = True

    async with _client(manager, owner_id) as client:
        response = await client.get(f"/api/v1/agents/{agent_id}/chats", headers=AUTH_HEADERS)

    assert response.status_code == 409
    assert "запустите его" in response.json()["detail"]


@pytest.mark.asyncio
async def test_other_users_cannot_read_the_dialogs() -> None:
    manager = ChatsAgentManager()
    agent_id = await _agent(manager, uuid4())
    manager.chats = CHATS

    async with _client(manager, uuid4()) as client:
        response = await client.get(f"/api/v1/agents/{agent_id}/chats", headers=AUTH_HEADERS)

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_telegram_failure_is_a_bad_gateway_without_leaking_details() -> None:
    owner_id = uuid4()
    manager = ChatsAgentManager()
    agent_id = await _agent(manager, owner_id)
    manager.broken = True

    async with _client(manager, owner_id) as client:
        response = await client.get(f"/api/v1/agents/{agent_id}/chats", headers=AUTH_HEADERS)

    assert response.status_code == 502
    assert "telegram is down" not in response.text


@pytest.mark.asyncio
async def test_manager_without_chat_support_answers_not_implemented() -> None:
    owner_id = uuid4()
    manager = FakeAgentManager()
    agent_id = await _agent(manager, owner_id)

    async with _client(manager, owner_id) as client:
        response = await client.get(f"/api/v1/agents/{agent_id}/chats", headers=AUTH_HEADERS)

    assert response.status_code == 501
