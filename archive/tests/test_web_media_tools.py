from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

from malibu.agent.tool_server.core.workspace import WorkspaceManager
from malibu.agent.tool_server.tools.media.image_generate import ImageGenerateTool
from malibu.agent.tool_server.tools.web.image_search_tool import ImageSearchTool
from malibu.agent.tool_server.tools.web.web_search_tool import WebSearchTool
from malibu.agent.tool_server.tools.web.web_visit_tool import WebVisitTool


class _FakeWebSearchClient:
    async def search(self, query: str, max_results: int = 10):
        return SimpleNamespace(
            result=[
                {
                    "query": query,
                    "title": "Example",
                    "url": "https://example.com",
                    "content": "Snippet",
                }
            ][:max_results]
        )


class _FakeWebVisitService:
    async def visit(self, url: str, prompt: str | None = None):
        return SimpleNamespace(content=f"URL: {url}\nPrompt: {prompt}")


class _FakeImageSearchClient:
    async def search(self, **kwargs):
        return SimpleNamespace(
            result=[
                {
                    "title": "Sample image",
                    "source": "Example Source",
                    "image_url": "https://example.com/image.png",
                    "width": 800,
                    "height": 600,
                    "is_product": False,
                }
            ]
        )


class _FallbackImageGenerationClient:
    async def generate_image(self, prompt: str, aspect_ratio: str = "1:1"):
        return SimpleNamespace(
            url=None,
            mime_type=None,
            size=0,
            search_results=[
                {
                    "title": "Fallback result",
                    "source": "DuckDuckGo",
                    "image_url": "https://example.com/fallback.png",
                }
            ],
        )


def test_web_search_tool_calls_client_directly():
    tool = WebSearchTool(_FakeWebSearchClient(), max_results=5)
    result = asyncio.run(tool.execute({"query": "malibu"}))
    assert "Example" in result.llm_content
    assert result.is_error is False


def test_web_visit_tool_uses_service_directly():
    tool = WebVisitTool(_FakeWebVisitService())
    result = asyncio.run(tool.execute({"url": "https://example.com", "prompt": "Summarize"}))
    assert "https://example.com" in result.llm_content
    assert "Summarize" in result.llm_content


def test_image_search_tool_uses_direct_client():
    tool = ImageSearchTool(_FakeImageSearchClient(), max_results=5)
    result = asyncio.run(tool.execute({"query": "landing page hero"}))
    assert "Sample image" in result.llm_content
    assert "https://example.com/image.png" in result.llm_content


def test_image_generate_tool_writes_local_fallback_summary(tmp_path: Path):
    tool = ImageGenerateTool(
        WorkspaceManager(tmp_path),
        _FallbackImageGenerationClient(),
    )
    output_path = tmp_path / "generated" / "hero.png"
    result = asyncio.run(
        tool.execute(
            {
                "prompt": "coastal sunrise",
                "output_path": str(output_path),
                "aspect_ratio": "16:9",
            }
        )
    )
    summary_path = output_path.with_suffix(".md")
    assert summary_path.exists()
    assert "DuckDuckGo image search results" in summary_path.read_text(encoding="utf-8")
    assert "saved to" in result.llm_content
