from __future__ import annotations

from typing import Any

from googleapiclient.discovery import build


YOUTUBE_DATA_READ_SCOPE = "https://www.googleapis.com/auth/youtube.readonly"
YOUTUBE_ANALYTICS_READ_SCOPE = "https://www.googleapis.com/auth/yt-analytics.readonly"
YOUTUBE_ANALYTICS_MONETARY_SCOPE = "https://www.googleapis.com/auth/yt-analytics-monetary.readonly"
YOUTUBE_ANALYTICS_REQUIRED_SCOPES = (
    YOUTUBE_DATA_READ_SCOPE,
    YOUTUBE_ANALYTICS_READ_SCOPE,
)
YOUTUBE_MONETARY_REQUIRED_SCOPES = (
    YOUTUBE_DATA_READ_SCOPE,
    YOUTUBE_ANALYTICS_MONETARY_SCOPE,
)


class YouTubeAnalyticsScopeError(PermissionError):
    """Raised when persisted Google credentials lack required Analytics read scopes."""


def create_youtube_analytics_service(credentials: Any) -> Any:
    if credentials is None:
        raise ValueError("credentials are required")
    has_scopes = getattr(credentials, "has_scopes", None)
    if not callable(has_scopes) or not has_scopes(list(YOUTUBE_ANALYTICS_REQUIRED_SCOPES)):
        raise YouTubeAnalyticsScopeError(
            "YouTube Analytics OAuth scopes are missing: "
            + ", ".join(YOUTUBE_ANALYTICS_REQUIRED_SCOPES)
        )
    return build("youtubeAnalytics", "v2", credentials=credentials)



def create_youtube_monetary_analytics_service(credentials: Any) -> Any:
    if credentials is None:
        raise ValueError("credentials are required")
    has_scopes = getattr(credentials, "has_scopes", None)
    if not callable(has_scopes) or not has_scopes(list(YOUTUBE_MONETARY_REQUIRED_SCOPES)):
        raise YouTubeAnalyticsScopeError(
            "YouTube monetary Analytics OAuth scopes are missing: "
            + ", ".join(YOUTUBE_MONETARY_REQUIRED_SCOPES)
        )
    return build("youtubeAnalytics", "v2", credentials=credentials)
