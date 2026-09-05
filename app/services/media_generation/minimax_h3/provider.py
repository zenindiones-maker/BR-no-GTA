from app.services.media_generation.config import (
    MediaGenerationProviderConfig,
)
from app.services.media_generation.models import (
    GeneratedMedia,
    MediaGenerationError,
    MediaGenerationRequest,
)


class MiniMaxH3Provider:
    """Provider boundary for MiniMax H3 media generation.

    The initial implementation intentionally contains no model runtime,
    network client, GPU dependency, or checkpoint loading.
    """

    def __init__(
        self,
        config: MediaGenerationProviderConfig,
    ) -> None:
        self._config = config

    @property
    def name(self) -> str:
        return self._config.provider

    @property
    def config(self) -> MediaGenerationProviderConfig:
        return self._config

    def generate(
        self,
        request: MediaGenerationRequest,
    ) -> GeneratedMedia:
        raise MediaGenerationError(
            "MiniMax H3 provider is not configured for generation yet"
        )
