"""Load media generation provider configuration from the environment."""

import os

from app.services.media_generation.config import (
    MediaGenerationProviderConfig,
)


def load_media_generation_provider_config(
    provider: str,
) -> MediaGenerationProviderConfig:
    """Build provider configuration from environment variables."""

    prefix = provider.upper().replace("-", "_")

    return MediaGenerationProviderConfig(
        provider=provider,
        api_key=os.getenv(f"{prefix}_API_KEY"),
        endpoint=os.getenv(f"{prefix}_ENDPOINT"),
        model=os.getenv(f"{prefix}_MODEL"),
    )
