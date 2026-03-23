from vibe.cli.inline_ui.approval import format_approval_prompt


def test_format_approval_prompt():
    text = format_approval_prompt("write_file", {"path": "/tmp/foo.py"})
    assert "write_file" in text
    assert "/tmp/foo.py" in text
