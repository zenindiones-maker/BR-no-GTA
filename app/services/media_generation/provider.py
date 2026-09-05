from typing import Protocol

from app.services.media_generation.models import (
    GeneratedMedia,
    MediaGenerationRequest,
)


class MediaGenerationProvider(Protocol):
    """Contract implemented by media generation providers."""

    @property
    def name(self) -> str:
        """Return the provider identifier."""

    def generate(
        self,
        request: MediaGenerationRequest,
    ) -> GeneratedMedia:
        """Generate media for the given request."""
