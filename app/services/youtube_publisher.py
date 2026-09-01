from dataclasses import dataclass
from typing import Protocol, Any


@dataclass(frozen=True)
class YouTubePublishResult:
    """
    Resultado explícito de uma tentativa de publicação no YouTube.
    """

    success: bool
    youtube_video_id: str | None = None
    youtube_url: str | None = None
    error: str | None = None


# Compatibilidade com o nome inicialmente introduzido pelo Publisher.
PublishResult = YouTubePublishResult


class YouTubePublisher(Protocol):
    """
    Contrato para qualquer implementação de publicação no YouTube.

    A camada superior conhece apenas este contrato.
    A implementação concreta pode ser fake, Google API etc.
    """

    def publish(
        self,
        publication: Any,
    ) -> YouTubePublishResult:
        """
        Publica uma YouTubePublication e retorna o resultado da operação.
        """
        ...
