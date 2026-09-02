import pytest

from app.database.content_repository import insert_content_item
from app.database.video_repository import insert_video
from app.database.youtube_repository import (
    get_youtube_publication,
    get_youtube_publication_by_video_id,
    get_next_pending_youtube_publication,
    insert_youtube_publication,
    list_youtube_publications,
    mark_youtube_failed,
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
        file_path="output/youtube-test.mp4",
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
    assert publication["file_path"] == "output/youtube-test.mp4"
    assert publication["status"] == "pending"


def test_get_youtube_publication_by_video_id():
    content_item_id, video_id = _create_video()

    publication_id = insert_youtube_publication(
        video_id=video_id,
        content_item_id=content_item_id,
        title="Publicação",
        file_path="output/by-video-id.mp4",
    )

    publication = get_youtube_publication_by_video_id(video_id)

    assert publication is not None
    assert publication["id"] == publication_id
    assert publication["video_id"] == video_id
    assert publication["file_path"] == "output/by-video-id.mp4"


def test_list_youtube_publications():
    content_item_id, video_id = _create_video()

    first_id = insert_youtube_publication(
        video_id=video_id,
        content_item_id=content_item_id,
        title="Publicação 1",
        file_path="output/list-one.mp4",
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
        file_path="output/list-two.mp4",
    )

    publications = list_youtube_publications()
    ids = [item["id"] for item in publications]

    assert first_id in ids
    assert second_id in ids

    first = next(item for item in publications if item["id"] == first_id)
    second = next(item for item in publications if item["id"] == second_id)

    assert first["file_path"] == "output/list-one.mp4"
    assert second["file_path"] == "output/list-two.mp4"


def test_get_next_pending_youtube_publication_returns_none_when_empty():
    publication = get_next_pending_youtube_publication()

    assert publication is None


def test_get_next_pending_youtube_publication_returns_oldest_pending():
    first_id = insert_youtube_publication(
        video_id=101,
        content_item_id=201,
        title="Primeira",
        description="",
        tags=["first"],
        category_id="20",
        file_path="/tmp/first.mp4",
        privacy_status="private",
        publish_at=None,
    )
    second_id = insert_youtube_publication(
        video_id=102,
        content_item_id=202,
        title="Segunda",
        description="",
        tags=["second"],
        category_id="20",
        file_path="/tmp/second.mp4",
        privacy_status="private",
        publish_at=None,
    )

    publication = get_next_pending_youtube_publication()

    assert publication is not None
    assert publication["id"] == first_id
    assert publication["id"] != second_id
    assert publication["status"] == "pending"


def test_get_next_pending_youtube_publication_ignores_non_pending():
    published_id = insert_youtube_publication(
        video_id=103,
        content_item_id=203,
        title="Publicado",
        description="",
        tags=["published"],
        category_id="20",
        file_path="/tmp/published.mp4",
        privacy_status="private",
        publish_at=None,
    )
    mark_youtube_published(
        published_id,
        youtube_video_id="youtube-published",
        youtube_url="https://www.youtube.com/watch?v=youtube-published",
    )

    failed_id = insert_youtube_publication(
        video_id=104,
        content_item_id=204,
        title="Falhou",
        description="",
        tags=["failed"],
        category_id="20",
        file_path="/tmp/failed.mp4",
        privacy_status="private",
        publish_at=None,
    )
    mark_youtube_failed(
        failed_id,
        error="erro de teste",
    )

    pending_id = insert_youtube_publication(
        video_id=105,
        content_item_id=205,
        title="Pendente",
        description="",
        tags=["pending", "test"],
        category_id="20",
        file_path="/tmp/pending.mp4",
        privacy_status="private",
        publish_at=None,
    )

    publication = get_next_pending_youtube_publication()

    assert publication is not None
    assert publication["id"] == pending_id
    assert publication["id"] != published_id
    assert publication["id"] != failed_id
    assert publication["tags"] == ["pending", "test"]
    assert isinstance(publication["tags"], list)

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
