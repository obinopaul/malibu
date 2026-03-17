from __future__ import annotations

from collections.abc import AsyncGenerator
from enum import StrEnum, auto
from typing import TYPE_CHECKING, Any, ClassVar

import httpx
from pydantic import BaseModel, Field

from vibe.core.tools.base import (
    BaseTool,
    BaseToolConfig,
    BaseToolState,
    InvokeContext,
    ToolError,
    ToolPermission,
)
from vibe.core.tools.builtins._web_providers import (
    ddgs_is_available,
    ddgs_text_search,
    resolve_tavily_api_key,
    tavily_search,
)
from vibe.core.tools.ui import ToolCallDisplay, ToolResultDisplay, ToolUIData
from vibe.core.types import ToolStreamEvent

if TYPE_CHECKING:
    from vibe.core.types import ToolCallEvent, ToolResultEvent


class WebSearchHit(BaseModel):
    title: str
    url: str
    snippet: str = ""
    score: float | None = None


class WebSearchArgs(BaseModel):
    query: str = Field(min_length=1)


class WebSearchResult(BaseModel):
    query: str
    provider: str
    answer: str | None = None
    hits: list[WebSearchHit] = Field(default_factory=list)


class WebSearchProvider(StrEnum):
    AUTO = auto()
    TAVILY = auto()
    DDGS = auto()


class WebSearchConfig(BaseToolConfig):
    permission: ToolPermission = ToolPermission.ASK
    timeout: int = Field(default=30, description="HTTP timeout in seconds.")
    max_results: int = Field(default=8, description="Maximum results to return.")
    provider_preference: WebSearchProvider = Field(
        default=WebSearchProvider.AUTO,
        description="Preferred search provider order.",
    )


class WebSearch(
    BaseTool[WebSearchArgs, WebSearchResult, WebSearchConfig, BaseToolState],
    ToolUIData[WebSearchArgs, WebSearchResult],
):
    description: ClassVar[str] = (
        "Search the web for current information using Tavily first, then DDGS as fallback."
    )

    @classmethod
    def is_available(cls) -> bool:
        return (
            bool(resolve_tavily_api_key("WEB_SEARCH_TAVILY_API_KEY"))
            or ddgs_is_available()
        )

    async def run(
        self, args: WebSearchArgs, ctx: InvokeContext | None = None
    ) -> AsyncGenerator[ToolStreamEvent | WebSearchResult, None]:
        errors: list[str] = []

        for provider in self._provider_order():
            match provider:
                case WebSearchProvider.TAVILY:
                    if not (
                        tavily_key := resolve_tavily_api_key("WEB_SEARCH_TAVILY_API_KEY")
                    ):
                        continue
                    try:
                        response = await tavily_search(
                            api_key=tavily_key,
                            query=args.query,
                            max_results=self.config.max_results,
                            timeout=self.config.timeout,
                        )
                        yield self._parse_tavily_response(args.query, response)
                        return
                    except (httpx.HTTPError, ValueError) as exc:
                        errors.append(f"Tavily search failed: {exc}")
                case WebSearchProvider.DDGS:
                    if not ddgs_is_available():
                        continue
                    try:
                        response = await ddgs_text_search(
                            query=args.query,
                            max_results=self.config.max_results,
                            timeout=self.config.timeout,
                        )
                        yield self._parse_ddgs_response(args.query, response)
                        return
                    except Exception as exc:
                        errors.append(f"DDGS search failed: {exc}")

        detail = (
            "; ".join(errors)
            if errors
            else "No web search provider is available. Configure TAVILY_API_KEY in /config or install DDGS for fallback."
        )
        raise ToolError(detail)

    def _provider_order(self) -> tuple[WebSearchProvider, ...]:
        match self.config.provider_preference:
            case WebSearchProvider.DDGS:
                return (WebSearchProvider.DDGS, WebSearchProvider.TAVILY)
            case WebSearchProvider.TAVILY | WebSearchProvider.AUTO:
                return (WebSearchProvider.TAVILY, WebSearchProvider.DDGS)

    def _parse_tavily_response(
        self, query: str, response: dict[str, Any]
    ) -> WebSearchResult:
        hits = [
            WebSearchHit(
                title=str(item.get("title", "")),
                url=str(item.get("url", "")),
                snippet=str(item.get("content", "") or item.get("raw_content", "")),
                score=self._coerce_score(item.get("score")),
            )
            for item in response.get("results", [])
            if isinstance(item, dict) and item.get("url")
        ]
        return WebSearchResult(
            query=query,
            provider="tavily",
            answer=_strip_or_none(response.get("answer")),
            hits=hits,
        )

    def _parse_ddgs_response(
        self, query: str, response: list[dict[str, Any]]
    ) -> WebSearchResult:
        hits = [
            WebSearchHit(
                title=str(item.get("title", "")),
                url=str(item.get("href", "")),
                snippet=str(item.get("body", "")),
            )
            for item in response
            if item.get("href")
        ]
        return WebSearchResult(query=query, provider="ddgs", hits=hits)

    def _coerce_score(self, value: Any) -> float | None:
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return float(value)
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @classmethod
    def get_call_display(cls, event: ToolCallEvent) -> ToolCallDisplay:
        if event.args is None or not isinstance(event.args, WebSearchArgs):
            return ToolCallDisplay(summary="websearch")
        return ToolCallDisplay(summary=f"Searching the web: '{event.args.query}'")

    @classmethod
    def get_result_display(cls, event: ToolResultEvent) -> ToolResultDisplay:
        if not isinstance(event.result, WebSearchResult):
            return ToolResultDisplay(
                success=False, message=event.error or event.skip_reason or "No result"
            )
        warnings = (
            []
            if event.result.answer
            else ["No direct answer returned; inspect hits for source material"]
        )
        return ToolResultDisplay(
            success=True,
            message=f"{len(event.result.hits)} hits from {event.result.provider}",
            warnings=warnings,
        )

    @classmethod
    def get_status_text(cls) -> str:
        return "Searching the web"


def _strip_or_none(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None
