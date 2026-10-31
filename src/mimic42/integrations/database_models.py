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
        ForeignKey("agents.id", ondelete="SET NULL"),
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
