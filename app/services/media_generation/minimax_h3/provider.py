from app.services.media_generation.config import (
    MediaGenerationProviderConfig,
)
from app.services.media_generation.minimax_h3.client import (
    MiniMaxH3Client,
)
from app.services.media_generation.minimax_h3.mapper import (
    MiniMaxH3RequestMapper,
)
from app.services.media_generation.minimax_h3.response import (
    MiniMaxH3GenerationResponse,
)
from app.services.media_generation.minimax_h3.response_mapper import (
    MiniMaxH3ResponseMapper,
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
    """Provider boundary for MiniMax H3 media generation."""

    def __init__(
        self,
        config: MediaGenerationProviderConfig,
        client: MiniMaxH3Client | None = None,
    ) -> None:
        self._config = config
        self._client = client
        self._mapper = MiniMaxH3RequestMapper()
        self._validator = MiniMaxH3RequestValidator()
        self._response_mapper = MiniMaxH3ResponseMapper()

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

        if self._client is None:
            raise MediaGenerationError(
                "MiniMax H3 provider is not configured for submission yet"
            )

        response = self._client.submit(h3_request)

        return self._response_mapper.map_task(response)

    def get_status(
        self,
        remote_id: str,
    ) -> MediaGenerationTask:
        if self._client is None:
            raise MediaGenerationError(
                "MiniMax H3 provider is not configured for status queries yet"
            )

        response = self._client.get_status(remote_id)

        return self._response_mapper.map_task(response)

    def get_result(
        self,
        remote_id: str,
    ) -> GeneratedMedia:
        if self._client is None:
            raise MediaGenerationError(
                "MiniMax H3 provider is not configured for result retrieval yet"
            )

        response = self._client.get_result(remote_id)

        return self._response_mapper.map_result(response)

    def _map_response(
        self,
        response: MiniMaxH3GenerationResponse,
    ) -> GeneratedMedia:
        return self._response_mapper.map_result(response)
