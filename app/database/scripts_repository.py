from typing import Any

from app.database.connection import get_connection


def insert_script(
    idea_id: int,
    title: str,
    content: str,
    status: str = "draft",
    version: int = 1,
) -> int:
    """Cria um roteiro e retorna seu ID."""
    connection = get_connection()

    try:
        cursor = connection.execute(
            """
            INSERT INTO scripts (
                idea_id,
                title,
                content,
                status,
                version
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                idea_id,
                title,
                content,
                status,
                version,
            ),
        )

        connection.commit()
        return int(cursor.lastrowid)
    finally:
        connection.close()


def get_script(script_id: int) -> dict[str, Any] | None:
    """Retorna um roteiro pelo ID."""
    connection = get_connection()

    try:
        row = connection.execute(
            """
            SELECT
                id,
                idea_id,
                title,
                content,
                status,
                version,
                created_at,
                updated_at
            FROM scripts
            WHERE id = ?
            """,
            (script_id,),
        ).fetchone()

        return dict(row) if row else None
    finally:
        connection.close()


def list_scripts() -> list[dict[str, Any]]:
    """Retorna todos os roteiros."""
    connection = get_connection()

    try:
        rows = connection.execute(
            """
            SELECT
                id,
                idea_id,
                title,
                content,
                status,
                version,
                created_at,
                updated_at
            FROM scripts
            ORDER BY id
            """
        ).fetchall()

        return [dict(row) for row in rows]
    finally:
        connection.close()


def get_latest_script_by_idea(
    idea_id: int,
) -> dict[str, Any] | None:
    """Retorna a versão mais recente de um roteiro de uma ideia."""
    connection = get_connection()

    try:
        row = connection.execute(
            """
            SELECT
                id,
                idea_id,
                title,
                content,
                status,
                version,
                created_at,
                updated_at
            FROM scripts
            WHERE idea_id = ?
            ORDER BY version DESC
            LIMIT 1
            """,
            (idea_id,),
        ).fetchone()

        return dict(row) if row else None
    finally:
        connection.close()


def update_script_status(
    script_id: int,
    status: str,
) -> bool:
    """Atualiza o status de um roteiro."""
    connection = get_connection()

    try:
        cursor = connection.execute(
            """
            UPDATE scripts
            SET
                status = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (status, script_id),
        )

        connection.commit()
        return cursor.rowcount > 0
    finally:
        connection.close()
