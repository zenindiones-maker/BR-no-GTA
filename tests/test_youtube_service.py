import pytest

from app.database.content_repository import insert_content_item
from app.database.video_repository import get_video, insert_video
from app.database.youtube_repository import get_youtube_publication
from app.services.youtube_service import (
    create_youtube_publish_spec,
    create_youtube_publication,
)


def _create_video() -> dict:
    content_item_id = insert_content_item(
        title="Conteúdo YouTube",
        content_type="short",
        status="ready",
    )

    video_id = insert_video(
        content_item_id=content_item_id,
        title="Vídeo GTA",
        status="ready",
        file_path="output/video.mp4",
    )

    video = get_video(video_id)

    assert video is not None

    return video


def test_create_youtube_publish_spec():
    video = _create_video()

    spec = create_youtube_publish_spec(
        video,
        title="GTA 6 — O que mudou?",
        description="Descrição do vídeo.",
        tags=["gta6", "gta"],
        category_id="20",
        privacy_status="private",
    )

    assert spec["video_id"] == video["id"]
    assert spec["content_item_id"] == video["content_item_id"]
    assert spec["file_path"] == "output/video.mp4"
    assert spec["title"] == "GTA 6 — O que mudou?"
    assert spec["description"] == "Descrição do vídeo."
    assert spec["tags"] == ["gta6", "gta"]
    assert spec["category_id"] == "20"
    assert spec["privacy_status"] == "private"


def test_create_youtube_publish_spec_defaults_title_from_video():
    video = _create_video()

    spec = create_youtube_publish_spec(video)

    assert spec["title"] == "Vídeo GTA"
    assert spec["description"] == ""
    assert spec["tags"] == []
    assert spec["category_id"] == "20"
    assert spec["privacy_status"] == "private"


def test_create_youtube_publish_spec_requires_file_path():
    video = _create_video()
    video["file_path"] = None

    with pytest.raises(ValueError, match="file_path"):
        create_youtube_publish_spec(video)


def test_create_youtube_publish_spec_rejects_invalid_privacy():
    video = _create_video()

    with pytest.raises(
        ValueError,
        match="privacy_status inválido",
    ):
        create_youtube_publish_spec(
            video,
            privacy_status="invalid",
        )


def test_create_youtube_publish_spec_rejects_invalid_tags():
    video = _create_video()

    with pytest.raises(
        ValueError,
        match="tags deve ser uma lista",
    ):
        create_youtube_publish_spec(
            video,
            tags="gta6",
        )


def test_create_youtube_publish_spec_rejects_non_string_tags():
    video = _create_video()

    with pytest.raises(
        ValueError,
        match="elementos de tags",
    ):
        create_youtube_publish_spec(
            video,
            tags=["gta6", 6],
        )


def test_create_youtube_publication_persists_spec():
    video = _create_video()

    spec = create_youtube_publish_spec(
        video,
        title="Título publicado",
        description="Descrição",
        tags=["gta6"],
    )

    publication = create_youtube_publication(spec)

    assert publication["id"] > 0
    assert publication["status"] == "pending"
    assert publication["youtube_video_id"] is None
    assert publication["youtube_url"] is None
    assert publication["error"] is None

    persisted = get_youtube_publication(publication["id"])

    assert persisted is not None
    assert persisted["video_id"] == video["id"]
    assert persisted["title"] == "Título publicado"


def test_create_youtube_publication_rejects_duplicate_video():
    video = _create_video()

    spec = create_youtube_publish_spec(video)

    create_youtube_publication(spec)

    with pytest.raises(
        ValueError,
        match="já possui uma publicação YouTube",
    ):
        create_youtube_publication(spec)
