"""Subprocess executor for hook commands."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from typing import Any

from malibu.hooks.models import HookCommand
from malibu.telemetry.logging import get_logger

_log = get_logger(__name__)


@dataclass
class HookResult:
    """Result from a single hook command execution."""

    command: str
    exit_code: int = 0
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False
    error: str | None = None

    @property
    def success(self) -> bool:
        return self.exit_code == 0 and not self.timed_out and self.error is None

    @property
    def should_block(self) -> bool:
        return self.exit_code == 2

    def parse_json_output(self) -> dict[str, Any]:
        if not self.stdout.strip():
            return {}
        try:
            return json.loads(self.stdout)
        except (json.JSONDecodeError, ValueError):
            return {}


class HookCommandExecutor:
    """Execute hook commands with JSON stdin payloads."""

    def execute(
        self,
        command: HookCommand,
        stdin_data: dict[str, Any],
        cwd: str | None = None,
    ) -> HookResult:
        stdin_json = json.dumps(stdin_data)
        try:
            result = subprocess.run(
                command.command,
                shell=True,
                input=stdin_json,
                capture_output=True,
                text=True,
                timeout=command.timeout,
                cwd=cwd,
            )
            return HookResult(
                command=command.command,
                exit_code=result.returncode,
                stdout=result.stdout,
                stderr=result.stderr,
            )
        except subprocess.TimeoutExpired:
            _log.warning(
                "hook_timeout",
                command=command.command,
                timeout=command.timeout,
            )
            return HookResult(
                command=command.command,
                exit_code=1,
                timed_out=True,
                error=f"Hook timed out after {command.timeout}s",
            )
        except OSError as exc:
            _log.error("hook_exec_failed", command=command.command, error=str(exc))
            return HookResult(
                command=command.command,
                exit_code=1,
                error=f"Failed to execute hook: {exc}",
            )
