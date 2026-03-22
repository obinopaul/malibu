"""Hook manager — orchestrates hook execution for lifecycle events."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from malibu.hooks.models import HookConfig, HookEvent
from malibu.hooks.executor import HookResult, HookCommandExecutor
from malibu.telemetry.logging import get_logger

log = get_logger(__name__)


@dataclass
class HookOutcome:
    """Aggregated outcome from running all hooks for an event."""

    blocked: bool = False
    block_reason: str = ""
    results: list[HookResult] = field(default_factory=list)
    additional_context: str | None = None
    updated_input: dict[str, Any] | None = None
    permission_decision: str | None = None
    decision: str | None = None


class HookManager:
    """Orchestrates hook execution for lifecycle events.

    Takes a snapshot of HookConfig at init. Mid-session changes to
    config are not reflected (security: prevents config TOCTOU).
    """

    def __init__(
        self,
        config: HookConfig,
        session_id: str = "",
        cwd: str = "",
    ) -> None:
        self._config = config
        self._session_id = session_id
        self._cwd = cwd
        self._executor = HookCommandExecutor()

    def has_hooks_for(self, event: HookEvent) -> bool:
        """Fast check: are there hooks registered for this event?"""
        return self._config.has_hooks_for(event)

    def run_hooks(
        self,
        event: HookEvent,
        match_value: str | None = None,
        event_data: dict[str, Any] | None = None,
    ) -> HookOutcome:
        """Run all matching hooks for an event.

        Hooks execute sequentially. Short-circuits on block (exit code 2).

        Args:
            event: The lifecycle event.
            match_value: Value to test against matcher regex (e.g., tool name).
            event_data: Additional event-specific data for stdin payload.

        Returns:
            HookOutcome aggregating all results.
        """
        outcome = HookOutcome()

        matchers = self._config.get_matchers(event)
        if not matchers:
            return outcome

        for matcher in matchers:
            if not matcher.matches(match_value):
                continue

            stdin_data = self._build_stdin(event, match_value, event_data)

            for command in matcher.hooks:
                result = self._executor.execute(command, stdin_data, self._cwd)
                outcome.results.append(result)

                if result.should_block:
                    outcome.blocked = True
                    parsed = result.parse_json_output()
                    outcome.block_reason = parsed.get(
                        "reason", result.stderr.strip() or "Blocked by hook"
                    )
                    outcome.decision = parsed.get("decision")
                    log.info(
                        "hook_blocked",
                        hook_event=event.value,
                        command=command.command,
                        reason=outcome.block_reason,
                    )
                    return outcome

                if result.success:
                    parsed = result.parse_json_output()
                    if parsed.get("additionalContext"):
                        outcome.additional_context = parsed["additionalContext"]
                    if parsed.get("updatedInput"):
                        outcome.updated_input = parsed["updatedInput"]

        return outcome

    def _build_stdin(
        self,
        event: HookEvent,
        match_value: str | None,
        event_data: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Build JSON stdin payload for hook command."""
        payload = {
            "event": event.value,
            "sessionId": self._session_id,
            "cwd": self._cwd,
        }
        if match_value:
            payload["matchValue"] = match_value
        if event_data:
            payload["data"] = event_data
        return payload
