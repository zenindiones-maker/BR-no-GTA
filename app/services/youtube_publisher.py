from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class YouTubePublishResult:
    """
    Resultado de uma tentativa de publicação no YouTube.
    """

    success: bool
    youtube_video_id: str | None = None
    youtube_url: str | None = None
    error: str | None = None


class YouTubePublisher(Protocol):
    """
    Contrato para qualquer mecanismo de publicação no YouTube.
    """

    def publish(
        self,
        publication: dict[str, Any],
    ) -> YouTubePublishResult:
        ...
