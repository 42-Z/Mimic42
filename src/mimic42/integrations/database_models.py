from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    BigInteger,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
)
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
    soul_prompt: Mapped[str] = mapped_column(Text, default="")
    settings: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    last_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_stopped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AgentOnboardingSessionModel(Base):
    __tablename__ = "agent_onboarding_sessions"
    __table_args__ = (
        Index("agent_onboarding_sessions_owner_id_idx", "owner_id"),
        Index("agent_onboarding_sessions_status_idx", "authorization_status"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("profiles.id", ondelete="CASCADE"))
    api_id: Mapped[int | None] = mapped_column(Integer)
    api_hash_ciphertext: Mapped[str | None] = mapped_column(Text)
    phone_number: Mapped[str | None] = mapped_column(Text)
    phone_code_hash_ciphertext: Mapped[str | None] = mapped_column(Text)
    session_ciphertext: Mapped[str | None] = mapped_column(Text)
    authorization_status: Mapped[str] = mapped_column(
        TelegramAuthorizationStatus,
        default="not_started",
    )
    agent_name: Mapped[str | None] = mapped_column(Text)
    soul_prompt: Mapped[str | None] = mapped_column(Text)
    completed_agent_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("agents.id", ondelete="SET NULL"),
        unique=True,
    )
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TelegramSessionModel(Base):
    __tablename__ = "telegram_sessions"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    agent_id: Mapped[UUID] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"),
        unique=True,
    )
    session_name: Mapped[str] = mapped_column(Text)
    phone_number: Mapped[str | None] = mapped_column(Text)
    api_id: Mapped[int | None] = mapped_column(Integer)
    api_hash_ciphertext: Mapped[str | None] = mapped_column(Text)
    session_ciphertext: Mapped[str | None] = mapped_column(Text)
    authorization_status: Mapped[str] = mapped_column(
        TelegramAuthorizationStatus,
        default="not_started",
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
