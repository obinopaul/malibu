from vibe.cli.inline_ui.input_session import InputSession


def test_input_session_creates():
    """Should instantiate without error."""
    session = InputSession(history_file=None)
    assert session is not None


def test_input_session_has_prompt_session():
    session = InputSession(history_file=None)
    assert session.prompt_session is not None
