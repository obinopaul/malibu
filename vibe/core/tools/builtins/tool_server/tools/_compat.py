from __future__ import annotations

from pathlib import Path
from typing import Any

from malibu.agent.tools import build_default_tools
from malibu.config import Settings, get_settings

_LEGACY_SETTING_MAP: dict[str, tuple[str, ...]] = {
    "TAVILY_API_KEY": ("web_search_tavily_api_key", "web_visit_tavily_api_key"),
    "FIRECRAWL_API_KEY": (
        "web_search_firecrawl_api_key",
        "web_visit_firecrawl_api_key",
    ),
    "SERPAPI_API_KEY": (
        "web_search_serpapi_api_key",
        "image_search_serpapi_api_key",
    ),
    "JINA_API_KEY": ("web_search_jina_api_key", "web_visit_jina_api_key"),
    "GEMINI_API_KEY": ("web_visit_gemini_api_key",),
    "GOOGLE_AI_STUDIO_API_KEY": (
        "image_generate_google_ai_studio_api_key",
        "video_generate_google_ai_studio_api_key",
    ),
    "GCP_PROJECT_ID": (
        "image_generate_gcp_project_id",
        "video_generate_gcp_project_id",
    ),
    "GCP_LOCATION": (
        "image_generate_gcp_location",
        "video_generate_gcp_location",
    ),
    "GCS_OUTPUT_BUCKET": (
        "image_generate_gcs_output_bucket",
        "video_generate_gcs_output_bucket",
    ),
}


def build_compat_settings(
    settings: Settings | None = None,
    credential: dict[str, Any] | None = None,
) -> Settings:
    """Overlay legacy credential keys onto native Settings."""

    base = settings or get_settings()
    if not credential:
        return base

    updates: dict[str, Any] = {}
    for legacy_key, setting_names in _LEGACY_SETTING_MAP.items():
        value = credential.get(legacy_key)
        if not value:
            continue
        for setting_name in setting_names:
            if not getattr(base, setting_name, None):
                updates[setting_name] = value

    return base.model_copy(update=updates) if updates else base


def build_native_tools(
    workspace_path: str | Path | None = None,
    credential: dict[str, Any] | None = None,
    *,
    settings: Settings | None = None,
    session_id: str | None = None,
) -> list[Any]:
    """Build the native tool bundle with optional legacy credential support."""

    resolved_settings = build_compat_settings(settings=settings, credential=credential)
    resolved_session_id = session_id or (credential or {}).get("session_id")
    cwd = Path(workspace_path or Path.cwd()).resolve()
    return build_default_tools(
        settings=resolved_settings,
        cwd=cwd,
        session_id=resolved_session_id,
        tool_profile="full",
    )


def filter_tools(
    tools: list[Any],
    *,
    names: set[str] | None = None,
    prefixes: tuple[str, ...] = (),
) -> list[Any]:
    """Return a stable, filtered subset of tools."""

    if names is None and not prefixes:
        return list(tools)

    filtered: list[Any] = []
    for tool in tools:
        if names and tool.name in names:
            filtered.append(tool)
            continue
        if prefixes and tool.name.startswith(prefixes):
            filtered.append(tool)
    return filtered
