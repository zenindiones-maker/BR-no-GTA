from app.services.media_generation.models import (
    GeneratedMedia,
    MediaGenerationRequest,
    MediaGenerationTask,
)
from app.services.media_generation.provider import MediaGenerationProvider


class MediaGenerationService:
    """Coordinates asynchronous media generation through a provider."""

    def __init__(self, provider: MediaGenerationProvider) -> None:
        self._provider = provider

    @property
    def provider_name(self) -> str:
        return self._provider.name

    def submit(
        self,
        request: MediaGenerationRequest,
    ) -> MediaGenerationTask:
        return self._provider.submit(request)

    def get_status(
        self,
        remote_id: str,
    ) -> MediaGenerationTask:
        return self._provider.get_status(remote_id)

    def get_result(
        self,
        remote_id: str,
    ) -> GeneratedMedia:
        return self._provider.get_result(remote_id)
