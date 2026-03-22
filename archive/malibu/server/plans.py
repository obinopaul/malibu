"""Plan lifecycle — create, update, clear ACP AgentPlanUpdate messages.

Wraps acp.helpers.update_plan / plan_entry for structured plan management
with database persistence.
"""

from __future__ import annotations

from typing import Any

from acp.helpers import plan_entry, update_plan
from acp.schema import AgentPlanUpdate, PlanEntry


def build_plan_update(todos: list[dict[str, Any]]) -> AgentPlanUpdate:
    """Convert a list of todo dicts into a proper AgentPlanUpdate."""
    entries: list[PlanEntry] = []
    for todo in todos:
        content = todo.get("content", "")
        status = todo.get("status", "pending")
        if status not in ("pending", "in_progress", "completed"):
            status = "pending"
        entries.append(plan_entry(content, status=status))
    return update_plan(entries)


def build_empty_plan() -> AgentPlanUpdate:
    """Create an empty plan update (clears the plan on the client)."""
    return update_plan([])


def all_tasks_completed(todos: list[dict[str, Any]]) -> bool:
    """Check if every entry in a plan is completed."""
    if not todos:
        return True
    return all(t.get("status") == "completed" for t in todos)


def format_plan_text(todos: list[dict[str, Any]]) -> str:
    """Render a plan as human-readable markdown text."""
    lines = ["## Plan\n"]
    for i, todo in enumerate(todos, 1):
        content = todo.get("content", "")
        status = todo.get("status", "pending")
        marker = {"completed": "x", "in_progress": "~", "pending": " "}.get(status, " ")
        lines.append(f"{i}. [{marker}] {content}")
    return "\n".join(lines)
