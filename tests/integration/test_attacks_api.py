"""HTTP-контракт атак: маршруты, владение, версии и медиа пула.

``AttackService`` подменён: здесь проверяется граница API — разбор формы,
статусы ошибок, сборка ответа и проверка папки владельца. Жизненный цикл
кампании покрыт ``test_attack_service.py`` и ``test_attack_repository.py``;
настоящий сервис участвует только в проверке двух новых чтений.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from io import BytesIO
from typing import Any, cast
from uuid import UUID, uuid4

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, Response
from PIL import Image

from mimic42.api.app import AgentManagerLike, create_app
from mimic42.config import Settings
from mimic42.core.agent_runtime import AgentRuntimeState, AgentStatus
from mimic42.core.attack import (
    AttackAgentStatus,
    AttackConfig,
    AttackEndReason,
    AttackNotFoundError,
    AttackPatch,
    AttackStateError,
    AttackStatus,
    AttackVersionConflictError,
    AttackView,
    ExitReason,
    MessagesLimit,
    MinutesLimit,
    ParticipationView,
    parse_target_link,
)
from mimic42.core.attack_service import (
    AgentAvailability,
    AttackActivityPort,
    AttackManagerPort,
    AttackRepositoryPort,
    AttackService,
)
from mimic42.core.media import MediaFile
from tests.api.auth_helpers import AUTH_HEADERS, FakeAuthVerifier

NOW = datetime(2026, 11, 16, 12, 0, tzinfo=UTC)
LIVE = (AttackAgentStatus.ASSIGNED, AttackAgentStatus.ACTIVE)
CLOSED = (AttackStatus.CANCELLED, AttackStatus.FINISHED)


def _image_bytes(image_format: str) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (4, 4), color=(30, 120, 200)).save(buffer, format=image_format)
    return buffer.getvalue()


PNG = _image_bytes("PNG")


def _config(*, media_paths: Sequence[str] = ()) -> AttackConfig:
    return AttackConfig(
        title="Розыгрыш",
        target=parse_target_link("https://t.me/example/412"),
        texts=("Участвую!",),
        media_paths=tuple(media_paths),
        limit=MessagesLimit(5),
    )


def _participation(
    attack_id: UUID,
    agent_id: UUID,
    status: AttackAgentStatus,
    *,
    exit_reason: ExitReason | None = None,
) -> ParticipationView:
    return ParticipationView(
        id=uuid4(),
        attack_id=attack_id,
        agent_id=agent_id,
        status=status,
        sent_count=0,
        next_at=None,
        last_error=None,
        exit_reason=exit_reason,
        note_written_at=None,
    )


def _view(
    owner_id: UUID,
    *,
    config: AttackConfig | None = None,
    status: AttackStatus = AttackStatus.DRAFT,
    agents: Sequence[UUID] = (),
    version: int = 1,
    sent_count: int = 0,
    claimed_count: int = 0,
    started_at: datetime | None = None,
    finished_at: datetime | None = None,
    end_reason: AttackEndReason | None = None,
    deadline_at: datetime | None = None,
    slowmode_seconds: int | None = None,
) -> AttackView:
    attack_id = uuid4()
    if status is AttackStatus.RUNNING:
        rows = tuple(
            _participation(attack_id, agent_id, AttackAgentStatus.ACTIVE) for agent_id in agents
        )
    elif status in CLOSED:
        exit_reason = (
            ExitReason.ATTACK_CANCELLED
            if status is AttackStatus.CANCELLED
            else ExitReason.ATTACK_FINISHED
        )
        rows = tuple(
            _participation(attack_id, agent_id, AttackAgentStatus.EXITED, exit_reason=exit_reason)
            for agent_id in agents
        )
    else:
        rows = tuple(
            _participation(attack_id, agent_id, AttackAgentStatus.ASSIGNED) for agent_id in agents
        )
    return AttackView(
        id=attack_id,
        owner_id=owner_id,
        config=config or _config(),
        status=status,
        sent_count=sent_count,
        claimed_count=claimed_count,
        version=version,
        started_at=started_at,
        finished_at=finished_at,
        end_reason=end_reason,
        participations=rows,
        slowmode_seconds=slowmode_seconds,
        deadline_at=deadline_at,
    )


class FakeAttacks:
    """Срез ``AttackService`` на памяти: ровно то, что вызывает роутер."""

    def __init__(self) -> None:
        self.attacks: dict[UUID, AttackView] = {}
        self.availability: dict[UUID, list[AgentAvailability]] = {}
        self.created_configs: list[AttackConfig] = []
        self.assigned: list[tuple[UUID, UUID]] = []
        self.paused: list[tuple[UUID, UUID]] = []
        self.start_calls: list[UUID] = []

    def seed(self, view: AttackView) -> AttackView:
        self.attacks[view.id] = view
        return view

    def _get(self, attack_id: UUID) -> AttackView:
        view = self.attacks.get(attack_id)
        if view is None:
            raise AttackNotFoundError(f"Атака {attack_id} не найдена")
        return view

    def _store(self, view: AttackView) -> AttackView:
        self.attacks[view.id] = view
        return view

    def _detach(self, agent_ids: Sequence[UUID]) -> None:
        wanted = set(agent_ids)
        for view in list(self.attacks.values()):
            rows = [
                replace(row, status=AttackAgentStatus.EXITED, exit_reason=ExitReason.MOVED)
                if row.agent_id in wanted and row.status in LIVE
                else row
                for row in view.participations
            ]
            if rows == list(view.participations):
                continue
            status = view.status
            finished_at = view.finished_at
            end_reason = view.end_reason
            if status is AttackStatus.RUNNING and not any(row.status in LIVE for row in rows):
                status = AttackStatus.CANCELLED
                finished_at = NOW
                end_reason = AttackEndReason.NO_AGENTS
            self._store(
                replace(
                    view,
                    status=status,
                    finished_at=finished_at,
                    end_reason=end_reason,
                    participations=tuple(rows),
                )
            )

    async def create_attack(
        self,
        owner_id: UUID,
        config: AttackConfig,
        agent_ids: Sequence[UUID],
    ) -> AttackView:
        self.created_configs.append(config)
        self._detach(agent_ids)
        return self.seed(_view(owner_id, config=config, agents=agent_ids))

    async def update_attack(self, attack_id: UUID, patch: AttackPatch) -> AttackView:
        view = self._get(attack_id)
        if patch.version != view.version:
            raise AttackVersionConflictError("версия устарела")
        if view.status not in (AttackStatus.DRAFT, AttackStatus.RUNNING):
            raise AttackStateError("Править можно только черновик или идущую атаку")
        deadline_at = (
            view.started_at + timedelta(minutes=patch.limit.minutes)
            if isinstance(patch.limit, MinutesLimit) and view.started_at is not None
            else None
        )
        return self._store(
            replace(
                view,
                config=replace(
                    view.config,
                    title=patch.title,
                    texts=patch.texts,
                    media_paths=patch.media_paths,
                    limit=patch.limit,
                ),
                version=view.version + 1,
                deadline_at=deadline_at,
            )
        )

    async def start_attack(self, attack_id: UUID) -> AttackView:
        view = self._get(attack_id)
        self.start_calls.append(attack_id)
        if view.status is AttackStatus.RUNNING:
            return view
        if view.status is not AttackStatus.DRAFT:
            raise AttackStateError("Запустить можно только черновик")
        if not any(row.status is AttackAgentStatus.ASSIGNED for row in view.participations):
            raise AttackStateError("В атаке нет назначенных мимиков")
        rows = tuple(
            replace(row, status=AttackAgentStatus.ACTIVE)
            if row.status is AttackAgentStatus.ASSIGNED
            else row
            for row in view.participations
        )
        deadline_at = (
            NOW + timedelta(minutes=view.config.limit_value)
            if isinstance(view.config.limit, MinutesLimit)
            else None
        )
        return self._store(
            replace(
                view,
                status=AttackStatus.RUNNING,
                started_at=NOW,
                deadline_at=deadline_at,
                participations=rows,
            )
        )

    async def cancel_attack(self, attack_id: UUID, reason: AttackEndReason) -> AttackView:
        view = self._get(attack_id)
        if view.status in CLOSED:
            return view
        rows = tuple(
            replace(row, status=AttackAgentStatus.EXITED, exit_reason=ExitReason.ATTACK_CANCELLED)
            if row.status in LIVE
            else row
            for row in view.participations
        )
        return self._store(
            replace(
                view,
                status=AttackStatus.CANCELLED,
                finished_at=NOW,
                end_reason=reason,
                participations=rows,
            )
        )

    async def repeat_attack(self, attack_id: UUID) -> AttackView:
        view = self._get(attack_id)
        if view.status not in CLOSED:
            raise AttackStateError("Повторить можно только завершённую или отменённую атаку")
        agents = tuple(dict.fromkeys(row.agent_id for row in view.participations))
        return self.seed(_view(view.owner_id, config=view.config, agents=agents))

    async def assign_agent(self, attack_id: UUID, agent_id: UUID) -> ParticipationView:
        view = self._get(attack_id)
        if view.status not in (AttackStatus.DRAFT, AttackStatus.RUNNING):
            raise AttackStateError("Добавлять мимиков можно в черновик или идущую атаку")
        existing = next(
            (row for row in view.participations if row.agent_id == agent_id and row.status in LIVE),
            None,
        )
        if existing is not None:
            return existing
        self._detach([agent_id])
        view = self._get(attack_id)
        row = _participation(
            attack_id,
            agent_id,
            AttackAgentStatus.ACTIVE
            if view.status is AttackStatus.RUNNING
            else AttackAgentStatus.ASSIGNED,
        )
        self._store(replace(view, participations=view.participations + (row,)))
        self.assigned.append((attack_id, agent_id))
        return row

    async def pause_agent(self, attack_id: UUID, agent_id: UUID) -> ParticipationView:
        view = self._get(attack_id)
        live = next(
            (
                row
                for row in reversed(view.participations)
                if row.agent_id == agent_id and row.status in LIVE
            ),
            None,
        )
        if live is None:
            raise AttackNotFoundError(f"Мимик {agent_id} не участвует в атаке {attack_id}")
        rows = tuple(
            replace(row, status=AttackAgentStatus.EXITED, exit_reason=ExitReason.PAUSED)
            if row.id == live.id
            else row
            for row in view.participations
        )
        status = view.status
        finished_at = view.finished_at
        end_reason = view.end_reason
        if status is AttackStatus.RUNNING and not any(row.status in LIVE for row in rows):
            status = AttackStatus.CANCELLED
            finished_at = NOW
            end_reason = AttackEndReason.NO_AGENTS
        self._store(
            replace(
                view,
                status=status,
                finished_at=finished_at,
                end_reason=end_reason,
                participations=rows,
            )
        )
        self.paused.append((attack_id, agent_id))
        return next(row for row in rows if row.id == live.id)

    async def list(self, owner_id: UUID) -> Sequence[AttackView]:
        return [view for view in self.attacks.values() if view.owner_id == owner_id]

    async def get(self, attack_id: UUID) -> AttackView | None:
        return self.attacks.get(attack_id)

    async def agent_availability(self, owner_id: UUID) -> Sequence[AgentAvailability]:
        return list(self.availability.get(owner_id, []))


class FakeManager:
    def __init__(
        self,
        attacks: FakeAttacks,
        states: Mapping[UUID, AgentRuntimeState] | None = None,
    ) -> None:
        self.attacks = attacks
        self.states = dict(states or {})

    async def list_agents(self, *, owner_id: UUID | None = None) -> list[AgentStatus]:
        return [
            AgentStatus(
                agent_id=agent_id,
                owner_id=owner_id or uuid4(),
                state=state,
            )
            for agent_id, state in self.states.items()
        ]


class FakeAttackStorage:
    def __init__(self, files: Mapping[str, bytes] | None = None) -> None:
        self.files = dict(files or {})
        self.uploaded: list[dict[str, Any]] = []
        self.signed: list[tuple[str, timedelta]] = []

    async def upload(
        self,
        *,
        agent_id: UUID,
        filename: str,
        data: bytes,
        mime_type: str,
        kind: str = "doc",
    ) -> MediaFile | None:
        return await self.upload_at_prefix(
            path_prefix=str(agent_id),
            filename=filename,
            data=data,
            mime_type=mime_type,
            kind=kind,
        )

    async def remove_prefix(self, agent_id: UUID) -> None:
        self.files = {
            path: data for path, data in self.files.items() if not path.startswith(f"{agent_id}/")
        }

    async def upload_at_prefix(
        self,
        *,
        path_prefix: str,
        filename: str,
        data: bytes,
        mime_type: str,
        kind: str = "doc",
    ) -> MediaFile | None:
        path = f"{path_prefix}/{uuid4()}/{filename}"
        self.uploaded.append(
            {
                "path_prefix": path_prefix,
                "path": path,
                "filename": filename,
                "mime_type": mime_type,
                "kind": kind,
            }
        )
        self.files[path] = data
        return MediaFile(
            kind=kind,
            name=filename,
            mime_type=mime_type,
            size=len(data),
            storage_path=path,
        )

    async def open(self, path: str) -> bytes | None:
        return self.files.get(path)

    async def sign_link(self, path: str, *, ttl: timedelta) -> str | None:
        self.signed.append((path, ttl))
        if path not in self.files:
            return None
        return f"https://storage.test/{path}"


def _app(
    owner_id: UUID,
    service: FakeAttacks,
    storage: FakeAttackStorage | None = None,
    manager: FakeManager | None = None,
) -> FastAPI:
    return create_app(
        manager=cast(AgentManagerLike, manager or FakeManager(service)),
        auth_verifier=FakeAuthVerifier(owner_id),
        media_uploader=storage,
        settings=Settings(supabase_url=None, supabase_service_key=None),
    )


def _payload(
    owner_id: UUID,
    *,
    media_paths: Sequence[str] = (),
    agent_ids: Sequence[UUID] = (),
    limit_kind: str = "messages",
    message_limit: int | None = 5,
    duration_minutes: int | None = None,
    title: str = "Розыгрыш",
) -> dict[str, Any]:
    return {
        "title": title,
        "target_link": "https://t.me/example/412",
        "texts": ["Участвую!"],
        "images": [{"path": path, "name": path.rsplit("/", 1)[-1]} for path in media_paths],
        "limit_kind": limit_kind,
        "message_limit": message_limit,
        "duration_minutes": duration_minutes,
        "agent_ids": [str(agent_id) for agent_id in agent_ids],
    }


def _media_path(owner_id: UUID, name: str = "a.png") -> str:
    return f"attacks/{owner_id}/{uuid4()}/{name}"


async def _request(app: FastAPI, method: str, path: str, **kwargs: Any) -> Response:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        return await client.request(method, path, headers=AUTH_HEADERS, **kwargs)


async def test_create_parses_the_link_and_builds_the_attack_config() -> None:
    owner_id = uuid4()
    agent_id = uuid4()
    media_path = _media_path(owner_id)
    service = FakeAttacks()
    service.availability[owner_id] = [
        AgentAvailability(
            agent_id=agent_id,
            name="Мимик А",
            state=AgentRuntimeState.STOPPED,
            telegram_authorized=True,
            warmup_restricted_at=None,
            active_attack_id=None,
        )
    ]
    storage = FakeAttackStorage({media_path: PNG})

    response = await _request(
        _app(owner_id, service, storage),
        "POST",
        "/api/v1/attacks",
        json=_payload(owner_id, media_paths=[media_path], agent_ids=[agent_id]),
    )

    assert response.status_code == 201
    body = response.json()
    assert body["target_link"] == "https://t.me/example/412"
    assert body["status"] == "draft"
    assert body["limit_kind"] == "messages"
    assert body["limit_value"] == 5
    assert body["texts"] == ["Участвую!"]
    assert body["media"] == [
        {
            "path": media_path,
            "name": "a.png",
            "url": f"https://storage.test/{media_path}",
        }
    ]
    assert body["agents"][0]["name"] == "Мимик А"
    assert body["agents"][0]["status"] == "assigned"
    config = service.created_configs[0]
    assert config.target.link == "https://t.me/example/412"
    assert config.target.channel == "example"
    assert config.target.post_id == 412
    assert config.media_paths == (media_path,)


async def test_list_splits_active_and_archive_and_joins_agent_names() -> None:
    owner_id = uuid4()
    agent_id = uuid4()
    other_id = uuid4()
    service = FakeAttacks()
    service.availability[owner_id] = [
        AgentAvailability(
            agent_id=agent_id,
            name="Мимик А",
            state=AgentRuntimeState.RUNNING,
            telegram_authorized=True,
            warmup_restricted_at=None,
            active_attack_id=None,
        )
    ]
    running = service.seed(
        _view(owner_id, status=AttackStatus.RUNNING, agents=[agent_id], started_at=NOW)
    )
    draft = service.seed(_view(owner_id, status=AttackStatus.DRAFT, agents=[agent_id]))
    cancelled = service.seed(
        _view(
            owner_id,
            status=AttackStatus.CANCELLED,
            agents=[agent_id],
            finished_at=NOW,
            end_reason=AttackEndReason.CANCELLED_BY_USER,
        )
    )
    finished = service.seed(
        _view(
            owner_id,
            status=AttackStatus.FINISHED,
            agents=[agent_id],
            finished_at=NOW,
            end_reason=AttackEndReason.LIMIT_REACHED,
        )
    )
    service.seed(_view(other_id, status=AttackStatus.RUNNING, agents=[uuid4()]))

    response = await _request(_app(owner_id, service), "GET", "/api/v1/attacks")

    assert response.status_code == 200
    body = response.json()
    assert [item["id"] for item in body["active"]] == [str(running.id), str(draft.id)]
    assert [item["id"] for item in body["archive"]] == [str(cancelled.id), str(finished.id)]
    assert body["archive"][0]["end_reason"] == "cancelled_by_user"
    assert body["active"][0]["agents"][0]["name"] == "Мимик А"
    assert all(item["owner_id"] == str(owner_id) for item in body["active"])
    assert "texts" not in body["active"][0]
    assert "media" not in body["active"][0]


async def test_detail_returns_texts_signed_media_and_progress_fields() -> None:
    owner_id = uuid4()
    media_path = _media_path(owner_id)
    service = FakeAttacks()
    view = service.seed(
        _view(
            owner_id,
            status=AttackStatus.RUNNING,
            started_at=NOW,
            sent_count=3,
            claimed_count=4,
            slowmode_seconds=30,
        )
    )
    storage = FakeAttackStorage({media_path: PNG})
    view = replace(view, config=_config(media_paths=[media_path]))
    service.seed(view)

    response = await _request(_app(owner_id, service, storage), "GET", f"/api/v1/attacks/{view.id}")

    assert response.status_code == 200
    body = response.json()
    assert body["texts"] == ["Участвую!"]
    assert body["sent_count"] == 3
    assert body["claimed_count"] == 4
    assert body["slowmode_seconds"] == 30
    assert body["media"][0]["url"] == f"https://storage.test/{media_path}"
    assert body["media"][0]["name"] == "a.png"


async def test_detail_omits_a_media_url_when_storage_is_unavailable() -> None:
    owner_id = uuid4()
    media_path = _media_path(owner_id)
    service = FakeAttacks()
    view = service.seed(_view(owner_id, config=_config(media_paths=[media_path])))

    response = await _request(
        _app(owner_id, service, storage=None), "GET", f"/api/v1/attacks/{view.id}"
    )

    assert response.status_code == 200
    assert response.json()["media"] == [{"path": media_path, "name": "a.png"}]


async def test_patch_updates_content_and_bumps_the_version() -> None:
    owner_id = uuid4()
    media_path = _media_path(owner_id)
    service = FakeAttacks()
    view = service.seed(_view(owner_id))
    storage = FakeAttackStorage({media_path: PNG})
    payload = {
        "version": 1,
        "title": "Новое название",
        "texts": ["Новый текст"],
        "images": [{"path": media_path, "name": "a.png"}],
        "limit_kind": "minutes",
        "message_limit": None,
        "duration_minutes": 30,
    }

    response = await _request(
        _app(owner_id, service, storage),
        "PATCH",
        f"/api/v1/attacks/{view.id}",
        json=payload,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "Новое название"
    assert body["texts"] == ["Новый текст"]
    assert body["limit_kind"] == "minutes"
    assert body["limit_value"] == 30
    assert body["version"] == 2
    assert body["media"][0]["path"] == media_path


async def test_patch_rejects_a_stale_version() -> None:
    owner_id = uuid4()
    service = FakeAttacks()
    view = service.seed(_view(owner_id, version=2))
    payload = {
        "version": 1,
        "title": "Новое название",
        "texts": ["Новый текст"],
        "images": [],
        "limit_kind": "messages",
        "message_limit": 5,
        "duration_minutes": None,
    }

    response = await _request(
        _app(owner_id, service), "PATCH", f"/api/v1/attacks/{view.id}", json=payload
    )

    assert response.status_code == 409
    assert "изменена" in response.json()["detail"]
    assert service.attacks[view.id].version == 2


async def test_patch_has_no_link_field() -> None:
    owner_id = uuid4()
    service = FakeAttacks()
    view = service.seed(_view(owner_id))
    payload = {
        "version": 1,
        "target_link": "https://t.me/other/7",
        "texts": ["Текст"],
        "images": [],
        "limit_kind": "messages",
        "message_limit": 5,
        "duration_minutes": None,
    }

    response = await _request(
        _app(owner_id, service), "PATCH", f"/api/v1/attacks/{view.id}", json=payload
    )

    assert response.status_code == 422
    assert service.attacks[view.id].version == 1


async def test_start_without_agents_is_a_conflict() -> None:
    owner_id = uuid4()
    service = FakeAttacks()
    view = service.seed(_view(owner_id))

    response = await _request(_app(owner_id, service), "POST", f"/api/v1/attacks/{view.id}/start")

    assert response.status_code == 409
    assert "нет назначенных" in response.json()["detail"]
    assert service.attacks[view.id].status is AttackStatus.DRAFT


async def test_start_cancel_and_repeat_follow_the_lifecycle() -> None:
    owner_id = uuid4()
    agent_id = uuid4()
    service = FakeAttacks()
    draft = service.seed(_view(owner_id, agents=[agent_id]))
    app = _app(owner_id, service)

    started = await _request(app, "POST", f"/api/v1/attacks/{draft.id}/start")
    assert started.status_code == 200
    assert started.json()["status"] == "running"
    assert started.json()["agents"][0]["status"] == "active"
    assert started.json()["started_at"] is not None

    cancelled = await _request(app, "POST", f"/api/v1/attacks/{draft.id}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    assert cancelled.json()["end_reason"] == "cancelled_by_user"
    assert cancelled.json()["agents"][0]["exit_reason"] == "attack_cancelled"

    repeated = await _request(app, "POST", f"/api/v1/attacks/{draft.id}/repeat")
    assert repeated.status_code == 201
    body = repeated.json()
    assert body["id"] != str(draft.id)
    assert body["status"] == "draft"
    assert body["texts"] == ["Участвую!"]
    assert body["agents"][0]["status"] == "assigned"
    assert service.attacks[draft.id].status is AttackStatus.CANCELLED


async def test_a_foreign_attack_is_indistinguishable_from_a_missing_one() -> None:
    owner_id = uuid4()
    stranger_id = uuid4()
    agent_id = uuid4()
    service = FakeAttacks()
    view = service.seed(_view(owner_id, agents=[agent_id]))
    app = _app(stranger_id, service)
    patch = {
        "version": 1,
        "texts": ["Текст"],
        "images": [],
        "limit_kind": "messages",
        "message_limit": 5,
        "duration_minutes": None,
    }

    detail = await _request(app, "GET", f"/api/v1/attacks/{view.id}")
    update = await _request(app, "PATCH", f"/api/v1/attacks/{view.id}", json=patch)
    start = await _request(app, "POST", f"/api/v1/attacks/{view.id}/start")
    cancel = await _request(app, "POST", f"/api/v1/attacks/{view.id}/cancel")
    repeat = await _request(app, "POST", f"/api/v1/attacks/{view.id}/repeat")
    add = await _request(
        app,
        "POST",
        f"/api/v1/attacks/{view.id}/agents",
        json={"agent_id": str(uuid4())},
    )
    remove = await _request(app, "DELETE", f"/api/v1/attacks/{view.id}/agents/{agent_id}")

    assert {
        detail.status_code,
        update.status_code,
        start.status_code,
        cancel.status_code,
        repeat.status_code,
        add.status_code,
        remove.status_code,
    } == {404}
    assert service.attacks[view.id].version == 1
    assert service.attacks[view.id].status is AttackStatus.DRAFT


async def test_adding_an_agent_moves_it_out_of_another_running_attack() -> None:
    owner_id = uuid4()
    agent_id = uuid4()
    service = FakeAttacks()
    running = service.seed(
        _view(owner_id, status=AttackStatus.RUNNING, agents=[agent_id], started_at=NOW)
    )
    draft = service.seed(_view(owner_id))
    app = _app(owner_id, service)

    added = await _request(
        app,
        "POST",
        f"/api/v1/attacks/{draft.id}/agents",
        json={"agent_id": str(agent_id)},
    )

    assert added.status_code == 200
    assert added.json()["agents"][0]["agent_id"] == str(agent_id)
    assert added.json()["agents"][0]["status"] == "assigned"
    assert service.assigned == [(draft.id, agent_id)]
    old = service.attacks[running.id]
    assert old.status is AttackStatus.CANCELLED
    assert old.end_reason is AttackEndReason.NO_AGENTS
    assert old.participations[0].exit_reason is ExitReason.MOVED


async def test_removing_agents_pauses_and_cancels_the_empty_attack() -> None:
    owner_id = uuid4()
    first = uuid4()
    second = uuid4()
    service = FakeAttacks()
    view = service.seed(
        _view(
            owner_id,
            status=AttackStatus.RUNNING,
            agents=[first, second],
            started_at=NOW,
        )
    )
    app = _app(owner_id, service)

    removed = await _request(app, "DELETE", f"/api/v1/attacks/{view.id}/agents/{first}")

    assert removed.status_code == 200
    rows = {row["agent_id"]: row for row in removed.json()["agents"]}
    assert rows[str(first)]["status"] == "exited"
    assert rows[str(first)]["exit_reason"] == "paused"
    assert rows[str(second)]["status"] == "active"
    assert removed.json()["status"] == "running"

    last = await _request(app, "DELETE", f"/api/v1/attacks/{view.id}/agents/{second}")

    assert last.status_code == 200
    assert last.json()["status"] == "cancelled"
    assert last.json()["end_reason"] == "no_agents"
    assert service.paused == [(view.id, first), (view.id, second)]


async def test_availability_reports_runtime_state_and_existing_attack() -> None:
    owner_id = uuid4()
    first = uuid4()
    second = uuid4()
    active_attack = uuid4()
    service = FakeAttacks()
    service.availability[owner_id] = [
        AgentAvailability(
            agent_id=first,
            name="Мимик А",
            state=AgentRuntimeState.STOPPED,
            telegram_authorized=True,
            warmup_restricted_at=None,
            active_attack_id=None,
        ),
        AgentAvailability(
            agent_id=second,
            name="Мимик Б",
            state=AgentRuntimeState.RUNNING,
            telegram_authorized=False,
            warmup_restricted_at=NOW,
            active_attack_id=active_attack,
        ),
    ]
    manager = FakeManager(service, {first: AgentRuntimeState.RUNNING})

    response = await _request(
        _app(owner_id, service, manager=manager), "GET", "/api/v1/attacks/agents"
    )

    assert response.status_code == 200
    assert response.json() == [
        {
            "agent_id": str(first),
            "name": "Мимик А",
            "state": "running",
            "telegram_authorized": True,
            "warmup_restricted_at": None,
            "active_attack_id": None,
        },
        {
            "agent_id": str(second),
            "name": "Мимик Б",
            "state": "running",
            "telegram_authorized": False,
            "warmup_restricted_at": NOW.isoformat().replace("+00:00", "Z"),
            "active_attack_id": str(active_attack),
        },
    ]


async def test_upload_stores_an_image_under_the_owner_prefix() -> None:
    owner_id = uuid4()
    service = FakeAttacks()
    storage = FakeAttackStorage()

    response = await _request(
        _app(owner_id, service, storage),
        "POST",
        "/api/v1/attack-media",
        files={"file": ("pic.png", PNG, "image/png")},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["storage_path"].startswith(f"attacks/{owner_id}/")
    assert body["mime_type"] == "image/png"
    assert body["size"] == len(PNG)
    assert body["name"] == "pic.png"
    assert storage.uploaded == [
        {
            "path_prefix": f"attacks/{owner_id}",
            "path": body["storage_path"],
            "filename": "pic.png",
            "mime_type": "image/png",
            "kind": "photo",
        }
    ]


async def test_upload_keeps_an_extension_when_the_name_is_not_ascii() -> None:
    owner_id = uuid4()
    service = FakeAttacks()
    storage = FakeAttackStorage()

    response = await _request(
        _app(owner_id, service, storage),
        "POST",
        "/api/v1/attack-media",
        files={"file": ("кадр.png", PNG, "image/png")},
    )

    assert response.status_code == 201
    assert response.json()["name"] == "image.png"
    assert storage.uploaded[0]["filename"] == "image.png"


async def test_upload_refuses_a_file_that_only_claims_to_be_an_image() -> None:
    owner_id = uuid4()
    service = FakeAttacks()
    storage = FakeAttackStorage()

    response = await _request(
        _app(owner_id, service, storage),
        "POST",
        "/api/v1/attack-media",
        files={"file": ("pic.png", b"%PDF-1.7", "image/png")},
    )

    assert response.status_code == 415
    assert storage.uploaded == []


async def test_create_refuses_media_of_another_owner() -> None:
    owner_id = uuid4()
    foreign_path = _media_path(uuid4())
    service = FakeAttacks()
    storage = FakeAttackStorage({foreign_path: PNG})

    response = await _request(
        _app(owner_id, service, storage),
        "POST",
        "/api/v1/attacks",
        json=_payload(owner_id, media_paths=[foreign_path]),
    )

    assert response.status_code == 403
    assert service.created_configs == []


async def test_media_link_refuses_a_foreign_path() -> None:
    owner_id = uuid4()
    foreign_path = _media_path(uuid4())
    service = FakeAttacks()
    storage = FakeAttackStorage({foreign_path: PNG})

    response = await _request(
        _app(owner_id, service, storage),
        "GET",
        f"/api/v1/attack-media-link/{foreign_path}",
    )

    assert response.status_code == 403
    assert storage.signed == []


async def test_attack_media_is_served_only_inside_the_owner_folder() -> None:
    owner_id = uuid4()
    path = _media_path(owner_id)
    foreign_path = _media_path(uuid4())
    service = FakeAttacks()
    storage = FakeAttackStorage({path: PNG, foreign_path: PNG})
    app = _app(owner_id, service, storage)

    own = await _request(app, "GET", f"/api/v1/attack-media/{path}")
    foreign = await _request(app, "GET", f"/api/v1/attack-media/{foreign_path}")
    missing = await _request(
        app, "GET", f"/api/v1/attack-media/{_media_path(owner_id, 'missing.png')}"
    )

    assert own.status_code == 200
    assert own.headers["content-type"] == "image/png"
    assert own.content == PNG
    assert foreign.status_code == 403
    assert missing.status_code == 404


async def test_attack_media_rejects_path_traversal() -> None:
    owner_id = uuid4()
    foreign_id = uuid4()
    path = f"attacks/{owner_id}/%2e%2e/{foreign_id}/{uuid4()}/secret.png"
    service = FakeAttacks()
    storage = FakeAttackStorage()

    media = await _request(_app(owner_id, service, storage), "GET", f"/api/v1/attack-media/{path}")
    link = await _request(
        _app(owner_id, service, storage), "GET", f"/api/v1/attack-media-link/{path}"
    )

    assert media.status_code == 403
    assert link.status_code == 403
    assert storage.signed == []


async def test_media_routes_report_unavailable_storage() -> None:
    owner_id = uuid4()
    service = FakeAttacks()
    app = _app(owner_id, service, storage=None)
    path = _media_path(owner_id)

    upload = await _request(
        app,
        "POST",
        "/api/v1/attack-media",
        files={"file": ("pic.png", PNG, "image/png")},
    )
    media = await _request(app, "GET", f"/api/v1/attack-media/{path}")
    link = await _request(app, "GET", f"/api/v1/attack-media-link/{path}")

    assert upload.status_code == 503
    assert media.status_code == 503
    assert link.status_code == 503


async def test_service_forwards_reads_to_the_repository() -> None:
    owner_id = uuid4()
    view = _view(owner_id)
    availability = AgentAvailability(
        agent_id=uuid4(),
        name="Мимик",
        state=AgentRuntimeState.STOPPED,
        telegram_authorized=True,
        warmup_restricted_at=None,
        active_attack_id=None,
    )

    class ReadRepo:
        async def list_attacks(self, owner: UUID) -> list[AttackView]:
            assert owner == owner_id
            return [view]

        async def load(self, attack_id: UUID) -> AttackView | None:
            return view if attack_id == view.id else None

        async def agent_availability(self, owner: UUID) -> list[AgentAvailability]:
            assert owner == owner_id
            return [availability]

    class NoActivity:
        async def record(self, **_: Any) -> None:
            return None

    service = AttackService(
        cast(AttackManagerPort, object()),
        cast(AttackRepositoryPort, ReadRepo()),
        cast(AttackActivityPort, NoActivity()),
    )

    assert list(await service.list(owner_id)) == [view]
    assert await service.get(view.id) is view
    assert await service.get(uuid4()) is None
    assert list(await service.agent_availability(owner_id)) == [availability]
