"""Snapshot module for reliable file change tracking and revert.

Uses a shadow git repository to create atomic snapshots of modified files
before and after tool execution, enabling reliable rollback of any change.

Adapted from OpenDev's snapshot system.
"""

from malibu.snapshot.manager import SnapshotManager

__all__ = ["SnapshotManager"]
