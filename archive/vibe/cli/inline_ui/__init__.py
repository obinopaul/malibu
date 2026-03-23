# vibe/cli/inline_ui/__init__.py
from __future__ import annotations

__all__ = ["run_inline_ui"]


def run_inline_ui(*args, **kwargs):  # type: ignore[no-untyped-def]
    """Lazy entry point — imports deferred to avoid loading the full agent stack."""
    from vibe.cli.inline_ui.app import run_inline_ui as _run

    return _run(*args, **kwargs)
