from pathlib import Path
from typing import Any

from googleapiclient.http import MediaFileUpload

from app.services.youtube_publisher import (
    YouTubePublishResult,
)


class GoogleYouTubePublisher:
    """
    Implementação real do contrato YouTubePublisher.

    Esta classe não autentica no Google.
    Recebe um cliente autenticado da API por injeção.

    OAuth será implementado separadamente.
    """

    def __init__(
        self,
        *,
        youtube_service: Any,
    ) -> None:
        self.youtube_service = youtube_service

    def publish(
        self,
        publication: dict[str, Any],
    ) -> YouTubePublishResult:
        """
        Executa o upload de uma publicação para o YouTube.

        Responsabilidades:
        - validar a publicação;
        - validar o arquivo;
        - montar os metadados;
        - chamar videos.insert();
        - transformar a resposta em YouTubePublishResult.

        Não persiste no SQLite.
        Não executa OAuth.
        """

        if not isinstance(publication, dict):
            raise TypeError("publication must be a dict")

        file_path = publication.get("file_path")

        if not isinstance(file_path, str) or not file_path.strip():
            return YouTubePublishResult(
                success=False,
                error="publication file_path is required",
            )

        path = Path(file_path)

        if not path.is_file():
            return YouTubePublishResult(
                success=False,
                error=f"video file not found: {file_path}",
            )

        title = publication.get("title")

        if not isinstance(title, str) or not title.strip():
            return YouTubePublishResult(
                success=False,
                error="publication title is required",
            )

        description = publication.get("description", "")
        tags = publication.get("tags", [])
        category_id = publication.get("category_id", "20")
        privacy_status = publication.get(
            "privacy_status",
            "private",
        )
        publish_at = publication.get("publish_at")

        body: dict[str, Any] = {
            "snippet": {
                "title": title,
                "description": description,
                "tags": tags,
                "categoryId": category_id,
            },
            "status": {
                "privacyStatus": privacy_status,
            },
        }

        if publish_at is not None:
            body["status"]["publishAt"] = publish_at

        try:
            media_body = MediaFileUpload(
                str(path),
                chunksize=-1,
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
                return YouTubePublishResult(
                    success=False,
                    error=(
                        "YouTube API response did not "
                        "contain video id"
                    ),
                )

            youtube_url = (
                "https://www.youtube.com/watch?v="
                f"{youtube_video_id}"
            )

            return YouTubePublishResult(
                success=True,
                youtube_video_id=youtube_video_id,
                youtube_url=youtube_url,
            )

        except Exception as exc:
            return YouTubePublishResult(
                success=False,
                error=str(exc),
            )
