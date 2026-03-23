from .config import ImageGenerateConfig
from .base import BaseImageGenerationClient


def create_image_generation_client(settings: ImageGenerateConfig) -> BaseImageGenerationClient:
    """Factory function that creates an image generation client based on available configuration."""
    if (
        settings.gcp_project_id
        and settings.gcp_location
        and settings.gcs_output_bucket
    ):
        from .vertex import VertexImageGenerationClient

        return VertexImageGenerationClient(
            project_id=settings.gcp_project_id,
            location=settings.gcp_location,
            output_bucket=settings.gcs_output_bucket,
        )

    from .duckduckgo import DuckDuckGoImageGenerationClient

    return DuckDuckGoImageGenerationClient()
