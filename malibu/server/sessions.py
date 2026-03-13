"""Session lifecycle and lightweight persistence for Malibu ACP sessions."""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
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
    """Manage agents, callbacks, and persisted session records."""

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
        self._session_cache: dict[str, dict[str, Any]] = {}

        self._skill_registry = SkillRegistry()
        self._plugin_manager = PluginManager()
        self._load_skills()

    # ------------------------------------------------------------------
    # Skill loading
    # ------------------------------------------------------------------

    def _load_skills(self) -> None:
        try:
            loader = SkillLoader(cwd=".")
            self._skill_registry.register_all(loader.load_all())
        except Exception as exc:
            log.warning("skills_load_failed", error=str(exc))

        try:
            for plugin in self._plugin_manager.list_enabled():
                for skill_dir in self._plugin_manager.get_plugin_skills(plugin):
                    try:
                        self._skill_registry.register_all(SkillLoader.load_from_directory(skill_dir))
                    except Exception as exc:
                        log.warning(
                            "plugin_skill_load_failed",
                            plugin=plugin.name,
                            skill_dir=str(skill_dir),
                            error=str(exc),
                        )
        except Exception as exc:
            log.warning("plugin_skills_scan_failed", error=str(exc))

    @property
    def skill_registry(self) -> SkillRegistry:
        return self._skill_registry

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def _session_dir(self, cwd: str) -> Path:
        root = Path(cwd).resolve()
        candidate = root / ".malibu" / "sessions"
        try:
            if root.exists():
                candidate.parent.mkdir(parents=True, exist_ok=True)
                return candidate
        except Exception:
            pass
        fallback_root = Path(tempfile.gettempdir()) / "malibu-session-store" / sha256(str(root).encode("utf-8")).hexdigest()[:12]
        fallback_root.mkdir(parents=True, exist_ok=True)
        return fallback_root / "sessions"

    def _session_file(self, cwd: str, session_id: str) -> Path:
        return self._session_dir(cwd) / f"{session_id}.json"

    def _load_record(self, session_id: str, *, cwd: str | None = None) -> dict[str, Any] | None:
        cached = self._session_cache.get(session_id)
        if cached is not None:
            return cached
        if cwd is None:
            cwd = self._cwds.get(session_id)
        if cwd is None:
            return None
        file_path = self._session_file(cwd, session_id)
        if not file_path.exists():
            return None
        try:
            record = json.loads(file_path.read_text(encoding="utf-8"))
        except Exception as exc:
            log.warning("session_record_load_failed", session_id=session_id, error=str(exc))
            return None
        self._session_cache[session_id] = record
        return record

    def _save_record(self, session_id: str) -> None:
        record = self._session_cache.get(session_id)
        cwd = self._cwds.get(session_id)
        if record is None or cwd is None:
            return
        file_path = self._session_file(cwd, session_id)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        record["updated_at"] = self._now()
        file_path.write_text(json.dumps(record, indent=2, ensure_ascii=True), encoding="utf-8")

    def _ensure_record(
        self,
        session_id: str,
        *,
        cwd: str,
        mode_id: str,
        model_id: str | None = None,
    ) -> dict[str, Any]:
        record = self._load_record(session_id, cwd=cwd)
        if record is None:
            record = {
                "session_id": session_id,
                "cwd": cwd,
                "title": f"Session {session_id[:8]}",
                "mode": mode_id,
                "model": model_id or self._settings.llm_model,
                "config": {},
                "history": [],
                "created_at": self._now(),
                "updated_at": self._now(),
            }
            self._session_cache[session_id] = record
            self._save_record(session_id)
        return record

    def record_session_update(self, session_id: str, update: Any) -> None:
        record = self._session_cache.get(session_id)
        if record is None:
            cwd = self._cwds.get(session_id, ".")
            mode = self._modes.get(session_id, DEFAULT_MODES.current_mode_id)
            record = self._ensure_record(session_id, cwd=cwd, mode_id=mode, model_id=self.get_model(session_id))
        payload = update.model_dump(by_alias=True, mode="json") if hasattr(update, "model_dump") else update
        record.setdefault("history", []).append({"kind": "session_update", "payload": payload})
        self._save_record(session_id)

    def record_tui_event(self, session_id: str, params: dict[str, Any]) -> None:
        record = self._session_cache.get(session_id)
        if record is None:
            cwd = self._cwds.get(session_id, ".")
            mode = self._modes.get(session_id, DEFAULT_MODES.current_mode_id)
            record = self._ensure_record(session_id, cwd=cwd, mode_id=mode, model_id=self.get_model(session_id))
        record.setdefault("history", []).append({"kind": "tui_event", "payload": params})
        self._save_record(session_id)

    def list_session_records(self, *, cwd: str | None = None) -> list[dict[str, Any]]:
        if cwd is None:
            records = list(self._session_cache.values())
        else:
            session_dir = self._session_dir(cwd)
            records = []
            if session_dir.exists():
                for path in session_dir.glob("*.json"):
                    try:
                        records.append(json.loads(path.read_text(encoding="utf-8")))
                    except Exception:
                        continue
        records.sort(key=lambda item: item.get("updated_at", ""), reverse=True)
        return records

    def get_bootstrap_payload(self, session_id: str) -> dict[str, Any]:
        record = self._load_record(session_id)
        return {
            "session_id": session_id,
            "session_title": record.get("title", f"Session {session_id[:8]}") if record else f"Session {session_id[:8]}",
            "cwd": self.get_cwd(session_id),
            "mode": self.get_mode(session_id),
            "model": self.get_model(session_id),
            "config": (record or {}).get("config", {}),
            "history": list((record or {}).get("history", [])),
        }

    # ------------------------------------------------------------------
    # Agent creation
    # ------------------------------------------------------------------

    def _collect_extra_tools(self, cwd: str) -> tuple[list, str]:
        extra_tools: list = []
        extra_prompt_parts: list[str] = []
        skill_prompt = build_skill_prompt_section(self._skill_registry)
        if skill_prompt:
            extra_prompt_parts.append(skill_prompt)
        extra_prompt = "\n\n".join(extra_prompt_parts) if extra_prompt_parts else ""
        return extra_tools, extra_prompt

    def _create_hook_manager(self, session_id: str, cwd: str) -> HookManager | None:
        if not self._settings.hooks_enabled:
            return None
        try:
            config = load_hooks_config(cwd)
            manager = HookManager(config, session_id=session_id, cwd=cwd)
            self._hook_managers[session_id] = manager
            return manager
        except Exception as exc:
            log.warning("hooks_init_failed", session_id=session_id, error=str(exc))
            return None

    def create_session(
        self,
        session_id: str,
        *,
        cwd: str,
        mode_id: str | None = None,
    ) -> CompiledStateGraph:
        persisted = self._load_record(session_id, cwd=cwd)
        mode = mode_id or (persisted.get("mode") if persisted else DEFAULT_MODES.current_mode_id) or DEFAULT_MODES.current_mode_id
        model_id = (persisted.get("model") if persisted else None) or self._settings.llm_model
        extra_tools, extra_prompt = self._collect_extra_tools(cwd)

        hook_manager = self._create_hook_manager(session_id, cwd)
        if hook_manager is not None:
            hook_manager.run_hooks(HookEvent.SESSION_START)

        self._create_cost_callback(session_id)

        agent = build_agent(
            settings=self._settings,
            cwd=cwd,
            mode=mode,
            checkpointer=self._checkpointer,
            model_id=model_id,
            extra_tools=extra_tools or None,
            extra_prompt=extra_prompt or None,
            hook_manager=hook_manager,
        )
        self._agents[session_id] = agent
        self._cwds[session_id] = cwd
        self._modes[session_id] = mode
        self._models[session_id] = model_id
        record = self._ensure_record(session_id, cwd=cwd, mode_id=mode, model_id=model_id)
        record["cwd"] = cwd
        record["mode"] = mode
        record["model"] = model_id
        self._save_record(session_id)
        return agent

    def get_agent(self, session_id: str) -> CompiledStateGraph | None:
        return self._agents.get(session_id)

    def get_or_create_agent(self, session_id: str, *, cwd: str) -> CompiledStateGraph:
        agent = self._agents.get(session_id)
        if agent is None:
            agent = self.create_session(session_id, cwd=cwd, mode_id=self._modes.get(session_id))
        return agent

    def set_mode(self, session_id: str, mode_id: str) -> None:
        cwd = self._cwds.get(session_id, ".")
        self._modes[session_id] = mode_id
        extra_tools, extra_prompt = self._collect_extra_tools(cwd)
        hook_manager = self._hook_managers.get(session_id)
        self._agents[session_id] = build_agent(
            settings=self._settings,
            cwd=cwd,
            mode=mode_id,
            checkpointer=self._checkpointer,
            model_id=self.get_model(session_id),
            extra_tools=extra_tools or None,
            extra_prompt=extra_prompt or None,
            hook_manager=hook_manager,
        )
        record = self._ensure_record(session_id, cwd=cwd, mode_id=mode_id, model_id=self.get_model(session_id))
        record["mode"] = mode_id
        self._save_record(session_id)

    def set_model(self, session_id: str, model_id: str) -> None:
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
        record = self._ensure_record(session_id, cwd=cwd, mode_id=mode, model_id=model_id)
        record["model"] = model_id
        self._save_record(session_id)

    def update_config(self, session_id: str, config_id: str, value: Any) -> None:
        record = self._load_record(session_id)
        if record is None:
            cwd = self._cwds.get(session_id, ".")
            record = self._ensure_record(
                session_id,
                cwd=cwd,
                mode_id=self.get_mode(session_id),
                model_id=self.get_model(session_id),
            )
        config = record.setdefault("config", {})
        config[config_id] = value
        self._save_record(session_id)

    def set_title(self, session_id: str, title: str) -> None:
        record = self._load_record(session_id)
        if record is None:
            cwd = self._cwds.get(session_id, ".")
            record = self._ensure_record(
                session_id,
                cwd=cwd,
                mode_id=self.get_mode(session_id),
                model_id=self.get_model(session_id),
            )
        record["title"] = title
        self._save_record(session_id)

    def get_cwd(self, session_id: str) -> str:
        if session_id in self._cwds:
            return self._cwds[session_id]
        record = self._load_record(session_id)
        return str(record.get("cwd", ".")) if record else "."

    def get_mode(self, session_id: str) -> str:
        if session_id in self._modes:
            return self._modes[session_id]
        record = self._load_record(session_id)
        return str(record.get("mode", DEFAULT_MODES.current_mode_id)) if record else DEFAULT_MODES.current_mode_id

    def get_model(self, session_id: str) -> str:
        if session_id in self._models:
            return self._models[session_id]
        record = self._load_record(session_id)
        return str(record.get("model", self._settings.llm_model)) if record else self._settings.llm_model

    def fork_session(self, source_id: str, new_id: str, *, cwd: str) -> CompiledStateGraph:
        source_record = self._load_record(source_id)
        agent = self.create_session(
            new_id,
            cwd=cwd,
            mode_id=(source_record or {}).get("mode", self.get_mode(source_id)),
        )
        if source_record is not None:
            clone = json.loads(json.dumps(source_record))
            clone["session_id"] = new_id
            clone["cwd"] = cwd
            clone["title"] = f"Fork of {source_record.get('title', source_id[:8])}"
            self._session_cache[new_id] = clone
            self._save_record(new_id)
        return agent

    def remove_session(self, session_id: str) -> None:
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
        return self._hook_managers.get(session_id)

    # ------------------------------------------------------------------
    # Cost tracking
    # ------------------------------------------------------------------

    def _create_cost_callback(self, session_id: str) -> CostTrackingCallback | None:
        if not self._settings.cost_tracking_enabled:
            return None
        tracker = CostTracker()
        callback = CostTrackingCallback(tracker, model_name=self.get_model(session_id))
        self._cost_trackers[session_id] = tracker
        self._cost_callbacks[session_id] = callback
        return callback

    def get_session_cost(self, session_id: str) -> dict[str, Any]:
        tracker = self._cost_trackers.get(session_id)
        if tracker is None:
            return {}
        data = tracker.to_dict()
        data["formatted_cost"] = tracker.format_cost()
        return data

    def get_callbacks(self, session_id: str) -> list[Any]:
        callback = self._cost_callbacks.get(session_id)
        return [callback] if callback is not None else []
