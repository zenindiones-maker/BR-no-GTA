from app.services.media_generation.models import (
    GeneratedMedia,
    MediaGenerationRequest,
)
from app.services.media_generation.provider import MediaGenerationProvider


class MediaGenerationService:
    """Coordinates media generation through a provider."""

    def __init__(self, provider: MediaGenerationProvider) -> None:
        self._provider = provider

    @property
    def provider_name(self) -> str:
        return self._provider.name

    def generate(
        self,
        request: MediaGenerationRequest,
    ) -> GeneratedMedia:
        return self._provider.generate(request)
