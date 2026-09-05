from pathlib import Path
from typing import Any

from googleapiclient.http import MediaFileUpload

from app.services.youtube_publisher import (
    YouTubeUploadResult,
    YouTubeVisibilityResult,
)


class GoogleYouTubePublisher:
    """
    Implementação real do contrato YouTubePublisher usando
    a YouTube Data API.

    Responsabilidades:
    - fazer upload de vídeos;
    - alterar visibilidade de vídeos já existentes.

    Não é responsabilidade desta classe:
    - persistir SQLite;
    - decidir o ciclo de vida da publicação;
    - executar OAuth;
    - decidir quando um vídeo deve ser publicado.
    """

    def __init__(self, youtube_service: Any) -> None:
        if youtube_service is None:
            raise ValueError("youtube_service is required")

        self.youtube_service = youtube_service

    def upload(
        self,
        publication: Any,
    ) -> YouTubeUploadResult:
        file_path = publication.get("file_path")
        title = publication.get("title")

        if not file_path:
            return YouTubeUploadResult(
                success=False,
                error="YouTube publication requires file_path",
            )

        if not title:
            return YouTubeUploadResult(
                success=False,
                error="YouTube publication requires title",
            )

        path = Path(file_path)

        if not path.is_file():
            return YouTubeUploadResult(
                success=False,
                error=f"YouTube video file not found: {file_path}",
            )

        description = publication.get("description", "")
        tags = publication.get("tags", [])
        category_id = publication.get("category_id", "22")

        body = {
            "snippet": {
                "title": title,
                "description": description,
                "tags": tags,
                "categoryId": category_id,
            },
            "status": {
                "privacyStatus": "private",
            },
        }

        try:
            media_body = MediaFileUpload(
                str(path),
                resumable=True,
            )

            request = self.youtube_service.videos().insert(
                part="snippet,status",
                body=body,
                media_body=media_body,
            )

            response = request.execute()

            youtube_video_id = response.get("id")

            if not youtube_video_id:
                return YouTubeUploadResult(
                    success=False,
                    error="YouTube API upload response missing video id",
                )

            return YouTubeUploadResult(
                success=True,
                youtube_video_id=youtube_video_id,
                youtube_url=(
                    f"https://www.youtube.com/watch?v={youtube_video_id}"
                ),
            )

        except Exception as exc:
            return YouTubeUploadResult(
                success=False,
                error=str(exc),
            )

    def make_public(
        self,
        youtube_video_id: str,
    ) -> YouTubeVisibilityResult:
        if not youtube_video_id:
            return YouTubeVisibilityResult(
                success=False,
                error="youtube_video_id is required",
            )

        try:
            self.youtube_service.videos().update(
                part="status",
                body={
                    "id": youtube_video_id,
                    "status": {
                        "privacyStatus": "public",
                    },
                },
            ).execute()

            return YouTubeVisibilityResult(
                success=True,
            )

        except Exception as exc:
            return YouTubeVisibilityResult(
                success=False,
                error=str(exc),
            )
