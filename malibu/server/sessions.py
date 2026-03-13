"""Session management — creation, loading, listing, forking, resuming.

Coordinates between database persistence and in-memory LangGraph checkpointers.
Wires skills, MCP tools, and subagent delegation into each session's agent.
"""

from __future__ import annotations

from typing import Any

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph.state import CompiledStateGraph

from malibu.agent.graph import build_agent
from malibu.agent.modes import DEFAULT_MODES
from malibu.config import Settings
from malibu.hooks import HookEvent, HookManager, load_hooks_config
from malibu.plugins.manager import PluginManager
from malibu.runtime.cost_callback import CostTrackingCallback
from malibu.runtime.cost_tracker import CostTracker
from malibu.skills.loader import SkillLoader
from malibu.skills.middleware import build_skill_prompt_section
from malibu.skills.registry import SkillRegistry
from malibu.telemetry.logging import get_logger

log = get_logger(__name__)


class SessionManager:
    """Manages agent lifecycle per ACP session.

    Each session gets its own compiled agent (returned by ``build_agent()``
    from ``langchain.agents.create_agent``), potentially sharing a
    checkpointer for persistence.

    Skills are loaded once at construction and injected into every session.
    MCP tools and subagent tools are passed per-session via ``extra_tools``.
    """

    def __init__(self, settings: Settings, *, checkpointer: Any | None = None) -> None:
        self._settings = settings
        self._checkpointer = checkpointer or MemorySaver()
        self._agents: dict[str, CompiledStateGraph] = {}
        self._cwds: dict[str, str] = {}
        self._modes: dict[str, str] = {}
        self._models: dict[str, str] = {}
        self._hook_managers: dict[str, HookManager] = {}
        self._cost_trackers: dict[str, CostTracker] = {}
        self._cost_callbacks: dict[str, CostTrackingCallback] = {}

        # Load skills once at startup
        self._skill_registry = SkillRegistry()
        self._plugin_manager = PluginManager()
        self._load_skills()

    def _load_skills(self) -> None:
        """Discover and load skills from builtin, user, project, and plugin directories."""
        try:
            loader = SkillLoader(cwd=".")
            skills = loader.load_all()
            self._skill_registry.register_all(skills)
            log.info("skills_loaded", count=len(skills))
        except Exception as exc:
            log.warning("skills_load_failed", error=str(exc))

        # Load skills from enabled plugins
        try:
            for plugin in self._plugin_manager.list_enabled():
                skill_dirs = self._plugin_manager.get_plugin_skills(plugin)
                for skill_dir in skill_dirs:
                    try:
                        plugin_skills = SkillLoader.load_from_directory(skill_dir)
                        self._skill_registry.register_all(plugin_skills)
                    except Exception as exc:
                        log.warning(
                            "plugin_skill_load_failed",
                            plugin=plugin.name,
                            skill_dir=str(skill_dir),
                            error=str(exc),
                        )
            if self._plugin_manager.list_enabled():
                log.info(
                    "plugin_skills_loaded",
                    plugin_count=len(self._plugin_manager.list_enabled()),
                )
        except Exception as exc:
            log.warning("plugin_skills_scan_failed", error=str(exc))

    @property
    def skill_registry(self) -> SkillRegistry:
        return self._skill_registry

    def _collect_extra_tools(self, cwd: str) -> tuple[list, str]:
        """Collect extra tools and prompt text from skills and subagents."""
        extra_tools: list = []
        extra_prompt_parts: list[str] = []

        # Skills - provide instruction-based prompts, not tools
        skill_prompt = build_skill_prompt_section(self._skill_registry)
        if skill_prompt:
            extra_prompt_parts.append(skill_prompt)

        extra_prompt = "\n\n".join(extra_prompt_parts) if extra_prompt_parts else ""
        return extra_tools, extra_prompt

    def _create_hook_manager(self, session_id: str, cwd: str) -> HookManager | None:
        """Create and store a HookManager for a session if hooks are enabled."""
        if not self._settings.hooks_enabled:
            return None
        try:
            config = load_hooks_config(cwd)
            hm = HookManager(config, session_id=session_id, cwd=cwd)
            self._hook_managers[session_id] = hm
            return hm
        except Exception as exc:
            log.warning("hooks_init_failed", session_id=session_id, error=str(exc))
            return None

    def create_session(self, session_id: str, *, cwd: str, mode_id: str | None = None) -> CompiledStateGraph:
        """Create a new agent graph for a session."""
        mode = mode_id or DEFAULT_MODES.current_mode_id
        extra_tools, extra_prompt = self._collect_extra_tools(cwd)

        # Initialize hooks
        hook_manager = self._create_hook_manager(session_id, cwd)
        if hook_manager is not None:
            hook_manager.run_hooks(HookEvent.SESSION_START)

        # Initialize cost tracking
        cost_callback = self._create_cost_callback(session_id)

        agent = build_agent(
            settings=self._settings,
            cwd=cwd,
            mode=mode,
            checkpointer=self._checkpointer,
            extra_tools=extra_tools or None,
            extra_prompt=extra_prompt or None,
            hook_manager=hook_manager,
            callbacks=[cost_callback] if cost_callback else None,
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
        extra_tools, extra_prompt = self._collect_extra_tools(cwd)
        hook_manager = self._hook_managers.get(session_id)
        self._agents[session_id] = build_agent(
            settings=self._settings,
            cwd=cwd,
            mode=mode_id,
            checkpointer=self._checkpointer,
            extra_tools=extra_tools or None,
            extra_prompt=extra_prompt or None,
            hook_manager=hook_manager,
        )
        log.info("session_mode_changed", session_id=session_id, mode_id=mode_id)

    def set_model(self, session_id: str, model_id: str) -> None:
        """Update the LLM model for a session, rebuilding the agent."""
        cwd = self._cwds.get(session_id, ".")
        mode = self._modes.get(session_id, DEFAULT_MODES.current_mode_id)
        self._models[session_id] = model_id
        extra_tools, extra_prompt = self._collect_extra_tools(cwd)
        hook_manager = self._hook_managers.get(session_id)
        self._agents[session_id] = build_agent(
            settings=self._settings,
            cwd=cwd,
            mode=mode,
            checkpointer=self._checkpointer,
            model_id=model_id,
            extra_tools=extra_tools or None,
            extra_prompt=extra_prompt or None,
            hook_manager=hook_manager,
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
        hook_manager = self._hook_managers.pop(session_id, None)
        if hook_manager is not None:
            try:
                hook_manager.run_hooks(HookEvent.SESSION_END)
            except Exception:
                pass
        self._agents.pop(session_id, None)
        self._cwds.pop(session_id, None)
        self._modes.pop(session_id, None)
        self._models.pop(session_id, None)
        self._cost_trackers.pop(session_id, None)
        self._cost_callbacks.pop(session_id, None)

    def get_hook_manager(self, session_id: str) -> HookManager | None:
        """Return the HookManager for a session, if any."""
        return self._hook_managers.get(session_id)

    # ── Cost tracking ─────────────────────────────────────────────

    def _create_cost_callback(self, session_id: str) -> CostTrackingCallback | None:
        """Create a CostTrackingCallback for a session if cost tracking is enabled."""
        if not self._settings.cost_tracking_enabled:
            return None
        tracker = CostTracker()
        model_name = self._models.get(session_id, self._settings.llm_model)
        cb = CostTrackingCallback(tracker, model_name=model_name)
        self._cost_trackers[session_id] = tracker
        self._cost_callbacks[session_id] = cb
        return cb

    def get_session_cost(self, session_id: str) -> dict[str, Any]:
        """Return cost data for a session.

        Returns:
            Dict with ``total_cost_usd``, ``total_input_tokens``,
            ``total_output_tokens``, ``api_call_count``, and
            ``formatted_cost``.  Returns empty dict if not tracked.
        """
        tracker = self._cost_trackers.get(session_id)
        if tracker is None:
            return {}
        data = tracker.to_dict()
        data["formatted_cost"] = tracker.format_cost()
        return data
