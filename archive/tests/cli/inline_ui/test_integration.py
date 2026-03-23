"""Integration tests for the inline UI components working together."""
import io

from vibe.cli.inline_ui.renderer import OutputRenderer
from vibe.cli.inline_ui.tool_display import ToolDisplay
from vibe.cli.inline_ui.event_handler import InlineEventHandler
from vibe.cli.inline_ui.banner import print_banner
from vibe.cli.inline_ui.status import print_status


def test_full_output_flow():
    """Simulate a complete interaction flow."""
    buf = io.StringIO()
    kwargs = {"file": buf, "force_terminal": True}

    # Banner
    print_banner(model_name="test-model", version="0.1.0", **kwargs)

    # User message
    renderer = OutputRenderer(**kwargs)
    renderer.user_message("Hello")

    # Tool call + result
    td = ToolDisplay(**kwargs)
    td.show_tool_call("read_file", {"path": "/tmp/foo.py"})
    td.show_tool_complete("read_file", success=True)
    td.show_tool_result("read_file", "print('hello')", is_error=False, collapsed=False)

    # Status
    print_status(context_tokens=5000, max_tokens=128000, cost=0.05, **kwargs)

    output = buf.getvalue()
    assert "Hello" in output
    assert "read_file" in output
    assert "test-model" in output


def test_error_handling():
    buf = io.StringIO()
    renderer = OutputRenderer(file=buf, force_terminal=True)
    renderer.error("Something went wrong")
    renderer.warning("Be careful")
    renderer.interrupt()
    output = buf.getvalue()
    assert "Something went wrong" in output
    assert "Be careful" in output
    assert "Interrupted" in output
