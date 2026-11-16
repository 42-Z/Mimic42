from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.sql import func


class Base(DeclarativeBase):
    pass


AgentRuntimeStatus = Enum(
    "draft",
    "stopped",
    "starting",
    "running",
    "stopping",
    "error",
    name="agent_runtime_status",
)

TelegramAuthorizationStatus = Enum(
    "not_started",
    "code_requested",
    "password_required",
    "authorized",
    "revoked",
    "error",
    name="telegram_authorization_status",
)

AgentMessageDirection = Enum(
    "incoming",
    "outgoing",
    "dashboard_trigger",
    "agent_response",
    "tool_call",
    "tool_result",
    name="agent_message_direction",
)

AgentEventStatus = Enum(
    "pending",
    "running",
    "succeeded",
    "failed",
    "cancelled",
    name="agent_event_status",
)

AttackStatus = Enum(
    "draft",
    "running",
    "cancelled",
    "finished",
    name="attack_status",
)

AttackLimitType = Enum(
    "messages",
    "minutes",
    name="attack_limit_type",
)

AttackAgentStatus = Enum(
    "assigned",
    "active",
    "exited",
    name="attack_agent_status",
)


class ProfileModel(Base):
    __tablename__ = "profiles"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    email: Mapped[str | None] = mapped_column(Text)
    display_name: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AdminUserModel(Base):
    __tablename__ = "admin_users"

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("profiles.id", ondelete="CASCADE"),
        primary_key=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PlatformTelegramSettingsModel(Base):
    __tablename__ = "platform_telegram_settings"
    __table_args__ = (
        CheckConstraint("id = 1"),
        CheckConstraint("api_id > 0"),
        CheckConstraint("btrim(api_hash_ciphertext) <> ''"),
    )

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, default=1)
    api_id: Mapped[int] = mapped_column(Integer)
    api_hash_ciphertext: Mapped[str] = mapped_column(Text)
    updated_by: Mapped[UUID | None] = mapped_column(ForeignKey("profiles.id", ondelete="SET NULL"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TelegramProxyModel(Base):
    __tablename__ = "telegram_proxies"
    __table_args__ = (
        CheckConstraint("btrim(label) <> ''"),
        CheckConstraint("protocol in ('socks5', 'http')"),
        CheckConstraint("btrim(host) <> ''"),
        CheckConstraint("port between 1 and 65535"),
        Index("telegram_proxies_active_created_idx", "is_active", "created_at", "id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    label: Mapped[str | None] = mapped_column(Text)
    protocol: Mapped[str] = mapped_column(Text)
    host: Mapped[str] = mapped_column(Text)
    port: Mapped[int] = mapped_column(Integer)
    username: Mapped[str | None] = mapped_column(Text)
    password_ciphertext: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    unavailable_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[UUID | None] = mapped_column(ForeignKey("profiles.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AdminAuditLogModel(Base):
    __tablename__ = "admin_audit_log"
    __table_args__ = (
        CheckConstraint(
            "action in ('preset.created', 'preset.updated', "
            "'preset.visibility_changed', 'telegram.settings_updated', "
            "'proxy.created', 'proxy.updated', 'proxy.deleted', 'agent.proxy_changed')"
        ),
        CheckConstraint("object_type in ('preset', 'telegram_settings', 'proxy', 'agent')"),
        CheckConstraint("jsonb_typeof(metadata) = 'object'"),
        CheckConstraint(
            "(object_type in ('preset', 'proxy', 'agent') and object_id is not null) or "
            "(object_type = 'telegram_settings' and object_id is null)"
        ),
        CheckConstraint(
            "(action in ('preset.created', 'preset.updated', 'preset.visibility_changed') "
            "and object_type = 'preset' and object_id is not null) or "
            "(action = 'telegram.settings_updated' and "
            "object_type = 'telegram_settings' and object_id is null) or "
            "(action in ('proxy.created', 'proxy.updated', 'proxy.deleted') "
            "and object_type = 'proxy' and object_id is not null) or "
            "(action = 'agent.proxy_changed' and object_type = 'agent' and object_id is not null)",
            name="admin_audit_action_object_consistency",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    actor_user_id: Mapped[UUID] = mapped_column()
    action: Mapped[str] = mapped_column(Text)
    object_type: Mapped[str] = mapped_column(Text)
    object_id: Mapped[UUID | None] = mapped_column()
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


Index(
    "admin_audit_log_actor_created_idx",
    AdminAuditLogModel.actor_user_id,
    AdminAuditLogModel.created_at.desc(),
)


class PromptPresetModel(Base):
    __tablename__ = "prompt_presets"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    slug: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    summary: Mapped[str] = mapped_column(Text)
    body: Mapped[str] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    owner_id: Mapped[UUID | None] = mapped_column(ForeignKey("profiles.id", ondelete="CASCADE"))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    settings: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))


class AgentModel(Base):
    __tablename__ = "agents"
    __table_args__ = (
        Index("agents_owner_id_idx", "owner_id"),
        Index("agents_status_idx", "status"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("profiles.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(AgentRuntimeStatus, default="draft")
    restore_on_start: Mapped[bool] = mapped_column(Boolean, default=True)
    soul_prompt: Mapped[str] = mapped_column(Text, default="")
    settings: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    last_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_stopped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Short-term context only includes messages saved after this moment.
    context_reset_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    warmup_restricted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    warmup_recovery: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AgentOnboardingSessionModel(Base):
    __tablename__ = "agent_onboarding_sessions"
    __table_args__ = (
        Index("agent_onboarding_sessions_owner_id_idx", "owner_id"),
        Index("agent_onboarding_sessions_status_idx", "authorization_status"),
        Index("agent_onboarding_sessions_proxy_id_idx", "proxy_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("profiles.id", ondelete="CASCADE"))
    api_id: Mapped[int | None] = mapped_column(Integer)
    api_hash_ciphertext: Mapped[str | None] = mapped_column(Text)
    phone_number: Mapped[str | None] = mapped_column(Text)
    phone_code_hash_ciphertext: Mapped[str | None] = mapped_column(Text)
    session_ciphertext: Mapped[str | None] = mapped_column(Text)
    username: Mapped[str | None] = mapped_column(Text)
    auth_generation: Mapped[UUID] = mapped_column(server_default=func.gen_random_uuid())
    applied_auth_generation: Mapped[UUID | None] = mapped_column()
    authorization_status: Mapped[str] = mapped_column(
        TelegramAuthorizationStatus,
        default="not_started",
    )
    agent_name: Mapped[str | None] = mapped_column(Text)
    soul_prompt: Mapped[str | None] = mapped_column(Text)
    settings: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    completed_agent_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"),
        unique=True,
    )
    proxy_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("telegram_proxies.id", ondelete="SET NULL")
    )
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TelegramSessionModel(Base):
    __tablename__ = "telegram_sessions"
    __table_args__ = (Index("telegram_sessions_proxy_id_idx", "proxy_id"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    agent_id: Mapped[UUID] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"),
        unique=True,
    )
    session_name: Mapped[str] = mapped_column(Text)
    phone_number: Mapped[str | None] = mapped_column(Text)
    username: Mapped[str | None] = mapped_column(Text)
    api_id: Mapped[int | None] = mapped_column(Integer)
    api_hash_ciphertext: Mapped[str | None] = mapped_column(Text)
    session_ciphertext: Mapped[str | None] = mapped_column(Text)
    authorization_status: Mapped[str] = mapped_column(
        TelegramAuthorizationStatus,
        default="not_started",
    )
    proxy_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("telegram_proxies.id", ondelete="SET NULL")
    )
    last_authorized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MessageThreadModel(Base):
    __tablename__ = "message_threads"
    __table_args__ = (
        UniqueConstraint("agent_id", "telegram_peer_id"),
        Index("message_threads_agent_id_idx", "agent_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    agent_id: Mapped[UUID] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"))
    telegram_peer_id: Mapped[str] = mapped_column(Text)
    title: Mapped[str | None] = mapped_column(Text)
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AgentMessageModel(Base):
    __tablename__ = "agent_messages"
    __table_args__ = (
        Index("agent_messages_agent_id_created_at_idx", "agent_id", "created_at"),
        Index("agent_messages_thread_id_created_at_idx", "thread_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    agent_id: Mapped[UUID] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"))
    thread_id: Mapped[UUID | None] = mapped_column(ForeignKey("message_threads.id"))
    direction: Mapped[str] = mapped_column(AgentMessageDirection)
    role: Mapped[str] = mapped_column(Text)
    telegram_message_id: Mapped[str | None] = mapped_column(Text)
    content: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AgentEventModel(Base):
    __tablename__ = "agent_events"
    __table_args__ = (
        Index("agent_events_agent_id_status_created_at_idx", "agent_id", "status", "created_at"),
        Index("agent_events_actor_user_id_idx", "actor_user_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    agent_id: Mapped[UUID] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"))
    actor_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("profiles.id"))
    event_type: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(AgentEventStatus, default="pending")
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AgentTimerModel(Base):
    __tablename__ = "agent_timers"
    __table_args__ = (
        Index("agent_timers_agent_id_status_trigger_at_idx", "agent_id", "status", "trigger_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    agent_id: Mapped[UUID] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"))
    peer: Mapped[str] = mapped_column(Text)
    trigger_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    description: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AgentTokenUsageModel(Base):
    __tablename__ = "agent_token_usage"

    agent_id: Mapped[UUID] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"), primary_key=True
    )
    input_tokens: Mapped[int] = mapped_column(BigInteger, default=0)
    output_tokens: Mapped[int] = mapped_column(BigInteger, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AttackModel(Base):
    __tablename__ = "attacks"
    __table_args__ = (
        CheckConstraint("btrim(target_link) <> ''"),
        CheckConstraint("btrim(target_channel_peer) <> ''"),
        CheckConstraint("jsonb_typeof(texts) = 'array'"),
        CheckConstraint("jsonb_array_length(texts) > 0"),
        CheckConstraint("jsonb_typeof(media_paths) = 'array'"),
        CheckConstraint("limit_value > 0"),
        CheckConstraint("slowmode_seconds is null or slowmode_seconds >= 0"),
        CheckConstraint("sent_count >= 0 and claimed_count >= 0"),
        CheckConstraint("sent_count <= claimed_count"),
        CheckConstraint("status <> 'running' or started_at is not null"),
        CheckConstraint(
            "status not in ('finished', 'cancelled') "
            "or (finished_at is not null and end_reason is not null)"
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("profiles.id", ondelete="CASCADE"))
    title: Mapped[str | None] = mapped_column(Text)
    target_link: Mapped[str] = mapped_column(Text)
    target_channel_peer: Mapped[str] = mapped_column(Text)
    target_message_id: Mapped[int] = mapped_column(BigInteger)
    target_channel_id: Mapped[int | None] = mapped_column(BigInteger)
    anchor_message_id: Mapped[int | None] = mapped_column(BigInteger)
    slowmode_seconds: Mapped[int | None] = mapped_column(Integer)
    texts: Mapped[list[str]] = mapped_column(JSONB)
    media_paths: Mapped[list[str]] = mapped_column(JSONB, default=list)
    limit_type: Mapped[str] = mapped_column(AttackLimitType)
    limit_value: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(AttackStatus, default="draft")
    sent_count: Mapped[int] = mapped_column(Integer, default=0)
    claimed_count: Mapped[int] = mapped_column(Integer, default=0)
    version: Mapped[int] = mapped_column(Integer, default=1)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deadline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    end_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


Index(
    "attacks_owner_id_status_created_at_idx",
    AttackModel.owner_id,
    AttackModel.status,
    AttackModel.created_at.desc(),
)


class AttackAgentModel(Base):
    __tablename__ = "attack_agents"
    __table_args__ = (
        CheckConstraint("sent_count >= 0"),
        CheckConstraint("pending_attempts >= 0"),
        CheckConstraint("pending_media is null or jsonb_typeof(pending_media) = 'array'"),
        CheckConstraint("(pending_random_id is null) = (pending_text is null)"),
        CheckConstraint(
            "status <> 'exited' or (exit_reason is not null and exited_at is not null)"
        ),
        Index("attack_agents_agent_id_status_idx", "agent_id", "status"),
        Index("attack_agents_attack_id_status_idx", "attack_id", "status"),
        Index(
            "attack_agents_active_agent_idx",
            "agent_id",
            unique=True,
            postgresql_where=text("status in ('assigned', 'active')"),
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    attack_id: Mapped[UUID] = mapped_column(ForeignKey("attacks.id", ondelete="CASCADE"))
    agent_id: Mapped[UUID] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(AttackAgentStatus, default="assigned")
    sent_count: Mapped[int] = mapped_column(Integer, default=0)
    next_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    pending_random_id: Mapped[int | None] = mapped_column(BigInteger)
    pending_text: Mapped[str | None] = mapped_column(Text)
    pending_media: Mapped[list[str] | None] = mapped_column(JSONB)
    pending_attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_comment_message_id: Mapped[int | None] = mapped_column(BigInteger)
    last_error_code: Mapped[str | None] = mapped_column(Text)
    last_error: Mapped[str | None] = mapped_column(Text)
    exit_reason: Mapped[str | None] = mapped_column(Text)
    note_written_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    memory_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    exited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
