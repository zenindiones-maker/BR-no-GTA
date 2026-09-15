from __future__ import annotations

from typing import Any

from googleapiclient.discovery import build


YOUTUBE_ANALYTICS_READ_SCOPE = "https://www.googleapis.com/auth/yt-analytics.readonly"


class YouTubeAnalyticsScopeError(PermissionError):
    """Raised when persisted Google credentials lack Analytics read scope."""


def create_youtube_analytics_service(credentials: Any) -> Any:
    if credentials is None:
        raise ValueError("credentials are required")
    has_scopes = getattr(credentials, "has_scopes", None)
    if not callable(has_scopes) or not has_scopes([YOUTUBE_ANALYTICS_READ_SCOPE]):
        raise YouTubeAnalyticsScopeError(
            "YouTube Analytics OAuth scope is missing: " + YOUTUBE_ANALYTICS_READ_SCOPE
        )
    return build("youtubeAnalytics", "v2", credentials=credentials)
