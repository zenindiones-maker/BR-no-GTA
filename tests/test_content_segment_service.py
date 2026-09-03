import pytest

from app.services.content_segment_service import (
    ContentSegmentError,
    create_content_segment,
    create_segment_from_content_unit,
    validate_content_segment,
)


CONTENT_UNIT = {
    "title": "GTA 6 recebeu uma nova informação",
    "unit_type": "segment",
    "duration_seconds": 90.0,
    "media_format": "16:9",
    "script_id": 10,
    "idea_id": 20,
    "objective": "Informar a audiência",
    "hook": "Essa informação é importante para GTA 6.",
    "narration": "Narração da unidade.",
    "visual_requirements": [
        {
            "type": "gameplay",
            "description": "Gameplay relacionado.",
        }
    ],
}


def test_create_content_segment():
    segment = create_content_segment(
        content_unit_id=100,
        order=0,
        duration_seconds=60,
        media_format="16:9",
        source_start_seconds=0,
        source_end_seconds=60,
    )

    assert segment["content_unit_id"] == 100
    assert segment["order"] == 0
    assert segment["duration_seconds"] == 60.0
    assert segment["media_format"] == "16:9"
    assert segment["source_start_seconds"] == 0.0
    assert segment["source_end_seconds"] == 60.0
    assert segment["role"] == "content"
    assert segment["status"] == "ready"


def test_segment_can_use_vertical_format():
    segment = create_content_segment(
        content_unit_id=100,
        order=0,
        duration_seconds=30,
        media_format="9:16",
        source_start_seconds=10,
        source_end_seconds=40,
        role="short",
    )

    assert segment["media_format"] == "9:16"
    assert segment["duration_seconds"] == 30.0
    assert segment["role"] == "short"


def test_same_content_unit_can_feed_vertical_short():
    segment = create_segment_from_content_unit(
        CONTENT_UNIT,
        content_unit_id=100,
        order=0,
        media_format="9:16",
        source_start_seconds=0,
        source_end_seconds=45,
        role="short",
    )

    assert segment["content_unit_id"] == 100
    assert segment["media_format"] == "9:16"
    assert segment["source_start_seconds"] == 0.0
    assert segment["source_end_seconds"] == 45.0
    assert segment["duration_seconds"] == 45.0
    assert segment["role"] == "short"


def test_same_content_unit_can_feed_horizontal_long_form():
    segment = create_segment_from_content_unit(
        CONTENT_UNIT,
        content_unit_id=100,
        order=3,
        media_format="16:9",
        source_start_seconds=0,
        source_end_seconds=90,
        role="content",
    )

    assert segment["content_unit_id"] == 100
    assert segment["media_format"] == "16:9"
    assert segment["duration_seconds"] == 90.0
    assert segment["order"] == 3


def test_same_unit_supports_multiple_independent_segments():
    short_segment = create_segment_from_content_unit(
        CONTENT_UNIT,
        content_unit_id=100,
        order=0,
        media_format="9:16",
        source_start_seconds=0,
        source_end_seconds=30,
        role="short",
    )

    long_segment = create_segment_from_content_unit(
        CONTENT_UNIT,
        content_unit_id=100,
        order=5,
        media_format="16:9",
        source_start_seconds=30,
        source_end_seconds=90,
        role="content",
    )

    assert short_segment["content_unit_id"] == 100
    assert long_segment["content_unit_id"] == 100
    assert short_segment["media_format"] == "9:16"
    assert long_segment["media_format"] == "16:9"
    assert short_segment["source_end_seconds"] == 30.0
    assert long_segment["source_start_seconds"] == 30.0


@pytest.mark.parametrize(
    "order",
    [-1, -10],
)
def test_negative_order_is_rejected(order):
    with pytest.raises(ContentSegmentError):
        create_content_segment(
            content_unit_id=100,
            order=order,
            duration_seconds=30,
            media_format="9:16",
            source_start_seconds=0,
            source_end_seconds=30,
        )


@pytest.mark.parametrize(
    "content_unit_id",
    [0, -1],
)
def test_invalid_content_unit_id_is_rejected(content_unit_id):
    with pytest.raises(ContentSegmentError):
        create_content_segment(
            content_unit_id=content_unit_id,
            order=0,
            duration_seconds=30,
            media_format="9:16",
            source_start_seconds=0,
            source_end_seconds=30,
        )


def test_negative_source_start_is_rejected():
    with pytest.raises(ContentSegmentError):
        create_content_segment(
            content_unit_id=100,
            order=0,
            duration_seconds=30,
            media_format="9:16",
            source_start_seconds=-1,
            source_end_seconds=30,
        )


def test_source_end_must_be_after_source_start():
    with pytest.raises(ContentSegmentError):
        create_content_segment(
            content_unit_id=100,
            order=0,
            duration_seconds=30,
            media_format="9:16",
            source_start_seconds=30,
            source_end_seconds=30,
        )


def test_segment_duration_cannot_exceed_source_range():
    with pytest.raises(ContentSegmentError):
        create_content_segment(
            content_unit_id=100,
            order=0,
            duration_seconds=61,
            media_format="9:16",
            source_start_seconds=0,
            source_end_seconds=60,
        )


def test_invalid_media_format_is_rejected():
    with pytest.raises(ContentSegmentError):
        create_content_segment(
            content_unit_id=100,
            order=0,
            duration_seconds=30,
            media_format="4:3",
            source_start_seconds=0,
            source_end_seconds=30,
        )


def test_segment_duration_defaults_to_source_duration():
    segment = create_segment_from_content_unit(
        CONTENT_UNIT,
        content_unit_id=100,
        order=0,
        media_format="9:16",
        source_start_seconds=15,
        source_end_seconds=60,
    )

    assert segment["duration_seconds"] == 45.0


def test_segment_can_use_entire_content_unit_by_default():
    segment = create_segment_from_content_unit(
        CONTENT_UNIT,
        content_unit_id=100,
        order=0,
        media_format="16:9",
    )

    assert segment["source_start_seconds"] == 0.0
    assert segment["source_end_seconds"] == 90.0
    assert segment["duration_seconds"] == 90.0


def test_segment_duration_can_be_overridden():
    segment = create_segment_from_content_unit(
        CONTENT_UNIT,
        content_unit_id=100,
        order=0,
        media_format="9:16",
        source_start_seconds=10,
        source_end_seconds=60,
        duration_seconds=30,
    )

    assert segment["duration_seconds"] == 30.0
    assert segment["source_start_seconds"] == 10.0
    assert segment["source_end_seconds"] == 60.0


def test_role_is_normalized():
    segment = create_content_segment(
        content_unit_id=100,
        order=0,
        duration_seconds=30,
        media_format="9:16",
        source_start_seconds=0,
        source_end_seconds=30,
        role="  SHORT  ",
    )

    assert segment["role"] == "short"


def test_invalid_content_unit_is_rejected():
    invalid_unit = {
        **CONTENT_UNIT,
    }
    del invalid_unit["hook"]

    with pytest.raises(ContentSegmentError):
        create_segment_from_content_unit(
            invalid_unit,
            content_unit_id=100,
            order=0,
            media_format="9:16",
        )


def test_validate_content_segment_accepts_valid_segment():
    segment = create_content_segment(
        content_unit_id=100,
        order=2,
        duration_seconds=45,
        media_format="9:16",
        source_start_seconds=15,
        source_end_seconds=60,
        role="reel",
    )

    assert validate_content_segment(segment) is None


def test_validate_content_segment_rejects_missing_field():
    segment = create_content_segment(
        content_unit_id=100,
        order=2,
        duration_seconds=45,
        media_format="9:16",
        source_start_seconds=15,
        source_end_seconds=60,
    )
    del segment["content_unit_id"]

    with pytest.raises(ContentSegmentError):
        validate_content_segment(segment)


def test_segment_is_declarative_only():
    segment = create_content_segment(
        content_unit_id=100,
        order=0,
        duration_seconds=30,
        media_format="9:16",
        source_start_seconds=0,
        source_end_seconds=30,
    )

    assert "file_path" not in segment
    assert "render_job_id" not in segment
    assert "youtube_video_id" not in segment
