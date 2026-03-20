import io
from unittest.mock import patch
from vibe.cli.inline_ui.markdown_stream import MarkdownStream


def test_stream_renders_final_text():
    """Final update should flush all content to console."""
    buf = io.StringIO()
    ms = MarkdownStream(file=buf, force_terminal=True)
    ms.update("Hello **world**", final=True)
    output = buf.getvalue()
    assert "world" in output


def test_stream_stable_lines_are_flushed():
    """Lines beyond the live window should be flushed to permanent output."""
    buf = io.StringIO()
    ms = MarkdownStream(file=buf, force_terminal=True)
    # Send enough text to produce many lines
    long_text = "\n\n".join([f"Paragraph {i}" for i in range(20)])
    ms.update(long_text, final=False)
    ms.update(long_text, final=True)
    output = buf.getvalue()
    # All paragraphs should appear
    assert "Paragraph 0" in output
    assert "Paragraph 19" in output


def test_stream_throttle_skips_rapid_updates():
    """Updates within min_delay should be skipped."""
    buf = io.StringIO()
    ms = MarkdownStream(file=buf, force_terminal=True)
    ms.min_delay = 10  # 10 seconds — nothing should render
    ms.update("First", final=False)  # This one renders (first call)
    ms.update("Second", final=False)  # This should be skipped
    # Final always renders
    ms.update("Third", final=True)
    output = buf.getvalue()
    assert "Third" in output


def test_stream_cleanup_on_final():
    """After final=True, Live should be stopped."""
    buf = io.StringIO()
    ms = MarkdownStream(file=buf, force_terminal=True)
    ms.update("Done", final=True)
    assert ms.live is None
