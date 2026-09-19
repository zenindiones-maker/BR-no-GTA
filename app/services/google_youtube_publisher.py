from pathlib import Path
from typing import Any

from googleapiclient.http import MediaFileUpload

from app.services.youtube_publisher import (
    YouTubeProcessingStateResult,
    YouTubeUploadResult,
    YouTubeVisibilityResult,
    YouTubeVisibilityStateResult,
)


class GoogleYouTubePublisher:
    """YouTube Data API executor; persistence and publication authority stay above it."""

    def __init__(self, youtube_service: Any) -> None:
        if youtube_service is None:
            raise ValueError("youtube_service is required")
        self.youtube_service = youtube_service

    def upload(self, publication: Any) -> YouTubeUploadResult:
        file_path = publication.get("file_path")
        title = publication.get("title")
        if not file_path:
            return YouTubeUploadResult(success=False, error="YouTube publication requires file_path")
        if not title:
            return YouTubeUploadResult(success=False, error="YouTube publication requires title")
        path = Path(file_path)
        if not path.is_file():
            return YouTubeUploadResult(success=False, error=f"YouTube video file not found: {file_path}")
        body = {
            "snippet": {
                "title": title,
                "description": publication.get("description", ""),
                "tags": publication.get("tags", []),
                "categoryId": publication.get("category_id", "22"),
            },
            "status": {"privacyStatus": "private"},
        }
        try:
            response = self.youtube_service.videos().insert(
                part="snippet,status",
                body=body,
                media_body=MediaFileUpload(str(path), resumable=True),
            ).execute()
            youtube_video_id = response.get("id")
            if not youtube_video_id:
                return YouTubeUploadResult(success=False, error="YouTube API upload response missing video id")
            return YouTubeUploadResult(
                success=True,
                youtube_video_id=youtube_video_id,
                youtube_url=f"https://www.youtube.com/watch?v={youtube_video_id}",
            )
        except Exception as exc:
            return YouTubeUploadResult(success=False, error=str(exc))

    def get_processing_state(self, youtube_video_id: str) -> YouTubeProcessingStateResult:
        if not youtube_video_id:
            return YouTubeProcessingStateResult(success=False, error="youtube_video_id is required")
        try:
            response = self.youtube_service.videos().list(
                part="status,processingDetails,contentDetails",
                id=youtube_video_id,
                maxResults=1,
            ).execute()
            items = response.get("items") if isinstance(response, dict) else None
            if not isinstance(items, list) or len(items) != 1:
                return YouTubeProcessingStateResult(
                    success=False,
                    error="YouTube processing query did not return exactly one video",
                )
            item = items[0] if isinstance(items[0], dict) else {}
            status = item.get("status") if isinstance(item.get("status"), dict) else {}
            processing = item.get("processingDetails") if isinstance(item.get("processingDetails"), dict) else {}
            content = item.get("contentDetails") if isinstance(item.get("contentDetails"), dict) else {}
            return YouTubeProcessingStateResult(
                success=True,
                privacy_status=status.get("privacyStatus"),
                upload_status=status.get("uploadStatus"),
                processing_status=processing.get("processingStatus"),
                definition=content.get("definition"),
            )
        except Exception as exc:
            return YouTubeProcessingStateResult(success=False, error=str(exc))

    def make_public(self, youtube_video_id: str) -> YouTubeVisibilityResult:
        if not youtube_video_id:
            return YouTubeVisibilityResult(success=False, error="youtube_video_id is required")
        try:
            self.youtube_service.videos().update(
                part="status",
                body={"id": youtube_video_id, "status": {"privacyStatus": "public"}},
            ).execute()
            return YouTubeVisibilityResult(success=True)
        except Exception as exc:
            return YouTubeVisibilityResult(success=False, error=str(exc))

    def get_visibility(self, youtube_video_id: str) -> YouTubeVisibilityStateResult:
        """Read remote privacy status without mutating the YouTube video."""
        if not youtube_video_id:
            return YouTubeVisibilityStateResult(success=False, error="youtube_video_id is required")
        try:
            response = self.youtube_service.videos().list(
                part="status",
                id=youtube_video_id,
                maxResults=1,
            ).execute()
            items = response.get("items") if isinstance(response, dict) else None
            if not isinstance(items, list) or len(items) != 1:
                return YouTubeVisibilityStateResult(
                    success=False,
                    error="YouTube visibility query did not return exactly one video",
                )
            status = items[0].get("status") if isinstance(items[0], dict) else None
            privacy = status.get("privacyStatus") if isinstance(status, dict) else None
            if privacy not in {"private", "unlisted", "public"}:
                return YouTubeVisibilityStateResult(
                    success=False,
                    error="YouTube visibility query returned invalid privacy status",
                )
            return YouTubeVisibilityStateResult(success=True, privacy_status=privacy)
        except Exception as exc:
            return YouTubeVisibilityStateResult(success=False, error=str(exc))
