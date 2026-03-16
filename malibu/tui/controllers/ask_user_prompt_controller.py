"""Modal controller for LangGraph ask-user prompts."""

from __future__ import annotations

from typing import Any

from malibu.tui.managers.interrupt_manager import InterruptKind, InterruptManager
from malibu.tui.managers.run_state import RunPhase
from malibu.tui.screens.interrupt_prompt import QuestionPromptScreen


class AskUserPromptController:
    """Collect answers through modal question prompts."""

    def __init__(self, screen: Any, interrupt_manager: InterruptManager) -> None:
        self.screen = screen
        self.interrupt_manager = interrupt_manager
        self._active = False

    @property
    def active(self) -> bool:
        return self._active

    async def start(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self.active:
            raise RuntimeError("ask-user prompt already active")

        self._active = True
        questions = list(payload.get("questions", []))
        summary = "\n".join(
            f"{index + 1}. {str(question.get('question', '')).strip()}"
            for index, question in enumerate(questions)
        ) or "The agent needs clarification before it can continue."

        block = self.screen.conversation.add_interrupt_status(
            title="Question",
            subtitle="The agent needs input before continuing.",
            body=summary,
            state="waiting",
            detail="Awaiting your answers",
        )
        self.interrupt_manager.enter(InterruptKind.ASK_USER, payload, controller=self)
        self.screen.set_run_state(
            RunPhase.WAITING_USER,
            "User input required",
            lock_input=True,
            details="Answer the active question",
        )

        try:
            answers: list[str] = []
            for index, question in enumerate(questions):
                answer = await self.screen.app.push_screen_wait(  # type: ignore[attr-defined]
                    QuestionPromptScreen(
                        question=question,
                        index=index,
                        total=len(questions),
                    )
                )
                if answer is None:
                    block.set_state("cancelled", detail="User cancelled the question flow")
                    self.screen.set_run_state(RunPhase.STARTING, "Resuming run", lock_input=False)
                    return {"status": "cancelled", "answers": []}

                answers.append(self._normalize_answer(answer, question))
                block.set_state(
                    "waiting",
                    detail=f"Collected {len(answers)}/{len(questions)} answer(s)",
                )

            block.set_state("answered", detail=f"Collected {len(answers)} answer(s)")
            self.screen.set_run_state(RunPhase.STARTING, "Resuming run", lock_input=False)
            return {"status": "answered", "answers": answers}
        finally:
            self._finish()

    def _finish(self) -> None:
        self.interrupt_manager.clear()
        self.screen.set_input_locked(False)
        self._active = False

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
