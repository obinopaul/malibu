from __future__ import annotations

from collections.abc import Sequence
import os
from typing import Any

import httpx

TAVILY_API_BASE = "https://api.tavily.com"


def resolve_tavily_api_key(*preferred_env_vars: str) -> str | None:
    for env_var in (*preferred_env_vars, "TAVILY_API_KEY"):
        if value := os.getenv(env_var):
            return value
    return None


async def tavily_search(
    *, api_key: str, query: str, max_results: int, timeout: int
) -> dict[str, Any]:
    payload = {
        "query": query,
        "search_depth": "advanced",
        "max_results": max_results,
        "include_answer": "advanced",
        "include_raw_content": False,
        "include_favicon": True,
        "topic": "general",
    }
    return await _post_tavily(
        endpoint="/search", api_key=api_key, timeout=timeout, payload=payload
    )


async def tavily_extract(
    *, api_key: str, url: str, timeout: int, prompt: str | None = None
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "urls": [url],
        "extract_depth": "advanced",
        "format": "markdown",
        "include_favicon": True,
        "timeout": float(timeout),
    }
    if prompt:
        payload["query"] = prompt
        payload["chunks_per_source"] = 5

    return await _post_tavily(
        endpoint="/extract", api_key=api_key, timeout=timeout, payload=payload
    )


def ddgs_is_available() -> bool:
    try:
        from ddgs import DDGS
    except ImportError:
        return False
    _ = DDGS
    return True


async def ddgs_text_search(
    *, query: str, max_results: int, timeout: int
) -> list[dict[str, Any]]:
    from ddgs import DDGS

    def _search() -> list[dict[str, Any]]:
        client = DDGS(timeout=timeout)
        return list(client.text(query, max_results=max_results))

    import anyio

    return await anyio.to_thread.run_sync(_search)


async def _post_tavily(
    *, endpoint: str, api_key: str, timeout: int, payload: dict[str, Any]
) -> dict[str, Any]:
    async with httpx.AsyncClient(
        base_url=TAVILY_API_BASE, timeout=httpx.Timeout(timeout)
    ) as client:
        response = await client.post(
            endpoint,
            json=payload,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
        )
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        raise ValueError("Unexpected Tavily response payload")
    return data


def first_non_empty(values: Sequence[str | None]) -> str | None:
    for value in values:
        if value:
            return value
    return None
