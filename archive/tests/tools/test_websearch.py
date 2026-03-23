from __future__ import annotations

import pytest

from tests.mock.utils import collect_result
from vibe.core.tools.base import BaseToolState, ToolError
from vibe.core.tools.builtins.websearch import (
    WebSearch,
    WebSearchArgs,
    WebSearchConfig,
    WebSearchProvider,
)


@pytest.fixture
def websearch() -> WebSearch:
    return WebSearch(config=WebSearchConfig(), state=BaseToolState())


def test_parse_tavily_response(websearch: WebSearch) -> None:
    result = websearch._parse_tavily_response(
        "latest docs",
        {
            "answer": "Use the official docs.",
            "results": [
                {
                    "title": "Official Docs",
                    "url": "https://example.com/docs",
                    "content": "Current API reference",
                    "score": 0.92,
                }
            ],
        },
    )

    assert result.provider == "tavily"
    assert result.answer == "Use the official docs."
    assert result.hits[0].url == "https://example.com/docs"
    assert result.hits[0].score == 0.92


def test_parse_ddgs_response(websearch: WebSearch) -> None:
    result = websearch._parse_ddgs_response(
        "search term",
        [{"title": "Example", "href": "https://example.com", "body": "Snippet"}],
    )

    assert result.provider == "ddgs"
    assert result.answer is None
    assert result.hits[0].snippet == "Snippet"


@pytest.mark.asyncio
async def test_run_uses_tavily_when_key_present(
    websearch: WebSearch, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "vibe.core.tools.builtins.websearch.resolve_tavily_api_key",
        lambda *args: "test-key",
    )

    async def fake_tavily_search(**kwargs):
        return {
            "answer": "Tavily answer",
            "results": [
                {"title": "Result", "url": "https://example.com", "content": "Snippet"}
            ],
        }

    monkeypatch.setattr(
        "vibe.core.tools.builtins.websearch.tavily_search", fake_tavily_search
    )
    monkeypatch.setattr(
        "vibe.core.tools.builtins.websearch.ddgs_is_available", lambda: False
    )

    result = await collect_result(websearch.run(WebSearchArgs(query="latest docs")))

    assert result.provider == "tavily"
    assert result.answer == "Tavily answer"
    assert len(result.hits) == 1


@pytest.mark.asyncio
async def test_run_falls_back_to_ddgs_on_tavily_failure(
    websearch: WebSearch, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "vibe.core.tools.builtins.websearch.resolve_tavily_api_key",
        lambda *args: "test-key",
    )

    async def failing_tavily(**kwargs):
        raise ValueError("tavily down")

    async def fake_ddgs(**kwargs):
        return [
            {
                "title": "Fallback",
                "href": "https://fallback.example.com",
                "body": "fallback snippet",
            }
        ]

    monkeypatch.setattr(
        "vibe.core.tools.builtins.websearch.tavily_search", failing_tavily
    )
    monkeypatch.setattr(
        "vibe.core.tools.builtins.websearch.ddgs_is_available", lambda: True
    )
    monkeypatch.setattr(
        "vibe.core.tools.builtins.websearch.ddgs_text_search", fake_ddgs
    )

    result = await collect_result(websearch.run(WebSearchArgs(query="latest docs")))

    assert result.provider == "ddgs"
    assert result.hits[0].url == "https://fallback.example.com"


@pytest.mark.asyncio
async def test_run_respects_ddgs_provider_preference(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    websearch = WebSearch(
        config=WebSearchConfig(provider_preference=WebSearchProvider.DDGS),
        state=BaseToolState(),
    )
    monkeypatch.setattr(
        "vibe.core.tools.builtins.websearch.resolve_tavily_api_key",
        lambda *args: "test-key",
    )
    monkeypatch.setattr(
        "vibe.core.tools.builtins.websearch.ddgs_is_available", lambda: True
    )

    async def fake_tavily_search(**kwargs):
        raise AssertionError("Tavily should not be called first")

    async def fake_ddgs(**kwargs):
        return [
            {
                "title": "Preferred",
                "href": "https://preferred.example.com",
                "body": "preferred snippet",
            }
        ]

    monkeypatch.setattr(
        "vibe.core.tools.builtins.websearch.tavily_search", fake_tavily_search
    )
    monkeypatch.setattr(
        "vibe.core.tools.builtins.websearch.ddgs_text_search", fake_ddgs
    )

    result = await collect_result(websearch.run(WebSearchArgs(query="latest docs")))

    assert result.provider == "ddgs"
    assert result.hits[0].url == "https://preferred.example.com"


@pytest.mark.asyncio
async def test_run_errors_when_no_provider_available(
    websearch: WebSearch, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "vibe.core.tools.builtins.websearch.resolve_tavily_api_key", lambda *args: None
    )
    monkeypatch.setattr(
        "vibe.core.tools.builtins.websearch.ddgs_is_available", lambda: False
    )

    with pytest.raises(ToolError, match="No web search provider is available"):
        await collect_result(websearch.run(WebSearchArgs(query="latest docs")))


def test_is_available_with_ddgs_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "vibe.core.tools.builtins.websearch.resolve_tavily_api_key", lambda *args: None
    )
    monkeypatch.setattr(
        "vibe.core.tools.builtins.websearch.ddgs_is_available", lambda: True
    )

    assert WebSearch.is_available() is True


def test_get_status_text() -> None:
    assert WebSearch.get_status_text() == "Searching the web"
