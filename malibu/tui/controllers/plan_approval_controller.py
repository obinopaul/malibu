"""Inline controller for reviewing `write_todos` plans."""

from __future__ import annotations

import asyncio
from typing import Any

from malibu.tui.managers.interrupt_manager import InterruptKind, InterruptManager
from malibu.tui.widgets.conversation.blocks import InlineDecisionBlock


class PlanApprovalController:
    """Prompt for plan approval or revision."""

    def __init__(self, screen: Any, interrupt_manager: InterruptManager) -> None:
        self.screen = screen
        self.interrupt_manager = interrupt_manager
        self._future: asyncio.Future[dict[str, Any]] | None = None
        self._block: InlineDecisionBlock | None = None

    @property
    def active(self) -> bool:
        return self._future is not None and not self._future.done()

    async def start(self, payload: dict[str, Any]) -> dict[str, Any]:
        todos = payload.get("todos", [])
        body = "\n".join(
            f"{index + 1}. {todo.get('content', '')} [{todo.get('status', 'pending')}]"
            for index, todo in enumerate(todos)
        ) or "No plan entries were provided."
        self._block = InlineDecisionBlock(
            title="Review plan",
            subtitle="Approve to continue or reject to request a revision.",
            body=body,
            options=[("approve", "Approve"), ("reject", "Request revision"), ("always_allow", "Always allow plan updates")],
        )
        self.screen.conversation.render_inline_prompt(self._block)
        self.interrupt_manager.enter(InterruptKind.PLAN_REVIEW, payload, controller=self)
        self._future = asyncio.get_running_loop().create_future()
        return await self._future

    def handle_key(self, key: str) -> bool:
        if not self.active or self._block is None:
            return False
        if key in {"left", "up", "k"}:
            self._block.set_selected((self._block.selected_index - 1) % 3)
            return True
        if key in {"right", "down", "j"}:
            self._block.set_selected((self._block.selected_index + 1) % 3)
            return True
        if key == "enter":
            self.confirm()
            return True
        if key == "escape":
            self.cancel()
            return True
        return False

    def confirm(self) -> None:
        if self._future is None or self._future.done() or self._block is None:
            return
        option_id = self._block.options[self._block.selected_index][0]
        if option_id == "always_allow":
            result = {
                "decision": {"type": "approve"},
                "remember": {"type": "always_allow"},
            }
        elif option_id == "reject":
            result = {
                "decision": {
                    "type": "reject",
                    "message": "The user requested a revised plan. Gather feedback and regenerate write_todos.",
                }
            }
        else:
            result = {"decision": {"type": "approve"}}
        self._future.set_result(result)
        self._finish()

    def cancel(self) -> None:
        if self._future is None or self._future.done():
            return
        self._future.set_result(
            {"decision": {"type": "reject", "message": "The user cancelled the plan review."}}
        )
        self._finish()

    def _finish(self) -> None:
        self.screen.conversation.clear_inline_prompt()
        self.interrupt_manager.clear()
        self._block = None
