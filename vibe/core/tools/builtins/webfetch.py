from __future__ import annotations

from collections.abc import AsyncGenerator
from enum import StrEnum, auto
import re
from typing import TYPE_CHECKING, ClassVar
from urllib.parse import urlparse

import httpx
from markdownify import MarkdownConverter
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
    resolve_tavily_api_key,
    tavily_extract,
)
from vibe.core.tools.ui import ToolCallDisplay, ToolResultDisplay, ToolUIData
from vibe.core.types import ToolStreamEvent

if TYPE_CHECKING:
    from vibe.core.types import ToolCallEvent, ToolResultEvent


_HONEST_USER_AGENT = "vibe-cli"
_HTTP_FORBIDDEN = 403
_PROMPT_KEYWORD_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{2,}")


class _Converter(MarkdownConverter):
    convert_script = convert_style = convert_noscript = convert_iframe = (
        convert_object
    ) = convert_embed = lambda *_, **__: ""


class WebFetchArgs(BaseModel):
    url: str = Field(description="URL to fetch (http/https)")
    prompt: str | None = Field(
        default=None, description="Optional extraction prompt for focused retrieval."
    )
    timeout: int | None = Field(
        default=None, description="Timeout in seconds (max 120)"
    )


class WebFetchResult(BaseModel):
    url: str
    provider: str
    content: str
    content_type: str
    prompt: str | None = None


class WebFetchProvider(StrEnum):
    AUTO = auto()
    TAVILY = auto()
    HTTP = auto()


class WebFetchConfig(BaseToolConfig):
    permission: ToolPermission = ToolPermission.ASK
    default_timeout: int = Field(default=30, description="Default timeout in seconds.")
    max_timeout: int = Field(default=120, description="Maximum allowed timeout.")
    provider_preference: WebFetchProvider = Field(
        default=WebFetchProvider.AUTO,
        description="Preferred fetch provider order.",
    )
    max_content_bytes: int = Field(
        default=512_000, description="Maximum content size to fetch."
    )
    user_agent: str = Field(
        default=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        description="User agent string for raw HTTP fallback requests.",
    )


class WebFetch(
    BaseTool[WebFetchArgs, WebFetchResult, WebFetchConfig, BaseToolState],
    ToolUIData[WebFetchArgs, WebFetchResult],
):
    description: ClassVar[str] = (
        "Fetch content from a URL using Tavily extract first, then raw HTTP fallback."
    )

    async def run(
        self, args: WebFetchArgs, ctx: InvokeContext | None = None
    ) -> AsyncGenerator[ToolStreamEvent | WebFetchResult, None]:
        self._validate_args(args)

        url = self._normalize_url(args.url)
        timeout = self._resolve_timeout(args.timeout)
        errors: list[str] = []

        for provider in self._provider_order():
            match provider:
                case WebFetchProvider.TAVILY:
                    if not (
                        tavily_key := resolve_tavily_api_key(
                            "WEB_FETCH_TAVILY_API_KEY", "WEB_VISIT_TAVILY_API_KEY"
                        )
                    ):
                        continue
                    try:
                        content = await self._fetch_with_tavily(
                            url, timeout, args.prompt, tavily_key
                        )
                        yield WebFetchResult(
                            url=url,
                            provider="tavily",
                            content=content,
                            content_type="text/markdown",
                            prompt=args.prompt,
                        )
                        return
                    except (httpx.HTTPError, ValueError) as exc:
                        errors.append(f"Tavily extract failed: {exc}")
                case WebFetchProvider.HTTP:
                    try:
                        content, content_type = await self._fetch_raw(url, timeout)
                        content = self._prepare_http_content(
                            content,
                            content_type,
                            prompt=args.prompt,
                        )
                        if not content.strip():
                            raise ToolError("Fetched content was empty after extraction")
                        yield WebFetchResult(
                            url=url,
                            provider="http",
                            content=content,
                            content_type=content_type,
                            prompt=args.prompt,
                        )
                        return
                    except ToolError as exc:
                        errors.append(str(exc))

        detail = (
            "; ".join(errors)
            if errors
            else "No web fetch provider is available. Configure TAVILY_API_KEY in /config or use raw HTTP."
        )
        raise ToolError(detail)

    def _validate_args(self, args: WebFetchArgs) -> None:
        if not args.url.strip():
            raise ToolError("URL cannot be empty")

        parsed = urlparse(args.url)
        if parsed.scheme and parsed.scheme not in {"http", "https"}:
            raise ToolError(
                f"Invalid URL scheme: {parsed.scheme}. Must be http or https."
            )

        if args.timeout is not None:
            if args.timeout <= 0:
                raise ToolError("Timeout must be a positive number")
            if args.timeout > self.config.max_timeout:
                raise ToolError(
                    f"Timeout cannot exceed {self.config.max_timeout} seconds"
                )

    def _normalize_url(self, raw_url: str) -> str:
        raw = raw_url.lstrip("/") if raw_url.startswith("//") else raw_url
        return raw if raw.startswith(("http://", "https://")) else "https://" + raw

    def _resolve_timeout(self, timeout: int | None) -> int:
        if timeout is None:
            return self.config.default_timeout
        return min(timeout, self.config.max_timeout)

    def _provider_order(self) -> tuple[WebFetchProvider, ...]:
        match self.config.provider_preference:
            case WebFetchProvider.HTTP:
                return (WebFetchProvider.HTTP, WebFetchProvider.TAVILY)
            case WebFetchProvider.TAVILY | WebFetchProvider.AUTO:
                return (WebFetchProvider.TAVILY, WebFetchProvider.HTTP)

    async def _fetch_with_tavily(
        self, url: str, timeout: int, prompt: str | None, api_key: str
    ) -> str:
        response = await tavily_extract(
            api_key=api_key, url=url, timeout=timeout, prompt=prompt
        )

        results = response.get("results", [])
        if not isinstance(results, list) or not results:
            raise ValueError("Tavily extract returned no results")

        first_result = results[0]
        if not isinstance(first_result, dict):
            raise ValueError("Unexpected Tavily extract payload")

        content = str(
            first_result.get("raw_content")
            or first_result.get("content")
            or first_result.get("markdown")
            or ""
        )
        if not content.strip():
            raise ValueError("Tavily extract returned empty content")
        return self._truncate_content(content)

    async def _fetch_raw(self, url: str, timeout: int) -> tuple[str, str]:
        headers = {
            "User-Agent": self.config.user_agent,
            "Accept": (
                "text/html,application/xhtml+xml,application/xml;q=0.9,"
                "image/avif,image/webp,image/apng,*/*;q=0.8"
            ),
            "Accept-Language": "en-US,en;q=0.9",
        }

        try:
            response = await self._do_fetch(url, timeout, headers)
        except httpx.TimeoutException as exc:
            raise ToolError(f"Request timed out after {timeout} seconds") from exc
        except httpx.RequestError as exc:
            raise ToolError(f"Failed to fetch URL: {exc}") from exc

        if response.is_error:
            raise ToolError(
                f"HTTP error {response.status_code}: {response.reason_phrase}"
            )

        content_type = response.headers.get("Content-Type", "text/plain")
        content = response.content.decode("utf-8", errors="ignore")
        return self._truncate_content(content), content_type

    def _prepare_http_content(
        self,
        content: str,
        content_type: str,
        *,
        prompt: str | None,
    ) -> str:
        prepared = _html_to_markdown(content) if "text/html" in content_type else content
        if prompt:
            prepared = self._focus_content(prepared, prompt)
        return self._truncate_content(prepared)

    async def _do_fetch(
        self, url: str, timeout: int, headers: dict[str, str]
    ) -> httpx.Response:
        async with httpx.AsyncClient(
            follow_redirects=True, timeout=httpx.Timeout(timeout)
        ) as client:
            response = await client.get(url, headers=headers)
            if (
                response.status_code == _HTTP_FORBIDDEN
                and response.headers.get("cf-mitigated") == "challenge"
            ):
                headers["User-Agent"] = _HONEST_USER_AGENT
                response = await client.get(url, headers=headers)
            return response

    def _truncate_content(self, content: str) -> str:
        encoded = content.encode("utf-8")
        if len(encoded) <= self.config.max_content_bytes:
            return content

        truncated = encoded[: self.config.max_content_bytes].decode(
            "utf-8", errors="ignore"
        )
        return truncated + "[Content truncated due to size limit]"

    def _focus_content(self, content: str, prompt: str) -> str:
        keywords = {
            match.group(0).lower() for match in _PROMPT_KEYWORD_RE.finditer(prompt)
        }
        if not keywords:
            return content

        sections = [
            section.strip()
            for section in re.split(r"\n\s*\n", content)
            if section.strip()
        ]
        scored_sections: list[tuple[int, int, str]] = []

        for index, section in enumerate(sections):
            lowered = section.lower()
            score = sum(keyword in lowered for keyword in keywords)
            if score:
                scored_sections.append((score, index, section))

        if not scored_sections:
            return content

        top_sections = sorted(scored_sections, key=lambda item: (-item[0], item[1]))[:5]
        ordered = [
            section for _, _, section in sorted(top_sections, key=lambda item: item[1])
        ]
        return f"Prompt: {prompt}\n\n" + "\n\n".join(ordered)

    @classmethod
    def get_call_display(cls, event: ToolCallEvent) -> ToolCallDisplay:
        if event.args is None or not isinstance(event.args, WebFetchArgs):
            return ToolCallDisplay(summary="webfetch")

        parsed = urlparse(event.args.url)
        domain = parsed.netloc or event.args.url[:50]
        summary = f"Fetching: {domain}"
        if event.args.prompt:
            summary += " (focused)"
        if event.args.timeout:
            summary += f" (timeout {event.args.timeout}s)"
        return ToolCallDisplay(summary=summary)

    @classmethod
    def get_result_display(cls, event: ToolResultEvent) -> ToolResultDisplay:
        if not isinstance(event.result, WebFetchResult):
            return ToolResultDisplay(
                success=False, message=event.error or event.skip_reason or "No result"
            )

        content_len = len(event.result.content)
        message = (
            f"Fetched {content_len:,} chars from {event.result.provider}"
            f" ({event.result.content_type.split(';')[0]})"
        )
        return ToolResultDisplay(success=True, message=message)

    @classmethod
    def get_status_text(cls) -> str:
        return "Fetching URL"


def _html_to_markdown(html: str) -> str:
    return _Converter(heading_style="ATX", bullets="-").convert(html)
