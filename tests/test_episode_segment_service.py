import pytest

from app.services.episode_segment_service import (
    EpisodeSegmentError,
    create_episode_segment,
    validate_episode_segment,
)


def test_create_episode_segment():
    segment = create_episode_segment(
        episode_id=1,
        content_segment_id=10,
        order=0,
    )

    assert segment["episode_id"] == 1
    assert segment["content_segment_id"] == 10
    assert segment["order"] == 0
    assert segment["start_offset_seconds"] == 0.0
    assert segment["role"] == "content"
    assert segment["status"] == "ready"


def test_episode_segment_can_use_same_content_segment_multiple_times():
    first = create_episode_segment(
        episode_id=1,
        content_segment_id=10,
        order=0,
    )

    second = create_episode_segment(
        episode_id=2,
        content_segment_id=10,
        order=5,
    )

    assert first["content_segment_id"] == 10
    assert second["content_segment_id"] == 10
    assert first["episode_id"] != second["episode_id"]
    assert first["order"] != second["order"]


@pytest.mark.parametrize(
    "episode_id",
    [0, -1, True],
)
def test_invalid_episode_id_is_rejected(episode_id):
    with pytest.raises(EpisodeSegmentError):
        create_episode_segment(
            episode_id=episode_id,
            content_segment_id=1,
            order=0,
        )


@pytest.mark.parametrize(
    "content_segment_id",
    [0, -1, True],
)
def test_invalid_content_segment_id_is_rejected(
    content_segment_id,
):
    with pytest.raises(EpisodeSegmentError):
        create_episode_segment(
            episode_id=1,
            content_segment_id=content_segment_id,
            order=0,
        )


@pytest.mark.parametrize(
    "order",
    [-1, True],
)
def test_invalid_order_is_rejected(order):
    with pytest.raises(EpisodeSegmentError):
        create_episode_segment(
            episode_id=1,
            content_segment_id=1,
            order=order,
        )


@pytest.mark.parametrize(
    "offset",
    [-1, -0.1],
)
def test_negative_start_offset_is_rejected(offset):
    with pytest.raises(EpisodeSegmentError):
        create_episode_segment(
            episode_id=1,
            content_segment_id=1,
            order=0,
            start_offset_seconds=offset,
        )


def test_role_is_normalized():
    segment = create_episode_segment(
        episode_id=1,
        content_segment_id=1,
        order=0,
        role="  content  ",
    )

    assert segment["role"] == "content"


def test_empty_role_is_rejected():
    with pytest.raises(EpisodeSegmentError):
        create_episode_segment(
            episode_id=1,
            content_segment_id=1,
            order=0,
            role="   ",
        )


def test_validate_episode_segment_accepts_valid_segment():
    segment = create_episode_segment(
        episode_id=1,
        content_segment_id=10,
        order=3,
        start_offset_seconds=12.5,
        role="content",
    )

    validated = validate_episode_segment(segment)

    assert validated == segment


def test_validate_episode_segment_rejects_missing_field():
    with pytest.raises(EpisodeSegmentError):
        validate_episode_segment(
            {
                "episode_id": 1,
                "content_segment_id": 10,
                "order": 0,
            }
        )


def test_episode_segment_does_not_own_media_asset():
    segment = create_episode_segment(
        episode_id=1,
        content_segment_id=10,
        order=0,
    )

    assert "file_path" not in segment
    assert "render_job_id" not in segment
    assert "youtube_video_id" not in segment
