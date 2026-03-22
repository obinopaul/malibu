"""Tests for malibu.server.permissions module."""

from __future__ import annotations

from malibu.server.permissions import PermissionManager


def test_nothing_auto_approved_by_default():
    pm = PermissionManager()
    # No allowlist entries → nothing auto-approved
    assert pm.is_auto_approved("sess-1", "read_file", {}) is False
    assert pm.is_auto_approved("sess-1", "execute", {"command": "ls"}) is False


def test_register_always_allow_tool():
    pm = PermissionManager()
    pm.register_always_allow("sess-1", "read_file", {})
    assert pm.is_auto_approved("sess-1", "read_file", {}) is True
    # Different session → not approved
    assert pm.is_auto_approved("sess-2", "read_file", {}) is False


def test_register_always_allow_execute():
    pm = PermissionManager()
    pm.register_always_allow("sess-1", "execute", {"command": "ls -la"})
    assert pm.is_auto_approved("sess-1", "execute", {"command": "ls -la"}) is True
    # Different command → not approved
    assert pm.is_auto_approved("sess-1", "execute", {"command": "rm -rf /"}) is False


def test_build_permission_options():
    pm = PermissionManager()
    opts = pm.build_permission_options("execute", {"command": "rm -rf /"})
    assert len(opts) == 3  # approve, reject, approve_always
    option_ids = {o.option_id for o in opts}
    assert "approve" in option_ids
    assert "reject" in option_ids
    assert "approve_always" in option_ids


def test_plan_approval_and_auto_approve():
    pm = PermissionManager()
    pm.approve_plan("sess-1", {"todos": [{"content": "step 1", "status": "pending"}]})
    # write_todos should auto-approve when plan is in progress
    assert pm.is_auto_approved("sess-1", "write_todos", {"todos": [{"content": "step 1", "status": "completed"}]}) is True
    pm.clear_plan("sess-1")
    # After clearing, write_todos should not auto-approve
    assert pm.is_auto_approved("sess-1", "write_todos", {"todos": []}) is False
