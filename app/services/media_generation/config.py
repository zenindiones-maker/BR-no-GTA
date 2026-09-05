"""Configuration contracts for media generation providers."""

from dataclasses import dataclass


@dataclass(frozen=True)
class MediaGenerationProviderConfig:
    """Configuration required to initialize a media generation provider."""

    provider: str
    api_key: str | None = None
    endpoint: str | None = None
    model: str | None = None

    def __post_init__(self) -> None:
        if not self.provider.strip():
            raise ValueError("provider must be provided")
