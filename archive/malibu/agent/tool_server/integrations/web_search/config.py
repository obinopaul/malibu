from pydantic_settings import BaseSettings, SettingsConfigDict


class WebSearchConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="WEB_SEARCH_",
        env_file=".env",
        extra="ignore",
    )

    firecrawl_api_key: str | None = None
    serpapi_api_key: str | None = None
    jina_api_key: str | None = None
    tavily_api_key: str | None = None

    max_results: int = 5
