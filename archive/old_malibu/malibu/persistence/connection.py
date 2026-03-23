"""Async database engine and session factory."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from malibu.config import Settings

_engine = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


async def init_db(settings: Settings) -> None:
    """Initialise the async engine and session factory (call once at startup)."""
    global _engine, _session_factory
    _engine = create_async_engine(
        settings.database_url,
        echo=(settings.log_level == "DEBUG"),
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=20,
    )
    _session_factory = async_sessionmaker(_engine, expire_on_commit=False)


async def close_db() -> None:
    """Dispose engine (call at shutdown)."""
    global _engine, _session_factory
    if _engine:
        await _engine.dispose()
    _engine = None
    _session_factory = None


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Return the current session factory (must call init_db first)."""
    if _session_factory is None:
        raise RuntimeError("Database not initialised — call init_db() first")
    return _session_factory


def get_engine():
    """Return the current engine."""
    if _engine is None:
        raise RuntimeError("Database not initialised — call init_db() first")
    return _engine
