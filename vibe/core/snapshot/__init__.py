"""Snapshot module for reliable file change tracking and revert.

Uses a shadow git repository to create atomic snapshots of modified files
before and after tool execution, enabling reliable rollback of any change.
"""

from vibe.core.snapshot.manager import SnapshotManager

__all__ = ["SnapshotManager"]
