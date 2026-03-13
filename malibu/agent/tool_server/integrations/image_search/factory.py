from .base import BaseImageSearchClient
from .config import ImageSearchConfig


def create_image_search_client(settings: ImageSearchConfig) -> BaseImageSearchClient:
    """
    Factory function that creates an image search client based on available API keys.

    Args:
        settings: Settings object containing API keys

    Returns:
        BaseImageSearchClient: An instance of an image search client, or None if no API key is available
    """
    serpapi_key = settings.serpapi_api_key

    if serpapi_key:
        from .serpapi import SerpAPIImageSearchClient

        return SerpAPIImageSearchClient(api_key=serpapi_key)

    from .duckduckgo import DuckDuckGoImageSearchClient

    return DuckDuckGoImageSearchClient()
