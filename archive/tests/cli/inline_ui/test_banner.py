import io
from vibe.cli.inline_ui.banner import print_banner


def test_banner_contains_malibu():
    buf = io.StringIO()
    print_banner(
        model_name="mistral-large",
        version="1.0.0",
        file=buf,
        force_terminal=True,
    )
    output = buf.getvalue()
    assert "malibu" in output.lower() or "Malibu" in output
