"""Tests for malibu.server.plans module."""

from __future__ import annotations

from malibu.server.plans import all_tasks_completed, build_empty_plan, build_plan_update, format_plan_text


def test_build_plan_update():
    entries = [
        {"content": "Research the problem", "status": "completed"},
        {"content": "Implement solution", "status": "in_progress"},
        {"content": "Write tests", "status": "pending"},
    ]
    update = build_plan_update(entries)
    assert update is not None
    assert len(update.entries) == 3


def test_build_empty_plan():
    update = build_empty_plan()
    assert update.entries == []


def test_all_tasks_completed_true():
    entries = [
        {"content": "A", "status": "completed"},
        {"content": "B", "status": "completed"},
    ]
    # all_tasks_completed operates on the raw todo dicts
    assert all_tasks_completed(entries) is True


def test_not_all_completed():
    entries = [
        {"content": "A", "status": "completed"},
        {"content": "B", "status": "pending"},
    ]
    assert all_tasks_completed(entries) is False


def test_all_tasks_completed_empty():
    assert all_tasks_completed([]) is True


def test_format_plan_text():
    entries = [
        {"content": "Do X", "status": "completed"},
        {"content": "Do Y", "status": "in_progress"},
    ]
    text = format_plan_text(entries)
    assert "Do X" in text
    assert "Do Y" in text
    assert "[x]" in text  # completed marker
    assert "[~]" in text  # in_progress marker
