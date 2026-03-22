"""Tests for hooks integration into middleware and sessions."""

import pytest

from malibu.hooks.models import HookConfig, HookEvent, HookCommand, HookMatcher
from malibu.hooks.manager import HookManager, HookOutcome


class TestHookManager:
    def test_empty_config_no_hooks(self) -> None:
        config = HookConfig()
        mgr = HookManager(config, session_id="test", cwd=".")
        outcome = mgr.run_hooks(HookEvent.PRE_TOOL_USE, match_value="execute")
        assert not outcome.blocked

    def test_blocking_hook(self, tmp_path) -> None:
        """Test that exit code 2 blocks execution."""
        import sys
        # Use python -c to exit with code 2 (cross-platform)
        exe = sys.executable
        cmd = f'"{exe}" -c "import sys; sys.exit(2)"'

        config = HookConfig.from_dict({
            "hooks": {
                "PreToolUse": [{
                    "matcher": "execute",
                    "hooks": [{"command": cmd, "timeout": 5}],
                }]
            }
        })
        mgr = HookManager(config, session_id="test", cwd=str(tmp_path))
        outcome = mgr.run_hooks(HookEvent.PRE_TOOL_USE, match_value="execute")
        assert outcome.blocked

    def test_non_matching_hook_skipped(self) -> None:
        config = HookConfig.from_dict({
            "hooks": {
                "PreToolUse": [{
                    "matcher": "execute",
                    "hooks": [{"command": "exit 2", "timeout": 5}],
                }]
            }
        })
        mgr = HookManager(config, session_id="test", cwd=".")
        # Different tool name — should not match
        outcome = mgr.run_hooks(HookEvent.PRE_TOOL_USE, match_value="read_file")
        assert not outcome.blocked

    def test_has_hooks_for(self) -> None:
        config = HookConfig.from_dict({
            "hooks": {
                "SessionStart": [{
                    "hooks": [{"command": "echo started"}]
                }]
            }
        })
        mgr = HookManager(config, session_id="test", cwd=".")
        assert mgr.has_hooks_for(HookEvent.SESSION_START) is True
        assert mgr.has_hooks_for(HookEvent.SESSION_END) is False


class TestHookConfig:
    def test_from_dict_ignores_unknown_events(self) -> None:
        config = HookConfig.from_dict({
            "hooks": {
                "UnknownEvent": [{"hooks": [{"command": "echo"}]}],
                "PreToolUse": [{"hooks": [{"command": "echo pre"}]}],
            }
        })
        assert "UnknownEvent" not in config.hooks
        assert "PreToolUse" in config.hooks

    def test_matcher_with_regex(self) -> None:
        matcher = HookMatcher(
            matcher="(execute|write_file)",
            hooks=[HookCommand(command="echo matched")],
        )
        assert matcher.matches("execute") is True
        assert matcher.matches("write_file") is True
        assert matcher.matches("read_file") is False

    def test_matcher_none_matches_everything(self) -> None:
        matcher = HookMatcher(hooks=[HookCommand(command="echo")])
        assert matcher.matches("anything") is True
        assert matcher.matches(None) is True


class TestHookMiddlewareFactory:
    def test_build_hook_middleware_returns_middleware(self) -> None:
        from malibu.agent.middleware import _build_hook_middleware

        config = HookConfig()
        mgr = HookManager(config, session_id="test", cwd=".")
        middleware = _build_hook_middleware(mgr)
        assert middleware is not None

    def test_build_middleware_stack_with_hooks(self) -> None:
        from malibu.agent.middleware import build_middleware_stack

        config = HookConfig()
        mgr = HookManager(config, session_id="test", cwd=".")
        stack = build_middleware_stack("accept_edits", hook_manager=mgr)
        # Should have HITL + hook middleware + log_tool_calls = 3
        assert len(stack) == 3

    def test_build_middleware_stack_without_hooks(self) -> None:
        from malibu.agent.middleware import build_middleware_stack

        stack = build_middleware_stack("accept_edits")
        # Should have HITL + log_tool_calls = 2
        assert len(stack) == 2
