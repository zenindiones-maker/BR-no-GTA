from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


@dataclass(frozen=True)
class MediaGenerationRequest:
    """Describes a request for generative media."""

    prompt: str
    reference_images: tuple[str, ...] = ()
    reference_videos: tuple[str, ...] = ()
    reference_audio: tuple[str, ...] = ()
    duration_seconds: int | None = None
    aspect_ratio: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.prompt.strip():
            raise ValueError("prompt must be provided")

        if self.duration_seconds is not None:
            if not 4 <= self.duration_seconds <= 15:
                raise ValueError(
                    "duration_seconds must be between 4 and 15 seconds"
                )


class MediaGenerationStatus(StrEnum):
    """Lifecycle status for a media generation task."""

    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(frozen=True)
class MediaGenerationTask:
    """Represents the lifecycle of an asynchronous media generation task."""

    provider: str
    status: MediaGenerationStatus
    remote_id: str | None = None
    output_path: str | None = None
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class GeneratedMedia:
    """Represents the result of a media generation request."""

    provider: str
    status: MediaGenerationStatus
    output_path: str | None = None
    remote_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class MediaGenerationError(RuntimeError):
    """Raised when media generation cannot be completed."""
