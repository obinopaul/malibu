"""SQLAlchemy ORM models for session persistence, messages, tool calls, plans, auth, and command allowlists."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _new_uuid() -> uuid.UUID:
    return uuid.uuid4()


class Base(DeclarativeBase):
    """Shared declarative base for all Malibu models."""

    type_annotation_map = {
        dict: JSONB,
    }


# ═══════════════════════════════════════════════════════════════════
# Sessions
# ═══════════════════════════════════════════════════════════════════
class SessionRecord(Base):
    """Persisted ACP session — maps 1:1 to a session_id."""

    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_new_uuid)
    session_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    cwd: Mapped[str] = mapped_column(Text, nullable=False)
    mode_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    model_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    title: Mapped[str | None] = mapped_column(String(256), nullable=True)
    config_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    # Relationships
    messages: Mapped[list[MessageRecord]] = relationship(back_populates="session", cascade="all, delete-orphan")
    tool_calls: Mapped[list[ToolCallRecord]] = relationship(back_populates="session", cascade="all, delete-orphan")
    plans: Mapped[list[PlanRecord]] = relationship(back_populates="session", cascade="all, delete-orphan")
    command_allowlist: Mapped[list[CommandAllowlistRecord]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )


# ═══════════════════════════════════════════════════════════════════
# Messages
# ═══════════════════════════════════════════════════════════════════
class MessageRecord(Base):
    """A single message in a session conversation (user or agent)."""

    __tablename__ = "messages"
    __table_args__ = (Index("ix_messages_session_created", "session_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_new_uuid)
    session_id: Mapped[str] = mapped_column(String(64), ForeignKey("sessions.session_id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(String(16), nullable=False)  # "user" | "assistant"
    content_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    session: Mapped[SessionRecord] = relationship(back_populates="messages")


# ═══════════════════════════════════════════════════════════════════
# Tool Calls
# ═══════════════════════════════════════════════════════════════════
class ToolCallRecord(Base):
    """Record of a tool call executed during a session."""

    __tablename__ = "tool_calls"
    __table_args__ = (Index("ix_tool_calls_session", "session_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_new_uuid)
    session_id: Mapped[str] = mapped_column(String(64), ForeignKey("sessions.session_id", ondelete="CASCADE"))
    tool_call_id: Mapped[str] = mapped_column(String(128), nullable=False)
    kind: Mapped[str | None] = mapped_column(String(32), nullable=True)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    input_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    output_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    session: Mapped[SessionRecord] = relationship(back_populates="tool_calls")


# ═══════════════════════════════════════════════════════════════════
# Plans
# ═══════════════════════════════════════════════════════════════════
class PlanRecord(Base):
    """Stored execution plan for a session."""

    __tablename__ = "plans"
    __table_args__ = (Index("ix_plans_session", "session_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_new_uuid)
    session_id: Mapped[str] = mapped_column(String(64), ForeignKey("sessions.session_id", ondelete="CASCADE"))
    entries_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    session: Mapped[SessionRecord] = relationship(back_populates="plans")


# ═══════════════════════════════════════════════════════════════════
# Auth Tokens
# ═══════════════════════════════════════════════════════════════════
class AuthTokenRecord(Base):
    """JWT / API-key authentication token record."""

    __tablename__ = "auth_tokens"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_new_uuid)
    user_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    method_id: Mapped[str] = mapped_column(String(64), nullable=False)  # "jwt" | "api_key"
    token_hash: Mapped[str] = mapped_column(String(256), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_revoked: Mapped[bool] = mapped_column(Boolean, default=False)


# ═══════════════════════════════════════════════════════════════════
# Command Allowlist
# ═══════════════════════════════════════════════════════════════════
class CommandAllowlistRecord(Base):
    """Per-session command type allowlist for auto-approval."""

    __tablename__ = "command_allowlist"
    __table_args__ = (Index("ix_command_allowlist_session", "session_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_new_uuid)
    session_id: Mapped[str] = mapped_column(String(64), ForeignKey("sessions.session_id", ondelete="CASCADE"))
    tool_name: Mapped[str] = mapped_column(String(64), nullable=False)
    command_signature: Mapped[str | None] = mapped_column(String(256), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    session: Mapped[SessionRecord] = relationship(back_populates="command_allowlist")
