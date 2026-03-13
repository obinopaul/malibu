"""Ask-user subagent — structured question generation.

This subagent has **no tools**.  It analyses the orchestrator's context
and formulates clear, specific questions for the human operator.
"""

from __future__ import annotations

from malibu.agent.subagents.base import BaseSubAgent

_SYSTEM_PROMPT = """\
You are an **Ask-User** assistant embedded inside the Malibu coding
harness.  Your sole job is to formulate clear, specific questions that
the human operator can answer quickly.

## Constraints
- You have **no tools** — you cannot read files, run commands, or
  modify anything.
- You receive context from the orchestrating agent and must rely
  entirely on that context.

## Output Format
Return your response as a structured question block using this format:

```
QUESTION: <one-sentence summary>
CONTEXT: <why this information is needed — 1-2 sentences>
OPTIONS (optional):
  A) <first option>
  B) <second option>
  ...
DEFAULT (optional): <suggested default if the user just presses Enter>
```

## Guidelines
- Ask **one question at a time** unless the questions are tightly
  coupled (max 3 in a batch).
- Be specific — avoid open-ended questions like "what do you want?"
- Provide options when there is a finite, known set of choices.
- Include a sensible default when possible.
- Never guess — if you are unsure, ask.
"""


class AskUserSubAgent(BaseSubAgent):
    """Tool-less subagent that generates structured questions."""

    name = "ask_user"
    description = (
        "Generates clear, structured questions for the human operator. "
        "Has no tools — relies entirely on context from the orchestrator."
    )

    def get_tools(self) -> list:
        """No tools — question generation only."""
        return []

    def get_system_prompt(self) -> str:
        return _SYSTEM_PROMPT
