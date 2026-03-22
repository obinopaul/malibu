"""Modal controller for reviewing `write_todos` plans."""

from __future__ import annotations

from typing import Any

from malibu.tui.managers.interrupt_manager import InterruptKind, InterruptManager
from malibu.tui.managers.run_state import RunPhase
from malibu.tui.screens.interrupt_prompt import ReviewPromptScreen


class PlanApprovalController:
    """Prompt for plan approval or revision."""

    def __init__(self, screen: Any, interrupt_manager: InterruptManager) -> None:
        self.screen = screen
        self.interrupt_manager = interrupt_manager
        self._active = False

    @property
    def active(self) -> bool:
        return self._active

    async def start(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self.active:
            raise RuntimeError("plan review prompt already active")

        self._active = True
        self.interrupt_manager.enter(InterruptKind.PLAN_REVIEW, payload, controller=self)
        todos = payload.get("todos", [])
        body = "\n".join(
            f"{index + 1}. {todo.get('content', '')} [{todo.get('status', 'pending')}]"
            for index, todo in enumerate(todos)
        ) or "No plan entries were provided."

        block = self.screen.conversation.add_interrupt_status(
            title="Review plan",
            subtitle="Approve to continue or request a revision.",
            body=body,
            state="waiting",
            detail="Awaiting plan approval",
        )
        self.screen.set_run_state(
            RunPhase.WAITING_APPROVAL,
            "Review plan",
            lock_input=True,
            details="Action required",
        )

        try:
            selection = await self.screen.app.push_screen_wait(  # type: ignore[attr-defined]
                ReviewPromptScreen(
                    title="Review plan",
                    subtitle="Approve to continue or request a revision.",
                    body=body,
                    options=[
                        ("approve", "Approve"),
                        ("reject", "Request revision"),
                        ("always_allow", "Always allow plan updates"),
                    ],
                )
            )
            if selection == "always_allow":
                result = {
                    "decision": {"type": "approve"},
                    "remember": {"type": "always_allow"},
                }
                block.set_state("approved", detail="Approved and remembered")
            elif selection in {None, "reject"}:
                message = "The user cancelled the plan review." if selection is None else (
                    "The user requested a revised plan. Gather feedback and regenerate write_todos."
                )
                result = {
                    "decision": {
                        "type": "reject",
                        "message": message,
                    }
                }
                block.set_state("rejected" if selection == "reject" else "cancelled", detail=message)
            else:
                result = {"decision": {"type": "approve"}}
                block.set_state("approved", detail="Plan approved")

            self.screen.set_run_state(RunPhase.STARTING, "Resuming run", lock_input=False)
            return result
        finally:
            self._finish()

    def _finish(self) -> None:
        self.interrupt_manager.clear()
        self.screen.set_input_locked(False)
        self._active = False
