"""Modal tool approval controller."""

from __future__ import annotations

from typing import Any

from malibu.tui.managers.interrupt_manager import InterruptKind, InterruptManager
from malibu.tui.managers.run_state import RunPhase
from malibu.tui.modals.detail_modal import JsonEditorModal
from malibu.tui.screens.interrupt_prompt import ReviewPromptScreen


class ApprovalPromptController:
    """Render and resolve modal tool approval prompts."""

    def __init__(self, screen: Any, interrupt_manager: InterruptManager) -> None:
        self.screen = screen
        self.interrupt_manager = interrupt_manager
        self._active = False
        self._payload: dict[str, Any] = {}

    @property
    def active(self) -> bool:
        return self._active

    async def start(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self.active:
            raise RuntimeError("tool approval prompt already active")

        self._active = True
        self._payload = payload
        self.interrupt_manager.enter(InterruptKind.TOOL_APPROVAL, payload, controller=self)

        title = str(payload.get("title", payload.get("tool_name", "Tool review")))
        subtitle = str(payload.get("subtitle", payload.get("tool_name", "")))
        body = self._body_text(payload)
        block = self.screen.conversation.add_interrupt_status(
            title=title,
            subtitle=subtitle,
            body=body,
            state="waiting",
            detail="Awaiting approval",
        )
        self.screen.set_run_state(
            RunPhase.WAITING_APPROVAL,
            title,
            lock_input=True,
            details=subtitle or "Action required",
        )

        try:
            result = await self._prompt_until_resolved(title, subtitle, body)
            decision_type = result.get("decision", {}).get("type", "approve")
            state = {
                "approve": "approved",
                "edit": "approved",
                "reject": "rejected",
            }.get(str(decision_type), "approved")
            detail = {
                "approve": "Approved",
                "edit": "Edited input and approved",
                "reject": result.get("decision", {}).get("message", "Rejected"),
            }.get(str(decision_type), "Approved")
            block.set_state(state, detail=detail)
            self.screen.set_run_state(RunPhase.STARTING, "Resuming run", lock_input=False)
            return result
        finally:
            self._finish()

    async def _prompt_until_resolved(self, title: str, subtitle: str, body: str) -> dict[str, Any]:
        options = self._build_options(self._payload)
        while True:
            option_id = await self.screen.app.push_screen_wait(  # type: ignore[attr-defined]
                ReviewPromptScreen(
                    title=title,
                    subtitle=subtitle or "Review this tool action before continuing.",
                    body=body,
                    options=options,
                )
            )

            if option_id == "edit":
                edited = await self.screen.app.push_screen_wait(  # type: ignore[attr-defined]
                    JsonEditorModal(
                        title=str(self._payload.get("title", "Edit tool input")),
                        value=self._payload.get("tool_args", {}),
                    )
                )
                if edited is None:
                    continue
                tool_name = str(self._payload.get("tool_name", "tool"))
                return {
                    "decision": {
                        "type": "edit",
                        "edited_action": {"name": tool_name, "args": edited},
                    }
                }

            if option_id == "always_allow":
                return {
                    "decision": {"type": "approve"},
                    "remember": {"type": "always_allow"},
                }

            if option_id in {None, "reject"}:
                message = "The user cancelled the request." if option_id is None else (
                    f"User rejected {self._payload.get('tool_name', 'the tool call')}."
                )
                return {
                    "decision": {
                        "type": "reject",
                        "message": message,
                    }
                }

            return {"decision": {"type": "approve"}}

    def _finish(self) -> None:
        self.interrupt_manager.clear()
        self.screen.set_input_locked(False)
        self._active = False
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
