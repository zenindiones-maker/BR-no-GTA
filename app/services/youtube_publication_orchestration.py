from typing import Any

from app.database.youtube_repository import (
    get_youtube_publication,
    mark_youtube_uploaded,
    mark_youtube_published,
    mark_youtube_visibility_failed,
    update_youtube_publication_status,
)
from app.services.youtube_publisher import (
    YouTubeUploadResult,
    YouTubeVisibilityResult,
    YouTubePublisher,
)


def upload_youtube_publication(
    publication_id: int,
    publisher: YouTubePublisher,
) -> dict[str, Any]:
    publication = get_youtube_publication(publication_id)

    if publication is None:
        raise ValueError(
            f"YouTube publication not found: {publication_id}"
        )

    if publication["status"] != "pending":
        raise ValueError(
            "YouTube publication is not pending: "
            f"{publication_id}"
        )

    result = publisher.upload(publication)

    if not isinstance(result, YouTubeUploadResult):
        raise TypeError(
            "publisher.upload() must return YouTubeUploadResult"
        )

    if result.success:
        if not result.youtube_video_id:
            raise ValueError(
                "Successful upload must provide youtube_video_id"
            )

        if not result.youtube_url:
            raise ValueError(
                "Successful upload must provide youtube_url"
            )

        updated = mark_youtube_uploaded(
            publication_id,
            result.youtube_video_id,
            result.youtube_url,
        )

        if not updated:
            raise RuntimeError(
                "Failed to persist YouTube upload success: "
                f"{publication_id}"
            )

    else:
        error = result.error or "YouTube upload failed"

        updated = update_youtube_publication_status(
            publication_id,
            "failed",
            error=error,
        )

        if not updated:
            raise RuntimeError(
                "Failed to persist YouTube upload failure: "
                f"{publication_id}"
            )

    persisted_publication = get_youtube_publication(publication_id)

    if persisted_publication is None:
        raise RuntimeError(
            "YouTube publication disappeared after upload: "
            f"{publication_id}"
        )

    return persisted_publication


def make_youtube_publication_public(
    publication_id: int,
    publisher: YouTubePublisher,
) -> dict[str, Any]:
    publication = get_youtube_publication(publication_id)

    if publication is None:
        raise ValueError(
            f"YouTube publication not found: {publication_id}"
        )

    if publication["status"] != "uploaded":
        raise ValueError(
            "YouTube publication is not uploaded: "
            f"{publication_id}"
        )

    youtube_video_id = publication.get("youtube_video_id")

    if not youtube_video_id:
        raise ValueError(
            "Uploaded YouTube publication must have youtube_video_id"
        )

    result = publisher.make_public(youtube_video_id)

    if not isinstance(result, YouTubeVisibilityResult):
        raise TypeError(
            "publisher.make_public() must return "
            "YouTubeVisibilityResult"
        )

    if not result.success:
        updated = mark_youtube_visibility_failed(
            publication_id,
            result.error or "YouTube visibility update failed",
        )

        if not updated:
            raise RuntimeError(
                "Failed to persist YouTube visibility failure: "
                f"{publication_id}"
            )

        persisted = get_youtube_publication(publication_id)

        if persisted is None:
            raise RuntimeError(
                "YouTube publication disappeared after visibility failure: "
                f"{publication_id}"
            )

        return persisted

    updated = mark_youtube_published(
        publication_id,
        youtube_video_id,
        publication["youtube_url"],
    )

    if not updated:
        raise RuntimeError(
            "Failed to persist YouTube publication success: "
            f"{publication_id}"
        )

    persisted_publication = get_youtube_publication(publication_id)

    if persisted_publication is None:
        raise RuntimeError(
            "YouTube publication disappeared after publication: "
        f"{publication_id}"
        )

    return persisted_publication
