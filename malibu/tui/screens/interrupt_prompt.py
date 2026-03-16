"""Modal prompt screens for approvals and interactive questions."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import DataTable, Input, Label, Static


class ReviewPromptScreen(ModalScreen[str | None]):
    """Modal screen for plan and tool approval decisions."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=True),
        Binding("enter", "select_option", "Select", show=True),
    ]

    DEFAULT_CSS = """
    ReviewPromptScreen {
        align: center middle;
        background: #14110F 84%;
    }
    #review-dialog {
        width: 92;
        height: 28;
        padding: 1 2;
        border: round #C25B4B;
        background: #27211E;
    }
    #review-title {
        text-style: bold;
        margin-bottom: 1;
    }
    #review-subtitle {
        color: #AA9988;
        margin-bottom: 1;
    }
    #review-body {
        height: 1fr;
        margin-bottom: 1;
        padding: 0 1;
        border: tall #4A3A31;
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
        self._title = title
        self._subtitle = subtitle
        self._body = body
        self._options = options

    def compose(self) -> ComposeResult:
        with Vertical(id="review-dialog"):
            yield Label(self._title, id="review-title")
            yield Static(self._subtitle, id="review-subtitle")
            yield Static(self._body, id="review-body")
            yield DataTable(id="review-options")

    def on_mount(self) -> None:
        table = self.query_one("#review-options", DataTable)
        table.add_columns("Option")
        table.cursor_type = "row"
        for option_id, label in self._options:
            table.add_row(label, key=option_id)
        table.focus()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_select_option(self) -> None:
        table = self.query_one("#review-options", DataTable)
        if table.row_count == 0:
            self.dismiss(None)
            return
        row = table.get_row_at(table.cursor_row or 0)
        self.dismiss(self._option_id_for_label(str(row[0])) if row else None)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        self.dismiss(str(event.row_key.value) if event.row_key is not None else None)

    def on_key(self, event) -> None:  # type: ignore[override]
        if event.key.isdigit():
            index = int(event.key) - 1
            if 0 <= index < len(self._options):
                self.dismiss(self._options[index][0])
                event.stop()
                event.prevent_default()

    def _option_id_for_label(self, label: str) -> str | None:
        for option_id, option_label in self._options:
            if option_label == label:
                return option_id
        return None


class QuestionPromptScreen(ModalScreen[str | None]):
    """Modal screen for a single ask-user question."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=True),
        Binding("enter", "submit_answer", "Submit", show=True),
    ]

    DEFAULT_CSS = """
    QuestionPromptScreen {
        align: center middle;
        background: #14110F 84%;
    }
    #question-dialog {
        width: 88;
        height: 24;
        padding: 1 2;
        border: round #D7A77A;
        background: #27211E;
    }
    #question-title {
        text-style: bold;
        margin-bottom: 1;
    }
    #question-body {
        margin-bottom: 1;
        color: #F3EBDD;
    }
    #question-hint {
        color: #AA9988;
        margin-top: 1;
    }
    #question-answer {
        margin-top: 1;
    }
    """

    def __init__(
        self,
        *,
        question: dict[str, object],
        index: int,
        total: int,
    ) -> None:
        super().__init__()
        self._question = question
        self._index = index
        self._total = total

    def compose(self) -> ComposeResult:
        with Vertical(id="question-dialog"):
            yield Label(f"Question {self._index + 1} of {self._total}", id="question-title")
            yield Static(str(self._question.get("question", "")), id="question-body")
            yield DataTable(id="question-options")
            yield Input(placeholder="Type your answer", id="question-answer")
            yield Static(
                "Choose an option or type a custom answer, then press Enter.",
                id="question-hint",
            )

    def on_mount(self) -> None:
        table = self.query_one("#question-options", DataTable)
        table.add_columns("Choice")
        table.cursor_type = "row"
        choices = list(self._question.get("choices", []))
        if choices:
            for choice in choices:
                label = str(choice.get("value", ""))
                table.add_row(label, key=label)
        else:
            table.display = False
        self.query_one("#question-answer", Input).focus()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_submit_answer(self) -> None:
        answer = self._resolve_answer()
        if answer is None:
            return
        self.dismiss(answer)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        answer_input = self.query_one("#question-answer", Input)
        answer_input.value = str(event.row_key.value)
        self.dismiss(str(event.row_key.value))

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "question-answer":
            self.action_submit_answer()

    def on_key(self, event) -> None:  # type: ignore[override]
        if event.key.isdigit():
            index = int(event.key) - 1
            table = self.query_one("#question-options", DataTable)
            if 0 <= index < table.row_count:
                row = table.get_row_at(index)
                if row:
                    answer = str(row[0])
                    self.query_one("#question-answer", Input).value = answer
                    self.dismiss(answer)
                    event.stop()
                    event.prevent_default()

    def _resolve_answer(self) -> str | None:
        answer = self.query_one("#question-answer", Input).value.strip()
        if answer:
            return answer

        if not bool(self._question.get("required", True)):
            return ""

        table = self.query_one("#question-options", DataTable)
        if table.display and table.row_count:
            row = table.get_row_at(table.cursor_row or 0)
            if row:
                return str(row[0])
        return None
