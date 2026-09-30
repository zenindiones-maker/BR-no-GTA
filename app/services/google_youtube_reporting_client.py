from __future__ import annotations

from typing import Any

from googleapiclient.discovery import build


YOUTUBE_REPORTING_READ_SCOPE = "https://www.googleapis.com/auth/yt-analytics.readonly"
YOUTUBE_REPORTING_MONETARY_SCOPE = "https://www.googleapis.com/auth/yt-analytics-monetary.readonly"


class YouTubeReportingScopeError(PermissionError):
    """Raised when persisted Google credentials lack Reporting read scope."""


def create_youtube_reporting_service(credentials: Any) -> Any:
    if credentials is None:
        raise ValueError("credentials are required")
    has_scopes = getattr(credentials, "has_scopes", None)
    if not callable(has_scopes) or not has_scopes([YOUTUBE_REPORTING_READ_SCOPE]):
        raise YouTubeReportingScopeError(
            "YouTube Reporting OAuth scope is missing: " + YOUTUBE_REPORTING_READ_SCOPE
        )
    return build("youtubereporting", "v1", credentials=credentials)


__all__ = [
    "YOUTUBE_REPORTING_READ_SCOPE",
    "YOUTUBE_REPORTING_MONETARY_SCOPE",
    "YouTubeReportingScopeError",
    "create_youtube_reporting_service",
]
