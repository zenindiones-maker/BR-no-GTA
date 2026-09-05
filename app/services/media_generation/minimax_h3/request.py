from dataclasses import dataclass


@dataclass(frozen=True)
class MiniMaxH3GenerationRequest:
    """Provider-specific request mapped from the BR media request."""

    prompt: str
    duration_seconds: int | None = None
    aspect_ratio: str | None = None
    reference_images: tuple[str, ...] = ()
    reference_videos: tuple[str, ...] = ()
    reference_audio: tuple[str, ...] = ()
