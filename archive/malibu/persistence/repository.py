"""Async CRUD repositories for session management and message history."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Sequence
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from malibu.persistence.models import (
    CommandAllowlistRecord,
    MessageRecord,
    PlanRecord,
    SessionRecord,
    ToolCallRecord,
)


class SessionRepository:
    """CRUD operations for ACP sessions."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def create(self, *, cwd: str, mode_id: str | None = None, model_id: str | None = None) -> SessionRecord:
        session_id = uuid4().hex
        record = SessionRecord(session_id=session_id, cwd=cwd, mode_id=mode_id, model_id=model_id)
        self._db.add(record)
        await self._db.flush()
        return record

    async def get_by_session_id(self, session_id: str) -> SessionRecord | None:
        stmt = select(SessionRecord).where(SessionRecord.session_id == session_id)
        result = await self._db.execute(stmt)
        return result.scalar_one_or_none()

    async def list_sessions(
        self, *, cwd: str | None = None, cursor: str | None = None, limit: int = 50
    ) -> Sequence[SessionRecord]:
        stmt = select(SessionRecord).where(SessionRecord.is_active.is_(True)).order_by(SessionRecord.updated_at.desc())
        if cwd:
            stmt = stmt.where(SessionRecord.cwd == cwd)
        if cursor:
            # cursor is the updated_at ISO string of the last item in the previous page
            stmt = stmt.where(SessionRecord.updated_at < datetime.fromisoformat(cursor))
        stmt = stmt.limit(limit)
        result = await self._db.execute(stmt)
        return result.scalars().all()

    async def update_mode(self, session_id: str, mode_id: str) -> None:
        stmt = update(SessionRecord).where(SessionRecord.session_id == session_id).values(mode_id=mode_id)
        await self._db.execute(stmt)

    async def update_model(self, session_id: str, model_id: str) -> None:
        stmt = update(SessionRecord).where(SessionRecord.session_id == session_id).values(model_id=model_id)
        await self._db.execute(stmt)

    async def update_title(self, session_id: str, title: str) -> None:
        stmt = update(SessionRecord).where(SessionRecord.session_id == session_id).values(title=title)
        await self._db.execute(stmt)

    async def update_config(self, session_id: str, config_json: dict) -> None:
        stmt = update(SessionRecord).where(SessionRecord.session_id == session_id).values(config_json=config_json)
        await self._db.execute(stmt)

    async def deactivate(self, session_id: str) -> None:
        stmt = update(SessionRecord).where(SessionRecord.session_id == session_id).values(is_active=False)
        await self._db.execute(stmt)

    async def fork(self, source_session_id: str, *, cwd: str) -> SessionRecord:
        """Deep-clone a session: copy the session row and all its messages."""
        source = await self.get_by_session_id(source_session_id)
        if source is None:
            raise ValueError(f"Session {source_session_id} not found")

        new_session_id = uuid4().hex
        new_record = SessionRecord(
            session_id=new_session_id,
            cwd=cwd,
            mode_id=source.mode_id,
            model_id=source.model_id,
            title=f"Fork of {source.title or source.session_id}",
            config_json=source.config_json,
        )
        self._db.add(new_record)
        await self._db.flush()

        # Clone messages
        msg_stmt = (
            select(MessageRecord)
            .where(MessageRecord.session_id == source_session_id)
            .order_by(MessageRecord.created_at)
        )
        result = await self._db.execute(msg_stmt)
        for msg in result.scalars():
            self._db.add(
                MessageRecord(
                    session_id=new_session_id,
                    role=msg.role,
                    content_json=msg.content_json,
                )
            )
        await self._db.flush()
        return new_record


class MessageRepository:
    """CRUD operations for session messages."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def add(self, *, session_id: str, role: str, content_json: dict) -> MessageRecord:
        record = MessageRecord(session_id=session_id, role=role, content_json=content_json)
        self._db.add(record)
        await self._db.flush()
        return record

    async def list_by_session(self, session_id: str, *, limit: int = 200) -> Sequence[MessageRecord]:
        stmt = (
            select(MessageRecord)
            .where(MessageRecord.session_id == session_id)
            .order_by(MessageRecord.created_at)
            .limit(limit)
        )
        result = await self._db.execute(stmt)
        return result.scalars().all()


class ToolCallRepository:
    """CRUD operations for tool call records."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def add(self, *, session_id: str, tool_call_id: str, kind: str | None, title: str, input_json: dict | None) -> ToolCallRecord:
        record = ToolCallRecord(
            session_id=session_id, tool_call_id=tool_call_id, kind=kind, title=title, input_json=input_json
        )
        self._db.add(record)
        await self._db.flush()
        return record

    async def update_status(self, tool_call_id: str, *, status: str, output_json: dict | None = None) -> None:
        values: dict = {"status": status}
        if status in ("completed", "failed"):
            values["completed_at"] = datetime.now(timezone.utc)
        if output_json is not None:
            values["output_json"] = output_json
        stmt = update(ToolCallRecord).where(ToolCallRecord.tool_call_id == tool_call_id).values(**values)
        await self._db.execute(stmt)


class PlanRepository:
    """CRUD operations for execution plans."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def upsert(self, session_id: str, entries_json: dict) -> PlanRecord:
        stmt = select(PlanRecord).where(PlanRecord.session_id == session_id).order_by(PlanRecord.updated_at.desc())
        result = await self._db.execute(stmt)
        existing = result.scalar_one_or_none()
        if existing:
            existing.entries_json = entries_json
            existing.updated_at = datetime.now(timezone.utc)
            await self._db.flush()
            return existing
        record = PlanRecord(session_id=session_id, entries_json=entries_json)
        self._db.add(record)
        await self._db.flush()
        return record

    async def get_latest(self, session_id: str) -> PlanRecord | None:
        stmt = select(PlanRecord).where(PlanRecord.session_id == session_id).order_by(PlanRecord.updated_at.desc())
        result = await self._db.execute(stmt)
        return result.scalar_one_or_none()

    async def clear(self, session_id: str) -> None:
        plan = await self.get_latest(session_id)
        if plan:
            await self._db.delete(plan)
            await self._db.flush()


class CommandAllowlistRepository:
    """Per-session command type auto-approval tracking."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def add(self, *, session_id: str, tool_name: str, command_signature: str | None = None) -> None:
        record = CommandAllowlistRecord(
            session_id=session_id, tool_name=tool_name, command_signature=command_signature
        )
        self._db.add(record)
        await self._db.flush()

    async def is_allowed(self, session_id: str, tool_name: str, command_signature: str | None = None) -> bool:
        stmt = select(CommandAllowlistRecord).where(
            CommandAllowlistRecord.session_id == session_id,
            CommandAllowlistRecord.tool_name == tool_name,
        )
        if command_signature:
            stmt = stmt.where(
                (CommandAllowlistRecord.command_signature == command_signature)
                | (CommandAllowlistRecord.command_signature.is_(None))
            )
        result = await self._db.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def list_for_session(self, session_id: str) -> Sequence[CommandAllowlistRecord]:
        stmt = select(CommandAllowlistRecord).where(CommandAllowlistRecord.session_id == session_id)
        result = await self._db.execute(stmt)
        return result.scalars().all()
