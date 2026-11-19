"""Репозиторий атак: кампания, участия и резерв отправки.

Единственный писатель таблиц ``attacks`` и ``attack_agents``. Каждый метод —
одна короткая транзакция: claim и settle держат строки под ``FOR UPDATE``
только до commit, поэтому отправитель уходит в сеть уже без замков, а отмена
задачи не оставляет транзакцию открытой.
"""

from __future__ import annotations

import random
from collections.abc import Sequence
from dataclasses import replace
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import and_, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from telethon.helpers import generate_random_long

from mimic42.core.agent_runtime import AgentRuntimeState
from mimic42.core.attack import (
    AttackAgentStatus,
    AttackConfig,
    AttackEndReason,
    AttackLimitType,
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
    SendOutcome,
    Settlement,
    SlotClaim,
    TargetRef,
    attack_end_reason,
    compose_comment,
    failure_text,
    validate_config,
)
from mimic42.core.attack_service import AgentAvailability
from mimic42.integrations.database_models import (
    AgentModel,
    AttackAgentModel,
    AttackModel,
    TelegramSessionModel,
)

_LIVE = (AttackAgentStatus.ASSIGNED.value, AttackAgentStatus.ACTIVE.value)
_CLOSED = (AttackStatus.FINISHED.value, AttackStatus.CANCELLED.value)
_EDITABLE = (AttackStatus.DRAFT.value, AttackStatus.RUNNING.value)
_INTERRUPTED_ERROR = "Результат отправки неизвестен: комментарий мог уйти."


class DatabaseAttackRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def create(
        self,
        owner_id: UUID,
        config: AttackConfig,
        agent_ids: Sequence[UUID],
        now: datetime,
    ) -> AttackView:
        validate_config(config)
        async with self._session_factory() as db, db.begin():
            attack = AttackModel(
                owner_id=owner_id,
                title=config.title,
                target_link=config.target.link,
                target_channel_peer=config.target.channel,
                target_message_id=config.target.post_id,
                texts=list(config.texts),
                media_paths=list(config.media_paths),
                limit_type=config.limit_type.value,
                limit_value=config.limit_value,
                status=AttackStatus.DRAFT.value,
                sent_count=0,
                claimed_count=0,
                version=1,
            )
            db.add(attack)
            await db.flush()
            for agent_id in dict.fromkeys(agent_ids):
                await self._lock_agent(db, agent_id, owner_id)
                await self._detach(db, agent_id, now)
                db.add(
                    AttackAgentModel(
                        attack_id=attack.id,
                        agent_id=agent_id,
                        status=AttackAgentStatus.ASSIGNED.value,
                        joined_at=now,
                    )
                )
            await db.flush()
            return _attack_view(attack, await _load_participations(db, attack.id))

    async def update(self, attack_id: UUID, patch: AttackPatch, now: datetime) -> AttackView:
        async with self._session_factory() as db, db.begin():
            attack = await self._lock_attack(db, attack_id)
            if attack is None:
                raise AttackNotFoundError(f"Атака {attack_id} не найдена")
            if attack.version != patch.version:
                raise AttackVersionConflictError(
                    f"Атака {attack_id} изменена: ожидалась версия {patch.version}, "
                    f"в базе {attack.version}"
                )
            if attack.status not in _EDITABLE:
                raise AttackStateError("Править можно только черновик или идущую атаку")
            config = AttackConfig(
                title=patch.title,
                target=TargetRef(
                    link=attack.target_link,
                    channel=attack.target_channel_peer,
                    post_id=attack.target_message_id,
                ),
                texts=patch.texts,
                media_paths=patch.media_paths,
                limit=patch.limit,
            )
            validate_config(config)
            attack.title = config.title
            attack.texts = list(config.texts)
            attack.media_paths = list(config.media_paths)
            attack.limit_type = config.limit_type.value
            attack.limit_value = config.limit_value
            if config.limit_type is AttackLimitType.MINUTES and attack.started_at is not None:
                attack.deadline_at = attack.started_at + timedelta(minutes=config.limit_value)
            else:
                attack.deadline_at = None
            attack.version += 1
            attack.updated_at = now
            await db.flush()
            return _attack_view(attack, await _load_participations(db, attack.id))

    async def start(self, attack_id: UUID, now: datetime) -> AttackView:
        async with self._session_factory() as db, db.begin():
            attack = await self._lock_attack(db, attack_id)
            if attack is None:
                raise AttackNotFoundError(f"Атака {attack_id} не найдена")
            if attack.status == AttackStatus.RUNNING.value:
                return _attack_view(attack, await _load_participations(db, attack.id))
            if attack.status != AttackStatus.DRAFT.value:
                raise AttackStateError("Запустить можно только черновик")
            assigned = list(
                await db.scalars(
                    select(AttackAgentModel)
                    .where(
                        AttackAgentModel.attack_id == attack.id,
                        AttackAgentModel.status == AttackAgentStatus.ASSIGNED.value,
                    )
                    .order_by(AttackAgentModel.joined_at, AttackAgentModel.id)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
            )
            if not assigned:
                raise AttackStateError("В атаке нет назначенных мимиков")
            attack.status = AttackStatus.RUNNING.value
            attack.started_at = now
            if AttackLimitType(attack.limit_type) is AttackLimitType.MINUTES:
                attack.deadline_at = now + timedelta(minutes=attack.limit_value)
            for participation in assigned:
                participation.status = AttackAgentStatus.ACTIVE.value
            await db.flush()
            return _attack_view(attack, await _load_participations(db, attack.id))

    async def cancel(self, attack_id: UUID, reason: AttackEndReason, now: datetime) -> AttackView:
        async with self._session_factory() as db, db.begin():
            attack = await self._lock_attack(db, attack_id)
            if attack is None:
                raise AttackNotFoundError(f"Атака {attack_id} не найдена")
            if attack.status in _CLOSED:
                return _attack_view(attack, await _load_participations(db, attack.id))
            live = list(
                await db.scalars(
                    select(AttackAgentModel)
                    .where(
                        AttackAgentModel.attack_id == attack.id,
                        AttackAgentModel.status.in_(_LIVE),
                    )
                    .order_by(AttackAgentModel.id)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
            )
            for participation in live:
                _exit_row(participation, attack, ExitReason.ATTACK_CANCELLED, now)
            attack.status = AttackStatus.CANCELLED.value
            attack.finished_at = now
            attack.end_reason = reason.value
            await db.flush()
            return _attack_view(attack, await _load_participations(db, attack.id))

    async def repeat(self, attack_id: UUID, now: datetime) -> AttackView:
        async with self._session_factory() as db, db.begin():
            old = await self._lock_attack(db, attack_id)
            if old is None:
                raise AttackNotFoundError(f"Атака {attack_id} не найдена")
            if old.status not in _CLOSED:
                raise AttackStateError("Повторить можно только завершённую или отменённую атаку")
            previous = set(
                await db.scalars(
                    select(AttackAgentModel.agent_id)
                    .where(AttackAgentModel.attack_id == old.id)
                    .distinct()
                )
            )
            blocked = select(AttackAgentModel.agent_id).where(AttackAgentModel.status.in_(_LIVE))
            eligible = (
                list(
                    await db.scalars(
                        select(AgentModel.id)
                        .join(TelegramSessionModel, TelegramSessionModel.agent_id == AgentModel.id)
                        .where(
                            AgentModel.id.in_(previous),
                            AgentModel.owner_id == old.owner_id,
                            AgentModel.warmup_restricted_at.is_(None),
                            TelegramSessionModel.authorization_status == "authorized",
                            AgentModel.id.not_in(blocked),
                        )
                        .order_by(AgentModel.id)
                    )
                )
                if previous
                else []
            )
            attack = AttackModel(
                owner_id=old.owner_id,
                title=old.title,
                target_link=old.target_link,
                target_channel_peer=old.target_channel_peer,
                target_message_id=old.target_message_id,
                target_channel_id=old.target_channel_id,
                anchor_message_id=old.anchor_message_id,
                slowmode_seconds=old.slowmode_seconds,
                texts=list(old.texts),
                media_paths=list(old.media_paths),
                limit_type=old.limit_type,
                limit_value=old.limit_value,
                status=AttackStatus.DRAFT.value,
                sent_count=0,
                claimed_count=0,
                version=1,
            )
            db.add(attack)
            await db.flush()
            for agent_id in eligible:
                db.add(
                    AttackAgentModel(
                        attack_id=attack.id,
                        agent_id=agent_id,
                        status=AttackAgentStatus.ASSIGNED.value,
                        joined_at=now,
                    )
                )
            await db.flush()
            return _attack_view(attack, await _load_participations(db, attack.id))

    async def assign(
        self, attack_id: UUID, agent_id: UUID, owner_id: UUID, now: datetime
    ) -> ParticipationView:
        async with self._session_factory() as db, db.begin():
            await self._lock_agent(db, agent_id, owner_id)
            live = await self._live_participation(db, agent_id)
            attack_ids = {attack_id}
            if live is not None:
                attack_ids.add(live.attack_id)
            locked = await self._lock_attacks(db, attack_ids)
            attack = locked.get(attack_id)
            if attack is None or attack.owner_id != owner_id:
                raise AttackNotFoundError(f"Атака {attack_id} не найдена у владельца")
            if attack.status not in _EDITABLE:
                raise AttackStateError("Добавлять мимиков можно в черновик или идущую атаку")
            if live is not None and live.attack_id == attack.id:
                existing = await self._lock_participation(db, live.id)
                if existing is not None and existing.status in _LIVE:
                    return _participation_view(existing)
                live = None
            if live is not None:
                await self._detach_locked(db, live, locked[live.attack_id], now)
            participation = AttackAgentModel(
                attack_id=attack.id,
                agent_id=agent_id,
                status=(
                    AttackAgentStatus.ACTIVE.value
                    if attack.status == AttackStatus.RUNNING.value
                    else AttackAgentStatus.ASSIGNED.value
                ),
                joined_at=now,
            )
            db.add(participation)
            await db.flush()
            return _participation_view(participation)

    async def pause(
        self, attack_id: UUID, agent_id: UUID, owner_id: UUID, now: datetime
    ) -> ParticipationView:
        async with self._session_factory() as db, db.begin():
            await self._lock_agent(db, agent_id, owner_id)
            attack = await self._lock_attack(db, attack_id)
            if attack is None or attack.owner_id != owner_id:
                raise AttackNotFoundError(f"Атака {attack_id} не найдена у владельца")
            live = await db.scalar(
                select(AttackAgentModel)
                .where(
                    AttackAgentModel.attack_id == attack.id,
                    AttackAgentModel.agent_id == agent_id,
                    AttackAgentModel.status.in_(_LIVE),
                )
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if live is None:
                latest = await db.scalar(
                    select(AttackAgentModel)
                    .where(
                        AttackAgentModel.attack_id == attack.id,
                        AttackAgentModel.agent_id == agent_id,
                    )
                    .order_by(AttackAgentModel.joined_at.desc(), AttackAgentModel.id.desc())
                    .limit(1)
                )
                if latest is None:
                    raise AttackNotFoundError(f"Мимик {agent_id} не участвует в атаке {attack_id}")
                return _participation_view(latest)
            _exit_row(live, attack, ExitReason.PAUSED, now)
            await self._cancel_if_empty(db, attack, now)
            await db.flush()
            return _participation_view(live)

    async def claim(
        self,
        attack_id: UUID,
        agent_id: UUID,
        now: datetime,
        rng: random.Random,
    ) -> SlotClaim | None:
        async with self._session_factory() as db, db.begin():
            attack = await self._lock_attack(db, attack_id)
            if attack is None:
                return None
            participation = await db.scalar(
                select(AttackAgentModel)
                .where(
                    AttackAgentModel.attack_id == attack.id,
                    AttackAgentModel.agent_id == agent_id,
                )
                .order_by(AttackAgentModel.joined_at.desc(), AttackAgentModel.id.desc())
                .limit(1)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if participation is None:
                return None
            if attack.status != AttackStatus.RUNNING.value or (
                participation.status != AttackAgentStatus.ACTIVE.value
            ):
                _release_pending(participation, attack)
                return None
            if participation.pending_random_id is not None:
                return SlotClaim(
                    attack_id=attack.id,
                    agent_id=agent_id,
                    participation_id=participation.id,
                    random_id=participation.pending_random_id,
                    text=participation.pending_text or "",
                    media=tuple(participation.pending_media or ()),
                    message_count=max(1, participation.pending_count),
                )
            remaining: int | None = None
            if AttackLimitType(attack.limit_type) is AttackLimitType.MINUTES:
                if attack.deadline_at is not None and attack.deadline_at <= now:
                    return None
            else:
                remaining = attack.limit_value - attack.claimed_count
                if remaining <= 0:
                    return None
            content = compose_comment(tuple(attack.texts), tuple(attack.media_paths), rng)
            if remaining is not None and len(content.media) > remaining:
                content = replace(content, media=content.media[:remaining])
            message_count = max(1, len(content.media))
            random_id = generate_random_long()
            attack.claimed_count += message_count
            participation.pending_random_id = random_id
            participation.pending_text = content.text
            participation.pending_media = list(content.media)
            participation.pending_count = message_count
            await db.flush()
            return SlotClaim(
                attack_id=attack.id,
                agent_id=agent_id,
                participation_id=participation.id,
                random_id=random_id,
                text=content.text,
                media=content.media,
                message_count=message_count,
            )

    async def settle(
        self,
        claim: SlotClaim,
        outcome: SendOutcome,
        now: datetime,
        next_at: datetime,
    ) -> Settlement:
        async with self._session_factory() as db, db.begin():
            attack = await self._lock_attack(db, claim.attack_id)
            if attack is None:
                raise AttackNotFoundError(f"Атака {claim.attack_id} не найдена")
            participation = await self._lock_participation(db, claim.participation_id)
            if participation is None or participation.pending_random_id != claim.random_id:
                return _settlement(attack)
            if outcome.kind == "sent":
                sent_messages = (
                    outcome.delivered if outcome.delivered is not None else max(1, len(claim.media))
                )
                sent_messages = min(max(sent_messages, 1), claim.message_count)
                partial = (
                    outcome.delivered is not None
                    and bool(claim.media)
                    and sent_messages < claim.message_count
                )
                attack.sent_count += sent_messages
                participation.sent_count += sent_messages
                participation.pending_attempts = 0
                participation.last_error_code = None
                participation.last_error = None
                if outcome.message_id:
                    participation.last_comment_message_id = outcome.message_id
                if partial:
                    remaining = claim.message_count - sent_messages
                    participation.pending_random_id = claim.random_id + sent_messages
                    participation.pending_text = ""
                    participation.pending_media = list(claim.media[sent_messages:])
                    participation.pending_count = remaining
                else:
                    attack.claimed_count -= claim.message_count - sent_messages
                    participation.pending_random_id = None
                    participation.pending_text = None
                    participation.pending_media = None
                    participation.pending_count = 0
            elif outcome.kind == "not_sent":
                _release_pending(participation, attack)
                participation.pending_attempts = 0
                if outcome.failure is not None:
                    participation.last_error_code = outcome.failure.value
                    participation.last_error = failure_text(outcome.failure)
            elif outcome.kind == "unknown":
                participation.pending_attempts += 1
                if outcome.failure is not None:
                    participation.last_error_code = outcome.failure.value
                    participation.last_error = failure_text(outcome.failure)
            else:
                _release_pending(participation, attack)
                participation.last_error_code = "interrupted"
                participation.last_error = _INTERRUPTED_ERROR
            participation.next_at = next_at
            reason = attack_end_reason(
                limit_type=AttackLimitType(attack.limit_type),
                limit_value=attack.limit_value,
                deadline_at=attack.deadline_at,
                sent_count=attack.sent_count,
                claimed_count=attack.claimed_count,
                now=now,
            )
            if attack.status == AttackStatus.RUNNING.value and reason is not None:
                attack.status = AttackStatus.FINISHED.value
                attack.finished_at = now
                attack.end_reason = reason.value
                still_live = await db.scalars(
                    select(AttackAgentModel)
                    .where(
                        AttackAgentModel.attack_id == attack.id,
                        AttackAgentModel.status.in_(_LIVE),
                    )
                    .order_by(AttackAgentModel.id)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
                for row in still_live:
                    _exit_row(row, attack, ExitReason.ATTACK_FINISHED, now)
            await db.flush()
            return _settlement(attack)

    async def finish(self, attack_id: UUID, reason: AttackEndReason, now: datetime) -> AttackView:
        """Завершить идущую атаку, когда лимит или срок уже наступили.

        Финал возможен только без резервов в полёте: слот, который ещё не осел,
        должен сначала получить исход. Повторный вызов на закрытой атаке
        возвращает её как есть.
        """
        async with self._session_factory() as db, db.begin():
            attack = await self._lock_attack(db, attack_id)
            if attack is None:
                raise AttackNotFoundError(f"Атака {attack_id} не найдена")
            if attack.status in _CLOSED:
                return _attack_view(attack, await _load_participations(db, attack.id))
            if attack.status != AttackStatus.RUNNING.value:
                raise AttackStateError("Завершить можно только идущую атаку")
            if attack.claimed_count != attack.sent_count:
                return _attack_view(attack, await _load_participations(db, attack.id))
            attack.status = AttackStatus.FINISHED.value
            attack.finished_at = now
            attack.end_reason = reason.value
            still_live = await db.scalars(
                select(AttackAgentModel)
                .where(
                    AttackAgentModel.attack_id == attack.id,
                    AttackAgentModel.status.in_(_LIVE),
                )
                .order_by(AttackAgentModel.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            for row in still_live:
                _exit_row(row, attack, ExitReason.ATTACK_FINISHED, now)
            await db.flush()
            return _attack_view(attack, await _load_participations(db, attack.id))

    async def set_target(
        self,
        attack_id: UUID,
        channel_id: int | None,
        anchor_id: int | None,
        slowmode_seconds: int | None,
        now: datetime,
    ) -> None:
        """Сохранить публичные id цели и последний slow mode для интерфейса."""
        async with self._session_factory() as db, db.begin():
            attack = await self._lock_attack(db, attack_id)
            if attack is None:
                raise AttackNotFoundError(f"Атака {attack_id} не найдена")
            attack.target_channel_id = channel_id
            attack.anchor_message_id = anchor_id
            attack.slowmode_seconds = slowmode_seconds
            attack.updated_at = now
            await db.flush()

    async def clear_media(self, attack_id: UUID, participation_id: UUID, random_id: int) -> bool:
        """Убрать картинки из резерва, оставив тот же ``random_id`` для текста.

        Резерв остаётся на исходное число сообщений: settle добавит фактически
        отправленный текст и вернёт разницу. Fallback на текст не должен менять
        идентификатор отправки: иначе повтор после сбоя мог бы создать второй
        комментарий.
        """
        async with self._session_factory() as db, db.begin():
            attack = await self._lock_attack(db, attack_id)
            participation = await self._lock_participation(db, participation_id)
            if attack is None or participation is None:
                return False
            if participation.pending_random_id != random_id:
                return False
            participation.pending_media = []
            await db.flush()
            return True

    async def exit_participation(
        self, participation_id: UUID, reason: ExitReason, now: datetime
    ) -> None:
        async with self._session_factory() as db, db.begin():
            keys = (
                await db.execute(
                    select(AttackAgentModel.attack_id, AttackAgentModel.agent_id).where(
                        AttackAgentModel.id == participation_id
                    )
                )
            ).first()
            if keys is None:
                return
            attack_id, agent_id = keys
            agent = await db.scalar(
                select(AgentModel).where(AgentModel.id == agent_id).with_for_update()
            )
            if agent is None:
                return
            attack = await self._lock_attack(db, attack_id)
            participation = await self._lock_participation(db, participation_id)
            if attack is None or participation is None:
                return
            if participation.status == AttackAgentStatus.EXITED.value:
                return
            _exit_row(participation, attack, reason, now)
            await self._cancel_if_empty(
                db,
                attack,
                now,
                end_reason=(
                    AttackEndReason.TARGET_UNAVAILABLE
                    if reason is ExitReason.TARGET_UNAVAILABLE
                    else AttackEndReason.NO_AGENTS
                ),
            )
            await db.flush()

    async def mark_note_written(self, participation_id: UUID, now: datetime) -> bool:
        async with self._session_factory() as db:
            changed = await db.scalar(
                update(AttackAgentModel)
                .where(
                    AttackAgentModel.id == participation_id,
                    AttackAgentModel.note_written_at.is_(None),
                )
                .values(note_written_at=now)
                .returning(AttackAgentModel.id)
            )
            await db.commit()
            return changed is not None

    async def load(self, attack_id: UUID) -> AttackView | None:
        async with self._session_factory() as db:
            attack = await db.get(AttackModel, attack_id)
            if attack is None:
                return None
            return _attack_view(attack, await _load_participations(db, attack.id))

    async def list_attacks(self, owner_id: UUID) -> list[AttackView]:
        async with self._session_factory() as db:
            attacks = list(
                await db.scalars(
                    select(AttackModel)
                    .where(AttackModel.owner_id == owner_id)
                    .order_by(AttackModel.created_at.desc(), AttackModel.id.desc())
                )
            )
            return [
                _attack_view(attack, await _load_participations(db, attack.id))
                for attack in attacks
            ]

    async def agent_availability(self, owner_id: UUID) -> list[AgentAvailability]:
        """Мимики владельца с авторизацией, ограничением и живой атакой.

        Частичный уникальный индекс не даёт мимику двух живых участий, поэтому
        левое соединение с ``attack_agents`` даёт не больше одной строки на
        мимика; отсутствие сессии значит «Telegram не авторизован».
        """
        async with self._session_factory() as db:
            rows = (
                await db.execute(
                    select(
                        AgentModel.id,
                        AgentModel.name,
                        AgentModel.status,
                        AgentModel.warmup_restricted_at,
                        TelegramSessionModel.authorization_status,
                        AttackAgentModel.attack_id,
                    )
                    .outerjoin(
                        TelegramSessionModel,
                        TelegramSessionModel.agent_id == AgentModel.id,
                    )
                    .outerjoin(
                        AttackAgentModel,
                        and_(
                            AttackAgentModel.agent_id == AgentModel.id,
                            AttackAgentModel.status.in_(_LIVE),
                        ),
                    )
                    .where(AgentModel.owner_id == owner_id)
                    .order_by(AgentModel.name, AgentModel.id)
                )
            ).all()
        return [
            AgentAvailability(
                agent_id=agent_id,
                name=name,
                state=_agent_state(status_value),
                telegram_authorized=authorization_status == "authorized",
                warmup_restricted_at=warmup_restricted_at,
                active_attack_id=active_attack_id,
            )
            for (
                agent_id,
                name,
                status_value,
                warmup_restricted_at,
                authorization_status,
                active_attack_id,
            ) in rows
        ]

    async def live_participation(self, agent_id: UUID) -> ParticipationView | None:
        """Живое участие мимика: по нему сервис находит прежнюю атаку при переносе."""
        async with self._session_factory() as db:
            row = await self._live_participation(db, agent_id)
            return _participation_view(row) if row is not None else None

    async def load_running(self) -> list[AttackView]:
        async with self._session_factory() as db:
            attacks = list(
                await db.scalars(
                    select(AttackModel)
                    .where(AttackModel.status == AttackStatus.RUNNING.value)
                    .order_by(AttackModel.created_at, AttackModel.id)
                )
            )
            return [
                _attack_view(attack, await _load_participations(db, attack.id))
                for attack in attacks
            ]

    async def pending_notes(self) -> list[ParticipationView]:
        async with self._session_factory() as db:
            rows = await db.scalars(
                select(AttackAgentModel)
                .where(
                    AttackAgentModel.status == AttackAgentStatus.EXITED.value,
                    AttackAgentModel.note_written_at.is_(None),
                )
                .order_by(AttackAgentModel.exited_at, AttackAgentModel.id)
            )
            return [_participation_view(row) for row in rows]

    async def _lock_agent(self, db: AsyncSession, agent_id: UUID, owner_id: UUID) -> None:
        # Агент блокируется раньше атак: перенос одного мимика сериализуется
        # до того, как транзакция возьмёт замки кампаний.
        agent = await db.scalar(
            select(AgentModel).where(AgentModel.id == agent_id).with_for_update()
        )
        if agent is None or agent.owner_id != owner_id:
            raise AttackNotFoundError(f"Агент {agent_id} не найден у владельца")

    async def _lock_attack(self, db: AsyncSession, attack_id: UUID) -> AttackModel | None:
        return await db.scalar(
            select(AttackModel)
            .where(AttackModel.id == attack_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )

    async def _lock_attacks(
        self, db: AsyncSession, attack_ids: set[UUID]
    ) -> dict[UUID, AttackModel]:
        # Детерминированный порядок не даёт двум переносам мимиков между
        # одними и теми же атаками схватиться за строки крест-накрест.
        rows = await db.scalars(
            select(AttackModel)
            .where(AttackModel.id.in_(attack_ids))
            .order_by(AttackModel.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return {row.id: row for row in rows}

    async def _lock_participation(
        self, db: AsyncSession, participation_id: UUID
    ) -> AttackAgentModel | None:
        return await db.scalar(
            select(AttackAgentModel)
            .where(AttackAgentModel.id == participation_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )

    async def _live_participation(
        self, db: AsyncSession, agent_id: UUID
    ) -> AttackAgentModel | None:
        return await db.scalar(
            select(AttackAgentModel).where(
                AttackAgentModel.agent_id == agent_id,
                AttackAgentModel.status.in_(_LIVE),
            )
        )

    async def _detach(self, db: AsyncSession, agent_id: UUID, now: datetime) -> None:
        live = await self._live_participation(db, agent_id)
        if live is None:
            return
        locked = await self._lock_attacks(db, {live.attack_id})
        await self._detach_locked(db, live, locked[live.attack_id], now)

    async def _detach_locked(
        self,
        db: AsyncSession,
        live: AttackAgentModel,
        previous: AttackModel,
        now: datetime,
    ) -> None:
        row = await self._lock_participation(db, live.id)
        if row is None or row.status not in _LIVE:
            return
        _exit_row(row, previous, ExitReason.MOVED, now)
        await self._cancel_if_empty(db, previous, now)

    async def _cancel_if_empty(
        self,
        db: AsyncSession,
        attack: AttackModel,
        now: datetime,
        *,
        end_reason: AttackEndReason = AttackEndReason.NO_AGENTS,
    ) -> None:
        if attack.status != AttackStatus.RUNNING.value:
            return
        remaining = int(
            await db.scalar(
                select(func.count())
                .select_from(AttackAgentModel)
                .where(
                    AttackAgentModel.attack_id == attack.id,
                    AttackAgentModel.status.in_(_LIVE),
                )
            )
            or 0
        )
        if remaining:
            return
        attack.status = AttackStatus.CANCELLED.value
        attack.finished_at = now
        attack.end_reason = end_reason.value


def _agent_state(value: str) -> AgentRuntimeState:
    """Статус из БД в состояние рантайма: неизвестное значение значит «остановлен»."""
    try:
        return AgentRuntimeState(value)
    except ValueError:
        return AgentRuntimeState.STOPPED


def _release_pending(participation: AttackAgentModel, attack: AttackModel) -> None:
    if participation.pending_random_id is None:
        return
    attack.claimed_count -= max(1, participation.pending_count)
    participation.pending_random_id = None
    participation.pending_text = None
    participation.pending_media = None
    participation.pending_count = 0


def _exit_row(
    participation: AttackAgentModel,
    attack: AttackModel,
    reason: ExitReason,
    now: datetime,
) -> None:
    _release_pending(participation, attack)
    participation.status = AttackAgentStatus.EXITED.value
    participation.exit_reason = reason.value
    participation.exited_at = now


def _participation_view(row: AttackAgentModel) -> ParticipationView:
    return ParticipationView(
        id=row.id,
        attack_id=row.attack_id,
        agent_id=row.agent_id,
        status=AttackAgentStatus(row.status),
        sent_count=row.sent_count,
        next_at=row.next_at,
        last_error=row.last_error,
        exit_reason=ExitReason(row.exit_reason) if row.exit_reason else None,
        note_written_at=row.note_written_at,
    )


def _attack_view(attack: AttackModel, participations: tuple[ParticipationView, ...]) -> AttackView:
    limit_type = AttackLimitType(attack.limit_type)
    limit: MessagesLimit | MinutesLimit = (
        MessagesLimit(attack.limit_value)
        if limit_type is AttackLimitType.MESSAGES
        else MinutesLimit(attack.limit_value)
    )
    return AttackView(
        id=attack.id,
        owner_id=attack.owner_id,
        config=AttackConfig(
            title=attack.title,
            target=TargetRef(
                link=attack.target_link,
                channel=attack.target_channel_peer,
                post_id=attack.target_message_id,
            ),
            texts=tuple(attack.texts),
            media_paths=tuple(attack.media_paths),
            limit=limit,
        ),
        status=AttackStatus(attack.status),
        sent_count=attack.sent_count,
        claimed_count=attack.claimed_count,
        version=attack.version,
        started_at=attack.started_at,
        finished_at=attack.finished_at,
        end_reason=AttackEndReason(attack.end_reason) if attack.end_reason else None,
        participations=participations,
        target_channel_id=attack.target_channel_id,
        anchor_message_id=attack.anchor_message_id,
        slowmode_seconds=attack.slowmode_seconds,
        deadline_at=attack.deadline_at,
    )


def _settlement(attack: AttackModel) -> Settlement:
    return Settlement(
        sent_count=attack.sent_count,
        claimed_count=attack.claimed_count,
        finished=attack.status in _CLOSED,
        end_reason=AttackEndReason(attack.end_reason) if attack.end_reason else None,
    )


async def _load_participations(db: AsyncSession, attack_id: UUID) -> tuple[ParticipationView, ...]:
    rows = await db.scalars(
        select(AttackAgentModel)
        .where(AttackAgentModel.attack_id == attack_id)
        .order_by(AttackAgentModel.joined_at, AttackAgentModel.id)
    )
    return tuple(_participation_view(row) for row in rows)
