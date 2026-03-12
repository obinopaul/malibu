"""Session management — creation, loading, listing, forking, resuming.

Coordinates between database persistence and in-memory LangGraph checkpointers.
"""

from __future__ import annotations

from typing import Any

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph.state import CompiledStateGraph

from malibu.agent.graph import build_agent
from malibu.agent.modes import DEFAULT_MODES
from malibu.config import Settings
from malibu.telemetry.logging import get_logger

log = get_logger(__name__)


class SessionManager:
    """Manages agent lifecycle per ACP session.

    Each session gets its own compiled agent (returned by ``build_agent()``
    from ``langchain.agents.create_agent``), potentially sharing a
    checkpointer for persistence.
    """

    def __init__(self, settings: Settings, *, checkpointer: Any | None = None) -> None:
        self._settings = settings
        self._checkpointer = checkpointer or MemorySaver()
        self._agents: dict[str, CompiledStateGraph] = {}
        self._cwds: dict[str, str] = {}
        self._modes: dict[str, str] = {}
        self._models: dict[str, str] = {}

    def create_session(self, session_id: str, *, cwd: str, mode_id: str | None = None) -> CompiledStateGraph:
        """Create a new agent graph for a session."""
        mode = mode_id or DEFAULT_MODES.current_mode_id
        agent = build_agent(
            settings=self._settings,
            cwd=cwd,
            mode=mode,
            checkpointer=self._checkpointer,
        )
        self._agents[session_id] = agent
        self._cwds[session_id] = cwd
        self._modes[session_id] = mode
        self._models[session_id] = self._settings.llm_model
        log.info("session_created", session_id=session_id, cwd=cwd, mode=mode)
        return agent

    def get_agent(self, session_id: str) -> CompiledStateGraph | None:
        """Retrieve the compiled agent for a session."""
        return self._agents.get(session_id)

    def get_or_create_agent(self, session_id: str, *, cwd: str) -> CompiledStateGraph:
        """Get existing or create new agent for a session."""
        agent = self._agents.get(session_id)
        if agent is None:
            mode = self._modes.get(session_id, DEFAULT_MODES.current_mode_id)
            agent = self.create_session(session_id, cwd=cwd, mode_id=mode)
        return agent

    def set_mode(self, session_id: str, mode_id: str) -> None:
        """Switch a session's mode, rebuilding the agent with new interrupt config."""
        cwd = self._cwds.get(session_id, ".")
        self._modes[session_id] = mode_id
        # Rebuild agent with new mode (new HITL middleware config)
        self._agents[session_id] = build_agent(
            settings=self._settings,
            cwd=cwd,
            mode=mode_id,
            checkpointer=self._checkpointer,
        )
        log.info("session_mode_changed", session_id=session_id, mode_id=mode_id)

    def set_model(self, session_id: str, model_id: str) -> None:
        """Update the LLM model for a session, rebuilding the agent."""
        cwd = self._cwds.get(session_id, ".")
        mode = self._modes.get(session_id, DEFAULT_MODES.current_mode_id)
        self._models[session_id] = model_id
        self._agents[session_id] = build_agent(
            settings=self._settings,
            cwd=cwd,
            mode=mode,
            checkpointer=self._checkpointer,
            model_id=model_id,
        )
        log.info("session_model_changed", session_id=session_id, model_id=model_id)

    def get_cwd(self, session_id: str) -> str:
        return self._cwds.get(session_id, ".")

    def get_mode(self, session_id: str) -> str:
        return self._modes.get(session_id, DEFAULT_MODES.current_mode_id)

    def get_model(self, session_id: str) -> str:
        return self._models.get(session_id, self._settings.llm_model)

    def fork_session(self, source_id: str, new_id: str, *, cwd: str) -> CompiledStateGraph:
        """Fork a session — create a new agent with the same mode."""
        mode = self._modes.get(source_id, DEFAULT_MODES.current_mode_id)
        return self.create_session(new_id, cwd=cwd, mode_id=mode)

    def remove_session(self, session_id: str) -> None:
        """Clean up a session's resources."""
        self._agents.pop(session_id, None)
        self._cwds.pop(session_id, None)
        self._modes.pop(session_id, None)
        self._models.pop(session_id, None)
