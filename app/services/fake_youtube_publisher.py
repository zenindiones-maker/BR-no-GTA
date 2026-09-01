from typing import Any

from app.services.youtube_publisher import YouTubePublishResult


class FakeYouTubePublisher:
    """
    Implementação determinística do contrato YouTubePublisher.

    Não acessa Google, navegador, rede ou filesystem.
    Serve para testar a camada de publicação internamente.
    """

    def __init__(
        self,
        *,
        success: bool = True,
        youtube_video_id: str = "fake-youtube-video-id",
        youtube_url: str | None = None,
        error: str | None = None,
    ) -> None:
        self.success = success
        self.youtube_video_id = youtube_video_id
        self.youtube_url = (
            youtube_url
            if youtube_url is not None
            else (
                "https://www.youtube.com/watch?v="
                f"{youtube_video_id}"
            )
        )
        self.error = error
        self.published_publication = None
        self.published_publications = []

    def publish(self, publication: Any) -> YouTubePublishResult:
        """
        Simula uma publicação no YouTube.

        Sem erro configurado e com success=True, retorna sucesso.
        Com success=False ou erro configurado, retorna falha.
        """
        self.published_publication = publication
        self.published_publications.append(publication)

        if not self.success or self.error is not None:
            return YouTubePublishResult(
                success=False,
                error=self.error,
            )

        return YouTubePublishResult(
            success=True,
            youtube_video_id=self.youtube_video_id,
            youtube_url=self.youtube_url,
        )
