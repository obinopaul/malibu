from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from malibu.agent.tool_server.core.workspace import WorkspaceManager
from malibu.agent.tool_server.tools.shell.terminal_manager import (
    LocalShellSessionManager,
)
from malibu.config import Settings


@dataclass(slots=True)
class ToolRuntime:
    """Session-scoped runtime shared by all native LangChain tools."""

    settings: Settings
    cwd: Path | str
    session_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    todo_state: list[dict[str, str]] = field(default_factory=list)

    workspace_root: Path = field(init=False)
    workspace_manager: WorkspaceManager = field(init=False)
    shell_manager: LocalShellSessionManager = field(init=False)

    _browser: Any = field(default=None, init=False, repr=False)
    _web_search_client: Any = field(default=None, init=False, repr=False)
    _image_search_client: Any = field(default=None, init=False, repr=False)
    _image_generation_client: Any = field(default=None, init=False, repr=False)
    _video_generation_client: Any = field(default=None, init=False, repr=False)
    _web_visit_service: Any = field(default=None, init=False, repr=False)
    _llm_client: Any = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        self.workspace_root = Path(self.cwd).resolve()
        self.workspace_manager = WorkspaceManager(self.workspace_root)
        self.shell_manager = LocalShellSessionManager()

    @property
    def browser(self) -> Any:
        if self._browser is None:
            from malibu.agent.tool_server.browser.browser import Browser

            self._browser = Browser()
        return self._browser

    @property
    def web_search_client(self) -> Any:
        if self._web_search_client is None:
            from malibu.agent.tool_server.integrations.web_search.config import (
                WebSearchConfig,
            )
            from malibu.agent.tool_server.integrations.web_search.factory import (
                create_web_search_client,
            )

            self._web_search_client = create_web_search_client(
                WebSearchConfig(
                    firecrawl_api_key=self.settings.web_search_firecrawl_api_key,
                    serpapi_api_key=self.settings.web_search_serpapi_api_key,
                    jina_api_key=self.settings.web_search_jina_api_key,
                    tavily_api_key=self.settings.web_search_tavily_api_key,
                    max_results=self.settings.web_search_max_results,
                )
            )
        return self._web_search_client

    @property
    def image_search_client(self) -> Any:
        if self._image_search_client is None:
            from malibu.agent.tool_server.integrations.image_search.config import (
                ImageSearchConfig,
            )
            from malibu.agent.tool_server.integrations.image_search.factory import (
                create_image_search_client,
            )

            self._image_search_client = create_image_search_client(
                ImageSearchConfig(
                    serpapi_api_key=self.settings.image_search_serpapi_api_key,
                    max_results=self.settings.image_search_max_results,
                )
            )
        return self._image_search_client

    @property
    def image_generation_client(self) -> Any:
        if self._image_generation_client is None:
            from malibu.agent.tool_server.integrations.image_generation.config import (
                ImageGenerateConfig,
            )
            from malibu.agent.tool_server.integrations.image_generation.factory import (
                create_image_generation_client,
            )

            self._image_generation_client = create_image_generation_client(
                ImageGenerateConfig(
                    gcp_project_id=self.settings.image_generate_gcp_project_id,
                    gcp_location=self.settings.image_generate_gcp_location,
                    gcs_output_bucket=self.settings.image_generate_gcs_output_bucket,
                    google_ai_studio_api_key=self.settings.image_generate_google_ai_studio_api_key,
                )
            )
        return self._image_generation_client

    @property
    def video_generation_client(self) -> Any:
        if self._video_generation_client is None:
            from malibu.agent.tool_server.integrations.video_generation.config import (
                VideoGenerateConfig,
            )
            from malibu.agent.tool_server.integrations.video_generation.factory import (
                create_video_generation_client,
            )

            self._video_generation_client = create_video_generation_client(
                VideoGenerateConfig(
                    gcp_project_id=self.settings.video_generate_gcp_project_id,
                    gcp_location=self.settings.video_generate_gcp_location,
                    gcs_output_bucket=self.settings.video_generate_gcs_output_bucket,
                    google_ai_studio_api_key=self.settings.video_generate_google_ai_studio_api_key,
                )
            )
        return self._video_generation_client

    @property
    def llm_client(self) -> Any:
        if self._llm_client is not None:
            return self._llm_client

        model_name = self.settings.llm_model
        provider = "openai"
        if ":" in model_name:
            provider, model_name = model_name.split(":", 1)

        if provider not in {"openai", ""} and not self.settings.llm_base_url:
            self._llm_client = None
            return None
        if not self.settings.llm_api_key:
            self._llm_client = None
            return None

        from malibu.agent.tool_server.integrations.llm.client import LLMClient
        from malibu.agent.tool_server.integrations.llm.config import LLMConfig

        self._llm_client = LLMClient(
            LLMConfig(
                openai_api_key=self.settings.llm_api_key,
                openai_base_url=self.settings.llm_base_url,
                openai_model=model_name,
            )
        )
        return self._llm_client

    @property
    def web_visit_service(self) -> Any:
        if self._web_visit_service is None:
            from malibu.agent.tool_server.integrations.web_visit.config import (
                CompressorConfig,
                WebVisitConfig,
            )
            from malibu.agent.tool_server.integrations.web_visit.factory import (
                create_all_web_visit_clients,
                create_web_visit_client,
            )
            from malibu.agent.tool_server.integrations.web_visit.service import (
                WebVisitService,
            )

            visit_config = WebVisitConfig(
                firecrawl_api_key=self.settings.web_visit_firecrawl_api_key,
                gemini_api_key=self.settings.web_visit_gemini_api_key,
                jina_api_key=self.settings.web_visit_jina_api_key,
                tavily_api_key=self.settings.web_visit_tavily_api_key,
                max_output_length=self.settings.web_visit_max_output_length,
            )
            compressor_config = CompressorConfig()
            self._web_visit_service = WebVisitService(
                web_visit_clients=create_all_web_visit_clients(
                    visit_config,
                    compressor_config,
                ),
                researcher_visit_client=create_web_visit_client(
                    visit_config,
                    compressor_config,
                ),
                llm_client=self.llm_client,
            )
        return self._web_visit_service
