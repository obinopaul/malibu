# vibe/cli/inline_ui/question.py
"""AskUserQuestion handler for the inline UI.

Replaces the Textual QuestionApp with prompt_toolkit prompts.
"""
from __future__ import annotations

from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import HTML
from rich.console import Console
from rich.text import Text

from vibe.core.tools.builtins.ask_user_question import (
    AskUserQuestionArgs,
    AskUserQuestionResult,
    Answer,
)


async def prompt_question(
    args: AskUserQuestionArgs,
    console: Console | None = None,
) -> AskUserQuestionResult:
    """Present questions to the user and collect answers."""
    console = console or Console(highlight=False)
    session: PromptSession[str] = PromptSession()
    answers: list[Answer] = []

    for question in args.questions:
        console.print()
        console.print(Text(question.question, style="bold blue"))

        if question.options:
            for i, opt in enumerate(question.options, 1):
                console.print(f"  {i}. {opt.label}")
            if not question.hide_other:
                console.print(f"  {len(question.options) + 1}. Other (type your answer)")

            reply = await session.prompt_async(
                HTML("<blue>Choice: </blue>")
            )
            reply = reply.strip()

            try:
                idx = int(reply) - 1
                if 0 <= idx < len(question.options):
                    answers.append(Answer(
                        question=question.question,
                        answer=question.options[idx].label,
                    ))
                else:
                    answers.append(Answer(
                        question=question.question,
                        answer=reply,
                        is_other=True,
                    ))
            except ValueError:
                answers.append(Answer(
                    question=question.question,
                    answer=reply,
                    is_other=True,
                ))
        else:
            reply = await session.prompt_async(
                HTML("<blue>> </blue>")
            )
            answers.append(Answer(
                    question=question.question,
                    answer=reply.strip(),
                ))

    return AskUserQuestionResult(answers=answers, cancelled=False)
