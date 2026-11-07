from __future__ import annotations

import logging
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import delete, or_, select, type_coerce
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mimic42.core.agent_runtime import DEFAULT_LLM_MODEL, AgentRuntimeConfig, AgentRuntimeState
from mimic42.core.agent_store import (
    AgentActivity,
    AgentMessageRecord,
    AgentOwnershipError,
    AgentRecord,
    ConversationPage,
    TelegramAccountMismatchError,
    TelegramRebindCredentials,
)
from mimic42.core.chat_access import parse_disabled_chats
from mimic42.core.first_comment import parse_first_comment
from mimic42.core.media_download import MediaRef
from mimic42.core.onboarding import (
    AgentProfileInput,
    OnboardingAlreadyCompletedError,
    OnboardingOwnershipError,
    OnboardingSession,
    SecretCipher,
    TelegramAuthorizationIncompleteError,
    TelegramAuthorizationRef,
    TelegramLoginStaleError,
)
from mimic42.core.tool_config import parse_enabled_tools
from mimic42.core.warmup import parse_warmup
from mimic42.integrations.database_conversation import load_conversation, stored_structured_text
from mimic42.integrations.database_models import (
    AgentEventModel,
    AgentMessageModel,
    AgentModel,
    AgentOnboardingSessionModel,
    TelegramProxyModel,
    TelegramSessionModel,
)
from mimic42.integrations.database_onboarding import _model_to_session
from mimic42.integrations.database_proxies import lock_proxy_pool, telegram_proxy_config
from mimic42.integrations.database_warmup import load_warmup_state

logger = logging.getLogger("mimic42.agent_store")


def _owned_media_ref(agent_id: UUID, payload: dict[str, Any]) -> MediaRef:
    """Storage uses a privileged client: never open another agent's path."""
    ref = MediaRef.from_payload(payload)
    path = ref.storage_path
    if path is not None and (not path.startswith(f"{agent_id}/") or ".." in path.split("/")):
        return replace(ref, storage_path=None)
    return ref


class DatabaseAgentStore:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        cipher: SecretCipher | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._cipher = cipher
        self._llm_model = DEFAULT_LLM_MODEL

    async def lookup_media_ref(self, *, agent_id: UUID, media_id: str) -> MediaRef | None:
        """Resolve persisted media without the context TTL or dashboard page limit.

        Incoming attachments live in message payloads; tool-only archives and
        history references live in existing activity events. Every lookup is
        scoped to the Telegram account's agent because access_hash is private.
        """
        ref: MediaRef | None = None
        async with self._session_factory() as db_session:
            payloads = await db_session.scalars(
                select(AgentMessageModel.payload)
                .where(
                    AgentMessageModel.agent_id == agent_id,
                    type_coerce(AgentMessageModel.payload, JSONB).contains(
                        {"media": [{"media_id": media_id}]}
                    ),
                )
                .order_by(AgentMessageModel.created_at.desc(), AgentMessageModel.id.desc())
            )
            for payload in payloads:
                for entry in payload.get("media") or []:
                    if isinstance(entry, dict) and entry.get("media_id") == media_id:
                        candidate = _owned_media_ref(agent_id, entry)
                        ref = candidate.merged_with(ref) if ref is not None else candidate
                        if ref.storage_path:
                            return ref

            results = await db_session.scalars(
                select(AgentEventModel.result)
                .where(
                    AgentEventModel.agent_id == agent_id,
                    AgentEventModel.event_type == "tool.view_image",
                    AgentEventModel.status == "succeeded",
                    AgentEventModel.payload["args"]["media_id"].as_string() == media_id,
                    type_coerce(AgentEventModel.result, JSONB).contains(
                        {"items": [{"type": "media_ref"}]}
                    ),
                )
                .order_by(AgentEventModel.created_at.desc(), AgentEventModel.id.desc())
            )
            for result in results:
                if result is None:
                    continue
                for entry in result.get("items") or []:
                    if isinstance(entry, dict) and entry.get("type") == "media_ref":
                        archived = _owned_media_ref(agent_id, entry)
                        ref = archived.merged_with(ref) if ref is not None else archived
                        break
                if ref is not None and ref.storage_path:
                    return ref

            result = await db_session.scalar(
                select(AgentEventModel.result)
                .where(
                    AgentEventModel.agent_id == agent_id,
                    AgentEventModel.event_type == "tool.get_messages",
                    AgentEventModel.status == "succeeded",
                    type_coerce(AgentEventModel.result, JSONB).contains(
                        {"items": [{"media": {"media_id": media_id}}]}
                    ),
                )
                .order_by(AgentEventModel.created_at.desc(), AgentEventModel.id.desc())
                .limit(1)
            )
            if result is not None:
                for item in result.get("items") or []:
                    entry = item.get("media") if isinstance(item, dict) else None
                    if isinstance(entry, dict) and entry.get("media_id") == media_id:
                        history_ref = _owned_media_ref(agent_id, entry)
                        return ref.merged_with(history_ref) if ref is not None else history_ref
        return ref

    async def create_from_onboarding(self, session: OnboardingSession) -> AgentRecord:
        if not session.name or not session.soul_prompt:
            raise ValueError("Onboarding session is missing agent profile fields")
        return await self.finalize_onboarding(
            session.authorization_ref(),
            AgentProfileInput(name=session.name, soul_prompt=session.soul_prompt),
        )

    async def finalize_onboarding(
        self, ref: TelegramAuthorizationRef, profile: AgentProfileInput
    ) -> AgentRecord:
        async with self._session_factory() as db_session, db_session.begin():
            await lock_proxy_pool(db_session)
            agent = await db_session.scalar(
                select(AgentModel).where(AgentModel.id == ref.onboarding_id).with_for_update()
            )
            telegram_session = await db_session.scalar(
                select(TelegramSessionModel)
                .where(TelegramSessionModel.agent_id == ref.onboarding_id)
                .with_for_update()
            )
            model = await db_session.scalar(
                select(AgentOnboardingSessionModel)
                .where(AgentOnboardingSessionModel.id == ref.onboarding_id)
                .with_for_update()
            )
            if model is None:
                raise TelegramLoginStaleError()
            if agent is not None and agent.owner_id != ref.owner_id:
                raise AgentOwnershipError(ref.onboarding_id)
            current_ref = ref
            if ref.completed_agent_id is None and model.completed_agent_id == ref.onboarding_id:
                current_ref = ref.model_copy(update={"completed_agent_id": ref.onboarding_id})
            current_ref.check(_model_to_session(model))
            if model.completed_agent_id not in (None, ref.onboarding_id):
                raise OnboardingAlreadyCompletedError(ref.onboarding_id)
            if model.authorization_status != "authorized":
                raise TelegramAuthorizationIncompleteError(ref.onboarding_id)
            if agent is None:
                if (
                    model.api_id is None
                    or model.api_hash_ciphertext is None
                    or model.session_ciphertext is None
                ):
                    raise TelegramAuthorizationIncompleteError(ref.onboarding_id)
                agent = AgentModel(
                    id=ref.onboarding_id,
                    owner_id=ref.owner_id,
                    name=profile.name,
                    soul_prompt=profile.soul_prompt,
                    status=AgentRuntimeState.STOPPED.value,
                    settings=dict(model.settings or {}),
                )
                db_session.add(agent)
                await db_session.flush()
                telegram_session = TelegramSessionModel(
                    agent_id=agent.id,
                    session_name=agent.id.hex,
                    proxy_id=model.proxy_id,
                    phone_number=model.phone_number,
                    username=model.username,
                    api_id=model.api_id,
                    api_hash_ciphertext=model.api_hash_ciphertext,
                    session_ciphertext=model.session_ciphertext,
                    authorization_status="authorized",
                    last_authorized_at=_now(),
                )
                db_session.add(telegram_session)
                model.agent_name = profile.name
                model.soul_prompt = profile.soul_prompt
            elif telegram_session is None:
                raise TelegramLoginStaleError()
            elif model.completed_agent_id == agent.id:
                return _agent_record(agent)
            model.completed_agent_id = agent.id
            model.proxy_id = None
            model.applied_auth_generation = model.auth_generation
            await db_session.flush()
            return _agent_record(agent)

    async def rebind_telegram_session(self, agent_id: UUID, session: OnboardingSession) -> None:
        await self.apply_rebind(session.authorization_ref(), agent_id)

    async def apply_rebind(self, ref: TelegramAuthorizationRef, agent_id: UUID) -> None:
        async with self._session_factory() as db_session, db_session.begin():
            await lock_proxy_pool(db_session)
            agent = await db_session.scalar(
                select(AgentModel).where(AgentModel.id == agent_id).with_for_update()
            )
            if agent is None:
                raise KeyError(f"Agent {agent_id} does not exist")
            if agent.owner_id != ref.owner_id:
                raise AgentOwnershipError(agent_id)
            telegram_session = await db_session.scalar(
                select(TelegramSessionModel)
                .where(TelegramSessionModel.agent_id == agent_id)
                .with_for_update()
            )
            if telegram_session is None:
                raise KeyError(f"Agent {agent_id} does not have a telegram session")
            model = await db_session.scalar(
                select(AgentOnboardingSessionModel)
                .where(AgentOnboardingSessionModel.id == ref.onboarding_id)
                .with_for_update()
            )
            if model is None:
                raise TelegramLoginStaleError()
            session = _model_to_session(model)
            ref.check(session)
            if session.completed_agent_id != agent_id or session.owner_id != agent.owner_id:
                raise OnboardingOwnershipError(ref.onboarding_id)
            if (
                model.authorization_status != "authorized"
                or session.api_id is None
                or session.api_hash_secret is None
                or session.session_secret is None
                or session.phone_number is None
            ):
                raise TelegramAuthorizationIncompleteError(ref.onboarding_id)
            stored_api_hash = telegram_session.api_hash_ciphertext or ""
            rebound_api_hash = session.api_hash_secret
            if self._cipher is not None:
                stored_api_hash = self._cipher.decrypt(stored_api_hash)
                rebound_api_hash = self._cipher.decrypt(rebound_api_hash)
            if (
                telegram_session.phone_number != session.phone_number
                or telegram_session.api_id != session.api_id
                or stored_api_hash != rebound_api_hash
            ):
                raise TelegramAccountMismatchError(
                    "Rebind session belongs to a different Telegram account or application"
                )
            if model.applied_auth_generation == model.auth_generation:
                return
            telegram_session.session_ciphertext = session.session_secret
            telegram_session.username = session.username
            telegram_session.authorization_status = "authorized"
            telegram_session.last_authorized_at = _now()
            telegram_session.last_error = None
            model.applied_auth_generation = model.auth_generation

    async def get_runtime_config(self, agent_id: UUID) -> AgentRuntimeConfig:
        async with self._session_factory() as db_session:
            row = await db_session.execute(
                select(AgentModel, TelegramSessionModel, TelegramProxyModel)
                .join(TelegramSessionModel, TelegramSessionModel.agent_id == AgentModel.id)
                .outerjoin(
                    TelegramProxyModel,
                    TelegramProxyModel.id == TelegramSessionModel.proxy_id,
                )
                .where(AgentModel.id == agent_id)
            )
            item = row.first()
            if item is None:
                raise KeyError(f"Agent {agent_id} does not have a runtime config")
            agent, telegram_session, proxy_model = item
            from mimic42.core.onboarding import load_default_system_prompt

            return AgentRuntimeConfig(
                agent_id=agent.id,
                owner_id=agent.owner_id,
                telegram_api_id=telegram_session.api_id or 0,
                telegram_api_hash=(
                    self._cipher.decrypt(telegram_session.api_hash_ciphertext)
                    if self._cipher and telegram_session.api_hash_ciphertext
                    else telegram_session.api_hash_ciphertext or ""
                ),
                telegram_session_string=(
                    self._cipher.decrypt(telegram_session.session_ciphertext)
                    if self._cipher and telegram_session.session_ciphertext
                    else telegram_session.session_ciphertext
                ),
                telegram_session_token=telegram_session.session_ciphertext,
                telegram_proxy=(
                    telegram_proxy_config(proxy_model, self._cipher)
                    if proxy_model is not None
                    else None
                ),
                llm_model=(
                    agent.settings.get("model", self._llm_model)
                    if agent.settings
                    else self._llm_model
                ),
                reasoning_effort=agent.settings.get("reasoning_effort", "high")
                if agent.settings
                else "high",
                enabled_tools=parse_enabled_tools(
                    agent.settings.get("enabled_tools") if agent.settings else None
                ),
                disabled_chats=parse_disabled_chats(
                    agent.settings.get("disabled_chats") if agent.settings else None
                ),
                system_prompt=load_default_system_prompt(),
                soul_prompt=agent.soul_prompt,
                name=agent.name,
                first_comment=parse_first_comment(
                    agent.settings.get("first_comment") if agent.settings else None
                ),
                warmup=parse_warmup(agent.settings.get("warmup") if agent.settings else None),
                warmup_state=await load_warmup_state(db_session, agent.id),
            )

    async def get_telegram_rebind_credentials(self, agent_id: UUID) -> TelegramRebindCredentials:
        async with self._session_factory() as db_session:
            row = await db_session.execute(
                select(AgentModel, TelegramSessionModel)
                .join(TelegramSessionModel, TelegramSessionModel.agent_id == AgentModel.id)
                .where(AgentModel.id == agent_id)
            )
            item = row.first()
            if item is None:
                raise KeyError(f"Agent {agent_id} does not have saved Telegram credentials")
            agent, telegram_session = item
            if (
                telegram_session.api_id is None
                or telegram_session.api_hash_ciphertext is None
                or telegram_session.phone_number is None
            ):
                raise KeyError(f"Agent {agent_id} does not have saved Telegram credentials")
            return TelegramRebindCredentials(
                owner_id=agent.owner_id,
                api_id=telegram_session.api_id,
                api_hash_secret=telegram_session.api_hash_ciphertext,
                phone_number=telegram_session.phone_number,
                username=telegram_session.username,
            )

    async def list_agents(self, *, owner_id: UUID | None = None) -> list[AgentRecord]:
        statement = select(AgentModel).order_by(AgentModel.created_at.desc())
        if owner_id is not None:
            statement = statement.where(AgentModel.owner_id == owner_id)
        async with self._session_factory() as db_session:
            return [_agent_record(agent) for agent in await db_session.scalars(statement)]

    async def update_status(self, agent_id: UUID, state: AgentRuntimeState) -> None:
        async with self._session_factory() as db_session:
            agent = await db_session.get(AgentModel, agent_id)
            if agent is None:
                return
            agent.status = state.value
            if state is AgentRuntimeState.RUNNING:
                agent.last_started_at = _now()
            if state is AgentRuntimeState.STOPPED:
                agent.last_stopped_at = _now()
            await db_session.commit()

    async def delete_agent(self, agent_id: UUID) -> None:
        async with self._session_factory() as db_session:
            await lock_proxy_pool(db_session)
            # Копия по id нужна для черновика, который фронтенд не успел
            # связать через completed_agent_id: каскад её не достанет.
            await db_session.execute(
                delete(AgentOnboardingSessionModel).where(
                    or_(
                        AgentOnboardingSessionModel.completed_agent_id == agent_id,
                        AgentOnboardingSessionModel.id == agent_id,
                    )
                )
            )
            # telegram_sessions, message_threads, agent_messages, agent_events
            # and agent_timers are removed by ON DELETE CASCADE.
            await db_session.execute(delete(AgentModel).where(AgentModel.id == agent_id))
            await db_session.commit()

    async def reset_context(self, agent_id: UUID, *, actor_user_id: UUID) -> datetime:
        """Move the short-term context boundary to now.

        Message rows are kept for the dashboard; DatabaseShortTermMemory stops
        loading everything saved before the boundary. A turn already underway
        finishes with the context it loaded, and its rows land after the reset.
        The feed event is written in the same transaction as the boundary.
        """
        async with self._session_factory() as db_session:
            # Row lock serializes concurrent resets: the boundary is computed
            # only after the lock is taken, so it always moves forward. Without
            # it a slower reset could commit an older mark and bring back the
            # messages a fresher reset had just hidden.
            agent = await db_session.scalar(
                select(AgentModel).where(AgentModel.id == agent_id).with_for_update()
            )
            if agent is None:
                raise KeyError(f"Agent {agent_id} does not exist")
            reset_at = _now()
            agent.context_reset_at = reset_at
            db_session.add(
                AgentEventModel(
                    agent_id=agent_id,
                    actor_user_id=actor_user_id,
                    event_type="agent.context_reset",
                    status="succeeded",
                    payload={},
                    started_at=reset_at,
                    completed_at=reset_at,
                )
            )
            await db_session.commit()
        return reset_at

    async def list_messages(
        self, *, agent_id: UUID, limit: int = 50, offset: int = 0
    ) -> list[AgentMessageRecord]:
        async with self._session_factory() as db_session:
            messages = await db_session.scalars(
                select(AgentMessageModel)
                .where(AgentMessageModel.agent_id == agent_id)
                .order_by(AgentMessageModel.created_at.desc())
                .offset(offset)
                .limit(limit)
            )
            records = []
            for message in messages:
                content = message.content
                # With structured output the assistant message content is empty.
                # Present the human-readable text from the stored schema instead.
                if not content.strip() and message.role == "assistant":
                    content = stored_structured_text(message)
                records.append(
                    AgentMessageRecord(
                        id=message.id,
                        agent_id=message.agent_id,
                        peer=str(message.payload.get("peer", "")),
                        peer_name=str(message.payload.get("peer_name", "")),
                        agent_name=str(message.payload.get("agent_name", "")),
                        role=message.role,
                        content=content,
                        direction=message.direction,
                        payload=message.payload or {},
                        thread_id=message.thread_id,
                        created_at=message.created_at,
                    )
                )
            return records

    async def list_activities(
        self, *, agent_id: UUID, limit: int = 50, offset: int = 0
    ) -> list[AgentActivity]:
        async with self._session_factory() as db_session:
            activities = await db_session.scalars(
                select(AgentEventModel)
                .where(AgentEventModel.agent_id == agent_id)
                .order_by(AgentEventModel.created_at.desc())
                .offset(offset)
                .limit(limit)
            )
            return [
                AgentActivity(
                    id=activity.id,
                    agent_id=activity.agent_id,
                    event_type=activity.event_type,
                    status=activity.status,
                    created_at=activity.created_at,
                    payload=activity.payload or {},
                    result=activity.result,
                    error=activity.error,
                    started_at=activity.started_at,
                    completed_at=activity.completed_at,
                )
                for activity in activities
            ]

    async def get_conversation(
        self,
        *,
        agent_id: UUID,
        limit: int = 50,
        before: datetime | None = None,
        before_id: UUID | None = None,
    ) -> ConversationPage:
        async with self._session_factory() as db_session:
            return await load_conversation(
                db_session, agent_id=agent_id, limit=limit, before=before, before_id=before_id
            )


def _agent_record(agent: AgentModel) -> AgentRecord:
    # The DB enum carries extra values (e.g. the `draft` default for rows
    # created outside AgentRuntimeState). One unexpected status must not break
    # the whole agent list or the startup restore — treat it as stopped.
    try:
        state = AgentRuntimeState(agent.status)
    except ValueError:
        logger.warning(
            "Agent %s has unsupported status %r, treating it as stopped", agent.id, agent.status
        )
        state = AgentRuntimeState.STOPPED
    return AgentRecord(
        agent_id=agent.id,
        owner_id=agent.owner_id,
        name=agent.name,
        state=state,
        warmup_restricted_at=agent.warmup_restricted_at,
        restore_on_start=agent.restore_on_start,
    )


def _now() -> datetime:
    return datetime.now(UTC)
