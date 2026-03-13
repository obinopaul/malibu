"""Inline tool approval controller."""

from __future__ import annotations

import asyncio
from typing import Any

from malibu.tui.managers.interrupt_manager import InterruptKind, InterruptManager
from malibu.tui.modals.detail_modal import JsonEditorModal
from malibu.tui.widgets.conversation.blocks import InlineDecisionBlock


class ApprovalPromptController:
    """Render and resolve inline tool approval prompts."""

    def __init__(self, screen: Any, interrupt_manager: InterruptManager) -> None:
        self.screen = screen
        self.interrupt_manager = interrupt_manager
        self._future: asyncio.Future[dict[str, Any]] | None = None
        self._payload: dict[str, Any] = {}
        self._block: InlineDecisionBlock | None = None
        self._options: list[tuple[str, str]] = []

    @property
    def active(self) -> bool:
        return self._future is not None and not self._future.done()

    async def start(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self.active:
            raise RuntimeError("tool approval prompt already active")
        self._payload = payload
        self._options = self._build_options(payload)
        self._block = InlineDecisionBlock(
            title=str(payload.get("title", payload.get("tool_name", "Tool review"))),
            subtitle=str(payload.get("subtitle", payload.get("tool_name", ""))),
            body=self._body_text(payload),
            options=self._options,
        )
        self.screen.conversation.render_inline_prompt(self._block)
        self.interrupt_manager.enter(InterruptKind.TOOL_APPROVAL, payload, controller=self)
        self._future = asyncio.get_running_loop().create_future()
        return await self._future

    def handle_key(self, key: str) -> bool:
        if not self.active or self._block is None:
            return False
        if key in {"left", "up", "k"}:
            self._move(-1)
            return True
        if key in {"right", "down", "j"}:
            self._move(1)
            return True
        if key == "enter":
            self.screen.run_worker(self.confirm())
            return True
        if key == "escape":
            self.cancel()
            return True
        return False

    def cancel(self) -> None:
        if self._future is None or self._future.done():
            return
        self._future.set_result({"decision": {"type": "reject", "message": "The user cancelled the request."}})
        self._finish()

    async def confirm(self) -> None:
        if self._future is None or self._future.done():
            return
        option_id = self._options[self._block.selected_index][0]
        if option_id == "edit":
            edited = await self.screen.app.push_screen_wait(  # type: ignore[attr-defined]
                JsonEditorModal(
                    title=str(self._payload.get("title", "Edit tool input")),
                    value=self._payload.get("tool_args", {}),
                )
            )
            if edited is None:
                return
            tool_name = str(self._payload.get("tool_name", "tool"))
            result = {
                "decision": {
                    "type": "edit",
                    "edited_action": {"name": tool_name, "args": edited},
                }
            }
        elif option_id == "always_allow":
            result = {
                "decision": {"type": "approve"},
                "remember": {"type": "always_allow"},
            }
        elif option_id == "reject":
            result = {
                "decision": {
                    "type": "reject",
                    "message": f"User rejected {self._payload.get('tool_name', 'the tool call')}.",
                }
            }
        else:
            result = {"decision": {"type": "approve"}}

        self._future.set_result(result)
        self._finish()

    def _move(self, delta: int) -> None:
        if self._block is None:
            return
        count = len(self._options)
        next_index = (self._block.selected_index + delta) % count
        self._block.set_selected(next_index)

    def _finish(self) -> None:
        self.screen.conversation.clear_inline_prompt()
        self.interrupt_manager.clear()
        self._block = None
        self._payload = {}

    @staticmethod
    def _build_options(payload: dict[str, Any]) -> list[tuple[str, str]]:
        allowed = list(payload.get("allowed_decisions", []))
        options: list[tuple[str, str]] = [("approve", "Approve")]
        if "edit" in allowed:
            options.append(("edit", "Edit input"))
        options.append(("reject", "Reject"))
        if payload.get("can_always_allow"):
            options.append(("always_allow", "Always allow"))
        return options

    @staticmethod
    def _body_text(payload: dict[str, Any]) -> str:
        tool_name = str(payload.get("tool_name", "tool"))
        tool_args = payload.get("tool_args", {})
        try:
            import json

            rendered_args = json.dumps(tool_args, indent=2, default=str)
        except Exception:
            rendered_args = str(tool_args)
        cwd = payload.get("cwd")
        body = f"Tool: {tool_name}\n"
        if cwd:
            body += f"Working directory: {cwd}\n"
        body += f"\nArguments:\n{rendered_args}"
        return body
