from dataclasses import FrozenInstanceError

import pytest

from app.services.youtube_publisher import (
    PublishResult,
    YouTubePublisher,
)


def test_publish_result_represents_success():
    result = PublishResult(
        success=True,
        youtube_video_id="youtube-123",
        youtube_url="https://youtube.com/watch?v=youtube-123",
    )

    assert result.success is True
    assert result.youtube_video_id == "youtube-123"
    assert result.youtube_url == "https://youtube.com/watch?v=youtube-123"
    assert result.error is None


def test_publish_result_represents_failure():
    result = PublishResult(
        success=False,
        error="upload failed",
    )

    assert result.success is False
    assert result.youtube_video_id is None
    assert result.youtube_url is None
    assert result.error == "upload failed"


def test_publish_result_is_immutable():
    result = PublishResult(success=True)

    with pytest.raises(FrozenInstanceError):
        result.success = False


def test_youtube_publisher_exposes_publish_contract():
    assert hasattr(YouTubePublisher, "publish")


def test_publish_contract_is_callable():
    publish = YouTubePublisher.publish

    assert callable(publish)
