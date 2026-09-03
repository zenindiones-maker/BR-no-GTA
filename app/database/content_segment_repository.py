from __future__ import annotations

from typing import Any

from app.database.connection import get_connection


def insert_content_segment(
    *,
    content_unit_id: int,
    segment_order: int,
    duration_seconds: float,
    media_format: str,
    source_start_seconds: float,
    source_end_seconds: float,
    role: str = "content",
    status: str = "ready",
    file_path: str | None = None,
) -> int:
    connection = get_connection()

    cursor = connection.execute(
        """
        INSERT INTO content_segments (
            content_unit_id,
            segment_order,
            duration_seconds,
            media_format,
            source_start_seconds,
            source_end_seconds,
            role,
            status,
            file_path
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            content_unit_id,
            segment_order,
            duration_seconds,
            media_format,
            source_start_seconds,
            source_end_seconds,
            role,
            status,
            file_path,
        ),
    )

    connection.commit()
    return int(cursor.lastrowid)


def get_content_segment(
    segment_id: int,
) -> dict[str, Any] | None:
    connection = get_connection()

    row = connection.execute(
        """
        SELECT *
        FROM content_segments
        WHERE id = ?
        """,
        (segment_id,),
    ).fetchone()

    if row is None:
        return None

    return dict(row)


def list_content_segments(
    content_unit_id: int,
) -> list[dict[str, Any]]:
    connection = get_connection()

    rows = connection.execute(
        """
        SELECT *
        FROM content_segments
        WHERE content_unit_id = ?
        ORDER BY segment_order ASC
        """,
        (content_unit_id,),
    ).fetchall()

    return [dict(row) for row in rows]


def update_content_segment_status(
    segment_id: int,
    status: str,
) -> bool:
    connection = get_connection()

    cursor = connection.execute(
        """
        UPDATE content_segments
        SET status = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (status, segment_id),
    )

    connection.commit()
    return cursor.rowcount == 1


def update_content_segment_file_path(
    segment_id: int,
    file_path: str | None,
) -> bool:
    connection = get_connection()

    cursor = connection.execute(
        """
        UPDATE content_segments
        SET file_path = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (file_path, segment_id),
    )

    connection.commit()
    return cursor.rowcount == 1
