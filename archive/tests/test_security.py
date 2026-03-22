"""Tests for malibu.server.security module."""

from __future__ import annotations

from malibu.server.security import extract_command_types, truncate_command_for_display


def test_extract_simple_command():
    types = extract_command_types("ls -la")
    assert "ls" in types


def test_extract_piped_commands():
    types = extract_command_types("cat file.txt | grep pattern | wc -l")
    assert "cat" in types
    assert "grep" in types
    assert "wc" in types


def test_extract_chained_commands():
    types = extract_command_types("mkdir -p dir && cd dir && touch file.txt")
    assert "mkdir" in types
    assert "cd" in types
    assert "touch" in types


def test_extract_python_command():
    types = extract_command_types("python -c 'print(hello)'")
    assert any("python" in t for t in types)


def test_extract_npm_command():
    types = extract_command_types("npm install express")
    assert any("npm" in t for t in types)


def test_truncate_short_command():
    cmd = "ls -la"
    assert truncate_command_for_display(cmd) == cmd


def test_truncate_long_command():
    cmd = "echo " + "a" * 200
    truncated = truncate_command_for_display(cmd, max_length=50)
    assert len(truncated) <= 53  # max_length + "..."
    assert truncated.endswith("...")
