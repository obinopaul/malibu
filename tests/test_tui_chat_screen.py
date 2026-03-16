from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from textual import events
from textual.app import App, ComposeResult

from acp.schema import AgentMessageChunk, TextContentBlock, UserMessageChunk

from malibu.tui.commands import create_default_registry
from malibu.tui.managers import RunPhase
from malibu.tui.screens.chat import ChatScreen
from malibu.tui.widgets.autocomplete_popup import AutocompletePopup
from malibu.tui.widgets.chat_input import ChatTextArea
from malibu.tui.widgets.conversation.blocks import (
    SystemMessageBlock,
    UserMessageBlock,
    WelcomeMessageBlock,
)
from malibu.tui.widgets.plan_panel import PlanPanel


class ShellHarness(App[None]):
    def __init__(self, cwd: Path) -> None:
        super().__init__()
        self.cwd = str(cwd)
        self.command_registry = create_default_registry()
        self.dispatched: list[str] = []

    def compose(self) -> ComposeResult:
        yield ChatScreen()

    async def dispatch_prompt(self, text: str) -> None:
        self.dispatched.append(text)


class LayoutHarness(App[None]):
    def __init__(self, cwd: Path) -> None:
        super().__init__()
        self.cwd = str(cwd)
        self.command_registry = create_default_registry()
        self._screen = ChatScreen()

    def on_mount(self) -> None:
        self.install_screen(self._screen, name="chat")
        self.push_screen("chat")

    async def dispatch_prompt(self, text: str) -> None:
        return None


async def test_chat_screen_dispatches_prompt(tmp_path: Path) -> None:
    app = ShellHarness(tmp_path)
    async with app.run_test() as pilot:
        screen = app.query_one(ChatScreen)
        screen.handle_chat_submitted(ChatTextArea.Submitted("hello world"))
        await pilot.pause()
        assert app.dispatched == ["hello world"]
        assert len(screen.conversation.children) >= 1


async def test_chat_screen_dedupes_remote_user_echo_after_local_submit(tmp_path: Path) -> None:
    app = ShellHarness(tmp_path)
    async with app.run_test() as pilot:
        screen = app.query_one(ChatScreen)

        screen.handle_chat_submitted(ChatTextArea.Submitted("hello"))
        await pilot.pause()

        before_echo = [
            child for child in screen.conversation.children if isinstance(child, UserMessageBlock)
        ]
        assert len(before_echo) == 1

        screen.on_user_message_chunk(
            UserMessageChunk(
                session_update="user_message_chunk",
                content=TextContentBlock(type="text", text="hello"),
            )
        )
        await pilot.pause()

        after_echo = [
            child for child in screen.conversation.children if isinstance(child, UserMessageBlock)
        ]
        assert len(after_echo) == 1


async def test_chat_screen_welcome_dock_hides_after_activity(tmp_path: Path) -> None:
    app = ShellHarness(tmp_path)
    async with app.run_test() as pilot:
        screen = app.query_one(ChatScreen)
        dock = screen.query_one("#welcome-dock")
        assert dock.display is True

        screen.handle_chat_submitted(ChatTextArea.Submitted("hello world"))
        await pilot.pause()

        assert dock.display is False


async def test_chat_screen_preserves_welcome_card_in_history(tmp_path: Path) -> None:
    app = ShellHarness(tmp_path)
    async with app.run_test() as pilot:
        screen = app.query_one(ChatScreen)

        screen.handle_chat_submitted(ChatTextArea.Submitted("hello world"))
        await pilot.pause()

        welcome_block = screen.query_one(WelcomeMessageBlock)
        assert welcome_block is not None


async def test_chat_screen_toggles_plan_panel(tmp_path: Path) -> None:
    app = ShellHarness(tmp_path)
    async with app.run_test() as pilot:
        screen = app.query_one(ChatScreen)
        panel = app.query_one(PlanPanel)
        assert panel.visible is False
        screen.action_toggle_plan()
        await pilot.pause()
        assert panel.visible is True


async def test_chat_screen_shows_plan_panel_when_plan_arrives(tmp_path: Path) -> None:
    app = ShellHarness(tmp_path)
    async with app.run_test() as pilot:
        screen = app.query_one(ChatScreen)
        panel = app.query_one(PlanPanel)
        assert panel.visible is False

        screen.on_plan_update(
            SimpleNamespace(
                entries=[
                    SimpleNamespace(content="Inspect shell layout", status="in_progress"),
                    SimpleNamespace(content="Tighten autocomplete", status="pending"),
                ]
            )
        )
        await pilot.pause()

        assert panel.visible is True


async def test_chat_screen_bootstrap_hydrates_history(tmp_path: Path) -> None:
    app = ShellHarness(tmp_path)
    async with app.run_test():
        screen = app.query_one(ChatScreen)
        screen.load_bootstrap(
            {
                "history": [
                    {
                        "kind": "session_update",
                        "payload": UserMessageChunk(
                            session_update="user_message_chunk",
                            content=TextContentBlock(type="text", text="hello"),
                        ).model_dump(by_alias=True, mode="json"),
                    },
                    {
                        "kind": "session_update",
                        "payload": AgentMessageChunk(
                            session_update="agent_message_chunk",
                            content=TextContentBlock(type="text", text="hi there"),
                        ).model_dump(by_alias=True, mode="json"),
                    },
                ]
            }
        )

        assert len(screen.conversation.children) >= 2


async def test_chat_screen_layout_keeps_conversation_visible(tmp_path: Path) -> None:
    app = LayoutHarness(tmp_path)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        screen = app.screen
        body = screen.query_one("#shell-body")
        conversation = screen.query_one("#conversation-log")
        composer = screen.query_one("#composer")
        chat_input = screen.query_one("#chat-input")

        assert body.region.height > composer.region.height
        assert conversation.region.height == body.region.height
        assert chat_input.region.height == 4


async def test_chat_screen_tool_block_does_not_crash_layout(tmp_path: Path) -> None:
    app = LayoutHarness(tmp_path)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        screen = app.screen

        screen.conversation.add_user_message("list files")
        screen.conversation.start_tool_call(
            "tool-1",
            "shell_command",
            kind="tool",
            status="in_progress",
            raw_input={"command": "Get-ChildItem"},
        )
        await pilot.pause()

        screen.conversation.update_tool_call(
            "tool-1",
            status="completed",
            output_text="README.md\nsrc\npyproject.toml\n.venv-fresh",
            truncated=True,
        )
        await pilot.pause()

        tool_block = screen.query_one("#tool-tool-1")
        assert tool_block.region.height > 0


async def test_chat_screen_slash_popup_renders_below_input(tmp_path: Path) -> None:
    app = LayoutHarness(tmp_path)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        screen = app.screen
        screen.handle_completions_changed(
            ChatTextArea.CompletionsChanged(
                [
                    ("/clear", "Clear the chat"),
                    ("/config", "Configure Malibu"),
                    ("/help", "Show help"),
                    ("/init", "Create CLAUDE.md"),
                    ("/mode", "Change mode"),
                    ("/model", "Change model"),
                    ("/session", "Browse sessions"),
                ],
                0,
            )
        )
        await pilot.pause()

        popup = screen.query_one("#autocomplete-popup")
        chat_input = screen.query_one("#chat-input")
        composer = screen.query_one("#composer")

        assert popup.display is True
        assert composer.region.height > 6
        assert popup.region.y >= chat_input.region.y + chat_input.region.height


async def test_chat_screen_mode_completion_returns_real_modes(tmp_path: Path) -> None:
    app = ShellHarness(tmp_path)
    async with app.run_test():
        screen = app.query_one(ChatScreen)
        items = screen._build_completions("/mode ", len("/mode "))

        labels = {item.label for item in items}
        assert "plan" in labels
        assert "ask_before_edits" in labels
        assert "accept_edits" in labels
        assert "accept_everything" in labels


async def test_chat_screen_enter_accepts_selected_slash_completion(tmp_path: Path) -> None:
    app = ShellHarness(tmp_path)
    async with app.run_test() as pilot:
        screen = app.query_one(ChatScreen)
        screen.chat_input.load_text("/mod")
        screen.chat_input.cursor_location = screen.chat_input.document.get_location_from_index(
            len(screen.chat_input.text)
        )
        screen.chat_input._refresh_completions()
        await pilot.pause()

        await screen.chat_input._on_key(events.Key("enter", None))
        await pilot.pause()

        assert app.dispatched == []
        assert screen.chat_input.text == "/mode "


async def test_chat_screen_clicking_popup_changes_selected_completion(tmp_path: Path) -> None:
    app = ShellHarness(tmp_path)
    async with app.run_test() as pilot:
        screen = app.query_one(ChatScreen)
        screen.chat_input.load_text("/mod")
        screen.chat_input.cursor_location = screen.chat_input.document.get_location_from_index(
            len(screen.chat_input.text)
        )
        screen.chat_input._refresh_completions()
        await pilot.pause()

        screen.handle_completion_selection_requested(AutocompletePopup.SelectionRequested(1))
        await screen.chat_input._on_key(events.Key("enter", None))
        await pilot.pause()

        assert app.dispatched == []
        assert screen.chat_input.text == "/model "


async def test_chat_screen_status_event_locks_and_unlocks_input(tmp_path: Path) -> None:
    app = ShellHarness(tmp_path)
    async with app.run_test() as pilot:
        screen = app.query_one(ChatScreen)

        screen.on_status_event(
            {
                "phase": "waiting_approval",
                "label": "Review plan",
                "lock_input": True,
                "details": "Action required",
            }
        )
        await pilot.pause()

        assert screen.input_locked is True
        assert screen.chat_input.disabled is True
        assert screen.conversation._activity_block is not None
        assert screen.conversation._activity_block.phase is RunPhase.WAITING_APPROVAL

        screen.on_status_event(
            {
                "phase": "starting",
                "label": "Resuming run",
                "lock_input": False,
            }
        )
        await pilot.pause()

        assert screen.input_locked is False
        assert screen.chat_input.disabled is False


async def test_chat_screen_blocks_submission_while_action_required(tmp_path: Path) -> None:
    app = ShellHarness(tmp_path)
    async with app.run_test() as pilot:
        screen = app.query_one(ChatScreen)
        screen.set_input_locked(True, "Action required")

        screen.handle_chat_submitted(ChatTextArea.Submitted("hello again"))
        await pilot.pause()

        assert app.dispatched == []
        notices = [
            child for child in screen.conversation.children if isinstance(child, SystemMessageBlock)
        ]
        assert any(block._title == "Action Required" for block in notices)
