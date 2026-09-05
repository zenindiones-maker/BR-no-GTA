from typing import Any

from app.services.youtube_publisher import (
    YouTubeUploadResult,
    YouTubeVisibilityResult,
)


class FakeYouTubePublisher:
    """
    Publisher determinístico para testes.

    Não executa:
    - OAuth;
    - Google API;
    - rede;
    - upload real;
    - alteração real de visibilidade.

    Simula separadamente:
    - upload;
    - tornar público.
    """

    def __init__(
        self,
        *,
        upload_success: bool | None = None,
        upload_video_id: str | None = None,
        upload_url: str | None = None,
        upload_error: str | None = None,
        visibility_success: bool = True,
        visibility_error: str | None = None,
    ) -> None:
        if upload_success is None:
            upload_success = upload_error is None

        self.upload_success = upload_success
        self.upload_video_id = upload_video_id
        self.upload_url = upload_url
        self.upload_error = upload_error

        self.visibility_success = visibility_success
        self.visibility_error = visibility_error

        self.uploaded_publication: Any | None = None
        self.uploaded_publications: list[Any] = []

        self.made_public_video_ids: list[str] = []

    def upload(
        self,
        publication: Any,
    ) -> YouTubeUploadResult:
        self.uploaded_publication = publication
        self.uploaded_publications.append(publication)

        if not self.upload_success:
            return YouTubeUploadResult(
                success=False,
                error=self.upload_error or "Falha simulada no upload.",
            )

        return YouTubeUploadResult(
            success=True,
            youtube_video_id=self.upload_video_id,
            youtube_url=self.upload_url,
            error=None,
        )

    def make_public(
        self,
        youtube_video_id: str,
    ) -> YouTubeVisibilityResult:
        if not self.visibility_success:
            return YouTubeVisibilityResult(
                success=False,
                error=(
                    self.visibility_error
                    or "Falha simulada ao tornar vídeo público."
                ),
            )

        self.made_public_video_ids.append(youtube_video_id)

        return YouTubeVisibilityResult(
            success=True,
            error=None,
        )
