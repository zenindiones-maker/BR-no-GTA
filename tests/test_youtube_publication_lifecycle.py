import pytest

from app.database.content_repository import insert_content_item
from app.database.schema import initialize_schema
from app.database.video_repository import insert_video

from app.database.youtube_repository import (
    get_youtube_publication,
    insert_youtube_publication,
)
from app.services.youtube_publication_service import (
    mark_youtube_publication_failed,
    mark_youtube_publication_published,
)


def _create_publication():
    initialize_schema()

    content_item_id = insert_content_item(
        title="GTA 6 Test",
        content_type="video",
        status="ready",
    )

    video_id = insert_video(
        content_item_id=content_item_id,
        title="GTA 6 Test",
        status="ready",
        file_path="output/test.mp4",
    )

    return insert_youtube_publication(
        video_id=video_id,
        content_item_id=content_item_id,
        title="GTA 6 Test",
        description="Teste",
        tags=["GTA 6"],
        category_id="20",
        privacy_status="private",
        file_path="output/test.mp4",
        status="pending",
    )


def test_service_marks_publication_as_published():
    publication_id = _create_publication()

    publication = mark_youtube_publication_published(
        publication_id,
        "youtube123",
        "https://youtube.com/watch?v=youtube123",
    )

    assert publication["status"] == "published"
    assert publication["youtube_video_id"] == "youtube123"
    assert publication["youtube_url"] == (
        "https://youtube.com/watch?v=youtube123"
    )
    assert publication["error"] is None
    assert publication["published_at"] is not None


def test_service_marks_publication_as_failed():
    publication_id = _create_publication()

    publication = mark_youtube_publication_failed(
        publication_id,
        "Upload rejeitado pelo executor.",
    )

    assert publication["status"] == "failed"
    assert publication["error"] == (
        "Upload rejeitado pelo executor."
    )
    assert publication["youtube_video_id"] is None
    assert publication["youtube_url"] is None
    assert publication["published_at"] is None


def test_published_publication_cannot_be_published_again():
    publication_id = _create_publication()

    mark_youtube_publication_published(
        publication_id,
        "youtube123",
        "https://youtube.com/watch?v=youtube123",
    )

    with pytest.raises(ValueError):
        mark_youtube_publication_published(
            publication_id,
            "youtube456",
            "https://youtube.com/watch?v=youtube456",
        )


def test_published_publication_cannot_be_failed():
    publication_id = _create_publication()

    mark_youtube_publication_published(
        publication_id,
        "youtube123",
        "https://youtube.com/watch?v=youtube123",
    )

    with pytest.raises(ValueError):
        mark_youtube_publication_failed(
            publication_id,
            "Falha posterior.",
        )


def test_failed_publication_cannot_be_published():
    publication_id = _create_publication()

    mark_youtube_publication_failed(
        publication_id,
        "Primeira tentativa falhou.",
    )

    with pytest.raises(ValueError):
        mark_youtube_publication_published(
            publication_id,
            "youtube123",
            "https://youtube.com/watch?v=youtube123",
        )


def test_failed_publication_cannot_be_failed_again():
    publication_id = _create_publication()

    mark_youtube_publication_failed(
        publication_id,
        "Primeira tentativa falhou.",
    )

    with pytest.raises(ValueError):
        mark_youtube_publication_failed(
            publication_id,
            "Segunda tentativa falhou.",
        )


def test_published_requires_video_id():
    publication_id = _create_publication()

    with pytest.raises(ValueError):
        mark_youtube_publication_published(
            publication_id,
            "",
            "https://youtube.com/watch?v=youtube123",
        )


def test_published_requires_url():
    publication_id = _create_publication()

    with pytest.raises(ValueError):
        mark_youtube_publication_published(
            publication_id,
            "youtube123",
            "",
        )


def test_failed_requires_error():
    publication_id = _create_publication()

    with pytest.raises(ValueError):
        mark_youtube_publication_failed(
            publication_id,
            "",
        )


def test_nonexistent_publication_raises_runtime_error():
    with pytest.raises(RuntimeError):
        mark_youtube_publication_published(
            999999,
            "youtube123",
            "https://youtube.com/watch?v=youtube123",
        )

    with pytest.raises(RuntimeError):
        mark_youtube_publication_failed(
            999999,
            "Falha inexistente.",
        )


def test_service_persists_published_state():
    publication_id = _create_publication()

    mark_youtube_publication_published(
        publication_id,
        "youtube123",
        "https://youtube.com/watch?v=youtube123",
    )

    persisted = get_youtube_publication(publication_id)

    assert persisted is not None
    assert persisted["status"] == "published"
    assert persisted["youtube_video_id"] == "youtube123"
    assert persisted["youtube_url"] == (
        "https://youtube.com/watch?v=youtube123"
    )


def test_service_persists_failed_state():
    publication_id = _create_publication()

    mark_youtube_publication_failed(
        publication_id,
        "Erro de upload.",
    )

    persisted = get_youtube_publication(publication_id)

    assert persisted is not None
    assert persisted["status"] == "failed"
    assert persisted["error"] == "Erro de upload."
