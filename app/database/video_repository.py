from typing import Any

from app.database.connection import get_connection


def insert_video(
    content_item_id: int,
    title: str,
    status: str = "draft",
    file_path: str | None = None,
) -> int:
    """Cria um vídeo persistido e retorna seu ID."""
    connection = get_connection()

    try:
        cursor = connection.execute(
            """
            INSERT INTO videos (
                content_item_id,
                title,
                status,
                file_path
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                content_item_id,
                title,
                status,
                file_path,
            ),
        )
        connection.commit()

        return int(cursor.lastrowid)
    finally:
        connection.close()


def get_video(video_id: int) -> dict[str, Any] | None:
    """Busca um vídeo pelo ID."""
    connection = get_connection()

    try:
        row = connection.execute(
            """
            SELECT
                id,
                content_item_id,
                title,
                status,
                file_path,
                created_at
            FROM videos
            WHERE id = ?
            """,
            (video_id,),
        ).fetchone()

        if row is None:
            return None

        return dict(row)
    finally:
        connection.close()


def list_videos() -> list[dict[str, Any]]:
    """Lista os vídeos persistidos."""
    connection = get_connection()

    try:
        rows = connection.execute(
            """
            SELECT
                id,
                content_item_id,
                title,
                status,
                file_path,
                created_at
            FROM videos
            ORDER BY id ASC
            """
        ).fetchall()

        return [dict(row) for row in rows]
    finally:
        connection.close()


def update_video_status(
    video_id: int,
    status: str,
) -> bool:
    """Atualiza o status de um vídeo."""
    connection = get_connection()

    try:
        cursor = connection.execute(
            """
            UPDATE videos
            SET status = ?
            WHERE id = ?
            """,
            (status, video_id),
        )
        connection.commit()

        return cursor.rowcount > 0
    finally:
        connection.close()


def update_video_file_path(
    video_id: int,
    file_path: str | None,
) -> bool:
    """Atualiza o caminho do arquivo final do vídeo."""
    connection = get_connection()

    try:
        cursor = connection.execute(
            """
            UPDATE videos
            SET file_path = ?
            WHERE id = ?
            """,
            (file_path, video_id),
        )
        connection.commit()

        return cursor.rowcount > 0
    finally:
        connection.close()

def mark_video_ready(
    video_id: int,
    file_path: str,
) -> bool:
    connection = get_connection()
    try:
        connection.execute("BEGIN")

        cursor = connection.execute(
            """
            UPDATE videos
            SET file_path = ?,
                status = ?
            WHERE id = ?
            """,
            (file_path, "ready", video_id),
        )

        if cursor.rowcount != 1:
            connection.rollback()
            return False

        connection.commit()
        return True
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
