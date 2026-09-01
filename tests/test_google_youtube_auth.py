from unittest.mock import Mock, patch

from app.services.google_youtube_auth import (
    YOUTUBE_UPLOAD_SCOPE,
    build_youtube_service,
)


def test_youtube_upload_scope_is_correct():
    assert (
        YOUTUBE_UPLOAD_SCOPE
        == "https://www.googleapis.com/auth/youtube.upload"
    )


def test_build_youtube_service_uses_authenticated_credentials():
    credentials = Mock()

    with patch(
        "app.services.google_youtube_auth.build",
        return_value="fake-youtube-service",
    ) as build_mock:
        result = build_youtube_service(
            credentials=credentials,
        )

    assert result == "fake-youtube-service"

    build_mock.assert_called_once_with(
        "youtube",
        "v3",
        credentials=credentials,
    )


def test_build_youtube_service_rejects_missing_credentials():
    try:
        build_youtube_service(
            credentials=None,
        )
    except ValueError as exc:
        assert str(exc) == "credentials are required"
    else:
        raise AssertionError(
            "Expected ValueError for missing credentials"
        )


def test_build_youtube_service_does_not_execute_oauth():
    credentials = Mock()

    with patch(
        "app.services.google_youtube_auth.build",
        return_value="fake-youtube-service",
    ) as build_mock:
        result = build_youtube_service(
            credentials=credentials,
        )

    assert result == "fake-youtube-service"

    credentials.refresh.assert_not_called()
    credentials.authorize.assert_not_called()
    build_mock.assert_called_once()
