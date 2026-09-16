"""Test-only helpers for hardened YouTube private-upload lineage.

These helpers never run in production code.  They let unit/integration tests that
use in-process fake publishers attach the same minimum cloud-execution proof that
the real public-transition boundary requires after a GitHub Actions private upload.
"""

from __future__ import annotations

import json

from app.database.connection import get_connection
from app.database.youtube_repository import get_youtube_publication


def prove_private_upload_for_test(publication_id: int) -> dict:
    """Attach a synthetic SUCCEEDED cloud proof to an already fake-uploaded publication."""
    publication = get_youtube_publication(publication_id)
    if publication is None:
        raise ValueError(f"YouTube publication not found: {publication_id}")
    if publication.get("status") != "uploaded":
        raise ValueError("test publication must already be uploaded")
    youtube_video_id = publication.get("youtube_video_id")
    youtube_url = publication.get("youtube_url")
    if not isinstance(youtube_video_id, str) or not youtube_video_id:
        raise ValueError("test publication youtube_video_id is required")
    if not isinstance(youtube_url, str) or not youtube_url:
        raise ValueError("test publication youtube_url is required")

    cloud_execution = {
        "status": "SUCCEEDED",
        "execution_id": f"test-private-upload-execution-{publication_id}",
        "routing_id": f"test-private-upload-routing-{publication_id}",
        "authorization_id": f"test-private-upload-authorization-{publication_id}",
        "capability_id": "youtube.upload-private",
        "authorized_action": "YOUTUBE",
        "result": {
            "status": "UPLOADED",
            "publication_id": publication_id,
            "video_id": publication["video_id"],
            "youtube_video_id": youtube_video_id,
            "youtube_url": youtube_url,
        },
    }

    connection = get_connection()
    try:
        cursor = connection.execute(
            """
            UPDATE youtube_publications
            SET cloud_execution = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND status = 'uploaded'
              AND (cloud_execution IS NULL OR cloud_execution = '')
            """,
            (
                json.dumps(cloud_execution, ensure_ascii=False, sort_keys=True),
                publication_id,
            ),
        )
        if cursor.rowcount != 1:
            raise RuntimeError("test cloud proof could not be attached atomically")
        connection.commit()
    finally:
        connection.close()

    return cloud_execution
