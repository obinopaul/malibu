from .config import VideoGenerateConfig
from .base import BaseVideoGenerationClient


def create_video_generation_client(settings: VideoGenerateConfig) -> BaseVideoGenerationClient:
    """
    Factory function that creates a video generation client based on available configuration.
    """
    if (
        settings.gcp_project_id
        and settings.gcp_location
        and settings.gcs_output_bucket
    ):
        from .vertex import VertexVideoGenerationClient

        return VertexVideoGenerationClient(
            project_id=settings.gcp_project_id,
            location=settings.gcp_location,
            output_bucket=settings.gcs_output_bucket,
        )

    from .duckduckgo import DuckDuckGoVideoGenerationClient

    return DuckDuckGoVideoGenerationClient()
