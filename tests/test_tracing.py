"""Tests for malibu.telemetry.tracing — OpenTelemetry integration."""

from __future__ import annotations

from malibu.config import Settings
from malibu.telemetry.tracing import async_span, get_tracer, init_tracing, span


def _make_settings(**overrides) -> Settings:
    defaults = dict(
        database_url="sqlite+aiosqlite:///test.db",
        jwt_secret="test-secret",
        llm_model="openai:gpt-4o-mini",
        allowed_paths=["."],
    )
    defaults.update(overrides)
    return Settings(**defaults)


class TestTracing:
    def test_tracing_disabled_by_default(self):
        settings = _make_settings(otel_enabled=False)
        init_tracing(settings)
        assert get_tracer() is None

    def test_span_noop_when_disabled(self):
        """span() should yield None when tracing is disabled."""
        with span("test_operation") as s:
            assert s is None

    async def test_async_span_noop_when_disabled(self):
        """async_span() should yield None when tracing is disabled."""
        async with async_span("test_operation") as s:
            assert s is None

    def test_span_with_attributes_noop(self):
        with span("test", attributes={"key": "val"}) as s:
            assert s is None
