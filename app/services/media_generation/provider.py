from typing import Protocol

from app.services.media_generation.models import (
    GeneratedMedia,
    MediaGenerationRequest,
    MediaGenerationTask,
)


class MediaGenerationProvider(Protocol):
    """Contract implemented by asynchronous media generation providers."""

    @property
    def name(self) -> str:
        """Return the provider identifier."""

    def submit(
        self,
        request: MediaGenerationRequest,
    ) -> MediaGenerationTask:
        """Submit a generation request and return its remote task."""

    def get_status(
        self,
        remote_id: str,
    ) -> MediaGenerationTask:
        """Return the current state of a remote generation task."""

    def get_result(
        self,
        remote_id: str,
    ) -> GeneratedMedia:
        """Return the completed generated media artifact."""
