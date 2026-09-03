from __future__ import annotations

from typing import Any

from app.database.connection import get_connection


def insert_episode_segment(
    *,
    episode_id: int,
    content_segment_id: int,
    episode_order: int,
    start_offset_seconds: float = 0.0,
    role: str = "content",
) -> int:
    """Insere um Episode Segment e retorna seu ID persistido."""
    connection = get_connection()

    cursor = connection.execute(
        """
        INSERT INTO episode_segments (
            episode_id,
            content_segment_id,
            segment_order,
            start_offset_seconds,
            role
        )
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            episode_id,
            content_segment_id,
            episode_order,
            start_offset_seconds,
            role,
        ),
    )

    connection.commit()

    return int(cursor.lastrowid)


def get_episode_segment(
    episode_segment_id: int,
) -> dict[str, Any] | None:
    """Busca um Episode Segment pelo ID."""
    connection = get_connection()

    row = connection.execute(
        """
        SELECT
            id,
            episode_id,
            content_segment_id,
            segment_order,
            start_offset_seconds,
            role,
            status,
            created_at,
            updated_at
        FROM episode_segments
        WHERE id = ?
        """,
        (episode_segment_id,),
    ).fetchone()

    if row is None:
        return None

    return dict(row)


def list_episode_segments(
    episode_id: int,
) -> list[dict[str, Any]]:
    """Lista os segmentos de um Episode na ordem da montagem."""
    connection = get_connection()

    rows = connection.execute(
        """
        SELECT
            id,
            episode_id,
            content_segment_id,
            segment_order,
            start_offset_seconds,
            role,
            status,
            created_at,
            updated_at
        FROM episode_segments
        WHERE episode_id = ?
        ORDER BY segment_order ASC
        """,
        (episode_id,),
    ).fetchall()

    return [dict(row) for row in rows]


def update_episode_segment_status(
    episode_segment_id: int,
    status: str,
) -> bool:
    """Atualiza o status de um Episode Segment."""
    connection = get_connection()

    cursor = connection.execute(
        """
        UPDATE episode_segments
        SET
            status = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (status, episode_segment_id),
    )

    connection.commit()

    return cursor.rowcount > 0
