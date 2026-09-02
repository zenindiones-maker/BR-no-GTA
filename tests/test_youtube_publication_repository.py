import pytest

from app.database.schema import initialize_schema
from app.database.content_repository import insert_content_item
from app.database.video_repository import insert_video
from app.database.youtube_repository import (
    get_youtube_publication,
    get_youtube_publication_by_video_id,
    insert_youtube_publication,
)


@pytest.fixture(autouse=True)
def setup_database():
    initialize_schema()


def create_video():
    content_item_id = insert_content_item(
        title="Content Item YouTube",
        content_type="video",
        status="ready",
    )

    video_id = insert_video(
        content_item_id=content_item_id,
        title="Vídeo pronto",
        status="ready",
        file_path="output/video.mp4",
    )

    return content_item_id, video_id


def test_insert_youtube_publication_persists_pending_intention():
    content_item_id, video_id = create_video()

    publication_id = insert_youtube_publication(
        video_id=video_id,
        content_item_id=content_item_id,
        title="Título YouTube",
        description="Descrição",
        tags=["GTA 6", "GTA"],
        privacy_status="private",
    )

    publication = get_youtube_publication(publication_id)

    assert publication is not None
    assert publication["video_id"] == video_id
    assert publication["content_item_id"] == content_item_id
    assert publication["title"] == "Título YouTube"
    assert publication["description"] == "Descrição"
    assert publication["tags"] == ["GTA 6", "GTA"]
    assert publication["privacy_status"] == "private"
    assert publication["status"] == "pending"
    assert publication["youtube_video_id"] is None
    assert publication["youtube_url"] is None
    assert publication["error"] is None


def test_insert_youtube_publication_uses_private_as_default():
    content_item_id, video_id = create_video()

    publication_id = insert_youtube_publication(
        video_id=video_id,
        content_item_id=content_item_id,
        title="Vídeo privado",
    )

    publication = get_youtube_publication(publication_id)

    assert publication is not None
    assert publication["privacy_status"] == "private"
    assert publication["tags"] == []


def test_get_youtube_publication_by_video_id():
    content_item_id, video_id = create_video()

    publication_id = insert_youtube_publication(
        video_id=video_id,
        content_item_id=content_item_id,
        title="Busca por vídeo",
    )

    publication = get_youtube_publication_by_video_id(video_id)

    assert publication is not None
    assert publication["id"] == publication_id
    assert publication["video_id"] == video_id


def test_get_youtube_publication_returns_none_for_missing_id():
    assert get_youtube_publication(999999) is None


def test_get_youtube_publication_by_video_id_returns_none_for_missing_video():
    assert get_youtube_publication_by_video_id(999999) is None


def test_video_can_have_only_one_youtube_publication():
    content_item_id, video_id = create_video()

    insert_youtube_publication(
        video_id=video_id,
        content_item_id=content_item_id,
        title="Primeira publicação",
    )

    with pytest.raises(Exception):
        insert_youtube_publication(
            video_id=video_id,
            content_item_id=content_item_id,
            title="Segunda publicação",
        )
