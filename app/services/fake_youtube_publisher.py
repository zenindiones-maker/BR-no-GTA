from typing import Any

from app.services.youtube_publisher import YouTubePublishResult


class FakeYouTubePublisher:
    """
    Publisher determinístico para testes.

    Não executa:
    - OAuth;
    - Google API;
    - rede;
    - upload;
    - filesystem.

    Apenas simula o resultado de uma publicação e registra
    a Publication recebida.
    """

    def __init__(
        self,
        *,
        success: bool,
        youtube_video_id: str | None = None,
        youtube_url: str | None = None,
        error: str | None = None,
    ) -> None:
        self.success = success
        self.youtube_video_id = youtube_video_id
        self.youtube_url = youtube_url
        self.error = error

        self.published_publication: Any | None = None
        self.published_publications: list[Any] = []

    def publish(
        self,
        publication: Any,
    ) -> YouTubePublishResult:
        self.published_publication = publication
        self.published_publications.append(publication)

        if not self.success:
            return YouTubePublishResult(
                success=False,
                error=self.error or "Falha simulada no Publisher.",
            )

        return YouTubePublishResult(
            success=True,
            youtube_video_id=self.youtube_video_id,
            youtube_url=self.youtube_url,
            error=None,
        )
