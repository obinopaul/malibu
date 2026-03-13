"""Inline controller for LangGraph ask-user prompts."""

from __future__ import annotations

import asyncio
from typing import Any

from malibu.tui.managers.interrupt_manager import InterruptKind, InterruptManager
from malibu.tui.widgets.conversation.blocks import AskUserPromptBlock


class AskUserPromptController:
    """Collect answers through the main chat input while an ask-user prompt is active."""

    def __init__(self, screen: Any, interrupt_manager: InterruptManager) -> None:
        self.screen = screen
        self.interrupt_manager = interrupt_manager
        self._future: asyncio.Future[dict[str, Any]] | None = None
        self._block: AskUserPromptBlock | None = None
        self._questions: list[dict[str, Any]] = []
        self._answers: list[str] = []

    @property
    def active(self) -> bool:
        return self._future is not None and not self._future.done()

    async def start(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._questions = list(payload.get("questions", []))
        self._answers = []
        self._block = AskUserPromptBlock(self._questions)
        self.screen.conversation.render_inline_prompt(self._block)
        self.interrupt_manager.enter(InterruptKind.ASK_USER, payload, controller=self)
        self._future = asyncio.get_running_loop().create_future()
        return await self._future

    def submit_answer(self, text: str) -> bool:
        if not self.active or self._block is None:
            return False
        answer = self._normalize_answer(text, self._questions[len(self._answers)])
        self._answers.append(answer)
        self._block.record_answer(answer)
        if len(self._answers) >= len(self._questions):
            self._future.set_result({"status": "answered", "answers": list(self._answers)})
            self._finish()
        return True

    def cancel(self) -> None:
        if self._future is None or self._future.done():
            return
        self._future.set_result({"status": "cancelled", "answers": []})
        self._finish()

    def _finish(self) -> None:
        self.screen.conversation.clear_inline_prompt()
        self.interrupt_manager.clear()
        self._questions = []
        self._answers = []
        self._block = None

    @staticmethod
    def _normalize_answer(text: str, question: dict[str, Any]) -> str:
        cleaned = text.strip()
        if question.get("type") != "multiple_choice":
            return cleaned
        choices = question.get("choices", [])
        if cleaned.isdigit():
            index = int(cleaned) - 1
            if 0 <= index < len(choices):
                return str(choices[index].get("value", cleaned))
        return cleaned
