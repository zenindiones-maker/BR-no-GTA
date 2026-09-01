from typing import Any

from app.database.connection import get_connection


def insert_idea(
    title: str,
    description: str | None = None,
    status: str = "new",
    score: float | None = None,
) -> int:
    """Cria uma ideia e retorna seu ID."""
    connection = get_connection()

    try:
        cursor = connection.execute(
            """
            INSERT INTO ideas (
                title,
                description,
                status,
                score
            )
            VALUES (?, ?, ?, ?)
            """,
            (title, description, status, score),
        )

        connection.commit()
        return int(cursor.lastrowid)
    finally:
        connection.close()


def list_ideas() -> list[dict[str, Any]]:
    """Retorna todas as ideias cadastradas."""
    connection = get_connection()

    try:
        rows = connection.execute(
            """
            SELECT
                id,
                title,
                description,
                status,
                score,
                created_at
            FROM ideas
            ORDER BY id
            """
        ).fetchall()

        return [dict(row) for row in rows]
    finally:
        connection.close()


def get_idea(idea_id: int) -> dict[str, Any] | None:
    """Retorna uma ideia pelo ID."""
    connection = get_connection()

    try:
        row = connection.execute(
            """
            SELECT
                id,
                title,
                description,
                status,
                score,
                created_at
            FROM ideas
            WHERE id = ?
            """,
            (idea_id,),
        ).fetchone()

        return dict(row) if row else None
    finally:
        connection.close()


def update_idea_status(
    idea_id: int,
    status: str,
) -> bool:
    """Atualiza o status de uma ideia."""
    connection = get_connection()

    try:
        cursor = connection.execute(
            """
            UPDATE ideas
            SET status = ?
            WHERE id = ?
            """,
            (status, idea_id),
        )

        connection.commit()
        return cursor.rowcount > 0
    finally:
        connection.close()


def update_idea_score(
    idea_id: int,
    score: float | None,
) -> bool:
    """Atualiza o score de uma ideia."""
    connection = get_connection()

    try:
        cursor = connection.execute(
            """
            UPDATE ideas
            SET score = ?
            WHERE id = ?
            """,
            (score, idea_id),
        )

        connection.commit()
        return cursor.rowcount > 0
    finally:
        connection.close()
