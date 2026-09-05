from app.database.connection import get_connection
from app.database.schema import initialize_schema
from app.database.youtube_repository import (
    get_youtube_publication,
    insert_youtube_publication,
    mark_youtube_published,
    mark_youtube_uploaded,
)


def _create_dependencies() -> tuple[int, int]:
    initialize_schema()

    connection = get_connection()

    try:
        content_cursor = connection.execute(
            """
            INSERT INTO content_items (
                title,
                content_type,
                status
            )
            VALUES (?, ?, ?)
            """,
            (
                "Conteúdo ID Contract",
                "video",
                "ready",
            ),
        )

        content_item_id = int(content_cursor.lastrowid)

        video_cursor = connection.execute(
            """
            INSERT INTO videos (
                content_item_id,
                title,
                status
            )
            VALUES (?, ?, ?)
            """,
            (
                content_item_id,
                "Vídeo ID Contract",
                "ready",
            ),
        )

        video_id = int(video_cursor.lastrowid)

        connection.commit()

        return content_item_id, video_id

    finally:
        connection.close()


def _create_publication(
    *,
    content_item_id: int,
    video_id: int,
    title: str,
) -> int:
    publication_id = insert_youtube_publication(
        video_id=video_id,
        content_item_id=content_item_id,
        title=title,
        description="Descrição",
        tags=[],
        category_id="22",
        file_path="/tmp/video.mp4",
    )

    assert isinstance(publication_id, int)
    assert publication_id > 0

    return publication_id


def test_youtube_publication_id_is_database_generated():
    content_item_id, video_id = _create_dependencies()

    publication_id = _create_publication(
        content_item_id=content_item_id,
        video_id=video_id,
        title="Publicação ID Contract",
    )

    publication = get_youtube_publication(publication_id)

    assert publication is not None
    assert publication["id"] == publication_id


def test_youtube_publication_id_is_stable_across_lifecycle():
    content_item_id, video_id = _create_dependencies()

    publication_id = _create_publication(
        content_item_id=content_item_id,
        video_id=video_id,
        title="Publicação Lifecycle ID",
    )

    uploaded = mark_youtube_uploaded(
        publication_id,
        "youtube-test-id",
        "https://www.youtube.com/watch?v=youtube-test-id",
    )

    assert uploaded is True

    publication = get_youtube_publication(publication_id)

    assert publication is not None
    assert publication["id"] == publication_id
    assert publication["status"] == "uploaded"

    published = mark_youtube_published(
        publication_id,
        "youtube-test-id",
        "https://www.youtube.com/watch?v=youtube-test-id",
    )

    assert published is True

    publication = get_youtube_publication(publication_id)

    assert publication is not None
    assert publication["id"] == publication_id
    assert publication["status"] == "published"


def test_two_youtube_publications_receive_distinct_ids():
    content_item_id, first_video_id = _create_dependencies()

    connection = get_connection()

    try:
        second_content_cursor = connection.execute(
            """
            INSERT INTO content_items (
                title,
                content_type,
                status
            )
            VALUES (?, ?, ?)
            """,
            (
                "Segundo Conteúdo ID Contract",
                "video",
                "ready",
            ),
        )

        second_content_item_id = int(
            second_content_cursor.lastrowid
        )

        second_video_cursor = connection.execute(
            """
            INSERT INTO videos (
                content_item_id,
                title,
                status
            )
            VALUES (?, ?, ?)
            """,
            (
                second_content_item_id,
                "Segundo Vídeo ID Contract",
                "ready",
            ),
        )

        second_video_id = int(
            second_video_cursor.lastrowid
        )

        connection.commit()

    finally:
        connection.close()

    first_id = _create_publication(
        content_item_id=content_item_id,
        video_id=first_video_id,
        title="Primeira publicação",
    )

    second_id = _create_publication(
        content_item_id=second_content_item_id,
        video_id=second_video_id,
        title="Segunda publicação",
    )

    assert first_id != second_id
    assert first_id > 0
    assert second_id > 0
