"""Renderable conversation blocks for the Malibu shell."""

from __future__ import annotations

import json
from typing import Any

from rich.console import Group, RenderableType
from rich.panel import Panel
from rich.syntax import Syntax
from rich.text import Text
from textual.widget import Widget
from textual.widgets import Markdown, Static

from malibu.tui.widgets.welcome_dock import build_welcome_renderable


def _json_preview(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, indent=2, default=str)
    except Exception:
        return str(value)


def _status_icon(status: str) -> str:
    return {
        "pending": "o",
        "in_progress": ">",
        "completed": "x",
        "failed": "!",
    }.get(status, ">")


def _theme_color(widget: Widget, name: str, fallback: str) -> str:
    theme = getattr(widget.app, "current_theme", None) if getattr(widget, "app", None) else None
    if theme is None:
        return fallback
    direct = getattr(theme, name, None)
    if direct:
        return str(direct)
    return str(getattr(theme, "variables", {}).get(name, fallback))


class UserMessageBlock(Static):
    """Conversation block for a user message."""

    DEFAULT_CSS = """
    UserMessageBlock {
        margin: 0 0 1 0;
        width: 1fr;
    }
    """

    def __init__(self, text: str) -> None:
        super().__init__()
        self._text = text
        self._refresh_content()

    def refresh_theme(self) -> None:
        self._refresh_content()

    def _refresh_content(self) -> None:
        border = _theme_color(self, "secondary", "#0f766e")
        foreground = _theme_color(self, "foreground", "#e2e8f0")
        muted = _theme_color(self, "foreground-muted", "#94a3b8")
        self.update(
            Panel(
                Group(Text("You", style=f"bold {border}"), Text(self._text, style=foreground)),
                border_style=border,
                subtitle=Text("message", style=muted),
                padding=(0, 1),
            )
        )


class AssistantMessageBlock(Static):
    """Streaming assistant markdown block."""

    DEFAULT_CSS = """
    AssistantMessageBlock {
        margin: 0 0 1 0;
        width: 1fr;
    }
    """

    def __init__(self, text: str = "") -> None:
        super().__init__()
        self._text = text

    def compose(self):  # noqa: ANN201
        yield Markdown(self._text or "")

    def append_text(self, text: str) -> None:
        self._text += text
        try:
            markdown = self.query_one(Markdown)
            markdown.update(self._text)
        except Exception:
            self.update(self._text)

    @property
    def text(self) -> str:
        return self._text


class SystemMessageBlock(Static):
    """Muted system message."""

    DEFAULT_CSS = """
    SystemMessageBlock {
        margin: 0 0 1 0;
        width: 1fr;
    }
    """

    def __init__(self, text: str, *, title: str = "System", border_style: str = "#475569") -> None:
        super().__init__()
        self._text = text
        self._title = title
        self._border_style = border_style
        self._refresh_content()

    def refresh_theme(self) -> None:
        self._refresh_content()

    def _refresh_content(self) -> None:
        muted = _theme_color(self, "foreground-muted", "#94a3b8")
        border = _theme_color(self, "panel-lighten-1", self._border_style)
        self.update(
            Panel(
                Text(self._text, style=muted),
                title=self._title,
                border_style=border,
                padding=(0, 1),
            )
        )


class ThoughtMessageBlock(SystemMessageBlock):
    """Thought block."""

    def __init__(self, text: str) -> None:
        super().__init__(text, title="Thinking", border_style="#334155")


class WelcomeMessageBlock(Static):
    """Welcome card persisted inside the conversation history."""

    DEFAULT_CSS = """
    WelcomeMessageBlock {
        margin: 0 0 1 0;
        width: 1fr;
    }
    """

    def __init__(
        self,
        *,
        cwd: str,
        session_title: str,
        mode_name: str,
        model_id: str,
        ready: bool,
    ) -> None:
        super().__init__()
        self._cwd = cwd
        self._session_title = session_title
        self._mode_name = mode_name
        self._model_id = model_id
        self._ready = ready
        self._refresh_content()

    def refresh_theme(self) -> None:
        self._refresh_content()

    def _refresh_content(self) -> None:
        self.update(
            build_welcome_renderable(
                cwd=self._cwd,
                session_title=self._session_title,
                mode_name=self._mode_name,
                model_id=self._model_id,
                ready=self._ready,
                theme=getattr(self.app, "current_theme", None) if getattr(self, "app", None) else None,
            )
        )


class ToolCallBlock(Static):
    """Tool execution block with collapsible output."""

    DEFAULT_CSS = """
    ToolCallBlock {
        margin: 0 0 1 0;
        width: 1fr;
    }
    """

    def __init__(
        self,
        tool_call_id: str,
        title: str,
        *,
        kind: str = "tool",
        status: str = "pending",
        raw_input: Any = None,
    ) -> None:
        super().__init__(id=f"tool-{tool_call_id}")
        self.tool_call_id = tool_call_id
        self.title = title
        self.kind = kind
        self.status = status
        self.raw_input = raw_input
        self.output_text = ""
        self.expanded = False
        self._truncated = False
        self._refresh_content()

    def toggle_expand(self) -> None:
        self.expanded = not self.expanded
        self._refresh_content()

    def set_status(self, status: str) -> None:
        self.status = status
        self._refresh_content()

    def set_title(self, title: str) -> None:
        self.title = title
        self._refresh_content()

    def set_input(self, raw_input: Any) -> None:
        self.raw_input = raw_input
        self._refresh_content()

    def set_output(self, text: str, *, truncated: bool = False) -> None:
        self.output_text = text
        self._truncated = truncated
        self._refresh_content()

    def on_click(self) -> None:
        if self.output_text:
            self.toggle_expand()

    def _build_output_renderable(self) -> RenderableType:
        if not self.output_text:
            return Text("Waiting for output", style=_theme_color(self, "foreground-muted", "#94a3b8"))

        if "\n" in self.output_text or len(self.output_text) > 90:
            syntax = Syntax(
                self.output_text,
                "text",
                theme="monokai",
                word_wrap=True,
                line_numbers=False,
            )
            return Panel(
                syntax,
                title="Output",
                border_style=_theme_color(self, "panel-lighten-1", "#334155"),
                padding=(0, 1),
            )

        return Text(self.output_text, style=_theme_color(self, "foreground", "#e2e8f0"))

    def _build_renderable(self) -> RenderableType:
        accent = _theme_color(self, "accent", "#38bdf8")
        foreground = _theme_color(self, "foreground", "#e2e8f0")
        muted = _theme_color(self, "foreground-muted", "#94a3b8")
        success = _theme_color(self, "success", "#22c55e")
        error = _theme_color(self, "error", "#dc2626")
        warning = _theme_color(self, "warning", "#f59e0b")
        icon = _status_icon(self.status)
        header = Text()
        header_style = error if self.status == "failed" else success if self.status == "completed" else accent
        status_style = error if self.status == "failed" else warning if self.status == "in_progress" else muted
        header.append("Tool ", style=f"bold {header_style}")
        header.append(f"{icon} {self.title}", style=f"bold {foreground}")
        header.append(f"  [{self.kind} · {self.status}]", style=status_style)

        sections: list[RenderableType] = [header]
        if self.raw_input is not None:
            preview = _json_preview(self.raw_input)
            if preview:
                sections.append(Text(preview, style=muted))

        if self.output_text or self.status in {"pending", "in_progress"}:
            sections.append(self._build_output_renderable())
            if self._truncated and not self.expanded:
                sections.append(Text("Output collapsed. Click to expand.", style=muted))

        return Panel(
            Group(*sections),
            border_style=error if self.status == "failed" else success if self.status == "completed" else accent,
            padding=(0, 1),
            subtitle=Text("click to expand output" if self.output_text else "tool execution", style=muted),
        )

    def _refresh_content(self) -> None:
        self.update(self._build_renderable())

    def refresh_theme(self) -> None:
        self._refresh_content()


class ToolGroupBlock(Static):
    """Summary block for nested or parallel tools."""

    DEFAULT_CSS = """
    ToolGroupBlock {
        margin: 0 0 1 0;
        width: 1fr;
    }
    """

    def __init__(self, title: str, items: list[str]) -> None:
        super().__init__()
        self._title = title
        self._items = items
        self._refresh_content()

    def refresh_theme(self) -> None:
        self._refresh_content()

    def _refresh_content(self) -> None:
        foreground = _theme_color(self, "foreground", "#e2e8f0")
        muted = _theme_color(self, "foreground-muted", "#94a3b8")
        border = _theme_color(self, "panel-lighten-1", "#334155")
        lines = [Text(self._title, style=f"bold {foreground}")]
        lines.extend(Text(f"- {item}", style=muted) for item in self._items)
        self.update(Panel(Group(*lines), title="Tool Group", border_style=border, padding=(0, 1)))


class InlineDecisionBlock(Static):
    """Inline approval or plan review prompt."""

    DEFAULT_CSS = """
    InlineDecisionBlock {
        margin: 0 0 1 0;
        width: 1fr;
    }
    """

    def __init__(
        self,
        *,
        title: str,
        subtitle: str,
        body: str,
        options: list[tuple[str, str]],
    ) -> None:
        super().__init__()
        self.title = title
        self.subtitle = subtitle
        self.body = body
        self.options = options
        self.selected_index = 0
        self.footer = "Left/Right or j/k to change, Enter to confirm"
        self._refresh_content()

    def set_selected(self, index: int) -> None:
        self.selected_index = max(0, min(index, len(self.options) - 1))
        self._refresh_content()

    def set_footer(self, text: str) -> None:
        self.footer = text
        self._refresh_content()

    def _refresh_content(self) -> None:
        accent = _theme_color(self, "accent", "#38bdf8")
        foreground = _theme_color(self, "foreground", "#e2e8f0")
        muted = _theme_color(self, "foreground-muted", "#94a3b8")
        secondary = _theme_color(self, "secondary", "#0f766e")
        title = Text(self.title, style="bold white")
        title.stylize(f"bold {foreground}")
        subtitle = Text(self.subtitle, style=muted)
        option_lines: list[Text] = []
        for index, (_, label) in enumerate(self.options):
            active = index == self.selected_index
            line = Text()
            line.append(">" if active else " ", style=accent if active else muted)
            line.append(f" {label}", style=f"bold {foreground}" if active else foreground)
            option_lines.append(line)
        renderable = Panel(
            Group(title, subtitle, Text(""), Text(self.body, style=foreground), Text(""), *option_lines, Text(""), Text(self.footer, style=muted)),
            border_style=secondary,
            title="Review",
            padding=(0, 1),
        )
        self.update(renderable)

    def refresh_theme(self) -> None:
        self._refresh_content()


class AskUserPromptBlock(Static):
    """Inline ask-user questionnaire block."""

    DEFAULT_CSS = """
    AskUserPromptBlock {
        margin: 0 0 1 0;
        width: 1fr;
    }
    """

    def __init__(self, questions: list[dict[str, Any]]) -> None:
        super().__init__()
        self.questions = questions
        self.answers: list[str] = []
        self.current_index = 0
        self.hint = "Type an answer and press Enter. Esc cancels."
        self._refresh_content()

    def record_answer(self, answer: str) -> None:
        if self.current_index < len(self.questions):
            if len(self.answers) <= self.current_index:
                self.answers.append(answer)
            else:
                self.answers[self.current_index] = answer
            self.current_index += 1
        self._refresh_content()

    def _question_text(self, index: int) -> str:
        question = self.questions[index]
        base = str(question.get("question", "")).strip()
        if question.get("type") == "multiple_choice":
            choices = question.get("choices", [])
            rendered = ", ".join(
                f"{choice_index + 1}. {choice.get('value', '')}"
                for choice_index, choice in enumerate(choices)
            )
            if rendered:
                base = f"{base}\nChoices: {rendered} or type your own answer"
        return base

    def _refresh_content(self) -> None:
        foreground = _theme_color(self, "foreground", "#e2e8f0")
        accent = _theme_color(self, "accent", "#38bdf8")
        muted = _theme_color(self, "foreground-muted", "#94a3b8")
        parts: list[RenderableType] = [Text("The agent needs input before continuing.", style=f"bold {foreground}")]
        for index in range(len(self.questions)):
            prefix = ">" if index == self.current_index else "-"
            parts.append(Text(f"{prefix} {self._question_text(index)}", style=foreground))
            if index < len(self.answers):
                parts.append(Text(f"  Answer: {self.answers[index]}", style=accent))
        parts.append(Text(""))
        parts.append(Text(self.hint, style=muted))
        self.update(
            Panel(
                Group(*parts),
                title="Question",
                border_style=accent,
                padding=(0, 1),
            )
        )

    def refresh_theme(self) -> None:
        self._refresh_content()
