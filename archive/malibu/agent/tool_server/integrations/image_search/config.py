from pydantic_settings import BaseSettings, SettingsConfigDict


class ImageSearchConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="IMAGE_SEARCH_",
        env_file=".env",
        extra="ignore",
    )

    serpapi_api_key: str | None = None

    max_results: int = 5
