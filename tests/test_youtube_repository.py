import pytest

from app.database.content_repository import insert_content_item
from app.database.video_repository import insert_video
from app.database.youtube_repository import (
    get_youtube_publication,
    get_youtube_publication_by_video_id,
    insert_youtube_publication,
    list_youtube_publications,
    mark_youtube_published,
    update_youtube_publication_status,
)


def _create_video() -> tuple[int, int]:
    content_item_id = insert_content_item(
        title="Conteúdo YouTube",
        content_type="short",
        status="ready",
    )

    video_id = insert_video(
        content_item_id=content_item_id,
        title="Vídeo YouTube",
        status="ready",
        file_path="output/video.mp4",
    )

    return content_item_id, video_id


def test_insert_and_get_youtube_publication():
    content_item_id, video_id = _create_video()

    publication_id = insert_youtube_publication(
        video_id=video_id,
        content_item_id=content_item_id,
        title="Título YouTube",
        description="Descrição",
        tags=["gta", "gta6"],
        category_id="20",
        privacy_status="private",
    )

    publication = get_youtube_publication(publication_id)

    assert publication is not None
    assert publication["id"] == publication_id
    assert publication["video_id"] == video_id
    assert publication["content_item_id"] == content_item_id
    assert publication["title"] == "Título YouTube"
    assert publication["description"] == "Descrição"
    assert publication["tags"] == ["gta", "gta6"]
    assert publication["category_id"] == "20"
    assert publication["privacy_status"] == "private"
    assert publication["status"] == "pending"


def test_get_youtube_publication_by_video_id():
    content_item_id, video_id = _create_video()

    publication_id = insert_youtube_publication(
        video_id=video_id,
        content_item_id=content_item_id,
        title="Publicação",
    )

    publication = get_youtube_publication_by_video_id(video_id)

    assert publication is not None
    assert publication["id"] == publication_id
    assert publication["video_id"] == video_id


def test_list_youtube_publications():
    content_item_id, video_id = _create_video()

    first_id = insert_youtube_publication(
        video_id=video_id,
        content_item_id=content_item_id,
        title="Publicação 1",
    )

    content_item_id_2 = insert_content_item(
        title="Conteúdo 2",
        content_type="short",
        status="ready",
    )

    video_id_2 = insert_video(
        content_item_id=content_item_id_2,
        title="Vídeo 2",
        status="ready",
        file_path="output/video2.mp4",
    )

    second_id = insert_youtube_publication(
        video_id=video_id_2,
        content_item_id=content_item_id_2,
        title="Publicação 2",
    )

    publications = list_youtube_publications()
    ids = [item["id"] for item in publications]

    assert first_id in ids
    assert second_id in ids


def test_update_youtube_publication_status():
    content_item_id, video_id = _create_video()

    publication_id = insert_youtube_publication(
        video_id=video_id,
        content_item_id=content_item_id,
        title="Publicação",
    )

    assert update_youtube_publication_status(
        publication_id,
        "failed",
        error="Falha simulada",
    ) is True

    publication = get_youtube_publication(publication_id)

    assert publication is not None
    assert publication["status"] == "failed"
    assert publication["error"] == "Falha simulada"


def test_mark_youtube_published():
    content_item_id, video_id = _create_video()

    publication_id = insert_youtube_publication(
        video_id=video_id,
        content_item_id=content_item_id,
        title="Publicação",
    )

    assert mark_youtube_published(
        publication_id,
        "youtube123",
        "https://youtube.com/watch?v=youtube123",
    ) is True

    publication = get_youtube_publication(publication_id)

    assert publication is not None
    assert publication["status"] == "published"
    assert publication["youtube_video_id"] == "youtube123"
    assert publication["youtube_url"] == (
        "https://youtube.com/watch?v=youtube123"
    )
    assert publication["error"] is None
    assert publication["published_at"] is not None


def test_video_cannot_have_duplicate_youtube_publication():
    content_item_id, video_id = _create_video()

    insert_youtube_publication(
        video_id=video_id,
        content_item_id=content_item_id,
        title="Primeira",
    )

    with pytest.raises(Exception):
        insert_youtube_publication(
            video_id=video_id,
            content_item_id=content_item_id,
            title="Duplicada",
        )
