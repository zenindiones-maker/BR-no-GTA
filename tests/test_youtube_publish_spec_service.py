import pytest

from app.services.youtube_publish_spec_service import (
    create_youtube_publish_spec,
)


def build_video():
    return {
        "id": 10,
        "content_item_id": 20,
        "title": "GTA 6 mudou tudo",
        "status": "ready",
        "file_path": "output/video.mp4",
    }


def test_create_youtube_publish_spec_from_ready_video():
    video = build_video()

    result = create_youtube_publish_spec(video)

    assert result["video_id"] == 10
    assert result["content_item_id"] == 20
    assert result["title"] == "GTA 6 mudou tudo"
    assert result["file_path"] == "output/video.mp4"
    assert result["status"] == "ready"


def test_create_youtube_publish_spec_has_default_private_privacy():
    result = create_youtube_publish_spec(build_video())

    assert result["privacy_status"] == "private"


def test_create_youtube_publish_spec_preserves_youtube_metadata():
    video = build_video()
    video["description"] = "Descrição do vídeo"
    video["tags"] = ["GTA 6", "GTA", "Rockstar"]
    video["category_id"] = "20"
    video["privacy_status"] = "public"

    result = create_youtube_publish_spec(video)

    assert result["description"] == "Descrição do vídeo"
    assert result["tags"] == ["GTA 6", "GTA", "Rockstar"]
    assert result["category_id"] == "20"
    assert result["privacy_status"] == "public"


@pytest.mark.parametrize(
    "video",
    [
        None,
        {},
        [],
        "video",
    ],
)
def test_create_youtube_publish_spec_rejects_invalid_video(video):
    with pytest.raises(ValueError):
        create_youtube_publish_spec(video)


def test_create_youtube_publish_spec_rejects_missing_required_field():
    video = build_video()
    del video["file_path"]

    with pytest.raises(ValueError):
        create_youtube_publish_spec(video)


@pytest.mark.parametrize(
    "status",
    [
        "draft",
        "rendering",
        "failed",
        "queued",
    ],
)
def test_create_youtube_publish_spec_requires_ready_video(status):
    video = build_video()
    video["status"] = status

    with pytest.raises(ValueError):
        create_youtube_publish_spec(video)


@pytest.mark.parametrize(
    "file_path",
    [
        None,
        "",
        "   ",
    ],
)
def test_create_youtube_publish_spec_requires_file_path(file_path):
    video = build_video()
    video["file_path"] = file_path

    with pytest.raises(ValueError):
        create_youtube_publish_spec(video)


def test_create_youtube_publish_spec_requires_valid_video_id():
    video = build_video()
    video["id"] = 0

    with pytest.raises(ValueError):
        create_youtube_publish_spec(video)


def test_create_youtube_publish_spec_requires_valid_content_item_id():
    video = build_video()
    video["content_item_id"] = 0

    with pytest.raises(ValueError):
        create_youtube_publish_spec(video)


def test_create_youtube_publish_spec_requires_title():
    video = build_video()
    video["title"] = "   "

    with pytest.raises(ValueError):
        create_youtube_publish_spec(video)
