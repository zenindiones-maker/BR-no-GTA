import json
from typing import Any

from app.database.connection import get_connection


def insert_youtube_publication(
    video_id: int,
    content_item_id: int,
    title: str,
    description: str = "",
    tags: list[str] | None = None,
    category_id: str = "20",
    privacy_status: str = "private",
    publish_at: str | None = None,
    status: str = "pending",
) -> int:
    """Cria uma publicação destinada ao YouTube."""

    connection = get_connection()

    try:
        cursor = connection.execute(
            """
            INSERT INTO youtube_publications (
                video_id,
                content_item_id,
                title,
                description,
                tags,
                category_id,
                privacy_status,
                publish_at,
                status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                video_id,
                content_item_id,
                title,
                description,
                json.dumps(
                    tags or [],
                    ensure_ascii=False,
                ),
                category_id,
                privacy_status,
                publish_at,
                status,
            ),
        )

        connection.commit()

        return int(cursor.lastrowid)

    finally:
        connection.close()


def get_youtube_publication(
    publication_id: int,
) -> dict[str, Any] | None:
    """Busca uma publicação do YouTube pelo ID."""

    connection = get_connection()

    try:
        row = connection.execute(
            """
            SELECT
                id,
                video_id,
                content_item_id,
                title,
                description,
                tags,
                category_id,
                privacy_status,
                publish_at,
                youtube_video_id,
                youtube_url,
                status,
                error,
                created_at,
                updated_at,
                published_at
            FROM youtube_publications
            WHERE id = ?
            """,
            (publication_id,),
        ).fetchone()

        if row is None:
            return None

        return dict(row)

    finally:
        connection.close()


def get_youtube_publication_by_video_id(
    video_id: int,
) -> dict[str, Any] | None:
    """Busca a publicação YouTube associada a um vídeo."""

    connection = get_connection()

    try:
        row = connection.execute(
            """
            SELECT
                id,
                video_id,
                content_item_id,
                title,
                description,
                tags,
                category_id,
                privacy_status,
                publish_at,
                youtube_video_id,
                youtube_url,
                status,
                error,
                created_at,
                updated_at,
                published_at
            FROM youtube_publications
            WHERE video_id = ?
            """,
            (video_id,),
        ).fetchone()

        if row is None:
            return None

        return dict(row)

    finally:
        connection.close()


def list_youtube_publications() -> list[dict[str, Any]]:
    """Lista todas as publicações destinadas ao YouTube."""

    connection = get_connection()

    try:
        rows = connection.execute(
            """
            SELECT
                id,
                video_id,
                content_item_id,
                title,
                description,
                tags,
                category_id,
                privacy_status,
                publish_at,
                youtube_video_id,
                youtube_url,
                status,
                error,
                created_at,
                updated_at,
                published_at
            FROM youtube_publications
            ORDER BY id ASC
            """
        ).fetchall()

        return [dict(row) for row in rows]

    finally:
        connection.close()


def update_youtube_publication_status(
    publication_id: int,
    status: str,
    error: str | None = None,
) -> bool:
    """Atualiza o estado operacional da publicação."""

    connection = get_connection()

    try:
        cursor = connection.execute(
            """
            UPDATE youtube_publications
            SET
                status = ?,
                error = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                status,
                error,
                publication_id,
            ),
        )

        connection.commit()

        return cursor.rowcount > 0

    finally:
        connection.close()


def mark_youtube_published(
    publication_id: int,
    youtube_video_id: str,
    youtube_url: str,
) -> bool:
    """Registra uma publicação efetivamente realizada no YouTube."""

    connection = get_connection()

    try:
        cursor = connection.execute(
            """
            UPDATE youtube_publications
            SET
                status = 'published',
                youtube_video_id = ?,
                youtube_url = ?,
                error = NULL,
                published_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                youtube_video_id,
                youtube_url,
                publication_id,
            ),
        )

        connection.commit()

        return cursor.rowcount > 0

    finally:
        connection.close()
