from __future__ import annotations

import httpx
import pytest
import respx

from tests.mock.utils import collect_result
from vibe.core.tools.base import BaseToolState, ToolError
from vibe.core.tools.builtins.webfetch import (
    WebFetch,
    WebFetchArgs,
    WebFetchConfig,
    WebFetchProvider,
)


@pytest.fixture
def webfetch() -> WebFetch:
    return WebFetch(config=WebFetchConfig(), state=BaseToolState())


@pytest.fixture
def webfetch_small() -> WebFetch:
    return WebFetch(config=WebFetchConfig(max_content_bytes=100), state=BaseToolState())


@pytest.mark.asyncio
async def test_tavily_extract_used_when_available(
    webfetch: WebFetch, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "vibe.core.tools.builtins.webfetch.resolve_tavily_api_key",
        lambda *args: "test-key",
    )

    async def fake_tavily_extract(**kwargs):
        return {"results": [{"raw_content": "# Title\n\nFocused content"}]}

    monkeypatch.setattr(
        "vibe.core.tools.builtins.webfetch.tavily_extract", fake_tavily_extract
    )

    result = await collect_result(
        webfetch.run(WebFetchArgs(url="https://example.com", prompt="summarize"))
    )

    assert result.provider == "tavily"
    assert result.prompt == "summarize"
    assert "Focused content" in result.content


@pytest.mark.asyncio
@respx.mock
async def test_tavily_failure_falls_back_to_raw_http(
    webfetch: WebFetch, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "vibe.core.tools.builtins.webfetch.resolve_tavily_api_key",
        lambda *args: "test-key",
    )

    async def failing_tavily_extract(**kwargs):
        raise ValueError("tavily failed")

    monkeypatch.setattr(
        "vibe.core.tools.builtins.webfetch.tavily_extract", failing_tavily_extract
    )
    respx.get("https://example.com").mock(
        return_value=httpx.Response(
            200, text="fallback body", headers={"Content-Type": "text/plain"}
        )
    )

    result = await collect_result(webfetch.run(WebFetchArgs(url="https://example.com")))

    assert result.provider == "http"
    assert result.content == "fallback body"


@pytest.mark.asyncio
@respx.mock
async def test_http_provider_preference_runs_before_tavily(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    webfetch = WebFetch(
        config=WebFetchConfig(provider_preference=WebFetchProvider.HTTP),
        state=BaseToolState(),
    )
    monkeypatch.setattr(
        "vibe.core.tools.builtins.webfetch.resolve_tavily_api_key",
        lambda *args: "test-key",
    )

    async def fake_tavily_extract(**kwargs):
        raise AssertionError("Tavily should not be called first")

    monkeypatch.setattr(
        "vibe.core.tools.builtins.webfetch.tavily_extract", fake_tavily_extract
    )
    respx.get("https://example.com").mock(
        return_value=httpx.Response(
            200, text="http body", headers={"Content-Type": "text/plain"}
        )
    )

    result = await collect_result(webfetch.run(WebFetchArgs(url="https://example.com")))

    assert result.provider == "http"
    assert result.content == "http body"


@pytest.mark.asyncio
@respx.mock
async def test_bare_domain_gets_https(
    webfetch: WebFetch, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "vibe.core.tools.builtins.webfetch.resolve_tavily_api_key", lambda *args: None
    )
    respx.get("https://example.com").mock(
        return_value=httpx.Response(
            200, text="ok", headers={"Content-Type": "text/plain"}
        )
    )

    result = await collect_result(webfetch.run(WebFetchArgs(url="example.com")))

    assert result.url == "https://example.com"
    assert result.provider == "http"
    assert result.content == "ok"


@pytest.mark.asyncio
@respx.mock
async def test_html_converted_to_markdown(
    webfetch: WebFetch, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "vibe.core.tools.builtins.webfetch.resolve_tavily_api_key", lambda *args: None
    )
    html = "<html><body><h1>Title</h1><p>Hello world</p></body></html>"
    respx.get("https://example.com").mock(
        return_value=httpx.Response(
            200, text=html, headers={"Content-Type": "text/html; charset=utf-8"}
        )
    )

    result = await collect_result(webfetch.run(WebFetchArgs(url="https://example.com")))

    assert "# Title" in result.content
    assert "Hello world" in result.content


@pytest.mark.asyncio
@respx.mock
async def test_prompt_focuses_raw_http_content(
    webfetch: WebFetch, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "vibe.core.tools.builtins.webfetch.resolve_tavily_api_key", lambda *args: None
    )
    body = (
        "General intro.\n\n"
        "Pricing: Starter is $10 per month.\n\n"
        "Architecture: distributed system.\n\n"
        "Pricing: Pro is $50 per month."
    )
    respx.get("https://example.com").mock(
        return_value=httpx.Response(
            200, text=body, headers={"Content-Type": "text/plain"}
        )
    )

    result = await collect_result(
        webfetch.run(WebFetchArgs(url="https://example.com", prompt="pricing tiers"))
    )

    assert result.prompt == "pricing tiers"
    assert "Pricing: Starter" in result.content
    assert "Prompt: pricing tiers" in result.content


@pytest.mark.asyncio
@respx.mock
async def test_cloudflare_retry_on_challenge(
    webfetch: WebFetch, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "vibe.core.tools.builtins.webfetch.resolve_tavily_api_key", lambda *args: None
    )
    route = respx.get("https://example.com")
    route.side_effect = [
        httpx.Response(403, headers={"cf-mitigated": "challenge"}),
        httpx.Response(200, text="success", headers={"Content-Type": "text/plain"}),
    ]

    result = await collect_result(webfetch.run(WebFetchArgs(url="https://example.com")))

    assert result.content == "success"
    assert route.call_count == 2
    assert route.calls[1].request.headers["User-Agent"] == "vibe-cli"


@pytest.mark.asyncio
@respx.mock
async def test_truncates_to_max_bytes_with_disclaimer(
    webfetch_small: WebFetch, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "vibe.core.tools.builtins.webfetch.resolve_tavily_api_key", lambda *args: None
    )
    body = "a" * 200
    respx.get("https://example.com").mock(
        return_value=httpx.Response(
            200, text=body, headers={"Content-Type": "text/plain"}
        )
    )

    result = await collect_result(
        webfetch_small.run(WebFetchArgs(url="https://example.com"))
    )

    assert result.content.startswith("a" * 100)
    assert "[Content truncated due to size limit]" in result.content


@pytest.mark.asyncio
async def test_empty_url_rejected(webfetch: WebFetch) -> None:
    with pytest.raises(ToolError, match="URL cannot be empty"):
        await collect_result(webfetch.run(WebFetchArgs(url="   ")))


@pytest.mark.asyncio
async def test_over_max_timeout_rejected(webfetch: WebFetch) -> None:
    with pytest.raises(ToolError, match="Timeout cannot exceed"):
        await collect_result(
            webfetch.run(WebFetchArgs(url="https://example.com", timeout=999))
        )


def test_get_status_text() -> None:
    assert WebFetch.get_status_text() == "Fetching URL"
