import io
from vibe.cli.inline_ui.tool_display import ToolDisplay

def test_tool_call_display():
    buf = io.StringIO()
    td = ToolDisplay(file=buf, force_terminal=True)
    td.show_tool_call("read_file", {"path": "/tmp/test.py"})
    assert "read_file" in buf.getvalue()

def test_tool_result_display():
    buf = io.StringIO()
    td = ToolDisplay(file=buf, force_terminal=True)
    td.show_tool_result("read_file", "file contents here", is_error=False, collapsed=False)
    assert "file contents" in buf.getvalue()

def test_diff_display():
    buf = io.StringIO()
    td = ToolDisplay(file=buf, force_terminal=True)
    diff = "--- a/foo.py\n+++ b/foo.py\n@@ -1 +1 @@\n-old\n+new"
    td.show_diff(diff)
    output = buf.getvalue()
    assert "old" in output or "new" in output
