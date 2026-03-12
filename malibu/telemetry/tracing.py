"""Optional OpenTelemetry tracing integration.

Wraps acp.telemetry.span_context for distributed tracing when OTEL_ENABLED=true.
Falls back to no-op when disabled or when OTel SDK is not installed.
"""

from __future__ import annotations

import contextlib
from contextlib import asynccontextmanager, contextmanager
from typing import Any, AsyncIterator, Iterator

from malibu.config import Settings

_tracer = None


def init_tracing(settings: Settings) -> None:
    """Initialize OpenTelemetry tracer if enabled and available."""
    global _tracer
    if not settings.otel_enabled:
        return

    try:
        from opentelemetry import trace
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter

        resource = Resource.create({"service.name": settings.otel_service_name})
        provider = TracerProvider(resource=resource)

        # Default to console exporter; replace with OTLP in production
        provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
        trace.set_tracer_provider(provider)
        _tracer = trace.get_tracer(settings.otel_service_name)
    except ImportError:
        pass  # OTel packages not installed, tracing disabled


@contextmanager
def span(name: str, *, attributes: dict[str, Any] | None = None) -> Iterator[Any]:
    """Create a synchronous tracing span (no-op when tracing is disabled)."""
    if _tracer is None:
        yield None
        return

    with _tracer.start_as_current_span(name, attributes=attributes or {}) as s:
        yield s


@asynccontextmanager
async def async_span(name: str, *, attributes: dict[str, Any] | None = None) -> AsyncIterator[Any]:
    """Create an async tracing span (no-op when tracing is disabled)."""
    if _tracer is None:
        yield None
        return

    with _tracer.start_as_current_span(name, attributes=attributes or {}) as s:
        yield s


def get_tracer():
    """Return the current tracer (may be None if tracing is disabled)."""
    return _tracer
