"""Malibu context-engineering subsystem.

This package contains:
- adapter.py: production-safe context assembly used by Malibu runtime
- opendev_reference/: imported OpenDev context-engineering source for progressive integration
"""

from malibu.context_engineering.adapter import build_runtime_context

__all__ = ["build_runtime_context"]
