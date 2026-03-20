import io
import time
from vibe.cli.inline_ui.spinner import WaitingSpinner, StatusSpinner


def test_waiting_spinner_starts_and_stops():
    spinner = WaitingSpinner(text="Generating", delay=0.05, visible_after=0)
    spinner.start()
    time.sleep(0.15)
    spinner.stop()
    # Should not raise, should clean up


def test_status_spinner_renders():
    buf = io.StringIO()
    ss = StatusSpinner(file=buf, force_terminal=True)
    ss.start("read_file")
    ss.stop(success=True)
    output = buf.getvalue()
    assert "read_file" in output
