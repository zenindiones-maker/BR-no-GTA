from __future__ import annotations

from typing import Any

from app.database.connection import get_connection


def insert_episode(
    *,
    title: str,
    target_duration_seconds: float,
    min_duration_seconds: float,
    max_duration_seconds: float,
    status: str = "draft",
) -> int:
    """Insere um Episode e retorna seu ID persistido."""
    connection = get_connection()

    cursor = connection.execute(
        """
        INSERT INTO episodes (
            title,
            target_duration_seconds,
            min_duration_seconds,
            max_duration_seconds,
            status
        )
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            title,
            target_duration_seconds,
            min_duration_seconds,
            max_duration_seconds,
            status,
        ),
    )

    connection.commit()

    return int(cursor.lastrowid)


def get_episode(
    episode_id: int,
) -> dict[str, Any] | None:
    """Busca um Episode pelo ID."""
    connection = get_connection()

    row = connection.execute(
        """
        SELECT
            id,
            title,
            target_duration_seconds,
            min_duration_seconds,
            max_duration_seconds,
            status,
            created_at,
            updated_at
        FROM episodes
        WHERE id = ?
        """,
        (episode_id,),
    ).fetchone()

    if row is None:
        return None

    return dict(row)


def list_episodes(
    *,
    status: str | None = None,
) -> list[dict[str, Any]]:
    """Lista Episodes, opcionalmente filtrados por status."""
    connection = get_connection()

    if status is None:
        rows = connection.execute(
            """
            SELECT
                id,
                title,
                target_duration_seconds,
                min_duration_seconds,
                max_duration_seconds,
                status,
                created_at,
                updated_at
            FROM episodes
            ORDER BY id ASC
            """
        ).fetchall()
    else:
        rows = connection.execute(
            """
            SELECT
                id,
                title,
                target_duration_seconds,
                min_duration_seconds,
                max_duration_seconds,
                status,
                created_at,
                updated_at
            FROM episodes
            WHERE status = ?
            ORDER BY id ASC
            """,
            (status,),
        ).fetchall()

    return [dict(row) for row in rows]


def update_episode_status(
    episode_id: int,
    status: str,
) -> bool:
    """Atualiza o status de um Episode."""
    connection = get_connection()

    cursor = connection.execute(
        """
        UPDATE episodes
        SET
            status = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (status, episode_id),
    )

    connection.commit()

    return cursor.rowcount > 0
