from dataclasses import FrozenInstanceError

import pytest

from app.services.youtube_publisher import (
    YouTubePublisher,
    YouTubeUploadResult,
    YouTubeVisibilityResult,
)


def test_youtube_upload_result_represents_success():
    result = YouTubeUploadResult(
        success=True,
        youtube_video_id="youtube-123",
        youtube_url="https://youtube.com/watch?v=youtube-123",
    )

    assert result.success is True
    assert result.youtube_video_id == "youtube-123"
    assert result.youtube_url == (
        "https://youtube.com/watch?v=youtube-123"
    )
    assert result.error is None


def test_youtube_upload_result_represents_failure():
    result = YouTubeUploadResult(
        success=False,
        error="upload failed",
    )

    assert result.success is False
    assert result.youtube_video_id is None
    assert result.youtube_url is None
    assert result.error == "upload failed"


def test_youtube_upload_result_is_immutable():
    result = YouTubeUploadResult(success=True)

    with pytest.raises(FrozenInstanceError):
        result.success = False


def test_youtube_visibility_result_represents_success():
    result = YouTubeVisibilityResult(
        success=True,
    )

    assert result.success is True
    assert result.error is None


def test_youtube_visibility_result_represents_failure():
    result = YouTubeVisibilityResult(
        success=False,
        error="visibility failed",
    )

    assert result.success is False
    assert result.error == "visibility failed"


def test_youtube_visibility_result_is_immutable():
    result = YouTubeVisibilityResult(
        success=True,
    )

    with pytest.raises(FrozenInstanceError):
        result.success = False


def test_youtube_publisher_exposes_upload_contract():
    assert hasattr(YouTubePublisher, "upload")


def test_youtube_publisher_exposes_make_public_contract():
    assert hasattr(YouTubePublisher, "make_public")


def test_upload_contract_is_callable():
    upload = YouTubePublisher.upload

    assert callable(upload)


def test_make_public_contract_is_callable():
    make_public = YouTubePublisher.make_public

    assert callable(make_public)
