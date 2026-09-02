from unittest.mock import patch

import pytest

from app.services.google_youtube_client import (
    create_youtube_service,
)


def test_create_youtube_service_requires_credentials():
    with pytest.raises(
        ValueError,
        match="credentials are required",
    ):
        create_youtube_service(None)


def test_create_youtube_service_builds_youtube_v3_client():
    credentials = object()
    youtube_service = object()

    with patch(
        "app.services.google_youtube_client.build",
        return_value=youtube_service,
    ) as mock_build:
        result = create_youtube_service(credentials)

    assert result is youtube_service

    mock_build.assert_called_once_with(
        "youtube",
        "v3",
        credentials=credentials,
    )
