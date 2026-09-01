from typing import Any

from app.services.youtube_publisher import (
    YouTubePublishResult,
)


class FakeYouTubePublisher:
    """
    Implementação fake do contrato YouTubePublisher.

    Não acessa internet nem APIs externas.
    Serve para testar o fluxo de publicação de ponta a ponta.
    """

    def __init__(
        self,
        *,
        success: bool = True,
        youtube_video_id: str = "fake-youtube-video-id",
        error: str = "fake publication failed",
    ) -> None:
        self.success = success
        self.youtube_video_id = youtube_video_id
        self.error = error
        self.published_publications: list[dict[str, Any]] = []

    def publish(
        self,
        publication: dict[str, Any],
    ) -> YouTubePublishResult:
        """
        Simula uma tentativa de publicação.

        Em caso de sucesso, registra a publication e devolve
        um resultado equivalente ao que o publisher real deverá devolver.

        Em caso de falha, devolve apenas o erro simulado.
        """

        if not isinstance(publication, dict):
            raise TypeError("publication must be a dict")

        if self.success:
            self.published_publications.append(publication)

            return YouTubePublishResult(
                success=True,
                youtube_video_id=self.youtube_video_id,
                youtube_url=(
                    f"https://www.youtube.com/watch?v="
                    f"{self.youtube_video_id}"
                ),
            )

        return YouTubePublishResult(
            success=False,
            error=self.error,
        )
