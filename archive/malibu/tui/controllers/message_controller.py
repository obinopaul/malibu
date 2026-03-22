"""Prompt submission and queue management."""

from __future__ import annotations

from collections import deque
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from malibu.tui.screens.chat import ChatScreen


class MessageController:
    """Serialize prompt submission through one queue."""

    def __init__(self, screen: "ChatScreen") -> None:
        self.screen = screen
        self._queue: deque[tuple[str, bool]] = deque()
        self._busy = False

    @property
    def busy(self) -> bool:
        return self._busy

    @property
    def queue_depth(self) -> int:
        return len(self._queue)

    async def submit(self, text: str) -> None:
        if self.screen.input_locked:
            self.screen.conversation.add_system_message(
                "Resolve the current action-required prompt before sending another message.",
                title="Action Required",
                border_style="#C25B4B",
            )
            return

        expect_remote_echo = not self.screen.is_local_command(text)
        if not self.screen.shell_ready:
            self.screen.record_local_submission(text, expect_remote_echo=expect_remote_echo)
            self._queue.append((text, True))
            self.screen.update_queue_depth(self.queue_depth)
            self.screen.conversation.add_system_message(
                "Malibu is still starting the local session. Your prompt will run as soon as the shell is ready.",
                title="Startup Queue",
                border_style="#8B6A58",
            )
            return

        if self._busy:
            self._queue.append((text, False))
            self.screen.update_queue_depth(self.queue_depth)
            self.screen.conversation.add_system_message(
                f"Queued prompt while the current run is still active.\n\n{text}",
                title="Queue",
                border_style="#7c3aed",
            )
            return

        await self._dispatch(text, local_echoed=False)

    async def flush_ready_queue(self) -> None:
        if self._busy or not self.screen.shell_ready or not self._queue:
            self.screen.update_queue_depth(self.queue_depth)
            return
        next_text, local_echoed = self._queue.popleft()
        await self._dispatch(next_text, local_echoed=local_echoed)

    async def _dispatch(self, text: str, *, local_echoed: bool) -> None:
        self._busy = True
        self.screen.update_queue_depth(self.queue_depth)
        track_processing = not self.screen.is_local_command(text)
        if not local_echoed:
            self.screen.record_local_submission(text, expect_remote_echo=track_processing)
        if track_processing:
            self.screen.start_processing("Preparing agent")
        try:
            await self.screen.dispatch_prompt(text)
        finally:
            self._busy = False
            if track_processing:
                self.screen.stop_processing()
            self.screen.update_queue_depth(self.queue_depth)
            if self._queue:
                next_text, next_local_echoed = self._queue.popleft()
                await self._dispatch(next_text, local_echoed=next_local_echoed)
