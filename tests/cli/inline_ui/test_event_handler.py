import io
from vibe.cli.inline_ui.event_handler import InlineEventHandler
from vibe.cli.inline_ui.renderer import OutputRenderer
from vibe.cli.inline_ui.tool_display import ToolDisplay


def test_event_handler_creates():
    buf = io.StringIO()
    renderer = OutputRenderer(file=buf, force_terminal=True)
    tool_display = ToolDisplay(file=buf, force_terminal=True)
    handler = InlineEventHandler(renderer=renderer, tool_display=tool_display)
    assert handler is not None
