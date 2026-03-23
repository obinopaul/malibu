import io
from vibe.cli.inline_ui.renderer import OutputRenderer


def test_renderer_prints_user_message():
    buf = io.StringIO()
    r = OutputRenderer(file=buf, force_terminal=True)
    r.user_message("Hello world")
    output = buf.getvalue()
    assert "Hello world" in output


def test_renderer_prints_error():
    buf = io.StringIO()
    r = OutputRenderer(file=buf, force_terminal=True)
    r.error("Something broke")
    output = buf.getvalue()
    assert "Something broke" in output


def test_renderer_prints_warning():
    buf = io.StringIO()
    r = OutputRenderer(file=buf, force_terminal=True)
    r.warning("Be careful")
    output = buf.getvalue()
    assert "Be careful" in output


def test_renderer_prints_command_output():
    buf = io.StringIO()
    r = OutputRenderer(file=buf, force_terminal=True)
    r.command_message("Configuration reloaded.")
    output = buf.getvalue()
    assert "Configuration reloaded" in output


def test_renderer_prints_interrupt():
    buf = io.StringIO()
    r = OutputRenderer(file=buf, force_terminal=True)
    r.interrupt()
    output = buf.getvalue()
    assert "Interrupted" in output


def test_renderer_bash_output_success():
    buf = io.StringIO()
    r = OutputRenderer(file=buf, force_terminal=True)
    r.bash_output("ls -la", "total 42\nfile.txt", exit_code=0)
    output = buf.getvalue()
    assert "ls -la" in output
    assert "file.txt" in output


def test_renderer_bash_output_empty():
    buf = io.StringIO()
    r = OutputRenderer(file=buf, force_terminal=True)
    r.bash_output("mkdir test", "", exit_code=0)
    output = buf.getvalue()
    assert "mkdir test" in output


def test_renderer_bash_output_error():
    buf = io.StringIO()
    r = OutputRenderer(file=buf, force_terminal=True)
    r.bash_output("bad_cmd", "not found", exit_code=127)
    output = buf.getvalue()
    assert "bad_cmd" in output
    assert "not found" in output
