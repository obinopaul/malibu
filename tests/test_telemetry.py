"""Tests for malibu.telemetry module."""

from __future__ import annotations

from malibu.config import Settings
from malibu.telemetry.logging import get_logger, setup_logging


def _make_settings(log_level: str = "DEBUG") -> Settings:
    return Settings(
        database_url="sqlite+aiosqlite:///test.db",
        jwt_secret="test-secret",
        llm_api_key="sk-test",
        log_level=log_level,
    )


def test_setup_logging_dev():
    setup_logging(_make_settings("DEBUG"))
    log = get_logger("test")
    assert log is not None


def test_setup_logging_prod():
    setup_logging(_make_settings("INFO"))
    log = get_logger("test_prod")
    assert log is not None


def test_logger_can_log():
    setup_logging(_make_settings("DEBUG"))
    log = get_logger("test_can_log")
    # Should not raise
    log.info("test_message", key="value")
