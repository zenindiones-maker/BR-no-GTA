from app.services.media_generation.config import (
    MediaGenerationProviderConfig,
)
from app.services.media_generation.minimax_h3.mapper import (
    MiniMaxH3RequestMapper,
)
from app.services.media_generation.minimax_h3.validation import (
    MiniMaxH3RequestValidator,
)
from app.services.media_generation.models import (
    GeneratedMedia,
    MediaGenerationError,
    MediaGenerationRequest,
    MediaGenerationTask,
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
        self._mapper = MiniMaxH3RequestMapper()
        self._validator = MiniMaxH3RequestValidator()

    @property
    def name(self) -> str:
        return self._config.provider

    @property
    def config(self) -> MediaGenerationProviderConfig:
        return self._config

    def submit(
        self,
        request: MediaGenerationRequest,
    ) -> MediaGenerationTask:
        h3_request = self._mapper.map(request)
        self._validator.validate(h3_request)

        raise MediaGenerationError(
            "MiniMax H3 provider is not configured for submission yet"
        )

    def get_status(
        self,
        remote_id: str,
    ) -> MediaGenerationTask:
        raise MediaGenerationError(
            "MiniMax H3 provider is not configured for status queries yet"
        )

    def get_result(
        self,
        remote_id: str,
    ) -> GeneratedMedia:
        raise MediaGenerationError(
            "MiniMax H3 provider is not configured for result retrieval yet"
        )
