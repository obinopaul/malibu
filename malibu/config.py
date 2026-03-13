"""Environment-driven configuration via Pydantic BaseSettings.

All settings can be overridden via environment variables or a .env file.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from langchain_core.language_models import BaseChatModel
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central configuration for the Malibu harness."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Database ──────────────────────────────────────────────────
    database_url: str = "postgresql+asyncpg://malibu:malibu@localhost:5432/malibu"

    # ── LLM ───────────────────────────────────────────────────────
    # Model string in LangChain format: "provider:model-name"
    # Examples: "openai:gpt-4o", "anthropic:claude-sonnet-4-5"
    # Or just the model name to use with a custom base_url.
    llm_model: str = "openai:gpt-5.4"
    llm_api_key: str = ""
    llm_base_url: str | None = None

    # ── Authentication ────────────────────────────────────────────
    jwt_secret: str = "change-me-to-a-random-64-char-string"
    jwt_algorithm: str = "HS256"
    jwt_expiry_hours: int = 24

    # ── Server ────────────────────────────────────────────────────
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    stdio_buffer_limit_bytes: int = 50 * 1024 * 1024  # 50 MB

    # ── Security ──────────────────────────────────────────────────
    allowed_paths: list[str] = Field(default_factory=list)
    max_file_size: int = 10 * 1024 * 1024  # 10 MB

    # ── Unstable Protocol ─────────────────────────────────────────
    enable_unstable_protocol: bool = True

    # ── TUI ────────────────────────────────────────────────────────
    tui_theme: str = "dark"
    tui_unicode: bool = True
    tui_show_welcome: bool = True

    # ── Tool Providers ─────────────────────────────────────────────
    web_search_firecrawl_api_key: str | None = None
    web_search_serpapi_api_key: str | None = None
    web_search_jina_api_key: str | None = None
    web_search_tavily_api_key: str | None = None
    web_search_max_results: int = 5

    web_visit_firecrawl_api_key: str | None = None
    web_visit_gemini_api_key: str | None = None
    web_visit_jina_api_key: str | None = None
    web_visit_tavily_api_key: str | None = None
    web_visit_max_output_length: int = 40_000

    image_search_serpapi_api_key: str | None = None
    image_search_max_results: int = 5

    image_generate_gcp_project_id: str | None = None
    image_generate_gcp_location: str | None = None
    image_generate_gcs_output_bucket: str | None = None
    image_generate_google_ai_studio_api_key: str | None = None

    video_generate_gcp_project_id: str | None = None
    video_generate_gcp_location: str | None = None
    video_generate_gcs_output_bucket: str | None = None
    video_generate_google_ai_studio_api_key: str | None = None

    # ── Skills ─────────────────────────────────────────────────────
    skills_paths: list[str] = Field(default_factory=list)
    skills_enabled: bool = True

    # ── MCP ────────────────────────────────────────────────────────
    mcp_config_paths: list[str] = Field(default_factory=list)

    # ── Subsystem toggles ──────────────────────────────────────────
    hooks_enabled: bool = True
    cost_tracking_enabled: bool = True
    git_tools_enabled: bool = True
    dangerous_command_warn: bool = True

    def resolve_allowed_paths(self, cwd: str) -> list[Path]:
        """Return resolved allowed paths, defaulting to session cwd."""
        if self.allowed_paths:
            return [Path(p).resolve() for p in self.allowed_paths]
        return [Path(cwd).resolve()]

    def create_llm(self) -> BaseChatModel:
        """Instantiate the chat model from the model string.

        Supports model strings like "openai:gpt-4o" or "anthropic:claude-sonnet-4-5".
        If no provider prefix, defaults to OpenAI-compatible with optional base_url.
        """
        model_str = self.llm_model
        if ":" in model_str:
            provider, model_name = model_str.split(":", 1)
        else:
            provider, model_name = "openai", model_str

        provider = provider.lower()
        if provider == "anthropic":
            from langchain_anthropic import ChatAnthropic

            kwargs: dict = {"model": model_name, "max_tokens": 8192}
            if self.llm_api_key:
                kwargs["api_key"] = self.llm_api_key
            return ChatAnthropic(**kwargs)
        else:
            from langchain_openai import ChatOpenAI

            kwargs = {"model": model_name}
            if self.llm_api_key:
                kwargs["api_key"] = self.llm_api_key
            if self.llm_base_url:
                kwargs["base_url"] = self.llm_base_url
            return ChatOpenAI(**kwargs)


def get_settings() -> Settings:
    """Create a Settings instance (reads .env on first call)."""
    return Settings()
